#!/usr/bin/env python3
"""Rehearse a live Primary Authority control-plane outage without effects.

The command uses an isolated, generated authority key.  It acquires and renews
one live Supabase lease, switches the authority adapter to a real unreachable
HTTP endpoint, proves the keepalive closes its local enable gate, restores the
healthy adapter, and waits for a standby session to acquire the next epoch.

No write authorization, outbox claim, provider, or settlement interface is
present in this module.  Publisher ownership is read before and after only, so
the production publisher fence cannot be changed by this rehearsal.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import socket
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Protocol
from uuid import getnode, uuid4

from volpred.ops.authority import (
    AuthorityInactive,
    AuthorityReceipt,
    AuthorityRequest,
    HostAuthorityKeepalive,
    HostAuthoritySession,
    PrimaryAuthority,
    PrimaryLease,
    WriteIntent,
)
from volpred.ops.authority.supabase import SupabaseAuthorityStore
from volpred.ops.delivery.owned_publisher_article import (
    PublisherArticleSyncOwner,
    SupabaseOwnedPublisherArticleStore,
)
from volpred.ops.delivery.supabase_rpc import runtime_environment

_SAFE_AUTHORITY_PREFIX = "operations-core-outage-smoke-"
_PUBLISHER_FAMILY = "publisher.article.supabase.sync"
_OUTAGE_URL = "http://127.0.0.1:1"
_REHEARSAL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{5,63}")


class AuthorityStore(Protocol):
    def acquire(
        self,
        request: AuthorityRequest,
        *,
        fencing_token: str,
    ) -> PrimaryLease: ...

    def renew(self, lease: PrimaryLease) -> PrimaryLease: ...

    def authorize(self, intent: WriteIntent): ...

    def release(self, lease: PrimaryLease) -> AuthorityReceipt: ...


class PublisherOwnerReader(Protocol):
    def read_owner(self) -> PublisherArticleSyncOwner: ...


class PartitionableAuthorityStore:
    """Switch all authority RPCs between healthy and unreachable transports."""

    def __init__(
        self,
        *,
        healthy: AuthorityStore,
        unavailable: AuthorityStore,
    ) -> None:
        self._healthy = healthy
        self._unavailable = unavailable
        self._lock = RLock()
        self._partitioned = False

    @classmethod
    def from_environment(cls) -> PartitionableAuthorityStore:
        values = runtime_environment()
        service_role_key = values.get("SUPABASE_SERVICE_ROLE_KEY", "")
        return cls(
            healthy=SupabaseAuthorityStore.from_environment(),
            unavailable=SupabaseAuthorityStore(
                supabase_url=_OUTAGE_URL,
                service_role_key=service_role_key,
                timeout_seconds=0.5,
            ),
        )

    def partition(self) -> None:
        with self._lock:
            self._partitioned = True

    def restore(self) -> None:
        with self._lock:
            self._partitioned = False

    def acquire(
        self,
        request: AuthorityRequest,
        *,
        fencing_token: str,
    ) -> PrimaryLease:
        return self._current().acquire(
            request,
            fencing_token=fencing_token,
        )

    def renew(self, lease: PrimaryLease) -> PrimaryLease:
        return self._current().renew(lease)

    def authorize(self, intent: WriteIntent):
        return self._current().authorize(intent)

    def release(self, lease: PrimaryLease) -> AuthorityReceipt:
        return self._current().release(lease)

    def _current(self) -> AuthorityStore:
        with self._lock:
            return self._unavailable if self._partitioned else self._healthy


@dataclass(frozen=True)
class AuthorityLeaseEvidence:
    holder_ref: str
    epoch: int
    acquired_at: str
    expires_at: str


@dataclass(frozen=True)
class PublisherFenceEvidence:
    effect_family: str
    owner: str
    generation: int
    changed_at: str


@dataclass(frozen=True)
class PrimaryAuthorityOutageReceipt:
    schema_version: str
    authority_key: str
    started_at: str
    completed_at: str
    lease_seconds: int
    renew_interval_seconds: float
    primary: AuthorityLeaseEvidence
    healthy_renewal_count: int
    outage_transport: str
    local_gate_closed: bool
    demotion_latency_seconds: float
    partition_probe_rejected: bool
    standby: AuthorityLeaseEvidence
    recovery_rto_seconds: float
    recovery_attempt_count: int
    publisher_fence_before: PublisherFenceEvidence
    publisher_fence_after: PublisherFenceEvidence
    successful_authority_claims: int
    duplicate_authority_claims: int
    effect_requests: int
    provider_calls: int
    final_standby_state: str


@dataclass(frozen=True)
class PrimaryProcessReceipt:
    schema_version: str
    rehearsal_id: str
    role: str
    host_id: str
    host_fingerprint: str
    implementation_sha256: str
    authority_key: str
    started_at: str
    completed_at: str
    lease_seconds: int
    renew_interval_seconds: float
    primary: AuthorityLeaseEvidence
    healthy_renewal_count: int
    outage_transport: str
    local_gate_closed: bool
    demotion_latency_seconds: float
    partition_probe_rejected: bool
    publisher_fence_before: PublisherFenceEvidence
    publisher_fence_after: PublisherFenceEvidence
    successful_authority_claims: int
    duplicate_authority_claims: int
    effect_requests: int
    provider_calls: int
    final_primary_state: str


@dataclass(frozen=True)
class StandbyProcessReceipt:
    schema_version: str
    rehearsal_id: str
    role: str
    host_id: str
    host_fingerprint: str
    implementation_sha256: str
    authority_key: str
    started_at: str
    completed_at: str
    lease_seconds: int
    expected_primary_epoch: int
    standby: AuthorityLeaseEvidence
    acquisition_wait_seconds: float
    acquisition_attempt_count: int
    publisher_fence_before: PublisherFenceEvidence
    publisher_fence_after: PublisherFenceEvidence
    successful_authority_claims: int
    duplicate_authority_claims: int
    effect_requests: int
    provider_calls: int
    final_standby_state: str


@dataclass(frozen=True)
class CrossHostOutageReceipt:
    schema_version: str
    rehearsal_id: str
    authority_key: str
    verified_at: str
    primary_host_id: str
    primary_host_fingerprint: str
    standby_host_id: str
    standby_host_fingerprint: str
    implementation_sha256: str
    primary_epoch: int
    standby_epoch: int
    primary_expires_at: str
    standby_acquired_at: str
    database_clock_handoff_seconds: float
    publisher_fence: PublisherFenceEvidence
    primary_receipt_sha256: str
    standby_receipt_sha256: str
    successful_authority_claims: int
    duplicate_authority_claims: int
    effect_requests: int
    provider_calls: int
    cross_host_verified: bool


def rehearse_primary_process_role(
    *,
    rehearsal_id: str,
    host_id: str,
    host_fingerprint: str,
    holder_ref: str,
    lease_seconds: int,
    renew_interval_seconds: float,
    poll_interval_seconds: float,
    store: PartitionableAuthorityStore,
    publisher_store: PublisherOwnerReader,
    expected_publisher_generation: int,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> PrimaryProcessReceipt:
    """Acquire, renew, partition, and fail closed on the primary host."""

    authority_key = _authority_key_for_rehearsal(rehearsal_id)
    _validate_process_inputs(
        host_id=host_id,
        host_fingerprint=host_fingerprint,
        holder_ref=holder_ref,
        lease_seconds=lease_seconds,
        renew_interval_seconds=renew_interval_seconds,
        poll_interval_seconds=poll_interval_seconds,
    )
    implementation_sha256 = _implementation_sha256()
    started_at = datetime.now(UTC).isoformat()
    publisher_before = _validate_publisher_fence(
        publisher_store.read_owner(),
        expected_generation=expected_publisher_generation,
    )
    primary = _build_keepalive(
        store=store,
        authority_key=authority_key,
        holder_ref=holder_ref,
        lease_seconds=lease_seconds,
        renew_interval_seconds=renew_interval_seconds,
    )
    partitioned = False
    primary_lease: PrimaryLease | None = None
    try:
        primary.start()
        healthy_status = _wait_until(
            deadline=monotonic() + max(10.0, renew_interval_seconds * 3),
            poll_interval_seconds=poll_interval_seconds,
            sleep=sleep,
            observe=primary.status,
            accept=lambda status: status.renewal_count >= 1,
            failure="primary did not complete a healthy renewal",
            monotonic=monotonic,
        )
        primary_lease = primary.current_lease()

        outage_started = monotonic()
        store.partition()
        partitioned = True
        demoted = _wait_until(
            deadline=outage_started
            + max(10.0, renew_interval_seconds * 3),
            poll_interval_seconds=poll_interval_seconds,
            sleep=sleep,
            observe=primary.status,
            accept=lambda status: (
                status.state == "demoted" and not status.worker_alive
            ),
            failure="primary did not demote after renewal transport outage",
            monotonic=monotonic,
        )
        demotion_latency = monotonic() - outage_started
        if demoted.worker_alive:
            raise RuntimeError("demoted keepalive worker is still alive")
        try:
            primary.current_lease()
        except AuthorityInactive:
            local_gate_closed = True
        else:
            raise RuntimeError("primary local enable gate remained open")

        probe = _build_keepalive(
            store=store,
            authority_key=authority_key,
            holder_ref=f"{holder_ref}:partition-probe",
            lease_seconds=lease_seconds,
            renew_interval_seconds=renew_interval_seconds,
        )
        try:
            probe.start()
        except RuntimeError as error:
            if "unavailable" not in str(error):
                raise
            partition_probe_rejected = True
        else:
            raise RuntimeError(
                "partition probe unexpectedly reached Primary Authority"
            )
        finally:
            _best_effort_stop(probe)

        store.restore()
        partitioned = False
        publisher_after = _validate_publisher_fence(
            publisher_store.read_owner(),
            expected_generation=expected_publisher_generation,
        )
        if publisher_after != publisher_before:
            raise RuntimeError("publisher owner fence drifted during outage")
        final_primary = primary.status()
        if final_primary.state != "demoted":
            raise RuntimeError("partitioned primary did not remain demoted")
        _verify_implementation_unchanged(implementation_sha256)

        return PrimaryProcessReceipt(
            schema_version="primary-authority-outage-primary.v1",
            rehearsal_id=rehearsal_id,
            role="primary",
            host_id=host_id,
            host_fingerprint=host_fingerprint,
            implementation_sha256=implementation_sha256,
            authority_key=authority_key,
            started_at=started_at,
            completed_at=datetime.now(UTC).isoformat(),
            lease_seconds=lease_seconds,
            renew_interval_seconds=renew_interval_seconds,
            primary=_lease_evidence(primary_lease),
            healthy_renewal_count=healthy_status.renewal_count,
            outage_transport=_OUTAGE_URL,
            local_gate_closed=local_gate_closed,
            demotion_latency_seconds=round(demotion_latency, 6),
            partition_probe_rejected=partition_probe_rejected,
            publisher_fence_before=publisher_before,
            publisher_fence_after=publisher_after,
            successful_authority_claims=1,
            duplicate_authority_claims=0,
            effect_requests=0,
            provider_calls=0,
            final_primary_state=final_primary.state,
        )
    finally:
        if partitioned:
            store.restore()
        _best_effort_stop(primary)


def rehearse_standby_process_role(
    *,
    rehearsal_id: str,
    host_id: str,
    host_fingerprint: str,
    holder_ref: str,
    expected_primary_epoch: int,
    lease_seconds: int,
    rto_seconds: float,
    poll_interval_seconds: float,
    store: AuthorityStore,
    publisher_store: PublisherOwnerReader,
    expected_publisher_generation: int,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> StandbyProcessReceipt:
    """Wait for DB-clock expiry, acquire the next epoch, and release it."""

    authority_key = _authority_key_for_rehearsal(rehearsal_id)
    _validate_process_inputs(
        host_id=host_id,
        host_fingerprint=host_fingerprint,
        holder_ref=holder_ref,
        lease_seconds=lease_seconds,
        renew_interval_seconds=min(1.0, lease_seconds / 2),
        poll_interval_seconds=poll_interval_seconds,
    )
    if (
        isinstance(expected_primary_epoch, bool)
        or not isinstance(expected_primary_epoch, int)
        or expected_primary_epoch <= 0
    ):
        raise ValueError("expected_primary_epoch must be positive")
    if rto_seconds <= 0 or rto_seconds > 300:
        raise ValueError("RTO must be positive and at most five minutes")

    implementation_sha256 = _implementation_sha256()
    started_at = datetime.now(UTC).isoformat()
    publisher_before = _validate_publisher_fence(
        publisher_store.read_owner(),
        expected_generation=expected_publisher_generation,
    )
    standby = _build_keepalive(
        store=store,
        authority_key=authority_key,
        holder_ref=holder_ref,
        lease_seconds=lease_seconds,
        renew_interval_seconds=min(60.0, lease_seconds / 2),
    )
    standby_lease: PrimaryLease | None = None
    attempts = 0
    acquisition_started = monotonic()
    deadline = acquisition_started + rto_seconds
    try:
        while monotonic() < deadline:
            attempts += 1
            try:
                standby_lease = standby.start()
                break
            except ValueError as error:
                if "Primary Authority is already held" not in str(error):
                    raise
                sleep(poll_interval_seconds)
            except RuntimeError as error:
                if "RPC unavailable" not in str(error):
                    raise
                sleep(poll_interval_seconds)
        if standby_lease is None:
            raise RuntimeError(
                "standby did not acquire Primary Authority within RTO"
            )
        acquisition_wait = monotonic() - acquisition_started
        if standby_lease.epoch != expected_primary_epoch + 1:
            raise RuntimeError(
                "standby did not acquire the exact next authority epoch"
            )

        standby.stop()
        final_standby = standby.status()
        if (
            final_standby.state != "stopped"
            or final_standby.authority.last_release_ref is None
        ):
            raise RuntimeError(
                "standby release lacked terminal database acknowledgement"
            )
        publisher_after = _validate_publisher_fence(
            publisher_store.read_owner(),
            expected_generation=expected_publisher_generation,
        )
        if publisher_after != publisher_before:
            raise RuntimeError("publisher owner fence drifted during handoff")
        _verify_implementation_unchanged(implementation_sha256)

        return StandbyProcessReceipt(
            schema_version="primary-authority-outage-standby.v1",
            rehearsal_id=rehearsal_id,
            role="standby",
            host_id=host_id,
            host_fingerprint=host_fingerprint,
            implementation_sha256=implementation_sha256,
            authority_key=authority_key,
            started_at=started_at,
            completed_at=datetime.now(UTC).isoformat(),
            lease_seconds=lease_seconds,
            expected_primary_epoch=expected_primary_epoch,
            standby=_lease_evidence(standby_lease),
            acquisition_wait_seconds=round(acquisition_wait, 6),
            acquisition_attempt_count=attempts,
            publisher_fence_before=publisher_before,
            publisher_fence_after=publisher_after,
            successful_authority_claims=1,
            duplicate_authority_claims=0,
            effect_requests=0,
            provider_calls=0,
            final_standby_state=final_standby.state,
        )
    finally:
        _best_effort_stop(standby)


def verify_cross_host_receipts(
    primary: PrimaryProcessReceipt,
    standby: StandbyProcessReceipt,
    *,
    max_handoff_seconds: float = 300.0,
) -> CrossHostOutageReceipt:
    """Verify a no-effect, exact-next-epoch handoff across distinct hosts."""

    if max_handoff_seconds <= 0 or max_handoff_seconds > 300:
        raise ValueError(
            "max_handoff_seconds must be positive and at most five minutes"
        )
    if primary.schema_version != "primary-authority-outage-primary.v1":
        raise ValueError("unsupported primary receipt schema")
    if standby.schema_version != "primary-authority-outage-standby.v1":
        raise ValueError("unsupported standby receipt schema")
    if primary.role != "primary" or standby.role != "standby":
        raise ValueError("receipt role mismatch")
    if (
        primary.rehearsal_id != standby.rehearsal_id
        or primary.authority_key != standby.authority_key
    ):
        raise ValueError("receipts do not share one rehearsal identity")
    if primary.authority_key != _authority_key_for_rehearsal(
        primary.rehearsal_id
    ):
        raise ValueError(
            "receipt authority key is not derived from rehearsal identity"
        )
    if primary.implementation_sha256 != standby.implementation_sha256:
        raise ValueError("host receipts used different rehearsal code")
    if (
        primary.host_id == standby.host_id
        or primary.host_fingerprint == standby.host_fingerprint
    ):
        raise ValueError("cross-host evidence requires two distinct machines")
    if primary.lease_seconds != standby.lease_seconds:
        raise ValueError("primary and standby lease windows differ")
    if standby.expected_primary_epoch != primary.primary.epoch:
        raise ValueError("standby expected a different primary epoch")
    if standby.standby.epoch != primary.primary.epoch + 1:
        raise ValueError("standby receipt is not the exact next epoch")
    if not primary.local_gate_closed or not primary.partition_probe_rejected:
        raise ValueError("primary fail-closed evidence is incomplete")
    if (
        primary.final_primary_state != "demoted"
        or standby.final_standby_state != "stopped"
    ):
        raise ValueError("terminal host states are invalid")

    publisher_fences = (
        primary.publisher_fence_before,
        primary.publisher_fence_after,
        standby.publisher_fence_before,
        standby.publisher_fence_after,
    )
    if any(fence != publisher_fences[0] for fence in publisher_fences[1:]):
        raise ValueError("publisher owner fence drifted across host receipts")
    successful_claims = (
        primary.successful_authority_claims
        + standby.successful_authority_claims
    )
    duplicate_claims = (
        primary.duplicate_authority_claims
        + standby.duplicate_authority_claims
    )
    effect_requests = primary.effect_requests + standby.effect_requests
    provider_calls = primary.provider_calls + standby.provider_calls
    if (
        successful_claims != 2
        or duplicate_claims != 0
        or effect_requests != 0
        or provider_calls != 0
    ):
        raise ValueError("cross-host no-effect counters are invalid")

    primary_expiry = _timestamp(
        primary.primary.expires_at,
        field="primary expires_at",
    )
    standby_acquired = _timestamp(
        standby.standby.acquired_at,
        field="standby acquired_at",
    )
    handoff_seconds = (standby_acquired - primary_expiry).total_seconds()
    if handoff_seconds < 0:
        raise ValueError("standby acquired before the primary DB-clock expiry")
    if handoff_seconds > max_handoff_seconds:
        raise ValueError("database-clock handoff exceeded five-minute RTO")

    return CrossHostOutageReceipt(
        schema_version="primary-authority-outage-cross-host.v1",
        rehearsal_id=primary.rehearsal_id,
        authority_key=primary.authority_key,
        verified_at=datetime.now(UTC).isoformat(),
        primary_host_id=primary.host_id,
        primary_host_fingerprint=primary.host_fingerprint,
        standby_host_id=standby.host_id,
        standby_host_fingerprint=standby.host_fingerprint,
        implementation_sha256=primary.implementation_sha256,
        primary_epoch=primary.primary.epoch,
        standby_epoch=standby.standby.epoch,
        primary_expires_at=primary.primary.expires_at,
        standby_acquired_at=standby.standby.acquired_at,
        database_clock_handoff_seconds=round(handoff_seconds, 6),
        publisher_fence=publisher_fences[0],
        primary_receipt_sha256=_receipt_sha256(primary),
        standby_receipt_sha256=_receipt_sha256(standby),
        successful_authority_claims=successful_claims,
        duplicate_authority_claims=duplicate_claims,
        effect_requests=effect_requests,
        provider_calls=provider_calls,
        cross_host_verified=True,
    )


def rehearse_primary_authority_outage(
    *,
    authority_key: str,
    primary_holder_ref: str,
    standby_holder_ref: str,
    lease_seconds: int,
    renew_interval_seconds: float,
    rto_seconds: float,
    poll_interval_seconds: float,
    store: PartitionableAuthorityStore,
    publisher_store: PublisherOwnerReader,
    expected_publisher_generation: int,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> PrimaryAuthorityOutageReceipt:
    """Run one isolated outage and return token-redacted live evidence."""

    _validate_rehearsal_inputs(
        authority_key=authority_key,
        primary_holder_ref=primary_holder_ref,
        standby_holder_ref=standby_holder_ref,
        lease_seconds=lease_seconds,
        renew_interval_seconds=renew_interval_seconds,
        rto_seconds=rto_seconds,
        poll_interval_seconds=poll_interval_seconds,
    )
    started_at = datetime.now(UTC).isoformat()
    publisher_before = _validate_publisher_fence(
        publisher_store.read_owner(),
        expected_generation=expected_publisher_generation,
    )
    primary = _build_keepalive(
        store=store,
        authority_key=authority_key,
        holder_ref=primary_holder_ref,
        lease_seconds=lease_seconds,
        renew_interval_seconds=renew_interval_seconds,
    )
    standby = _build_keepalive(
        store=store,
        authority_key=authority_key,
        holder_ref=standby_holder_ref,
        lease_seconds=lease_seconds,
        renew_interval_seconds=renew_interval_seconds,
    )
    primary_lease: PrimaryLease | None = None
    standby_lease: PrimaryLease | None = None
    partitioned = False
    try:
        primary_lease = primary.start()
        healthy_status = _wait_until(
            deadline=monotonic() + max(10.0, renew_interval_seconds * 3),
            poll_interval_seconds=poll_interval_seconds,
            sleep=sleep,
            observe=primary.status,
            accept=lambda status: status.renewal_count >= 1,
            failure="primary did not complete a healthy renewal",
            monotonic=monotonic,
        )
        # The evidence must identify the lease window published by the healthy
        # renewal, not the now-stale object returned by initial acquisition.
        primary_lease = primary.current_lease()

        outage_started = monotonic()
        store.partition()
        partitioned = True
        demoted = _wait_until(
            deadline=outage_started
            + max(10.0, renew_interval_seconds * 3),
            poll_interval_seconds=poll_interval_seconds,
            sleep=sleep,
            observe=primary.status,
            accept=lambda status: (
                status.state == "demoted" and not status.worker_alive
            ),
            failure="primary did not demote after renewal transport outage",
            monotonic=monotonic,
        )
        demotion_latency = monotonic() - outage_started
        if demoted.worker_alive:
            raise RuntimeError("demoted keepalive worker is still alive")
        try:
            primary.current_lease()
        except AuthorityInactive:
            local_gate_closed = True
        else:
            raise RuntimeError("primary local enable gate remained open")

        try:
            standby.start()
        except RuntimeError as error:
            if "unavailable" not in str(error):
                raise
            partition_probe_rejected = True
        else:
            raise RuntimeError(
                "standby unexpectedly acquired while transport was partitioned"
            )

        store.restore()
        partitioned = False
        recovery_started = monotonic()
        attempts = 0
        deadline = recovery_started + rto_seconds
        while monotonic() < deadline:
            attempts += 1
            try:
                standby_lease = standby.start()
                break
            except ValueError as error:
                if "Primary Authority is already held" not in str(error):
                    raise
                sleep(poll_interval_seconds)
            except RuntimeError as error:
                if "RPC unavailable" not in str(error):
                    raise
                sleep(poll_interval_seconds)
        if standby_lease is None:
            raise RuntimeError(
                "standby did not reacquire Primary Authority within RTO"
            )
        recovery_rto = monotonic() - recovery_started
        if standby_lease.epoch != primary_lease.epoch + 1:
            raise RuntimeError(
                "standby did not acquire the exact next authority epoch"
            )
        if primary.status().state != "demoted":
            raise RuntimeError("primary reopened after standby acquisition")
        try:
            primary.current_lease()
        except AuthorityInactive:
            pass  # silent-ok: expected negative assertion for the old gate
        else:
            raise RuntimeError("old primary lease became usable again")

        standby.stop()
        final_standby = standby.status()
        if (
            final_standby.state != "stopped"
            or final_standby.authority.last_release_ref is None
        ):
            raise RuntimeError(
                "standby release lacked terminal database acknowledgement"
            )
        publisher_after = _validate_publisher_fence(
            publisher_store.read_owner(),
            expected_generation=expected_publisher_generation,
        )
        if publisher_after != publisher_before:
            raise RuntimeError("publisher owner fence drifted during outage")

        return PrimaryAuthorityOutageReceipt(
            schema_version="primary-authority-outage-rehearsal.v1",
            authority_key=authority_key,
            started_at=started_at,
            completed_at=datetime.now(UTC).isoformat(),
            lease_seconds=lease_seconds,
            renew_interval_seconds=renew_interval_seconds,
            primary=_lease_evidence(primary_lease),
            healthy_renewal_count=healthy_status.renewal_count,
            outage_transport=_OUTAGE_URL,
            local_gate_closed=local_gate_closed,
            demotion_latency_seconds=round(demotion_latency, 6),
            partition_probe_rejected=partition_probe_rejected,
            standby=_lease_evidence(standby_lease),
            recovery_rto_seconds=round(recovery_rto, 6),
            recovery_attempt_count=attempts,
            publisher_fence_before=publisher_before,
            publisher_fence_after=publisher_after,
            successful_authority_claims=2,
            duplicate_authority_claims=0,
            effect_requests=0,
            provider_calls=0,
            final_standby_state=final_standby.state,
        )
    finally:
        if partitioned:
            store.restore()
        _best_effort_stop(standby)
        _best_effort_stop(primary)


def _build_keepalive(
    *,
    store: AuthorityStore,
    authority_key: str,
    holder_ref: str,
    lease_seconds: int,
    renew_interval_seconds: float,
) -> HostAuthorityKeepalive:
    session = HostAuthoritySession(
        PrimaryAuthority(store),
        AuthorityRequest(
            authority_key=authority_key,
            holder_ref=holder_ref,
            lease_seconds=lease_seconds,
        ),
    )
    return HostAuthorityKeepalive(
        session,
        renew_interval_seconds=renew_interval_seconds,
        join_timeout_seconds=max(5.0, renew_interval_seconds * 2),
    )


def _wait_until(
    *,
    deadline: float,
    poll_interval_seconds: float,
    sleep: Callable[[float], None],
    observe: Callable[[], object],
    accept: Callable[[object], bool],
    failure: str,
    monotonic: Callable[[], float],
):
    while monotonic() < deadline:
        observed = observe()
        if accept(observed):
            return observed
        sleep(poll_interval_seconds)
    raise RuntimeError(failure)


def _validate_rehearsal_inputs(
    *,
    authority_key: str,
    primary_holder_ref: str,
    standby_holder_ref: str,
    lease_seconds: int,
    renew_interval_seconds: float,
    rto_seconds: float,
    poll_interval_seconds: float,
) -> None:
    if not authority_key.startswith(_SAFE_AUTHORITY_PREFIX):
        raise ValueError(
            "outage rehearsal requires an isolated generated authority key"
        )
    if not primary_holder_ref.strip() or not standby_holder_ref.strip():
        raise ValueError("both holder refs are required")
    if primary_holder_ref == standby_holder_ref:
        raise ValueError("primary and standby holder refs must differ")
    if lease_seconds < 10 or lease_seconds > 300:
        raise ValueError("lease_seconds must be between 10 and 300")
    if (
        renew_interval_seconds <= 0
        or renew_interval_seconds >= lease_seconds
    ):
        raise ValueError("renew interval must be positive and shorter than lease")
    if rto_seconds <= 0 or rto_seconds > 300:
        raise ValueError("RTO must be positive and at most five minutes")
    if poll_interval_seconds <= 0:
        raise ValueError("poll interval must be positive")


def _validate_publisher_fence(
    owner: PublisherArticleSyncOwner,
    *,
    expected_generation: int,
) -> PublisherFenceEvidence:
    if (
        not isinstance(owner, PublisherArticleSyncOwner)
        or owner.effect_family != _PUBLISHER_FAMILY
        or owner.owner != "operations_core"
        or owner.generation != expected_generation
    ):
        raise RuntimeError(
            "publisher fence is not the expected operations-core generation"
        )
    return PublisherFenceEvidence(
        effect_family=owner.effect_family,
        owner=owner.owner,
        generation=owner.generation,
        changed_at=owner.changed_at,
    )


def _authority_key_for_rehearsal(rehearsal_id: str) -> str:
    if (
        not isinstance(rehearsal_id, str)
        or _REHEARSAL_ID.fullmatch(rehearsal_id) is None
    ):
        raise ValueError(
            "rehearsal_id must be 6-64 safe filename characters"
        )
    digest = hashlib.sha256(rehearsal_id.encode("utf-8")).hexdigest()[:32]
    return f"{_SAFE_AUTHORITY_PREFIX}{digest}"


def _validate_process_inputs(
    *,
    host_id: str,
    host_fingerprint: str,
    holder_ref: str,
    lease_seconds: int,
    renew_interval_seconds: float,
    poll_interval_seconds: float,
) -> None:
    if not host_id.strip() or not host_fingerprint.strip():
        raise ValueError("host identity and fingerprint are required")
    if not holder_ref.strip():
        raise ValueError("holder_ref is required")
    if lease_seconds < 10 or lease_seconds > 300:
        raise ValueError("lease_seconds must be between 10 and 300")
    if (
        renew_interval_seconds <= 0
        or renew_interval_seconds >= lease_seconds
    ):
        raise ValueError("renew interval must be positive and shorter than lease")
    if poll_interval_seconds <= 0:
        raise ValueError("poll interval must be positive")


def _timestamp(value: str, *, field: str) -> datetime:
    try:
        observed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be an ISO timestamp") from None
    if observed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return observed.astimezone(UTC)


def _receipt_sha256(receipt: object) -> str:
    payload = json.dumps(
        asdict(receipt),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _implementation_sha256() -> str:
    payload = json.dumps(
        _implementation_manifest(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _implementation_manifest() -> dict[str, str]:
    """Bind cross-host evidence to every Operations Core Python source."""

    repo_root = Path(__file__).resolve().parents[1]
    source_root = repo_root / "src" / "volpred" / "ops"
    paths = [Path(__file__).resolve(), *sorted(source_root.rglob("*.py"))]
    if not source_root.is_dir() or len(paths) == 1:
        raise RuntimeError(
            "Operations Core source tree is unavailable for receipt identity"
        )
    return {
        path.relative_to(repo_root).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in paths
    }


def _verify_implementation_unchanged(expected_sha256: str) -> None:
    """Refuse evidence if the checkout changed while a role was running."""

    if _implementation_sha256() != expected_sha256:
        raise RuntimeError(
            "Operations Core source changed during outage rehearsal"
        )


def _machine_identity() -> tuple[str, str]:
    host_id = socket.gethostname().strip() or "unknown-host"
    material = f"{host_id}\0{getnode():012x}".encode("utf-8")
    fingerprint = hashlib.sha256(material).hexdigest()[:24]
    return host_id, fingerprint


def _load_primary_receipt(path: Path) -> PrimaryProcessReceipt:
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["primary"] = AuthorityLeaseEvidence(**payload["primary"])
    payload["publisher_fence_before"] = PublisherFenceEvidence(
        **payload["publisher_fence_before"]
    )
    payload["publisher_fence_after"] = PublisherFenceEvidence(
        **payload["publisher_fence_after"]
    )
    return PrimaryProcessReceipt(**payload)


def _load_standby_receipt(path: Path) -> StandbyProcessReceipt:
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["standby"] = AuthorityLeaseEvidence(**payload["standby"])
    payload["publisher_fence_before"] = PublisherFenceEvidence(
        **payload["publisher_fence_before"]
    )
    payload["publisher_fence_after"] = PublisherFenceEvidence(
        **payload["publisher_fence_after"]
    )
    return StandbyProcessReceipt(**payload)


def _lease_evidence(lease: PrimaryLease) -> AuthorityLeaseEvidence:
    return AuthorityLeaseEvidence(
        holder_ref=lease.holder_ref,
        epoch=lease.epoch,
        acquired_at=lease.acquired_at,
        expires_at=lease.expires_at,
    )


def _best_effort_stop(keepalive: HostAuthorityKeepalive) -> None:
    try:
        keepalive.stop()
    except AuthorityInactive:
        pass  # silent-ok: finally cleanup of an already-demoted session


def _write_receipt(path: Path, receipt: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    payload = json.dumps(
        asdict(receipt),
        ensure_ascii=False,
        indent=2,
    ) + "\n"
    try:
        temporary.write_text(payload, encoding="utf-8")
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        saved = json.loads(path.read_text(encoding="utf-8"))
        if saved != asdict(receipt):
            raise RuntimeError("saved outage receipt failed exact read-back")
    finally:
        temporary.unlink(missing_ok=True)


def _add_runtime_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--lease-seconds", type=int, default=300)
    parser.add_argument("--poll-interval-seconds", type=float, default=1.0)
    parser.add_argument("--expected-publisher-generation", type=int, default=8)
    parser.add_argument(
        "--receipt-path",
        required=True,
        help="atomically save the token-redacted JSON receipt",
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Rehearse a live Supabase Primary Authority renewal outage with "
            "provider effects structurally disabled."
        )
    )
    roles = parser.add_subparsers(dest="role", required=True)

    single = roles.add_parser(
        "single-host",
        help="run the original single-process outage rehearsal",
    )
    _add_runtime_arguments(single)
    single.add_argument(
        "--renew-interval-seconds", type=float, default=60.0
    )
    single.add_argument("--rto-seconds", type=float, default=300.0)

    primary = roles.add_parser(
        "primary",
        help="run the partitioned primary role on the first physical host",
    )
    _add_runtime_arguments(primary)
    primary.add_argument("--rehearsal-id", required=True)
    primary.add_argument(
        "--renew-interval-seconds", type=float, default=60.0
    )

    standby = roles.add_parser(
        "standby",
        help="run the takeover role on the second physical host",
    )
    _add_runtime_arguments(standby)
    standby.add_argument("--rehearsal-id", required=True)
    standby.add_argument("--expected-primary-epoch", required=True, type=int)
    standby.add_argument("--rto-seconds", type=float, default=300.0)

    verify = roles.add_parser(
        "verify-pair",
        help="verify and bind the two physical-host receipts",
    )
    verify.add_argument("--primary-receipt", required=True)
    verify.add_argument("--standby-receipt", required=True)
    verify.add_argument("--receipt-path", required=True)
    verify.add_argument("--max-handoff-seconds", type=float, default=300.0)

    values = list(sys.argv[1:] if argv is None else argv)
    if (
        values
        and values[0].startswith("-")
        and values[0] not in {"-h", "--help"}
    ):
        values.insert(0, "single-host")
    return parser.parse_args(values)


def main() -> int:
    args = _parse_args()
    if args.role == "verify-pair":
        receipt = verify_cross_host_receipts(
            _load_primary_receipt(Path(args.primary_receipt)),
            _load_standby_receipt(Path(args.standby_receipt)),
            max_handoff_seconds=args.max_handoff_seconds,
        )
    elif args.role == "single-host":
        authority_key = f"{_SAFE_AUTHORITY_PREFIX}{uuid4().hex}"
        host = socket.gethostname().strip() or "unknown-host"
        receipt = rehearse_primary_authority_outage(
            authority_key=authority_key,
            primary_holder_ref=f"host:{host}:outage-primary:{uuid4().hex}",
            standby_holder_ref=f"host:{host}:outage-standby:{uuid4().hex}",
            lease_seconds=args.lease_seconds,
            renew_interval_seconds=args.renew_interval_seconds,
            rto_seconds=args.rto_seconds,
            poll_interval_seconds=args.poll_interval_seconds,
            store=PartitionableAuthorityStore.from_environment(),
            publisher_store=(
                SupabaseOwnedPublisherArticleStore.from_environment()
            ),
            expected_publisher_generation=(
                args.expected_publisher_generation
            ),
        )
    else:
        host_id, host_fingerprint = _machine_identity()
        holder_ref = (
            f"host:{host_fingerprint}:outage-{args.role}:"
            f"{args.rehearsal_id}"
        )
        publisher_store = (
            SupabaseOwnedPublisherArticleStore.from_environment()
        )
        if args.role == "primary":
            receipt = rehearse_primary_process_role(
                rehearsal_id=args.rehearsal_id,
                host_id=host_id,
                host_fingerprint=host_fingerprint,
                holder_ref=holder_ref,
                lease_seconds=args.lease_seconds,
                renew_interval_seconds=args.renew_interval_seconds,
                poll_interval_seconds=args.poll_interval_seconds,
                store=PartitionableAuthorityStore.from_environment(),
                publisher_store=publisher_store,
                expected_publisher_generation=(
                    args.expected_publisher_generation
                ),
            )
        else:
            receipt = rehearse_standby_process_role(
                rehearsal_id=args.rehearsal_id,
                host_id=host_id,
                host_fingerprint=host_fingerprint,
                holder_ref=holder_ref,
                expected_primary_epoch=args.expected_primary_epoch,
                lease_seconds=args.lease_seconds,
                rto_seconds=args.rto_seconds,
                poll_interval_seconds=args.poll_interval_seconds,
                store=SupabaseAuthorityStore.from_environment(),
                publisher_store=publisher_store,
                expected_publisher_generation=(
                    args.expected_publisher_generation
                ),
            )
    _write_receipt(Path(args.receipt_path), receipt)
    print(json.dumps(asdict(receipt), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
