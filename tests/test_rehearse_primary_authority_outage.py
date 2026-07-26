from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

import scripts.rehearse_primary_authority_outage as outage_operator
from scripts.rehearse_primary_authority_outage import (
    CrossHostReadinessReceipt,
    HostReadinessReceipt,
    PartitionableAuthorityStore,
    PrimaryProcessReceipt,
    StandbyProcessReceipt,
    _authority_key_for_rehearsal,
    _implementation_manifest,
    _implementation_sha256,
    _validate_role_readiness,
    _write_receipt,
    prepare_cross_host_role_readiness,
    rehearse_primary_authority_outage,
    rehearse_primary_process_role,
    rehearse_standby_process_role,
    verify_cross_host_readiness,
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
    def __init__(self, *, lease_window_seconds: float = 0.25) -> None:
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


def _paired_readiness(
    *,
    rehearsal_id: str,
    publisher: _PublisherStore,
    primary_host_id: str = "primary-mac",
    primary_host_fingerprint: str = "primary-fingerprint",
    standby_host_id: str = "standby-mac",
    standby_host_fingerprint: str = "standby-fingerprint",
) -> CrossHostReadinessReceipt:
    primary = prepare_cross_host_role_readiness(
        rehearsal_id=rehearsal_id,
        role="primary",
        host_id=primary_host_id,
        host_fingerprint=primary_host_fingerprint,
        publisher_store=publisher,
        expected_publisher_generation=8,
    )
    standby = prepare_cross_host_role_readiness(
        rehearsal_id=rehearsal_id,
        role="standby",
        host_id=standby_host_id,
        host_fingerprint=standby_host_fingerprint,
        publisher_store=publisher,
        expected_publisher_generation=8,
    )
    return verify_cross_host_readiness(primary, standby)


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


def test_cross_host_readiness_fails_before_authority_mutation() -> None:
    publisher = _PublisherStore()
    primary = prepare_cross_host_role_readiness(
        rehearsal_id="physical-ready-test",
        role="primary",
        host_id="primary-mac",
        host_fingerprint="primary-fingerprint",
        publisher_store=publisher,
        expected_publisher_generation=8,
    )
    standby = prepare_cross_host_role_readiness(
        rehearsal_id="physical-ready-test",
        role="standby",
        host_id="standby-mac",
        host_fingerprint="standby-fingerprint",
        publisher_store=publisher,
        expected_publisher_generation=8,
    )

    paired = verify_cross_host_readiness(primary, standby)

    assert isinstance(primary, HostReadinessReceipt)
    assert isinstance(paired, CrossHostReadinessReceipt)
    assert paired.cross_host_ready is True
    assert paired.primary_host_fingerprint == "primary-fingerprint"
    assert paired.standby_host_fingerprint == "standby-fingerprint"
    assert publisher.read_count == 2

    with pytest.raises(ValueError, match="same source"):
        verify_cross_host_readiness(
            primary,
            replace(standby, implementation_sha256="0" * 64),
        )
    with pytest.raises(ValueError, match="two distinct physical machines"):
        verify_cross_host_readiness(
            primary,
            replace(standby, host_fingerprint=primary.host_fingerprint),
        )


def test_role_readiness_rejects_wrong_machine_or_stale_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    publisher = _PublisherStore()
    primary = prepare_cross_host_role_readiness(
        rehearsal_id="role-ready-test",
        role="primary",
        host_id="primary-mac",
        host_fingerprint="primary-fingerprint",
        publisher_store=publisher,
        expected_publisher_generation=8,
    )
    standby = prepare_cross_host_role_readiness(
        rehearsal_id="role-ready-test",
        role="standby",
        host_id="standby-mac",
        host_fingerprint="standby-fingerprint",
        publisher_store=publisher,
        expected_publisher_generation=8,
    )
    paired = verify_cross_host_readiness(primary, standby)

    _validate_role_readiness(
        paired,
        rehearsal_id="role-ready-test",
        role="primary",
        host_id="primary-mac",
        host_fingerprint="primary-fingerprint",
        expected_publisher_generation=8,
    )
    with pytest.raises(ValueError, match="does not match its readiness role"):
        _validate_role_readiness(
            paired,
            rehearsal_id="role-ready-test",
            role="standby",
            host_id="primary-mac",
            host_fingerprint="primary-fingerprint",
            expected_publisher_generation=8,
        )

    monkeypatch.setattr(
        outage_operator,
        "_implementation_sha256",
        lambda: "0" * 64,
    )
    with pytest.raises(ValueError, match="source drifted"):
        _validate_role_readiness(
            paired,
            rehearsal_id="role-ready-test",
            role="primary",
            host_id="primary-mac",
            host_fingerprint="primary-fingerprint",
            expected_publisher_generation=8,
        )


def test_primary_rechecks_readiness_source_before_remote_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    live = _LiveAuthorityStore()
    publisher = _PublisherStore()
    readiness = _paired_readiness(
        rehearsal_id="ready-race-test",
        publisher=publisher,
    )
    digests = iter((readiness.implementation_sha256, "2" * 64))
    monkeypatch.setattr(
        outage_operator,
        "_implementation_sha256",
        lambda: next(digests),
    )

    with pytest.raises(
        RuntimeError,
        match="source drifted after cross-host readiness",
    ):
        rehearse_primary_process_role(
            rehearsal_id="ready-race-test",
            host_id="primary-mac",
            host_fingerprint="primary-fingerprint",
            lease_seconds=10,
            renew_interval_seconds=0.01,
            poll_interval_seconds=0.005,
            store=PartitionableAuthorityStore(
                healthy=live,
                unavailable=_UnavailableAuthorityStore(),
            ),
            publisher_store=publisher,
            expected_publisher_generation=8,
            readiness=readiness,
        )

    assert publisher.read_count == 2
    assert live.acquire_successes == 0


def test_process_roles_produce_verifiable_cross_host_handoff(tmp_path) -> None:
    live = _LiveAuthorityStore()
    primary_store = PartitionableAuthorityStore(
        healthy=live,
        unavailable=_UnavailableAuthorityStore(),
    )
    publisher = _PublisherStore()
    readiness = _paired_readiness(
        rehearsal_id="cross-host-test",
        publisher=publisher,
    )

    primary = rehearse_primary_process_role(
        rehearsal_id="cross-host-test",
        host_id="primary-mac",
        host_fingerprint="primary-fingerprint",
        lease_seconds=10,
        renew_interval_seconds=0.01,
        poll_interval_seconds=0.005,
        store=primary_store,
        publisher_store=publisher,
        expected_publisher_generation=8,
        readiness=readiness,
    )
    standby = rehearse_standby_process_role(
        rehearsal_id="cross-host-test",
        host_id="standby-mac",
        host_fingerprint="standby-fingerprint",
        primary_receipt=primary,
        lease_seconds=10,
        rto_seconds=1.0,
        poll_interval_seconds=0.005,
        store=live,
        publisher_store=publisher,
        expected_publisher_generation=8,
        readiness=readiness,
    )
    paired = verify_cross_host_receipts(
        primary,
        standby,
        readiness=readiness,
    )
    paired_path = tmp_path / "cross-host.json"
    _write_receipt(paired_path, paired)

    assert isinstance(primary, PrimaryProcessReceipt)
    assert primary.final_primary_state == "demoted"
    assert primary.local_gate_closed is True
    assert primary.primary.holder_ref == (
        "host:primary-fingerprint:outage-primary:cross-host-test"
    )
    assert isinstance(standby, StandbyProcessReceipt)
    assert standby.standby.epoch == primary.primary.epoch + 1
    assert standby.final_standby_state == "stopped"
    assert standby.standby.holder_ref == (
        "host:standby-fingerprint:outage-standby:cross-host-test"
    )
    assert paired.schema_version == (
        "primary-authority-outage-cross-host.v3"
    )
    assert standby.schema_version == "primary-authority-outage-standby.v3"
    assert (
        standby.primary_receipt_sha256
        == paired.primary_receipt_sha256
    )
    assert (
        primary.cross_host_readiness_sha256
        == standby.cross_host_readiness_sha256
        == paired.cross_host_readiness_sha256
    )
    assert paired.database_clock_handoff_seconds >= 0
    assert paired.successful_authority_claims == 2
    assert paired.duplicate_authority_claims == 0
    assert paired.effect_requests == paired.provider_calls == 0
    assert paired.cross_host_verified is True
    saved_pair = json.loads(paired_path.read_text())
    assert saved_pair["schema_version"] == (
        "primary-authority-outage-cross-host.v3"
    )
    assert saved_pair["primary_receipt_sha256"] == (
        paired.primary_receipt_sha256
    )
    assert saved_pair["cross_host_verified"] is True
    assert live.authorize_calls == 0
    assert live.current is None


def test_standby_rejects_unbound_primary_receipt_before_remote_read() -> None:
    live = _LiveAuthorityStore()
    publisher = _PublisherStore()
    readiness = _paired_readiness(
        rehearsal_id="standby-primary-preflight",
        publisher=publisher,
    )
    primary = rehearse_primary_process_role(
        rehearsal_id="standby-primary-preflight",
        host_id="primary-mac",
        host_fingerprint="primary-fingerprint",
        lease_seconds=10,
        renew_interval_seconds=0.01,
        poll_interval_seconds=0.005,
        store=PartitionableAuthorityStore(
            healthy=live,
            unavailable=_UnavailableAuthorityStore(),
        ),
        publisher_store=publisher,
        expected_publisher_generation=8,
        readiness=readiness,
    )
    remote_reads_before = publisher.read_count

    with pytest.raises(ValueError, match="fail-closed evidence"):
        rehearse_standby_process_role(
            rehearsal_id="standby-primary-preflight",
            host_id="standby-mac",
            host_fingerprint="standby-fingerprint",
            primary_receipt=replace(primary, local_gate_closed=False),
            lease_seconds=10,
            rto_seconds=1.0,
            poll_interval_seconds=0.005,
            store=live,
            publisher_store=publisher,
            expected_publisher_generation=8,
            readiness=readiness,
        )

    assert publisher.read_count == remote_reads_before
    assert live.acquire_successes == 1


def test_pair_verifier_rejects_process_receipt_from_other_readiness() -> None:
    live = _LiveAuthorityStore()
    publisher = _PublisherStore()
    readiness = _paired_readiness(
        rehearsal_id="readiness-binding-test",
        publisher=publisher,
    )
    primary = rehearse_primary_process_role(
        rehearsal_id="readiness-binding-test",
        host_id="primary-mac",
        host_fingerprint="primary-fingerprint",
        lease_seconds=10,
        renew_interval_seconds=0.01,
        poll_interval_seconds=0.005,
        store=PartitionableAuthorityStore(
            healthy=live,
            unavailable=_UnavailableAuthorityStore(),
        ),
        publisher_store=publisher,
        expected_publisher_generation=8,
        readiness=readiness,
    )
    standby = rehearse_standby_process_role(
        rehearsal_id="readiness-binding-test",
        host_id="standby-mac",
        host_fingerprint="standby-fingerprint",
        primary_receipt=primary,
        lease_seconds=10,
        rto_seconds=1.0,
        poll_interval_seconds=0.005,
        store=live,
        publisher_store=publisher,
        expected_publisher_generation=8,
        readiness=readiness,
    )

    with pytest.raises(ValueError, match="not bound to this"):
        verify_cross_host_receipts(
            primary,
            replace(
                standby,
                cross_host_readiness_sha256="0" * 64,
            ),
            readiness=readiness,
        )


def test_pair_verifier_rejects_primary_artifact_not_used_by_standby() -> None:
    live = _LiveAuthorityStore()
    publisher = _PublisherStore()
    readiness = _paired_readiness(
        rehearsal_id="primary-artifact-binding",
        publisher=publisher,
    )
    primary = rehearse_primary_process_role(
        rehearsal_id="primary-artifact-binding",
        host_id="primary-mac",
        host_fingerprint="primary-fingerprint",
        lease_seconds=10,
        renew_interval_seconds=0.01,
        poll_interval_seconds=0.005,
        store=PartitionableAuthorityStore(
            healthy=live,
            unavailable=_UnavailableAuthorityStore(),
        ),
        publisher_store=publisher,
        expected_publisher_generation=8,
        readiness=readiness,
    )
    standby = rehearse_standby_process_role(
        rehearsal_id="primary-artifact-binding",
        host_id="standby-mac",
        host_fingerprint="standby-fingerprint",
        primary_receipt=primary,
        lease_seconds=10,
        rto_seconds=1.0,
        poll_interval_seconds=0.005,
        store=live,
        publisher_store=publisher,
        expected_publisher_generation=8,
        readiness=readiness,
    )

    with pytest.raises(
        ValueError,
        match="standby is not bound to this primary receipt",
    ):
        verify_cross_host_receipts(
            replace(
                primary,
                completed_at="2026-07-26T00:00:00+00:00",
            ),
            standby,
            readiness=readiness,
        )


def test_pair_verifier_rejects_same_machine_fingerprint() -> None:
    live = _LiveAuthorityStore()
    publisher = _PublisherStore()
    readiness = _paired_readiness(
        rehearsal_id="same-machine-test",
        publisher=publisher,
        primary_host_id="mac-a",
        primary_host_fingerprint="fingerprint-a",
        standby_host_id="mac-b",
        standby_host_fingerprint="fingerprint-b",
    )
    primary = rehearse_primary_process_role(
        rehearsal_id="same-machine-test",
        host_id="mac-a",
        host_fingerprint="fingerprint-a",
        lease_seconds=10,
        renew_interval_seconds=0.01,
        poll_interval_seconds=0.005,
        store=PartitionableAuthorityStore(
            healthy=live,
            unavailable=_UnavailableAuthorityStore(),
        ),
        publisher_store=publisher,
        expected_publisher_generation=8,
        readiness=readiness,
    )
    standby = rehearse_standby_process_role(
        rehearsal_id="same-machine-test",
        host_id="mac-b",
        host_fingerprint="fingerprint-b",
        primary_receipt=primary,
        lease_seconds=10,
        rto_seconds=1.0,
        poll_interval_seconds=0.005,
        store=live,
        publisher_store=publisher,
        expected_publisher_generation=8,
        readiness=readiness,
    )

    with pytest.raises(ValueError, match="two distinct physical machines"):
        verify_cross_host_receipts(
            primary,
            standby,
            readiness=replace(
                readiness,
                standby_host_fingerprint=readiness.primary_host_fingerprint,
            ),
        )

    with pytest.raises(ValueError, match="different rehearsal code"):
        verify_cross_host_receipts(
            primary,
            replace(
                standby,
                host_fingerprint="standby-fingerprint",
                implementation_sha256="0" * 64,
            ),
            readiness=readiness,
        )

    with pytest.raises(ValueError, match="standby authority holder"):
        verify_cross_host_receipts(
            primary,
            replace(
                standby,
                standby=replace(
                    standby.standby,
                    holder_ref="host:forged",
                ),
            ),
            readiness=readiness,
        )


def test_pair_identity_binds_safe_key_sources_and_runtime_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = _implementation_manifest()

    assert {
        "pyproject.toml",
        "scripts/rehearse_primary_authority_outage.py",
        "src/volpred/ops/authority/__init__.py",
        "src/volpred/ops/authority/keepalive.py",
        "src/volpred/ops/authority/session.py",
        "src/volpred/ops/authority/supabase.py",
        "src/volpred/ops/delivery/owned_publisher_article.py",
        "src/volpred/ops/delivery/supabase_rpc.py",
        "runtime/python-ssl.json",
        "uv.lock",
    } <= manifest.keys()
    assert all(len(digest) == 64 for digest in manifest.values())
    assert len(_implementation_sha256()) == 64
    runtime_digest = manifest["runtime/python-ssl.json"]
    monkeypatch.setattr(
        outage_operator.platform,
        "python_version",
        lambda: "0.0-runtime-drift",
    )
    assert (
        _implementation_manifest()["runtime/python-ssl.json"]
        != runtime_digest
    )

    live = _LiveAuthorityStore()
    publisher = _PublisherStore()
    readiness = _paired_readiness(
        rehearsal_id="unsafe-key-test",
        publisher=publisher,
        primary_host_id="mac-a",
        primary_host_fingerprint="fingerprint-a",
        standby_host_id="mac-b",
        standby_host_fingerprint="fingerprint-b",
    )
    primary = rehearse_primary_process_role(
        rehearsal_id="unsafe-key-test",
        host_id="mac-a",
        host_fingerprint="fingerprint-a",
        lease_seconds=10,
        renew_interval_seconds=0.01,
        poll_interval_seconds=0.005,
        store=PartitionableAuthorityStore(
            healthy=live,
            unavailable=_UnavailableAuthorityStore(),
        ),
        publisher_store=publisher,
        expected_publisher_generation=8,
        readiness=readiness,
    )
    standby = rehearse_standby_process_role(
        rehearsal_id="unsafe-key-test",
        host_id="mac-b",
        host_fingerprint="fingerprint-b",
        primary_receipt=primary,
        lease_seconds=10,
        rto_seconds=1.0,
        poll_interval_seconds=0.005,
        store=live,
        publisher_store=publisher,
        expected_publisher_generation=8,
        readiness=readiness,
    )
    unsafe_key = "operations-core-effects"

    with pytest.raises(
        ValueError,
        match="not derived from rehearsal identity",
    ):
        verify_cross_host_receipts(
            replace(primary, authority_key=unsafe_key),
            replace(standby, authority_key=unsafe_key),
            readiness=readiness,
        )

    assert primary.authority_key == _authority_key_for_rehearsal(
        primary.rehearsal_id
    )


def test_machine_identity_ignores_network_interface_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        outage_operator,
        "_physical_machine_anchor",
        lambda: "platform-uuid-a",
        raising=False,
    )
    monkeypatch.setattr(outage_operator.socket, "gethostname", lambda: "Mac")
    monkeypatch.setattr(outage_operator, "getnode", lambda: 1, raising=False)
    first = outage_operator._machine_identity()
    monkeypatch.setattr(outage_operator, "getnode", lambda: 2, raising=False)

    assert outage_operator._machine_identity() == first
    assert first[0] == "Mac"
    monkeypatch.setattr(
        outage_operator.socket,
        "gethostname",
        lambda: "renamed-mac",
    )
    assert outage_operator._machine_identity()[1] == first[1]


def test_machine_identity_fails_closed_without_stable_anchor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(outage_operator.sys, "platform", "darwin")
    monkeypatch.setattr(
        outage_operator.subprocess,
        "run",
        lambda *_args, **_kwargs: outage_operator.subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="",
            stderr="",
        ),
    )

    with pytest.raises(RuntimeError, match="physical Mac identity"):
        outage_operator._physical_machine_anchor()


@pytest.mark.parametrize("role", ["primary", "standby"])
def test_process_role_rejects_source_drift(
    monkeypatch: pytest.MonkeyPatch,
    role: str,
) -> None:
    live = _LiveAuthorityStore()
    publisher = _PublisherStore()
    rehearsal_id = f"source-drift-{role}"
    readiness = _paired_readiness(
        rehearsal_id=rehearsal_id,
        publisher=publisher,
    )
    primary_receipt = None
    if role == "standby":
        primary_receipt = rehearse_primary_process_role(
            rehearsal_id=rehearsal_id,
            host_id="primary-mac",
            host_fingerprint="primary-fingerprint",
            lease_seconds=10,
            renew_interval_seconds=0.01,
            poll_interval_seconds=0.005,
            store=PartitionableAuthorityStore(
                healthy=live,
                unavailable=_UnavailableAuthorityStore(),
            ),
            publisher_store=publisher,
            expected_publisher_generation=8,
            readiness=readiness,
        )
    digests = iter(
        (
            readiness.implementation_sha256,
            readiness.implementation_sha256,
            "2" * 64,
        )
    )
    monkeypatch.setattr(
        outage_operator,
        "_implementation_sha256",
        lambda: next(digests),
    )

    with pytest.raises(
        RuntimeError,
        match="source changed during outage rehearsal",
    ):
        if role == "primary":
            rehearse_primary_process_role(
                rehearsal_id=rehearsal_id,
                host_id="primary-mac",
                host_fingerprint="primary-fingerprint",
                lease_seconds=10,
                renew_interval_seconds=0.01,
                poll_interval_seconds=0.005,
                store=PartitionableAuthorityStore(
                    healthy=live,
                    unavailable=_UnavailableAuthorityStore(),
                ),
                publisher_store=publisher,
                expected_publisher_generation=8,
                readiness=readiness,
            )
        else:
            assert primary_receipt is not None
            rehearse_standby_process_role(
                rehearsal_id=rehearsal_id,
                host_id="standby-mac",
                host_fingerprint="standby-fingerprint",
                primary_receipt=primary_receipt,
                lease_seconds=10,
                rto_seconds=1.0,
                poll_interval_seconds=0.005,
                store=live,
                publisher_store=publisher,
                expected_publisher_generation=8,
                readiness=readiness,
            )

    if role == "standby":
        assert live.current is None
