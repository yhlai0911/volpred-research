from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from scripts.rehearse_primary_authority_outage import (
    PartitionableAuthorityStore,
    PrimaryProcessReceipt,
    StandbyProcessReceipt,
    _write_receipt,
    rehearse_primary_authority_outage,
    rehearse_primary_process_role,
    rehearse_standby_process_role,
    verify_cross_host_receipts,
)
from volpred.ops.authority import (
    AuthorityReceipt,
    AuthorityRequest,
    PrimaryLease,
)
from volpred.ops.delivery.owned_publisher_article import (
    PublisherArticleSyncOwner,
)


class _LiveAuthorityStore:
    def __init__(self, *, lease_window_seconds: float = 0.12) -> None:
        self.lease_window_seconds = lease_window_seconds
        self.current: PrimaryLease | None = None
        self.epoch = 0
        self.acquire_successes = 0
        self.authorize_calls = 0

    def acquire(
        self,
        request: AuthorityRequest,
        *,
        fencing_token: str,
    ) -> PrimaryLease:
        now = datetime.now(UTC)
        if (
            self.current is not None
            and datetime.fromisoformat(self.current.expires_at) > now
            and (
                self.current.holder_ref != request.holder_ref
                or self.current.fencing_token != fencing_token
            )
        ):
            raise ValueError("Primary Authority is already held")
        self.epoch += 1
        self.acquire_successes += 1
        self.current = PrimaryLease(
            schema_version="primary-lease.v1",
            authority_key=request.authority_key,
            holder_ref=request.holder_ref,
            epoch=self.epoch,
            fencing_token=fencing_token,
            lease_seconds=request.lease_seconds,
            acquired_at=now.isoformat(),
            expires_at=(
                now + timedelta(seconds=self.lease_window_seconds)
            ).isoformat(),
        )
        return self.current

    def renew(self, lease: PrimaryLease) -> PrimaryLease:
        if lease != self.current:
            raise ValueError("Primary Authority lease lost")
        now = datetime.now(UTC)
        self.current = replace(
            lease,
            expires_at=(
                now + timedelta(seconds=self.lease_window_seconds)
            ).isoformat(),
        )
        return self.current

    def authorize(self, _intent):
        self.authorize_calls += 1
        raise AssertionError("outage rehearsal must not authorize effects")

    def release(self, lease: PrimaryLease) -> AuthorityReceipt:
        if lease != self.current:
            raise ValueError("Primary Authority lease lost")
        self.current = None
        return AuthorityReceipt(
            schema_version="primary-authority-receipt.v1",
            authority_key=lease.authority_key,
            holder_ref=lease.holder_ref,
            epoch=lease.epoch,
            primary_authority_ref=(
                f"primary-authority:{lease.authority_key}:epoch-{lease.epoch}"
            ),
            released_at=datetime.now(UTC).isoformat(),
        )


class _UnavailableAuthorityStore:
    def acquire(self, *_args, **_kwargs):
        raise RuntimeError("Operations Core RPC unavailable")

    def renew(self, *_args, **_kwargs):
        raise RuntimeError("Operations Core RPC unavailable")

    def authorize(self, *_args, **_kwargs):
        raise RuntimeError("Operations Core RPC unavailable")

    def release(self, *_args, **_kwargs):
        raise RuntimeError("Operations Core RPC unavailable")


class _PublisherStore:
    def __init__(self, generation: int = 8) -> None:
        self.owner = PublisherArticleSyncOwner(
            schema_version="publisher-article-sync-owner.v1",
            effect_family="publisher.article.supabase.sync",
            owner="operations_core",
            generation=generation,
            changed_at="2026-07-25T00:00:00+00:00",
            changed_by="operator:test",
            change_reason="test",
        )
        self.read_count = 0

    def read_owner(self) -> PublisherArticleSyncOwner:
        self.read_count += 1
        return self.owner


def test_live_outage_closes_gate_and_standby_reacquires_next_epoch() -> None:
    live = _LiveAuthorityStore()
    publisher = _PublisherStore()
    store = PartitionableAuthorityStore(
        healthy=live,
        unavailable=_UnavailableAuthorityStore(),
    )

    receipt = rehearse_primary_authority_outage(
        authority_key="operations-core-outage-smoke-test",
        primary_holder_ref="host:a",
        standby_holder_ref="host:b",
        lease_seconds=10,
        renew_interval_seconds=0.01,
        rto_seconds=1.0,
        poll_interval_seconds=0.005,
        store=store,
        publisher_store=publisher,
        expected_publisher_generation=8,
    )

    assert receipt.schema_version == "primary-authority-outage-rehearsal.v1"
    assert receipt.primary.epoch == 1
    assert receipt.standby.epoch == 2
    assert (
        datetime.fromisoformat(receipt.primary.expires_at)
        > datetime.fromisoformat(receipt.primary.acquired_at)
    )
    assert receipt.healthy_renewal_count >= 1
    assert receipt.local_gate_closed is True
    assert receipt.partition_probe_rejected is True
    assert receipt.recovery_rto_seconds < 1.0
    assert receipt.successful_authority_claims == 2
    assert receipt.duplicate_authority_claims == 0
    assert receipt.effect_requests == receipt.provider_calls == 0
    assert receipt.final_standby_state == "stopped"
    assert publisher.read_count == 2
    assert live.acquire_successes == 2
    assert live.authorize_calls == 0
    assert live.current is None


def test_rehearsal_refuses_non_smoke_authority_key_before_remote_read() -> None:
    publisher = _PublisherStore()
    store = PartitionableAuthorityStore(
        healthy=_LiveAuthorityStore(),
        unavailable=_UnavailableAuthorityStore(),
    )

    with pytest.raises(ValueError, match="isolated generated authority key"):
        rehearse_primary_authority_outage(
            authority_key="operations-core-effects",
            primary_holder_ref="host:a",
            standby_holder_ref="host:b",
            lease_seconds=10,
            renew_interval_seconds=0.01,
            rto_seconds=1.0,
            poll_interval_seconds=0.005,
            store=store,
            publisher_store=publisher,
            expected_publisher_generation=8,
        )

    assert publisher.read_count == 0


def test_rehearsal_refuses_publisher_fence_drift_before_acquire() -> None:
    live = _LiveAuthorityStore()
    publisher = _PublisherStore(generation=9)
    store = PartitionableAuthorityStore(
        healthy=live,
        unavailable=_UnavailableAuthorityStore(),
    )

    with pytest.raises(RuntimeError, match="publisher fence"):
        rehearse_primary_authority_outage(
            authority_key="operations-core-outage-smoke-test",
            primary_holder_ref="host:a",
            standby_holder_ref="host:b",
            lease_seconds=10,
            renew_interval_seconds=0.01,
            rto_seconds=1.0,
            poll_interval_seconds=0.005,
            store=store,
            publisher_store=publisher,
            expected_publisher_generation=8,
        )

    assert live.acquire_successes == 0


def test_receipt_writer_round_trips_exact_payload(
    tmp_path,
) -> None:
    live = _LiveAuthorityStore()
    store = PartitionableAuthorityStore(
        healthy=live,
        unavailable=_UnavailableAuthorityStore(),
    )
    receipt = rehearse_primary_authority_outage(
        authority_key="operations-core-outage-smoke-test",
        primary_holder_ref="host:a",
        standby_holder_ref="host:b",
        lease_seconds=10,
        renew_interval_seconds=0.01,
        rto_seconds=1.0,
        poll_interval_seconds=0.005,
        store=store,
        publisher_store=_PublisherStore(),
        expected_publisher_generation=8,
    )
    target = tmp_path / "receipts" / "outage.json"

    _write_receipt(target, receipt)

    assert target.is_file()
    assert json.loads(target.read_text())["standby"]["epoch"] == 2
    assert list(target.parent.glob("*.tmp")) == []


def test_process_roles_produce_verifiable_cross_host_handoff(tmp_path) -> None:
    live = _LiveAuthorityStore()
    primary_store = PartitionableAuthorityStore(
        healthy=live,
        unavailable=_UnavailableAuthorityStore(),
    )
    publisher = _PublisherStore()

    primary = rehearse_primary_process_role(
        rehearsal_id="cross-host-test",
        host_id="primary-mac",
        host_fingerprint="primary-fingerprint",
        holder_ref="host:primary:outage",
        lease_seconds=10,
        renew_interval_seconds=0.01,
        poll_interval_seconds=0.005,
        store=primary_store,
        publisher_store=publisher,
        expected_publisher_generation=8,
    )
    standby = rehearse_standby_process_role(
        rehearsal_id="cross-host-test",
        host_id="standby-mac",
        host_fingerprint="standby-fingerprint",
        holder_ref="host:standby:outage",
        expected_primary_epoch=primary.primary.epoch,
        lease_seconds=10,
        rto_seconds=1.0,
        poll_interval_seconds=0.005,
        store=live,
        publisher_store=publisher,
        expected_publisher_generation=8,
    )
    paired = verify_cross_host_receipts(primary, standby)
    paired_path = tmp_path / "cross-host.json"
    _write_receipt(paired_path, paired)

    assert isinstance(primary, PrimaryProcessReceipt)
    assert primary.final_primary_state == "demoted"
    assert primary.local_gate_closed is True
    assert isinstance(standby, StandbyProcessReceipt)
    assert standby.standby.epoch == primary.primary.epoch + 1
    assert standby.final_standby_state == "stopped"
    assert paired.schema_version == (
        "primary-authority-outage-cross-host.v1"
    )
    assert paired.database_clock_handoff_seconds >= 0
    assert paired.successful_authority_claims == 2
    assert paired.duplicate_authority_claims == 0
    assert paired.effect_requests == paired.provider_calls == 0
    assert paired.cross_host_verified is True
    saved_pair = json.loads(paired_path.read_text())
    assert saved_pair["schema_version"] == (
        "primary-authority-outage-cross-host.v1"
    )
    assert saved_pair["primary_receipt_sha256"] == (
        paired.primary_receipt_sha256
    )
    assert saved_pair["cross_host_verified"] is True
    assert live.authorize_calls == 0
    assert live.current is None


def test_pair_verifier_rejects_same_machine_fingerprint() -> None:
    live = _LiveAuthorityStore()
    publisher = _PublisherStore()
    primary = rehearse_primary_process_role(
        rehearsal_id="same-machine-test",
        host_id="mac-a",
        host_fingerprint="shared-fingerprint",
        holder_ref="host:a:outage",
        lease_seconds=10,
        renew_interval_seconds=0.01,
        poll_interval_seconds=0.005,
        store=PartitionableAuthorityStore(
            healthy=live,
            unavailable=_UnavailableAuthorityStore(),
        ),
        publisher_store=publisher,
        expected_publisher_generation=8,
    )
    standby = rehearse_standby_process_role(
        rehearsal_id="same-machine-test",
        host_id="mac-b",
        host_fingerprint="shared-fingerprint",
        holder_ref="host:b:outage",
        expected_primary_epoch=primary.primary.epoch,
        lease_seconds=10,
        rto_seconds=1.0,
        poll_interval_seconds=0.005,
        store=live,
        publisher_store=publisher,
        expected_publisher_generation=8,
    )

    with pytest.raises(ValueError, match="two distinct machines"):
        verify_cross_host_receipts(primary, standby)

    with pytest.raises(ValueError, match="different rehearsal code"):
        verify_cross_host_receipts(
            primary,
            replace(
                standby,
                host_fingerprint="standby-fingerprint",
                implementation_sha256="0" * 64,
            ),
        )
