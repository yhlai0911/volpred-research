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
import json
import os
import socket
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Protocol
from uuid import uuid4

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
            accept=lambda status: status.state == "demoted",
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


def _write_receipt(path: Path, receipt: PrimaryAuthorityOutageReceipt) -> None:
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


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Rehearse a live Supabase Primary Authority renewal outage with "
            "provider effects structurally disabled."
        )
    )
    parser.add_argument("--lease-seconds", type=int, default=300)
    parser.add_argument("--renew-interval-seconds", type=float, default=60.0)
    parser.add_argument("--rto-seconds", type=float, default=300.0)
    parser.add_argument("--poll-interval-seconds", type=float, default=1.0)
    parser.add_argument("--expected-publisher-generation", type=int, default=8)
    parser.add_argument(
        "--receipt-path",
        help="atomically save the token-redacted JSON receipt",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
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
        publisher_store=SupabaseOwnedPublisherArticleStore.from_environment(),
        expected_publisher_generation=args.expected_publisher_generation,
    )
    if args.receipt_path:
        _write_receipt(Path(args.receipt_path), receipt)
    print(json.dumps(asdict(receipt), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
