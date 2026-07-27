from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from io import BytesIO
from types import SimpleNamespace
from urllib.error import HTTPError, URLError

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


def _sync_result(*, succeeded: bool) -> SimpleNamespace:
    return SimpleNamespace(
        succeeded=succeeded,
        cache_acknowledgement=SimpleNamespace(
            acknowledged=succeeded,
            target_ref=(
                "https://volpred.example.test/api/sync/revalidate/article/"
                "mile_effect_sync"
            ),
            status_code=204 if succeeded else 503,
            evidence_ref=(
                "https://volpred.example.test/api/sync/revalidate/article/"
                f"mile_effect_sync#status={204 if succeeded else 503}"
            ),
            evidence_sha256="e" * 64,
        ),
    )


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
    assert outcome.evidence_ref == (
        "supabase:articles/mile_effect_sync"
    )


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
            authority_key="operations-core-primary",
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


def test_formal_projection_requires_mirror_acknowledgement(
    monkeypatch,
) -> None:
    """A Supabase row alone must not settle the formal publish effect."""

    from scripts import supabase_sync

    article = _article()
    expected = supabase_sync.projected_article_row(article, verbose=False)

    def fake_select(table: str, *, select: str = "*", **filters):
        if table == "articles":
            return [{"id": "article-uuid", **expected}]
        if table == "article_tags":
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
    monkeypatch.setattr(
        supabase_sync,
        "readback_article_public_projection",
        lambda item: {
            "matches": False,
            "evidence_ref": (
                "https://volpred.example.test/api/publications/feed/"
                "mile_effect_sync#status=200"
            ),
            "evidence_sha256": "b" * 64,
        },
        raising=False,
    )

    readback = SupabaseArticleProjectionAdapter(
        require_mirror_ack=True
    ).readback(article)

    assert readback is not None
    assert readback.matches is False
    assert "supabase:articles/mile_effect_sync" in readback.evidence_ref
    assert "api/publications/feed/mile_effect_sync" in readback.evidence_ref


def test_formal_projection_requires_successful_cache_purge(
    monkeypatch,
) -> None:
    """A failed Mirror/cache acknowledgement remains retryable."""

    from scripts import supabase_sync

    calls: list[tuple[dict, object, bool]] = []
    monkeypatch.setattr(
        supabase_sync,
        "sync_article_projection_result",
        lambda item, storage_dir="storage", *, require_cache_ack=False: (
            calls.append((item, storage_dir, require_cache_ack))
            or _sync_result(succeeded=not require_cache_ack)
        ),
    )

    adapter = SupabaseArticleProjectionAdapter(
        storage_dir="fixture-storage",
        require_mirror_ack=True,
    )

    assert adapter.upsert(_article()) is False
    failure = adapter.failure_evidence(_article())
    assert failure is not None
    assert failure.matches is False
    assert "/api/sync/revalidate/article/" in failure.evidence_ref
    assert "#status=503" in failure.evidence_ref
    assert len(failure.evidence_sha256) == 64
    assert len(calls) == 1
    assert calls[0][0] == _article()
    assert str(calls[0][1]) == "fixture-storage"
    assert calls[0][2] is True


def test_public_projection_readback_compares_reader_visible_content(
    monkeypatch,
) -> None:
    from scripts import supabase_sync

    article = {
        **_article(),
        "details": {
            "data_source": "official",
            "experiment_refs": ["K1708"],
        },
    }
    expected = supabase_sync.projected_article_row(article, verbose=False)
    body = {
        "id": expected["slug"],
        "slug": expected["slug"],
        "title": expected["title"],
        "content": expected["content"],
        "audience": expected["audience"],
        "phase": expected["phase"],
        "status": expected["status"],
        "category": expected["category"],
        "proposer": expected["proposer"],
        "published_at": expected["published_at"],
        "excerpt": expected["excerpt"],
        "details": {"data_source": "official"},
        "tags": ["SPY", "K1708"],
    }

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return json.dumps(body).encode()

    monkeypatch.setattr(
        supabase_sync,
        "_mirror_base_url",
        lambda: "https://volpred.example.test",
    )
    monkeypatch.setattr(
        supabase_sync,
        "_urlopen",
        lambda request, timeout=10: Response(),
    )

    readback = supabase_sync.readback_article_public_projection(article)

    assert readback["matches"] is True
    assert readback["evidence_ref"].endswith(
        "/api/publications/feed/mile_effect_sync#status=200"
    )
    assert len(readback["evidence_sha256"]) == 64

    body["details"] = {"data_source": "stale metadata"}
    stale = supabase_sync.readback_article_public_projection(article)
    assert stale["matches"] is False
    assert stale["evidence_sha256"] != readback["evidence_sha256"]

    body["details"] = {
        "data_source": "official",
        "experiment_refs": ["K1708"],
    }
    leaked = supabase_sync.readback_article_public_projection(article)
    assert leaked["matches"] is False
    assert leaked["evidence_sha256"] != readback["evidence_sha256"]


def test_formal_public_readback_preserves_omitted_comma_packed_tags(
    monkeypatch,
) -> None:
    from scripts import supabase_sync

    article = {
        key: value for key, value in _article().items() if key != "tags"
    }
    expected = supabase_sync.projected_article_row(article, verbose=False)
    public_body = {
        "id": expected["slug"],
        "slug": expected["slug"],
        "title": expected["title"],
        "content": expected["content"],
        "excerpt": expected["excerpt"],
        "audience": expected["audience"],
        "phase": expected["phase"],
        "status": expected["status"],
        "category": expected["category"],
        "proposer": expected["proposer"],
        "published_at": expected["published_at"],
        "details": {},
        "tags": ["macro", "SPY"],
    }

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return json.dumps(public_body).encode()

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
            {"id": 1, "name": "macro,SPY"}
        ],
    )
    monkeypatch.setattr(
        supabase_sync,
        "_mirror_base_url",
        lambda: "https://volpred.example.test",
    )
    monkeypatch.setattr(
        supabase_sync,
        "_urlopen",
        lambda request, timeout=10: Response(),
    )

    readback = SupabaseArticleProjectionAdapter(
        require_mirror_ack=True
    ).readback(article)

    assert readback is not None
    assert readback.matches is True


def test_hidden_public_404_requires_same_attempt_cache_ack(
    monkeypatch,
) -> None:
    from scripts import supabase_sync

    article = {**_article(), "status": "unpublished"}
    expected = supabase_sync.projected_article_row(article, verbose=False)

    def fake_select(table: str, *, select: str = "*", **filters):
        if table == "articles":
            return [{"id": "article-uuid", **expected}]
        if table == "article_tags":
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
    monkeypatch.setattr(
        supabase_sync,
        "readback_article_public_projection",
        lambda item: {
            "matches": True,
            "evidence_ref": (
                "https://volpred.example.test/api/publications/feed/"
                "mile_effect_sync#status=404"
            ),
            "evidence_sha256": "c" * 64,
        },
    )
    monkeypatch.setattr(
        supabase_sync,
        "sync_article_projection_result",
        lambda item, storage_dir="storage", *, require_cache_ack=False: (
            _sync_result(succeeded=require_cache_ack)
        ),
    )
    adapter = SupabaseArticleProjectionAdapter(
        require_mirror_ack=True
    )

    before = adapter.readback(article)
    assert before is not None
    assert before.matches is False

    assert adapter.upsert(article) is True
    after = adapter.readback(article)
    assert after is not None
    assert after.matches is True
    assert "/api/sync/revalidate/article/" in after.evidence_ref
    assert "#status=204" in after.evidence_ref


def test_public_projection_404_is_typed_but_not_self_authorizing(
    monkeypatch,
) -> None:
    from scripts import supabase_sync

    article = {**_article(), "status": "unpublished"}
    url = (
        "https://volpred.example.test/api/publications/feed/"
        "mile_effect_sync"
    )
    monkeypatch.setattr(
        supabase_sync,
        "_mirror_base_url",
        lambda: "https://volpred.example.test",
    )
    monkeypatch.setattr(
        supabase_sync,
        "_urlopen",
        lambda request, timeout=10: (
            (_ for _ in ()).throw(
                HTTPError(
                    url,
                    404,
                    "not found",
                    {},
                    BytesIO(b'{"error":"not found"}'),
                )
            )
            if "/feed/mile_effect_sync" in request.full_url
            else HealthyFeedResponse()
        ),
    )

    readback = supabase_sync.readback_article_public_projection(article)

    assert readback["matches"] is True
    assert "#status=404" in readback["evidence_ref"]
    assert "/api/publications/feed?limit=1" in readback["evidence_ref"]


class HealthyFeedResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self):
        return json.dumps(
            {
                "items": [{"id": "mile_control"}],
                "total": 1,
                "limit": 1,
                "offset": 0,
                "nextOffset": None,
                "tagCounts": [],
            }
        ).encode()


def test_public_projection_hidden_404_rejects_unhealthy_feed_tombstone(
    monkeypatch,
) -> None:
    from scripts import supabase_sync

    article = {**_article(), "status": "unpublished"}
    url = (
        "https://volpred.example.test/api/publications/feed/"
        "mile_effect_sync"
    )

    class EmptyFallback:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return json.dumps(
                {
                    "items": [],
                    "total": 0,
                    "limit": 1,
                    "offset": 0,
                    "nextOffset": None,
                    "tagCounts": [],
                }
            ).encode()

    monkeypatch.setattr(
        supabase_sync,
        "_mirror_base_url",
        lambda: "https://volpred.example.test",
    )
    monkeypatch.setattr(
        supabase_sync,
        "_urlopen",
        lambda request, timeout=10: (
            (_ for _ in ()).throw(
                HTTPError(
                    url,
                    404,
                    "not found",
                    {},
                    BytesIO(b'{"error":"not found"}'),
                )
            )
            if "/feed/mile_effect_sync" in request.full_url
            else EmptyFallback()
        ),
    )

    readback = supabase_sync.readback_article_public_projection(article)

    assert readback["matches"] is False
    assert "#status=404" in readback["evidence_ref"]


def test_cache_ack_token_is_consumed_by_failed_post_write_readback(
    monkeypatch,
) -> None:
    from scripts import supabase_sync

    article = {**_article(), "status": "unpublished"}
    expected = supabase_sync.projected_article_row(article, verbose=False)
    fail_supabase_read = False

    def fake_select(table: str, *, select: str = "*", **filters):
        if table == "articles":
            if fail_supabase_read:
                raise RuntimeError("post-write Supabase read failed")
            return [{"id": "article-uuid", **expected}]
        if table == "article_tags":
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
    monkeypatch.setattr(
        supabase_sync,
        "readback_article_public_projection",
        lambda item: {
            "matches": True,
            "evidence_ref": (
                "https://volpred.example.test/api/publications/feed/"
                "mile_effect_sync#status=404"
            ),
            "evidence_sha256": "d" * 64,
        },
    )
    monkeypatch.setattr(
        supabase_sync,
        "sync_article_projection_result",
        lambda item, storage_dir="storage", *, require_cache_ack=False: (
            _sync_result(succeeded=require_cache_ack)
        ),
    )
    adapter = SupabaseArticleProjectionAdapter(
        require_mirror_ack=True
    )
    assert adapter.upsert(article) is True

    fail_supabase_read = True
    with pytest.raises(RuntimeError, match="post-write Supabase read failed"):
        adapter.readback(article)

    fail_supabase_read = False
    retry = adapter.readback(article)
    assert retry is not None
    assert retry.matches is False


def test_post_write_read_exception_receipt_keeps_cache_ack(
    monkeypatch,
) -> None:
    from scripts import supabase_sync

    article = {**_article(), "status": "unpublished"}
    expected = supabase_sync.projected_article_row(article, verbose=False)
    article_reads = 0

    def fake_select(table: str, *, select: str = "*", **filters):
        nonlocal article_reads
        if table == "articles":
            article_reads += 1
            if article_reads == 2:
                raise RuntimeError("post-write Supabase read failed")
            return [{"id": "article-uuid", **expected}]
        if table == "article_tags":
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
    monkeypatch.setattr(
        supabase_sync,
        "readback_article_public_projection",
        lambda item: {
            "matches": True,
            "evidence_ref": (
                "https://volpred.example.test/api/publications/feed/"
                "mile_effect_sync#status=404"
            ),
            "evidence_sha256": "d" * 64,
        },
    )
    monkeypatch.setattr(
        supabase_sync,
        "sync_article_projection_result",
        lambda item, storage_dir="storage", *, require_cache_ack=False: (
            _sync_result(succeeded=require_cache_ack)
        ),
    )
    payload = _payload(article)

    outcome = PublisherArticleSyncEffectAdapter(
        projection=SupabaseArticleProjectionAdapter(
            require_mirror_ack=True
        )
    ).deliver(_effect(payload), payload)

    assert isinstance(outcome, FailedEffect)
    assert outcome.reason_code == "publisher_article_sync_provider_error"
    assert outcome.evidence_ref.endswith(
        "mile_effect_sync#status=204"
    )
    assert outcome.evidence_sha256 == "e" * 64


def test_public_projection_non_2xx_is_not_acknowledged(
    monkeypatch,
) -> None:
    from scripts import supabase_sync

    class Response:
        status = 503

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return b'{"error":"unavailable"}'

    monkeypatch.setattr(
        supabase_sync,
        "_mirror_base_url",
        lambda: "https://volpred.example.test",
    )
    monkeypatch.setattr(
        supabase_sync,
        "_urlopen",
        lambda request, timeout=10: Response(),
    )

    readback = supabase_sync.readback_article_public_projection(_article())

    assert readback["matches"] is False
    assert readback["evidence_ref"].endswith("#status=503")


def test_public_projection_invalid_body_and_transport_fail_loud(
    monkeypatch,
) -> None:
    from scripts import supabase_sync

    class InvalidResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return b"not-json"

    monkeypatch.setattr(
        supabase_sync,
        "_mirror_base_url",
        lambda: "https://volpred.example.test",
    )
    monkeypatch.setattr(
        supabase_sync,
        "_urlopen",
        lambda request, timeout=10: InvalidResponse(),
    )
    with pytest.raises(RuntimeError, match="invalid JSON"):
        supabase_sync.readback_article_public_projection(_article())

    monkeypatch.setattr(
        supabase_sync,
        "_urlopen",
        lambda request, timeout=10: (_ for _ in ()).throw(
            URLError("frontend unreachable")
        ),
    )
    with pytest.raises(URLError, match="frontend unreachable"):
        supabase_sync.readback_article_public_projection(_article())


def test_direct_projection_can_require_cache_acknowledgement(
    monkeypatch,
) -> None:
    from scripts import supabase_sync

    article = {**_article(), "tags": []}
    expected = supabase_sync.projected_article_row(article, verbose=False)
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
        lambda table, filters: True,
    )
    monkeypatch.setattr(
        supabase_sync,
        "revalidate_article_cache_with_evidence",
        lambda slug: supabase_sync.ArticleCacheAcknowledgement(
            acknowledged=False,
            target_ref=(
                "https://volpred.example.test/api/sync/revalidate/article/"
                + slug
            ),
            status_code=503,
            evidence_ref=(
                "https://volpred.example.test/api/sync/revalidate/article/"
                + slug
                + "#status=503"
            ),
            evidence_sha256="f" * 64,
        ),
    )

    assert (
        supabase_sync.sync_article_projection(
            article,
            storage_dir="storage",
            require_cache_ack=True,
        )
        is False
    )


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
    from volpred.ops import authority, delivery

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
    projection_options: list[dict] = []
    projection = object()

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
        delivery.SupabaseOwnedPublisherArticleStore,
        "from_environment",
        classmethod(lambda cls: store),
    )
    monkeypatch.setattr(
        delivery,
        "OwnedPublisherArticleSync",
        FakeOwnedSync,
    )
    monkeypatch.setattr(
        delivery,
        "SupabaseArticleProjectionAdapter",
        lambda **kwargs: (
            projection_options.append(kwargs) or projection
        ),
    )
    monkeypatch.setattr(
        authority,
        "build_supabase_host_authority_keepalive",
        lambda **kwargs: (
            keepalive
            if kwargs
            == {
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
    assert projection_options == [
        {
            "storage_dir": "storage",
            "require_mirror_ack": True,
        }
    ]
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
