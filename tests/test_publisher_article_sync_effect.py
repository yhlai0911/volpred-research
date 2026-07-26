from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from volpred.ops.authority import PrimaryLease
from volpred.ops.delivery import (
    AcknowledgedEffect,
    AcknowledgementExpectation,
    EffectView,
    FailedEffect,
    PublisherArticleProjectionReadback,
    PublisherArticleSyncEffectAdapter,
    SupabaseArticleProjectionAdapter,
    encode_publisher_article_sync_payload,
)
from volpred.ops.delivery._effect_worker import (
    EffectAuthorityGrant,
    EffectOutboxWorker,
    EffectWorkerCommand,
)
from volpred.ops.delivery.postgres import (
    EffectAttemptReceipt,
    EffectOutboxLease,
)


def _article() -> dict:
    return {
        "id": "mile_effect_sync",
        "title": "Effect-backed single article sync",
        "content": "Canonical article body.",
        "description": "Canonical excerpt.",
        "audience": "research",
        "category": "milestone",
        "phase": "robustness",
        "status": "published",
        "published_at": "2026-07-24T08:00:00+08:00",
        "details": {"experiment_refs": ["K1708"]},
        "tags": ["K1708", "SPY", "SPY"],
    }


def _payload(article: dict | None = None) -> bytes:
    return encode_publisher_article_sync_payload(article or _article())


def _effect(payload: bytes | None = None) -> EffectView:
    encoded = payload or _payload()
    target = "supabase:articles/mile_effect_sync"
    return EffectView(
        schema_version="effect-request.v1",
        id="effect-publisher-sync-1",
        idempotency_key="publisher:article:mile_effect_sync:a1",
        work_item_id="work-publisher-sync-1",
        work_item_version=3,
        effect_kind="publisher.article.supabase.sync",
        target_ref=target,
        payload_ref="artifact:publisher/mile_effect_sync-a1.json",
        payload_sha256=hashlib.sha256(encoded).hexdigest(),
        risk="safe",
        acknowledgement=AcknowledgementExpectation(
            kind="publisher.article.supabase.readback",
            target_ref=target,
        ),
        requester_ref="publisher:single-article",
        request_sha256="a" * 64,
        status="requested",
        created_at="2026-07-24T00:00:00+00:00",
    )


class _Projection:
    def __init__(self) -> None:
        self.current: dict | None = None
        self.upserts = 0
        self.fail_upsert = False
        self.mismatch = False

    def readback(
        self,
        article: dict,
    ) -> PublisherArticleProjectionReadback | None:
        if self.current is None:
            return None
        encoded = json.dumps(
            self.current,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return PublisherArticleProjectionReadback(
            matches=not self.mismatch and self.current == article,
            evidence_ref=f"supabase:articles/{article['id']}",
            evidence_sha256=hashlib.sha256(encoded).hexdigest(),
        )

    def upsert(self, article: dict) -> bool:
        self.upserts += 1
        if self.fail_upsert:
            return False
        self.current = json.loads(json.dumps(article))
        return True


def test_equivalent_replay_reads_back_without_duplicate_write() -> None:
    projection = _Projection()
    adapter = PublisherArticleSyncEffectAdapter(projection=projection)
    payload = _payload()
    effect = _effect(payload)

    first = adapter.deliver(effect, payload)
    replay = adapter.deliver(effect, payload)

    assert isinstance(first, AcknowledgedEffect)
    assert replay == first
    assert projection.upserts == 1
    assert first.acknowledgement == effect.acknowledgement


def test_provider_failure_is_retryable_and_keeps_typed_evidence() -> None:
    projection = _Projection()
    projection.fail_upsert = True
    payload = _payload()

    outcome = PublisherArticleSyncEffectAdapter(
        projection=projection
    ).deliver(_effect(payload), payload)

    assert isinstance(outcome, FailedEffect)
    assert outcome.reason_code == "publisher_article_sync_provider_error"
    assert outcome.retryable is True
    assert len(outcome.evidence_sha256) == 64


@pytest.mark.parametrize(
    ("effect_change", "payload", "reason"),
    [
        (
            {"target_ref": "supabase:articles/other"},
            _payload(),
            "unsupported_publisher_article_sync_contract",
        ),
        (
            {},
            b'{"schema_version":"publisher-article-sync.v1","article":[]}',
            "invalid_publisher_article_sync_payload",
        ),
        (
            {},
            (
                b'{"schema_version":"publisher-article-sync.v1",'
                b'"article":{"id":"mile_effect_sync","tags":{}}}'
            ),
            "invalid_publisher_article_sync_payload",
        ),
        (
            {},
            (
                b'{"schema_version":"publisher-article-sync.v1",'
                b'"article":{"id":"mile_effect_sync","tags":null}}'
            ),
            "invalid_publisher_article_sync_payload",
        ),
    ],
)
def test_invalid_intent_is_terminal_before_projection_write(
    effect_change: dict,
    payload: bytes,
    reason: str,
) -> None:
    projection = _Projection()
    base = _effect(payload)
    acknowledgement = base.acknowledgement
    if "target_ref" in effect_change:
        acknowledgement = replace(
            acknowledgement,
            target_ref=str(effect_change["target_ref"]),
        )
    effect = replace(
        base,
        acknowledgement=acknowledgement,
        **effect_change,
    )

    outcome = PublisherArticleSyncEffectAdapter(
        projection=projection
    ).deliver(effect, payload)

    assert isinstance(outcome, FailedEffect)
    assert outcome.reason_code == reason
    assert outcome.retryable is False
    assert projection.upserts == 0


def test_post_write_readback_mismatch_is_retryable() -> None:
    projection = _Projection()
    projection.mismatch = True
    payload = _payload()

    outcome = PublisherArticleSyncEffectAdapter(
        projection=projection
    ).deliver(_effect(payload), payload)

    assert isinstance(outcome, FailedEffect)
    assert outcome.reason_code == "publisher_article_sync_readback_mismatch"
    assert outcome.retryable is True
    assert projection.upserts == 1


class _Authority:
    def authorize(self, request):
        return EffectAuthorityGrant(
            request_sha256=request.request_sha256,
            outbox_claim_ref="effect-outbox:44:attempt-1",
            primary_authority_ref="primary-authority:epoch-7",
        )


class _PrimaryAuthority:
    def current_lease(self) -> PrimaryLease:
        return PrimaryLease(
            schema_version="primary-lease.v1",
            authority_key="operations-core-effects",
            holder_ref="host:primary",
            epoch=7,
            fencing_token="primary-token",
            lease_seconds=300,
            acquired_at="2026-07-24T00:00:00+00:00",
            expires_at="2026-07-24T00:05:00+00:00",
        )


class _TerminalStore:
    def __init__(self, effect: EffectView) -> None:
        self.effect = effect
        self.outcome: FailedEffect | None = None

    def claim_outbox(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
        effect_kinds: frozenset[str],
    ):
        assert effect_kinds == frozenset(
            {"publisher.article.supabase.sync"}
        )
        return EffectOutboxLease(
            sequence=44,
            effect_id=self.effect.id,
            token="outbox-token",
            claimed_by=worker_id,
            attempt_count=1,
            expires_at="2026-07-24T00:05:00+00:00",
        )

    def inspect(self, effect_id: str) -> EffectView:
        assert effect_id == self.effect.id
        return self.effect

    def settle_outbox(self, *, lease, outcome, authority):
        assert isinstance(outcome, FailedEffect)
        assert outcome.retryable is False
        self.outcome = outcome
        return EffectAttemptReceipt(
            schema_version="effect-attempt-receipt.v1",
            effect_id=lease.effect_id,
            outbox_sequence=lease.sequence,
            attempt_count=lease.attempt_count,
            worker_id=lease.claimed_by,
            reported_outcome="terminal_failure",
            disposition="dead_lettered",
            acknowledgement=None,
            reason_code=outcome.reason_code,
            evidence_ref=outcome.evidence_ref,
            evidence_sha256=outcome.evidence_sha256,
            authority_request_sha256=authority.request_sha256,
            outbox_claim_ref=authority.outbox_claim_ref,
            primary_authority_ref=authority.primary_authority_ref,
            retry_at=None,
            recorded_at="2026-07-24T00:00:01+00:00",
        )


def test_invalid_article_effect_is_durably_dead_lettered_by_worker() -> None:
    payload = _payload()
    invalid = replace(
        _effect(payload),
        target_ref="supabase:articles/wrong-slug",
        acknowledgement=AcknowledgementExpectation(
            kind="publisher.article.supabase.readback",
            target_ref="supabase:articles/wrong-slug",
        ),
    )
    store = _TerminalStore(invalid)
    worker = EffectOutboxWorker(
        delivery=store,
        authority=_Authority(),
        primary_authority=_PrimaryAuthority(),
        payload_reader=type(
            "PayloadReader",
            (),
            {"read": lambda _self, _ref: payload},
        )(),
        provider=PublisherArticleSyncEffectAdapter(projection=_Projection()),
    )

    receipt = worker.run_once(
        EffectWorkerCommand(
            worker_id="effect-worker:publisher-sync",
            lease_seconds=300,
        )
    )

    assert receipt is not None
    assert receipt.disposition == "dead_lettered"
    assert store.outcome is not None
    assert (
        store.outcome.reason_code
        == "unsupported_publisher_article_sync_contract"
    )


def test_worker_fails_closed_if_store_returns_another_effect_family() -> None:
    payload = _payload()
    wrong_family = replace(
        _effect(payload),
        effect_kind="email.notification.send",
    )
    store = _TerminalStore(wrong_family)
    projection = _Projection()
    worker = EffectOutboxWorker(
        delivery=store,
        authority=_Authority(),
        primary_authority=_PrimaryAuthority(),
        payload_reader=type(
            "PayloadReader",
            (),
            {"read": lambda _self, _ref: payload},
        )(),
        provider=PublisherArticleSyncEffectAdapter(projection=projection),
    )

    with pytest.raises(
        RuntimeError,
        match="outside the provider capability",
    ):
        worker.run_once(
            EffectWorkerCommand(
                worker_id="effect-worker:publisher-sync",
                lease_seconds=300,
            )
        )

    assert projection.upserts == 0
    assert store.outcome is None


def test_supabase_projection_adapter_compares_full_row_and_tags(
    monkeypatch,
) -> None:
    from scripts import supabase_sync

    article = _article()
    expected = supabase_sync.projected_article_row(article, verbose=False)
    actual = {
        "id": "article-uuid",
        **expected,
        "published_at": "2026-07-24T00:00:00+00:00",
        "details": {
            **expected["details"],
            "view_display": 1234,
        },
    }

    def fake_select(table: str, *, select: str = "*", **filters):
        if table == "articles":
            assert filters == {"slug": article["id"]}
            return [actual]
        if table == "article_tags":
            assert filters == {"article_id": "article-uuid"}
            return [{"tag_id": 1}, {"tag_id": 2}]
        raise AssertionError(f"unexpected table: {table}")

    monkeypatch.setattr(supabase_sync, "_select_rows", fake_select)
    monkeypatch.setattr(
        supabase_sync,
        "_select_rows_in",
        lambda table, column, values, *, select="*": [
            {"id": 1, "name": "SPY"},
            {"id": 2, "name": "K1708"},
        ],
    )
    calls: list[dict] = []
    monkeypatch.setattr(
        supabase_sync,
        "sync_article_projection",
        lambda item, storage_dir="storage": calls.append(item) or True,
    )
    adapter = SupabaseArticleProjectionAdapter(storage_dir="storage")

    readback = adapter.readback(article)

    assert readback is not None
    assert readback.matches is True
    assert readback.evidence_ref == "supabase:articles/mile_effect_sync"
    assert adapter.upsert(article) is True
    assert calls == [article]


def test_supabase_projection_adapter_preserves_tags_outside_payload_scope(
    monkeypatch,
) -> None:
    from scripts import supabase_sync

    article = {
        key: value for key, value in _article().items() if key != "tags"
    }
    expected = supabase_sync.projected_article_row(article, verbose=False)

    def fake_select(table: str, *, select: str = "*", **filters):
        if table == "articles":
            return [{"id": "article-uuid", **expected}]
        if table == "article_tags":
            return [{"tag_id": 1}]
        raise AssertionError(f"unexpected table: {table}")

    monkeypatch.setattr(supabase_sync, "_select_rows", fake_select)
    monkeypatch.setattr(
        supabase_sync,
        "_select_rows_in",
        lambda table, column, values, *, select="*": [
            {"id": 1, "name": "existing-server-tag"}
        ],
    )

    readback = SupabaseArticleProjectionAdapter().readback(article)

    assert readback is not None
    assert readback.matches is True


def test_direct_sync_converges_an_empty_tag_projection(monkeypatch) -> None:
    from scripts import supabase_sync

    article = {**_article(), "tags": []}
    expected = supabase_sync.projected_article_row(article, verbose=False)
    deleted: list[tuple[str, dict]] = []

    monkeypatch.setattr(
        supabase_sync,
        "_remote_writes_blocked",
        lambda: True,
    )
    monkeypatch.setattr(supabase_sync, "_post", lambda table, row: True)
    monkeypatch.setattr(
        supabase_sync,
        "_select_rows",
        lambda table, **kwargs: [
            {
                "slug": expected["slug"],
                "status": expected["status"],
                "published_at": expected["published_at"],
                "audience": expected["audience"],
            }
        ],
    )
    monkeypatch.setattr(
        supabase_sync,
        "_get_article_id",
        lambda slug: "article-uuid",
    )
    monkeypatch.setattr(
        supabase_sync,
        "_delete_where",
        lambda table, filters: deleted.append((table, filters)) or True,
    )
    monkeypatch.setattr(
        supabase_sync,
        "revalidate_article_cache",
        lambda slug: True,
    )

    assert supabase_sync.sync_article(article, storage_dir="storage") is True
    assert deleted == [
        ("article_tags", {"article_id": "article-uuid"}),
    ]


def test_public_sync_routes_legacy_owner_to_projection(
    monkeypatch,
) -> None:
    from scripts import supabase_sync
    from volpred.ops.delivery import owned_publisher_article

    projection_calls: list[tuple[dict, object]] = []
    monkeypatch.setattr(
        supabase_sync,
        "_remote_writes_blocked",
        lambda: False,
    )
    monkeypatch.setattr(
        owned_publisher_article.SupabaseOwnedPublisherArticleStore,
        "from_environment",
        classmethod(
            lambda cls: SimpleNamespace(
                read_owner=lambda: SimpleNamespace(
                    effect_family="publisher.article.supabase.sync",
                    owner="legacy",
                    generation=1,
                )
            )
        ),
    )
    monkeypatch.setattr(
        supabase_sync,
        "sync_article_projection",
        lambda item, storage_dir="storage": (
            projection_calls.append((item, storage_dir)) or True
        ),
    )

    assert supabase_sync.sync_article(
        _article(),
        storage_dir="fixture-storage",
    )
    assert projection_calls == [(_article(), "fixture-storage")]


def test_public_sync_routes_operations_core_through_formal_caller(
    monkeypatch,
) -> None:
    from scripts import supabase_sync
    from volpred.ops import authority
    from volpred.ops.delivery import owned_publisher_article

    store = SimpleNamespace(
        read_owner=lambda: SimpleNamespace(
            effect_family="publisher.article.supabase.sync",
            owner="operations_core",
            generation=4,
        )
    )
    keepalive_calls: list[str] = []
    keepalive = SimpleNamespace(
        start=lambda: keepalive_calls.append("start"),
        stop=lambda: keepalive_calls.append("stop"),
    )
    commands = []

    class FakeOwnedSync:
        def __init__(self, **kwargs):
            assert kwargs["store"] is store
            assert kwargs["primary_authority"] is keepalive

        def sync(self, command):
            commands.append(command)
            return SimpleNamespace(delivered=True)

    monkeypatch.setattr(
        supabase_sync,
        "_remote_writes_blocked",
        lambda: False,
    )
    monkeypatch.setattr(
        owned_publisher_article.SupabaseOwnedPublisherArticleStore,
        "from_environment",
        classmethod(lambda cls: store),
    )
    monkeypatch.setattr(
        owned_publisher_article,
        "OwnedPublisherArticleSync",
        FakeOwnedSync,
    )
    monkeypatch.setattr(
        authority,
        "build_supabase_host_authority_keepalive",
        lambda **kwargs: (
            keepalive
            if kwargs
            == {
                "authority_key": "publisher:article.supabase.sync",
                "holder_ref": "effect-worker:publisher-article-sync",
            }
            else None
        ),
    )
    monkeypatch.setattr(
        supabase_sync,
        "sync_article_projection",
        lambda *args, **kwargs: pytest.fail(
            "operations_core must not call the legacy projection"
        ),
    )

    assert supabase_sync.sync_article(
        _article(),
        actor_ref="publisher:test",
    )
    assert keepalive_calls == ["start", "stop"]
    assert len(commands) == 1
    assert commands[0].article == _article()
    assert commands[0].actor_ref == "publisher:test"
    assert commands[0].idempotency_key == (
        "publisher:article:mile_effect_sync:"
        + hashlib.sha256(_payload()).hexdigest()
    )


def test_public_sync_fails_closed_on_owner_family_drift(
    monkeypatch,
) -> None:
    from scripts import supabase_sync
    from volpred.ops.delivery import owned_publisher_article

    monkeypatch.setattr(
        supabase_sync,
        "_remote_writes_blocked",
        lambda: False,
    )
    monkeypatch.setattr(
        owned_publisher_article.SupabaseOwnedPublisherArticleStore,
        "from_environment",
        classmethod(
            lambda cls: SimpleNamespace(
                read_owner=lambda: SimpleNamespace(
                    effect_family="email.ops_alert",
                    owner="legacy",
                    generation=4,
                )
            )
        ),
    )
    monkeypatch.setattr(
        supabase_sync,
        "sync_article_projection",
        lambda *args, **kwargs: pytest.fail(
            "owner drift must not call a writer"
        ),
    )

    with pytest.raises(RuntimeError, match="wrong effect family"):
        supabase_sync.sync_article(_article())
