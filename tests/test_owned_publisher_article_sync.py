from __future__ import annotations

import hashlib
from dataclasses import replace
from typing import Any

import pytest

from volpred.ops.authority import PrimaryLease
from volpred.ops.delivery import (
    AcknowledgedEffect,
    AcknowledgementExpectation,
    EffectView,
    PublisherArticleSyncEffectAdapter,
    encode_publisher_article_sync_payload,
)
from volpred.ops.delivery.owned_publisher_article import (
    OwnedPublisherArticleAttempt,
    OwnedPublisherArticleCommand,
    OwnedPublisherArticleRecovery,
    OwnedPublisherArticleReceipt,
    OwnedPublisherArticleRequest,
    OwnedPublisherArticleSync,
    PublisherArticleSyncOwner,
    PublisherArticleSyncOwnershipLost,
    SupabaseOwnedPublisherArticleStore,
)


def _article() -> dict[str, object]:
    return {
        "id": "mile_owned_sync",
        "title": "Owned publisher sync",
        "content": "Canonical article body.",
        "description": "Canonical excerpt.",
        "audience": "research",
        "category": "milestone",
        "phase": "robustness",
        "status": "published",
        "published_at": "2026-07-24T08:00:00+08:00",
        "details": {"experiment_refs": ["K1708"]},
        "tags": ["K1708", "SPY"],
    }


def _command() -> OwnedPublisherArticleCommand:
    return OwnedPublisherArticleCommand(
        idempotency_key="publisher:article:mile_owned_sync:revision-7",
        article=_article(),
        actor_ref="publisher:publish_milestone",
    )


def _owner(
    *,
    owner: str = "operations_core",
) -> PublisherArticleSyncOwner:
    return PublisherArticleSyncOwner(
        schema_version="publisher-article-sync-owner.v1",
        effect_family="publisher.article.supabase.sync",
        owner=owner,
        generation=4,
        changed_at="2026-07-24T12:00:00+00:00",
        changed_by="operator:test",
        change_reason="test owner",
    )


def _effect() -> EffectView:
    payload = encode_publisher_article_sync_payload(_article())
    target = "supabase:articles/mile_owned_sync"
    return EffectView(
        schema_version="effect-request.v1",
        id="effect-owned-publisher-1",
        idempotency_key="owned-publisher-effect:revision-7",
        work_item_id="work-owned-publisher-1",
        work_item_version=1,
        effect_kind="publisher.article.supabase.sync",
        target_ref=target,
        payload_ref="effect-payload:owned-publisher-1",
        payload_sha256=hashlib.sha256(payload).hexdigest(),
        risk="safe",
        acknowledgement=AcknowledgementExpectation(
            kind="publisher.article.supabase.readback",
            target_ref=target,
        ),
        requester_ref="publisher:publish_milestone",
        request_sha256="a" * 64,
        status="requested",
        created_at="2026-07-24T12:00:00+00:00",
    )


class _Projection:
    def __init__(self) -> None:
        self.article: dict | None = None
        self.upserts = 0

    def readback(self, article: dict):
        if self.article != article:
            return None
        from volpred.ops.delivery import (
            PublisherArticleProjectionReadback,
        )

        return PublisherArticleProjectionReadback(
            matches=True,
            evidence_ref="supabase:articles/mile_owned_sync",
            evidence_sha256="d" * 64,
        )

    def upsert(self, article: dict) -> bool:
        self.upserts += 1
        self.article = article
        return True


class _Store:
    def __init__(self, owner: PublisherArticleSyncOwner) -> None:
        self.owner = owner
        self.calls: list[tuple[str, object]] = []
        self.request_view = OwnedPublisherArticleRequest(
            owner_generation=owner.generation,
            work_id="work-owned-publisher-1",
            effect_id="effect-owned-publisher-1",
            request_sha256="b" * 64,
        )
        self.attempt = OwnedPublisherArticleAttempt(
            owner_generation=owner.generation,
            work_id=self.request_view.work_id,
            work_version=3,
            work_lease_token="assigned-by-caller",
            effect=_effect(),
            payload=encode_publisher_article_sync_payload(_article()),
            outbox_sequence=41,
            attempt_count=1,
            outbox_claim_token="assigned-by-caller",
            worker_id="effect-worker:publisher-article-sync",
            primary_authority_key=(
                "publisher:article.supabase.sync"
            ),
            primary_authority_holder_ref=(
                "effect-worker:publisher-article-sync"
            ),
            primary_authority_epoch=7,
            primary_fencing_token="primary-token",
            authority_request_sha256="c" * 64,
            outbox_claim_ref="effect-outbox:41:attempt-1",
            primary_authority_ref=(
                "primary-authority:"
                "publisher:article.supabase.sync:epoch-7"
            ),
            lease_expires_at="2026-07-24T12:05:00+00:00",
        )

    def read_owner(self) -> PublisherArticleSyncOwner:
        self.calls.append(("read_owner", None))
        return self.owner

    def request(
        self,
        command: OwnedPublisherArticleCommand,
        *,
        owner_generation: int,
    ) -> OwnedPublisherArticleRequest:
        self.calls.append(("request", (command, owner_generation)))
        return self.request_view

    def begin(
        self,
        request_view: OwnedPublisherArticleRequest,
        *,
        worker_id: str,
        lease_seconds: int,
        work_lease_token: str,
        outbox_claim_token: str,
        primary_fencing_token: str,
    ) -> OwnedPublisherArticleAttempt:
        self.calls.append(
            (
                "begin",
                (
                    request_view,
                    worker_id,
                    lease_seconds,
                    work_lease_token,
                    outbox_claim_token,
                    primary_fencing_token,
                ),
            )
        )
        return replace(
            self.attempt,
            work_lease_token=work_lease_token,
            outbox_claim_token=outbox_claim_token,
            primary_fencing_token=primary_fencing_token,
        )

    def settle(
        self,
        attempt: OwnedPublisherArticleAttempt,
        outcome,
    ) -> OwnedPublisherArticleReceipt:
        self.calls.append(("settle", (attempt, outcome)))
        assert isinstance(outcome, AcknowledgedEffect)
        return OwnedPublisherArticleReceipt(
            schema_version="owned-publisher-article-receipt.v1",
            owner_generation=attempt.owner_generation,
            work_id=attempt.work_id,
            work_status="succeeded",
            effect_id=attempt.effect.id,
            effect_status="delivered",
            attempt_count=attempt.attempt_count,
            disposition="delivered",
            evidence_ref=outcome.evidence_ref,
            evidence_sha256=outcome.evidence_sha256,
            primary_authority_ref=attempt.primary_authority_ref,
            recorded_at="2026-07-24T12:00:01+00:00",
        )


class _LeaseGate:
    def __init__(self) -> None:
        self.calls = 0
        self.lease = PrimaryLease(
            schema_version="primary-lease.v1",
            authority_key="publisher:article.supabase.sync",
            holder_ref="effect-worker:publisher-article-sync",
            epoch=7,
            fencing_token="primary-token",
            lease_seconds=300,
            acquired_at="2026-07-24T12:00:00+00:00",
            expires_at="2026-07-24T12:05:00+00:00",
        )

    def current_lease(self) -> PrimaryLease:
        self.calls += 1
        return self.lease


class _RecoveryStore(_Store):
    def __init__(self, owner: PublisherArticleSyncOwner) -> None:
        super().__init__(owner)
        self._candidates = [self.attempt]

    def recover_due(
        self,
        *,
        owner_generation: int,
        worker_id: str,
        lease_seconds: int,
        work_lease_token: str,
        outbox_claim_token: str,
        primary_fencing_token: str,
    ) -> OwnedPublisherArticleAttempt | None:
        self.calls.append(
            (
                "recover_due",
                (
                    owner_generation,
                    worker_id,
                    lease_seconds,
                    work_lease_token,
                    outbox_claim_token,
                    primary_fencing_token,
                ),
            )
        )
        if not self._candidates:
            return None
        return replace(
            self._candidates.pop(),
            attempt_count=2,
            work_lease_token=work_lease_token,
            outbox_claim_token=outbox_claim_token,
            primary_fencing_token=primary_fencing_token,
        )


def test_recovery_consumes_due_retry_through_existing_provider() -> None:
    store = _RecoveryStore(_owner())
    projection = _Projection()
    lease_gate = _LeaseGate()
    tokens = iter(("work-recovery-token", "outbox-recovery-token"))

    summary = OwnedPublisherArticleRecovery(
        store=store,
        provider=PublisherArticleSyncEffectAdapter(
            projection=projection
        ),
        primary_authority=lease_gate,
        token_factory=lambda: next(tokens),
    ).recover(limit=1)

    assert summary.recovered_count == 1
    assert summary.delivered_count == 1
    assert summary.retry_scheduled_count == 0
    assert projection.upserts == 1
    assert [name for name, _ in store.calls] == [
        "read_owner",
        "recover_due",
        "settle",
    ]
    assert lease_gate.calls == 4


def test_sync_hides_request_begin_provider_and_settlement() -> None:
    store = _Store(_owner())
    projection = _Projection()
    lease_gate = _LeaseGate()
    tokens = iter(("work-token", "outbox-token"))
    sync = OwnedPublisherArticleSync(
        store=store,
        provider=PublisherArticleSyncEffectAdapter(
            projection=projection
        ),
        primary_authority=lease_gate,
        token_factory=lambda: next(tokens),
    )

    receipt = sync.sync(_command())

    assert receipt.delivered is True
    assert projection.upserts == 1
    assert [name for name, _ in store.calls] == [
        "read_owner",
        "request",
        "begin",
        "settle",
    ]
    begin_args = store.calls[2][1]
    assert isinstance(begin_args, tuple)
    assert begin_args[-3:] == (
        "work-token",
        "outbox-token",
        "primary-token",
    )
    assert lease_gate.calls == 4


def test_sync_fails_closed_when_settlement_receipt_drifts() -> None:
    store = _Store(_owner())
    original_settle = store.settle

    def settle_with_drift(*args, **kwargs):
        return replace(
            original_settle(*args, **kwargs),
            effect_id="effect-from-another-attempt",
        )

    store.settle = settle_with_drift  # type: ignore[method-assign]

    with pytest.raises(
        PublisherArticleSyncOwnershipLost,
        match="settlement receipt drifted",
    ):
        OwnedPublisherArticleSync(
            store=store,
            provider=PublisherArticleSyncEffectAdapter(
                projection=_Projection()
            ),
            primary_authority=_LeaseGate(),
        ).sync(_command())


def test_sync_returns_terminal_replay_without_calling_provider() -> None:
    store = _Store(_owner())
    terminal = OwnedPublisherArticleReceipt(
        schema_version="owned-publisher-article-receipt.v1",
        owner_generation=store.owner.generation,
        work_id=store.request_view.work_id,
        work_status="succeeded",
        effect_id=store.request_view.effect_id,
        effect_status="delivered",
        attempt_count=1,
        disposition="delivered",
        evidence_ref="supabase:articles/mile_owned_sync",
        evidence_sha256="d" * 64,
        primary_authority_ref=(
            "primary-authority:"
            "publisher:article.supabase.sync:epoch-7"
        ),
        recorded_at="2026-07-24T12:00:01+00:00",
    )
    store.request_view = replace(
        store.request_view,
        terminal_receipt=terminal,
    )
    projection = _Projection()
    lease_gate = _LeaseGate()

    receipt = OwnedPublisherArticleSync(
        store=store,
        provider=PublisherArticleSyncEffectAdapter(
            projection=projection
        ),
        primary_authority=lease_gate,
    ).sync(_command())

    assert receipt == terminal
    assert [name for name, _ in store.calls] == [
        "read_owner",
        "request",
    ]
    assert projection.upserts == 0
    assert lease_gate.calls == 1


def test_sync_fails_closed_on_inconsistent_terminal_replay() -> None:
    store = _Store(_owner())
    store.request_view = replace(
        store.request_view,
        terminal_receipt=OwnedPublisherArticleReceipt(
            schema_version="owned-publisher-article-receipt.v1",
            owner_generation=store.owner.generation,
            work_id=store.request_view.work_id,
            work_status="failed",
            effect_id=store.request_view.effect_id,
            effect_status="dead_lettered",
            attempt_count=1,
            disposition="delivered",
            evidence_ref="supabase:articles/mile_owned_sync",
            evidence_sha256="d" * 64,
            primary_authority_ref=(
                "primary-authority:"
                "publisher:article.supabase.sync:epoch-7"
            ),
            recorded_at="2026-07-24T12:00:01+00:00",
        ),
    )

    with pytest.raises(
        PublisherArticleSyncOwnershipLost,
        match="terminal receipt drifted",
    ):
        OwnedPublisherArticleSync(
            store=store,
            provider=PublisherArticleSyncEffectAdapter(
                projection=_Projection()
            ),
            primary_authority=_LeaseGate(),
        ).sync(_command())


def test_sync_fails_closed_before_request_when_owner_is_legacy() -> None:
    store = _Store(_owner(owner="legacy"))
    projection = _Projection()

    with pytest.raises(
        PublisherArticleSyncOwnershipLost,
        match="does not own",
    ):
        OwnedPublisherArticleSync(
            store=store,
            provider=PublisherArticleSyncEffectAdapter(
                projection=projection
            ),
            primary_authority=_LeaseGate(),
        ).sync(_command())

    assert store.calls == [("read_owner", None)]
    assert projection.upserts == 0


def test_sync_fails_closed_before_provider_when_lease_is_replaced() -> None:
    store = _Store(_owner())
    projection = _Projection()
    lease_gate = _LeaseGate()
    original = lease_gate.lease

    original_begin = store.begin

    def begin_and_replace(*args, **kwargs):
        attempt = original_begin(*args, **kwargs)
        lease_gate.lease = replace(
            original,
            epoch=original.epoch + 1,
            fencing_token="replacement-token",
        )
        return attempt

    store.begin = begin_and_replace  # type: ignore[method-assign]

    with pytest.raises(
        PublisherArticleSyncOwnershipLost,
        match="lease was replaced",
    ):
        OwnedPublisherArticleSync(
            store=store,
            provider=PublisherArticleSyncEffectAdapter(
                projection=projection
            ),
            primary_authority=lease_gate,
        ).sync(_command())

    assert projection.upserts == 0
    assert [name for name, _ in store.calls] == [
        "read_owner",
        "request",
        "begin",
    ]


def test_sync_revalidates_lease_after_readback_before_write() -> None:
    store = _Store(_owner())
    projection = _Projection()
    lease_gate = _LeaseGate()
    original = lease_gate.lease
    original_readback = projection.readback

    def readback_and_replace_lease(article: dict):
        observed = original_readback(article)
        lease_gate.lease = replace(
            original,
            epoch=original.epoch + 1,
            fencing_token="replacement-token",
        )
        return observed

    projection.readback = readback_and_replace_lease  # type: ignore[method-assign]

    with pytest.raises(
        PublisherArticleSyncOwnershipLost,
        match="lease was replaced",
    ):
        OwnedPublisherArticleSync(
            store=store,
            provider=PublisherArticleSyncEffectAdapter(
                projection=projection
            ),
            primary_authority=lease_gate,
        ).sync(_command())

    assert projection.upserts == 0
    assert [name for name, _ in store.calls] == [
        "read_owner",
        "request",
        "begin",
    ]


def test_sync_fails_closed_when_begin_drifts_from_request() -> None:
    store = _Store(_owner())
    store.attempt = replace(store.attempt, work_id="other-work")
    projection = _Projection()

    with pytest.raises(
        PublisherArticleSyncOwnershipLost,
        match="drifted from its durable request",
    ):
        OwnedPublisherArticleSync(
            store=store,
            provider=PublisherArticleSyncEffectAdapter(
                projection=projection
            ),
            primary_authority=_LeaseGate(),
        ).sync(_command())

    assert projection.upserts == 0


def test_environment_adapter_never_uses_publishable_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "volpred.ops.delivery.owned_publisher_article.runtime_environment",
        lambda: {
            "SUPABASE_URL": "https://project.supabase.co",
            "SUPABASE_KEY": "publishable-or-anon-key",
        },
    )

    with pytest.raises(ValueError, match="service-role key"):
        SupabaseOwnedPublisherArticleStore.from_environment()


def test_service_role_adapter_sends_canonical_request_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = SupabaseOwnedPublisherArticleStore(
        supabase_url="https://project.supabase.co",
        service_role_key="service-role-secret",
    )
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_call(
        function: str,
        payload: dict[str, object],
    ) -> object:
        calls.append((function, payload))
        return {
            "owner_generation": 4,
            "work_id": "work-owned-publisher-1",
            "effect_id": "effect-owned-publisher-1",
            "request_sha256": "b" * 64,
        }

    monkeypatch.setattr(store._client, "call", fake_call)

    response = store.request(_command(), owner_generation=4)

    assert store.backend_sha256 == hashlib.sha256(
        b"https://project.supabase.co"
    ).hexdigest()
    assert response.work_id == "work-owned-publisher-1"
    assert calls[0][0] == (
        "volpred_request_owned_publisher_article_sync"
    )
    rpc_payload = calls[0][1]
    assert rpc_payload["p_owner_generation"] == 4
    assert rpc_payload["p_payload"] == {
        "schema_version": "publisher-article-sync.v1",
        "article": _article(),
    }
    assert "service-role-secret" not in repr(rpc_payload)


def test_service_role_adapter_parses_terminal_request_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = SupabaseOwnedPublisherArticleStore(
        supabase_url="https://project.supabase.co",
        service_role_key="service-role-secret",
    )
    terminal_payload = {
        "schema_version": "owned-publisher-article-receipt.v1",
        "owner_generation": 4,
        "work_id": "work-owned-publisher-1",
        "work_status": "succeeded",
        "effect_id": "effect-owned-publisher-1",
        "effect_status": "delivered",
        "attempt_count": 1,
        "disposition": "delivered",
        "evidence_ref": "supabase:articles/mile_owned_sync",
        "evidence_sha256": "d" * 64,
        "primary_authority_ref": (
            "primary-authority:"
            "publisher:article.supabase.sync:epoch-7"
        ),
        "recorded_at": "2026-07-24T12:00:01+00:00",
    }
    monkeypatch.setattr(
        store._client,
        "call",
        lambda function, payload: {
            "owner_generation": 4,
            "work_id": "work-owned-publisher-1",
            "effect_id": "effect-owned-publisher-1",
            "request_sha256": "b" * 64,
            "receipt": terminal_payload,
        },
    )

    response = store.request(_command(), owner_generation=4)

    assert response.terminal_receipt == OwnedPublisherArticleReceipt(
        **terminal_payload
    )


def test_service_role_adapter_exposes_owner_cas_with_rollback_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = SupabaseOwnedPublisherArticleStore(
        supabase_url="https://project.supabase.co",
        service_role_key="service-role-secret",
    )
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_call(
        function: str,
        payload: dict[str, object],
    ) -> object:
        calls.append((function, payload))
        return {
            "schema_version": "publisher-article-sync-owner.v1",
            "effect_family": "publisher.article.supabase.sync",
            "owner": "legacy",
            "generation": 5,
            "changed_at": "2026-07-24T12:01:00+00:00",
            "changed_by": "operator:test",
            "change_reason": "rollback rehearsal",
        }

    monkeypatch.setattr(store._client, "call", fake_call)

    owner = store.transfer_owner(
        expected_owner="operations_core",
        expected_generation=4,
        target_owner="legacy",
        actor_ref="operator:test",
        reason="rollback rehearsal",
        rollback_of_generation=4,
    )

    assert owner.owner == "legacy"
    assert owner.generation == 5
    assert calls == [
        (
            "volpred_transfer_publisher_article_sync_owner",
            {
                "p_expected_owner": "operations_core",
                "p_expected_generation": 4,
                "p_target_owner": "legacy",
                "p_actor_ref": "operator:test",
                "p_reason": "rollback rehearsal",
                "p_rollback_of_generation": 4,
            },
        )
    ]
