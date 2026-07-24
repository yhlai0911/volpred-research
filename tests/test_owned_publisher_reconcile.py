from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from volpred.ops.authority import PrimaryLease
from volpred.ops.delivery import (
    AcknowledgedEffect,
    AcknowledgementExpectation,
    EffectView,
    PublisherArticleReconcileEffectAdapter,
    encode_publisher_article_reconcile_payload,
)
from volpred.ops.delivery.owned_publisher_reconcile import (
    OwnedPublisherReconcileAttempt,
    OwnedPublisherReconcileCommand,
    OwnedPublisherReconcileReceipt,
    OwnedPublisherReconcileRequest,
    OwnedPublisherArticleReconcile,
    PublisherArticleReconcileOwner,
    PublisherArticleReconcileOwnershipLost,
    SupabaseOwnedPublisherReconcileStore,
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


def _command() -> OwnedPublisherReconcileCommand:
    return OwnedPublisherReconcileCommand(
        idempotency_key="publisher:reconcile:feed-revision-7",
        canonical_feed_sha256="f" * 64,
        articles=(_article(),),
        actor_ref="feed-sync:hourly-safe-reconcile",
    )


def _owner(
    *,
    owner: str = "operations_core",
) -> PublisherArticleReconcileOwner:
    return PublisherArticleReconcileOwner(
        schema_version="publisher-article-reconcile-owner.v1",
        effect_family="publisher.article.supabase.reconcile",
        owner=owner,
        generation=4,
        changed_at="2026-07-24T12:00:00+00:00",
        changed_by="operator:test",
        change_reason="test owner",
    )


def _effect() -> EffectView:
    payload = encode_publisher_article_reconcile_payload(
        canonical_feed_sha256="f" * 64,
        articles=(_article(),),
    )
    target = "supabase:articles"
    return EffectView(
        schema_version="effect-request.v1",
        id="effect-owned-publisher-1",
        idempotency_key="owned-publisher-effect:revision-7",
        work_item_id="work-owned-publisher-1",
        work_item_version=1,
        effect_kind="publisher.article.supabase.reconcile",
        target_ref=target,
        payload_ref="effect-payload:owned-publisher-1",
        payload_sha256=hashlib.sha256(payload).hexdigest(),
        risk="safe",
        acknowledgement=AcknowledgementExpectation(
            kind="publisher.article.supabase.reconcile.readback",
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
    def __init__(self, owner: PublisherArticleReconcileOwner) -> None:
        self.owner = owner
        self.calls: list[tuple[str, object]] = []
        self.request_view = OwnedPublisherReconcileRequest(
            owner_generation=owner.generation,
            work_id="work-owned-publisher-1",
            effect_id="effect-owned-publisher-1",
            request_sha256="b" * 64,
        )
        self.attempt = OwnedPublisherReconcileAttempt(
            owner_generation=owner.generation,
            work_id=self.request_view.work_id,
            work_version=3,
            work_lease_token="assigned-by-caller",
            effect=_effect(),
            payload=encode_publisher_article_reconcile_payload(
                canonical_feed_sha256="f" * 64,
                articles=(_article(),),
            ),
            outbox_sequence=41,
            attempt_count=1,
            outbox_claim_token="assigned-by-caller",
            worker_id="effect-worker:publisher-article-reconcile",
            primary_authority_key=(
                "publisher:article.supabase.reconcile"
            ),
            primary_authority_holder_ref=(
                "effect-worker:publisher-article-reconcile"
            ),
            primary_authority_epoch=7,
            primary_fencing_token="primary-token",
            authority_request_sha256="c" * 64,
            outbox_claim_ref="effect-outbox:41:attempt-1",
            primary_authority_ref=(
                "primary-authority:"
                "publisher:article.supabase.reconcile:epoch-7"
            ),
            lease_expires_at="2026-07-24T12:05:00+00:00",
        )

    def read_owner(self) -> PublisherArticleReconcileOwner:
        self.calls.append(("read_owner", None))
        return self.owner

    def request(
        self,
        command: OwnedPublisherReconcileCommand,
        *,
        owner_generation: int,
    ) -> OwnedPublisherReconcileRequest:
        self.calls.append(("request", (command, owner_generation)))
        return self.request_view

    def begin(
        self,
        request_view: OwnedPublisherReconcileRequest,
        *,
        worker_id: str,
        lease_seconds: int,
        work_lease_token: str,
        outbox_claim_token: str,
        primary_fencing_token: str,
    ) -> OwnedPublisherReconcileAttempt:
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
        attempt: OwnedPublisherReconcileAttempt,
        outcome,
    ) -> OwnedPublisherReconcileReceipt:
        self.calls.append(("settle", (attempt, outcome)))
        assert isinstance(outcome, AcknowledgedEffect)
        return OwnedPublisherReconcileReceipt(
            schema_version="owned-publisher-reconcile-receipt.v1",
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
            authority_key="publisher:article.supabase.reconcile",
            holder_ref="effect-worker:publisher-article-reconcile",
            epoch=7,
            fencing_token="primary-token",
            lease_seconds=300,
            acquired_at="2026-07-24T12:00:00+00:00",
            expires_at="2026-07-24T12:05:00+00:00",
        )

    def current_lease(self) -> PrimaryLease:
        self.calls += 1
        return self.lease


def test_reconcile_hides_request_begin_provider_and_settlement() -> None:
    store = _Store(_owner())
    projection = _Projection()
    lease_gate = _LeaseGate()
    tokens = iter(("work-token", "outbox-token"))
    reconcile = OwnedPublisherArticleReconcile(
        store=store,
        provider=PublisherArticleReconcileEffectAdapter(
            projection=projection
        ),
        primary_authority=lease_gate,
        token_factory=lambda: next(tokens),
    )

    receipt = reconcile.reconcile(_command())

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


def test_reconcile_fails_closed_when_settlement_receipt_drifts() -> None:
    store = _Store(_owner())
    original_settle = store.settle

    def settle_with_drift(*args, **kwargs):
        return replace(
            original_settle(*args, **kwargs),
            effect_id="effect-from-another-attempt",
        )

    store.settle = settle_with_drift  # type: ignore[method-assign]

    with pytest.raises(
        PublisherArticleReconcileOwnershipLost,
        match="settlement receipt drifted",
    ):
        OwnedPublisherArticleReconcile(
            store=store,
            provider=PublisherArticleReconcileEffectAdapter(
                projection=_Projection()
            ),
            primary_authority=_LeaseGate(),
        ).reconcile(_command())


def test_reconcile_returns_terminal_replay_without_calling_provider() -> None:
    store = _Store(_owner())
    terminal = OwnedPublisherReconcileReceipt(
        schema_version="owned-publisher-reconcile-receipt.v1",
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
            "publisher:article.supabase.reconcile:epoch-7"
        ),
        recorded_at="2026-07-24T12:00:01+00:00",
    )
    store.request_view = replace(
        store.request_view,
        terminal_receipt=terminal,
    )
    projection = _Projection()
    lease_gate = _LeaseGate()

    receipt = OwnedPublisherArticleReconcile(
        store=store,
        provider=PublisherArticleReconcileEffectAdapter(
            projection=projection
        ),
        primary_authority=lease_gate,
    ).reconcile(_command())

    assert receipt == terminal
    assert [name for name, _ in store.calls] == [
        "read_owner",
        "request",
    ]
    assert projection.upserts == 0
    assert lease_gate.calls == 1


def test_reconcile_fails_closed_on_inconsistent_terminal_replay() -> None:
    store = _Store(_owner())
    store.request_view = replace(
        store.request_view,
        terminal_receipt=OwnedPublisherReconcileReceipt(
            schema_version="owned-publisher-reconcile-receipt.v1",
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
                "publisher:article.supabase.reconcile:epoch-7"
            ),
            recorded_at="2026-07-24T12:00:01+00:00",
        ),
    )

    with pytest.raises(
        PublisherArticleReconcileOwnershipLost,
        match="terminal receipt drifted",
    ):
        OwnedPublisherArticleReconcile(
            store=store,
            provider=PublisherArticleReconcileEffectAdapter(
                projection=_Projection()
            ),
            primary_authority=_LeaseGate(),
        ).reconcile(_command())


def test_reconcile_fails_closed_before_request_when_owner_is_legacy() -> None:
    store = _Store(_owner(owner="legacy"))
    projection = _Projection()

    with pytest.raises(
        PublisherArticleReconcileOwnershipLost,
        match="does not own",
    ):
        OwnedPublisherArticleReconcile(
            store=store,
            provider=PublisherArticleReconcileEffectAdapter(
                projection=projection
            ),
            primary_authority=_LeaseGate(),
        ).reconcile(_command())

    assert store.calls == [("read_owner", None)]
    assert projection.upserts == 0


def test_reconcile_fails_closed_before_provider_when_lease_is_replaced() -> None:
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
        PublisherArticleReconcileOwnershipLost,
        match="lease was replaced",
    ):
        OwnedPublisherArticleReconcile(
            store=store,
            provider=PublisherArticleReconcileEffectAdapter(
                projection=projection
            ),
            primary_authority=lease_gate,
        ).reconcile(_command())

    assert projection.upserts == 0
    assert [name for name, _ in store.calls] == [
        "read_owner",
        "request",
        "begin",
    ]


def test_reconcile_revalidates_lease_after_readback_before_write() -> None:
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
        PublisherArticleReconcileOwnershipLost,
        match="lease was replaced",
    ):
        OwnedPublisherArticleReconcile(
            store=store,
            provider=PublisherArticleReconcileEffectAdapter(
                projection=projection
            ),
            primary_authority=lease_gate,
        ).reconcile(_command())

    assert projection.upserts == 0
    assert [name for name, _ in store.calls] == [
        "read_owner",
        "request",
        "begin",
    ]


def test_reconcile_fails_closed_when_begin_drifts_from_request() -> None:
    store = _Store(_owner())
    store.attempt = replace(store.attempt, work_id="other-work")
    projection = _Projection()

    with pytest.raises(
        PublisherArticleReconcileOwnershipLost,
        match="drifted from its durable request",
    ):
        OwnedPublisherArticleReconcile(
            store=store,
            provider=PublisherArticleReconcileEffectAdapter(
                projection=projection
            ),
            primary_authority=_LeaseGate(),
        ).reconcile(_command())

    assert projection.upserts == 0


def test_environment_adapter_never_uses_publishable_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "volpred.ops.delivery.owned_publisher_reconcile.runtime_environment",
        lambda: {
            "SUPABASE_URL": "https://project.supabase.co",
            "SUPABASE_KEY": "publishable-or-anon-key",
        },
    )

    with pytest.raises(ValueError, match="service-role key"):
        SupabaseOwnedPublisherReconcileStore.from_environment()


def test_service_role_adapter_sends_canonical_request_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = SupabaseOwnedPublisherReconcileStore(
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

    assert response.work_id == "work-owned-publisher-1"
    assert calls[0][0] == (
        "volpred_request_owned_publisher_article_reconcile"
    )
    rpc_payload = calls[0][1]
    assert rpc_payload["p_owner_generation"] == 4
    assert rpc_payload["p_payload"] == {
        "schema_version": "publisher-article-reconcile.v1",
        "canonical_feed_sha256": "f" * 64,
        "articles": [_article()],
    }
    assert "service-role-secret" not in repr(rpc_payload)


def test_service_role_adapter_parses_terminal_request_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = SupabaseOwnedPublisherReconcileStore(
        supabase_url="https://project.supabase.co",
        service_role_key="service-role-secret",
    )
    terminal_payload = {
        "schema_version": "owned-publisher-reconcile-receipt.v1",
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
            "publisher:article.supabase.reconcile:epoch-7"
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

    assert response.terminal_receipt == OwnedPublisherReconcileReceipt(
        **terminal_payload
    )


def test_service_role_adapter_exposes_owner_cas_with_rollback_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = SupabaseOwnedPublisherReconcileStore(
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
            "schema_version": "publisher-article-reconcile-owner.v1",
            "effect_family": "publisher.article.supabase.reconcile",
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
            "volpred_transfer_publisher_article_reconcile_owner",
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


def test_hourly_safe_upserts_preserve_legacy_owner_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from volpred.ops import delivery, feed_sync

    class Store:
        @classmethod
        def from_environment(cls):
            return cls()

        def read_owner(self):
            return _owner(owner="legacy")

    synced: list[str] = []
    monkeypatch.setattr(
        delivery,
        "SupabaseOwnedPublisherReconcileStore",
        Store,
    )
    monkeypatch.setattr(
        feed_sync,
        "sync_article",
        lambda article, **_kwargs: synced.append(str(article["id"])) or True,
    )

    outcome = feed_sync._apply_safe_projection_upserts(
        {
            "insert": ["mile_owned_sync"],
            "update": [],
            "delete": ["must_stay_outside_safe_effect"],
        },
        feed_by_slug={"mile_owned_sync": _article()},
        canonical_feed_sha256="f" * 64,
        storage_dir="storage",
    )

    assert synced == ["mile_owned_sync"]
    assert outcome["inserted"] == 1
    assert outcome["failed"] == 0
    assert outcome["safe_effect"]["mode"] == "legacy_per_article"


def test_apply_diff_binds_articles_and_hash_from_one_feed_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from volpred.ops import feed_sync

    captured: dict[str, object] = {}

    def apply_upserts(
        _diff,
        *,
        feed_by_slug,
        canonical_feed_sha256,
        storage_dir,
    ):
        captured.update(
            {
                "feed_by_slug": feed_by_slug,
                "canonical_feed_sha256": canonical_feed_sha256,
                "storage_dir": storage_dir,
            }
        )
        return {
            "inserted": 1,
            "updated": 0,
            "failed": 0,
            "failures": [],
            "safe_effect": {"mode": "test"},
        }

    monkeypatch.setattr(
        feed_sync,
        "_load_feed_snapshot",
        lambda _storage_dir: ([_article()], "a" * 64),
    )
    monkeypatch.setattr(
        feed_sync,
        "_load_feed",
        lambda _storage_dir: pytest.fail(
            "apply_diff must not perform a second feed read"
        ),
    )
    monkeypatch.setattr(
        feed_sync,
        "_apply_safe_projection_upserts",
        apply_upserts,
    )

    outcome = feed_sync.apply_diff(
        {
            "insert": ["mile_owned_sync"],
            "update": [],
            "delete": [],
        },
        storage_dir="snapshot-storage",
    )

    assert outcome["inserted"] == 1
    assert captured == {
        "feed_by_slug": {"mile_owned_sync": _article()},
        "canonical_feed_sha256": "a" * 64,
        "storage_dir": "snapshot-storage",
    }


def test_hourly_operations_core_owner_emits_one_immutable_batch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from volpred.ops import authority, delivery, feed_sync

    second = {**_article(), "id": "mile_a_first", "title": "First"}
    reports = tmp_path / "reports"
    reports.mkdir()
    feed = [_article(), second]
    (reports / "feed.json").write_text(json.dumps(feed), encoding="utf-8")
    canonical_feed_sha256 = hashlib.sha256(
        (reports / "feed.json").read_bytes()
    ).hexdigest()
    # The helper must use the caller's exact parse/hash snapshot. Removing the
    # file here makes any second read (and old-objects/new-hash race) fail.
    (reports / "feed.json").unlink()

    class Store:
        @classmethod
        def from_environment(cls):
            return cls()

        def read_owner(self):
            return _owner()

    commands: list[OwnedPublisherReconcileCommand] = []

    class Reconcile:
        def __init__(self, **_kwargs):
            pass

        def reconcile(self, command):
            commands.append(command)
            return SimpleNamespace(
                delivered=True,
                owner_generation=4,
                effect_id="effect-batch-1",
                attempt_count=1,
                disposition="delivered",
                evidence_ref="supabase:articles:reconcile:" + "f" * 64,
                evidence_sha256="e" * 64,
            )

    class Keepalive:
        def start(self):
            return None

        def stop(self):
            return None

    monkeypatch.setattr(
        delivery,
        "SupabaseOwnedPublisherReconcileStore",
        Store,
    )
    monkeypatch.setattr(
        delivery,
        "OwnedPublisherArticleReconcile",
        Reconcile,
    )
    monkeypatch.setattr(
        authority,
        "build_supabase_host_authority_keepalive",
        lambda **_kwargs: Keepalive(),
    )

    outcome = feed_sync._apply_safe_projection_upserts(
        {
            "insert": ["mile_owned_sync"],
            "update": ["mile_a_first"],
            "delete": ["must_stay_outside_safe_effect"],
        },
        feed_by_slug={article["id"]: article for article in feed},
        canonical_feed_sha256=canonical_feed_sha256,
        storage_dir=tmp_path,
    )

    assert outcome["inserted"] == 1
    assert outcome["updated"] == 1
    assert outcome["failed"] == 0
    assert len(commands) == 1
    assert [article["id"] for article in commands[0].articles] == [
        "mile_a_first",
        "mile_owned_sync",
    ]
    assert commands[0].canonical_feed_sha256 == canonical_feed_sha256
