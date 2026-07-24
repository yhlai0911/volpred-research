from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from volpred.ops.authority import PrimaryLease
from volpred.ops.delivery import (
    AcknowledgedEffect,
    AcknowledgementExpectation,
    EffectDelivery,
    EffectView,
    FailedEffect,
    PublisherArticleProjectionReadback,
    PublisherArticleReconcileEffectAdapter,
    encode_publisher_article_reconcile_payload,
    prepare_publisher_article_reconcile,
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

FEED_SHA256 = "f" * 64


def _article(slug: str) -> dict:
    return {
        "id": slug,
        "title": f"Reconcile {slug}",
        "content": f"Canonical body for {slug}.",
        "audience": "research",
        "status": "published",
        "tags": ["SPY"],
    }


def _payload() -> bytes:
    return encode_publisher_article_reconcile_payload(
        canonical_feed_sha256=FEED_SHA256,
        articles=[
            _article("mile_reconcile_b"),
            _article("mile_reconcile_a"),
        ],
    )


def _effect(payload: bytes | None = None) -> EffectView:
    encoded = payload or _payload()
    return EffectView(
        schema_version="effect-request.v1",
        id="effect-publisher-reconcile-1",
        idempotency_key=f"publisher:reconcile:{FEED_SHA256}",
        work_item_id="work-publisher-reconcile-1",
        work_item_version=2,
        effect_kind="publisher.article.supabase.reconcile",
        target_ref="supabase:articles",
        payload_ref="artifact:publisher/reconcile-f.json",
        payload_sha256=hashlib.sha256(encoded).hexdigest(),
        risk="safe",
        acknowledgement=AcknowledgementExpectation(
            kind="publisher.article.supabase.reconcile.readback",
            target_ref="supabase:articles",
        ),
        requester_ref="publisher:hourly-reconcile",
        request_sha256="a" * 64,
        status="requested",
        created_at="2026-07-25T00:00:00+00:00",
    )


class _Projection:
    def __init__(self) -> None:
        self.current: dict[str, dict] = {}
        self.upserts: list[str] = []
        self.fail_slug: str | None = None
        self.mismatch_slug: str | None = None
        self.invalid_evidence_slug: str | None = None

    def readback(
        self,
        article: dict,
    ) -> PublisherArticleProjectionReadback | None:
        slug = article["id"]
        current = self.current.get(slug)
        if current is None:
            return None
        encoded = json.dumps(
            current,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return PublisherArticleProjectionReadback(
            matches=(slug != self.mismatch_slug and current == article),
            evidence_ref=(
                ""
                if slug == self.invalid_evidence_slug
                else f"supabase:articles/{slug}"
            ),
            evidence_sha256=hashlib.sha256(encoded).hexdigest(),
        )

    def upsert(self, article: dict) -> bool:
        slug = article["id"]
        self.upserts.append(slug)
        if slug == self.fail_slug:
            return False
        self.current[slug] = json.loads(json.dumps(article))
        return True


def test_prepare_hides_contract_and_materializes_one_effect_request() -> None:
    prepared = prepare_publisher_article_reconcile(
        idempotency_key=f"publisher:reconcile:{FEED_SHA256}",
        work_item_id="work-publisher-reconcile-1",
        work_item_version=2,
        payload_ref="artifact:publisher/reconcile-f.json",
        canonical_feed_sha256=FEED_SHA256,
        articles=[
            _article("mile_reconcile_b"),
            _article("mile_reconcile_a"),
        ],
        requester_ref="publisher:hourly-reconcile",
    )
    delivery = EffectDelivery(
        clock=lambda: datetime(2026, 7, 25, tzinfo=UTC),
        id_factory=lambda: "effect-publisher-reconcile-1",
    )

    first = delivery.request(prepared.request)
    replay = delivery.request(prepared.request)

    assert replay == first
    assert first.effect_kind == "publisher.article.supabase.reconcile"
    assert first.target_ref == "supabase:articles"
    assert first.payload_sha256 == hashlib.sha256(prepared.payload).hexdigest()
    assert first.acknowledgement == AcknowledgementExpectation(
        kind="publisher.article.supabase.reconcile.readback",
        target_ref="supabase:articles",
    )


def test_batch_plan_is_canonical_and_replay_skips_converged_rows() -> None:
    projection = _Projection()
    already_converged = _article("mile_reconcile_a")
    projection.current[already_converged["id"]] = already_converged
    payload = _payload()
    decoded = json.loads(payload)

    first = PublisherArticleReconcileEffectAdapter(projection=projection).deliver(
        _effect(payload), payload
    )
    replay = PublisherArticleReconcileEffectAdapter(projection=projection).deliver(
        _effect(payload), payload
    )

    assert [article["id"] for article in decoded["articles"]] == [
        "mile_reconcile_a",
        "mile_reconcile_b",
    ]
    assert isinstance(first, AcknowledgedEffect)
    assert replay == first
    assert projection.upserts == ["mile_reconcile_b"]
    assert first.evidence_ref == f"supabase:articles:reconcile:{FEED_SHA256}"


def test_provider_failure_is_retryable_without_writing_later_rows() -> None:
    projection = _Projection()
    projection.fail_slug = "mile_reconcile_a"
    payload = _payload()

    outcome = PublisherArticleReconcileEffectAdapter(projection=projection).deliver(
        _effect(payload), payload
    )

    assert isinstance(outcome, FailedEffect)
    assert outcome.reason_code == "publisher_article_reconcile_provider_error"
    assert outcome.retryable is True
    assert projection.upserts == ["mile_reconcile_a"]


def test_invalid_post_write_evidence_is_not_an_acknowledgement() -> None:
    projection = _Projection()
    projection.invalid_evidence_slug = "mile_reconcile_b"
    payload = _payload()

    outcome = PublisherArticleReconcileEffectAdapter(projection=projection).deliver(
        _effect(payload), payload
    )

    assert isinstance(outcome, FailedEffect)
    assert outcome.reason_code == ("publisher_article_reconcile_readback_mismatch")
    assert outcome.retryable is True
    assert projection.upserts == [
        "mile_reconcile_a",
        "mile_reconcile_b",
    ]


@pytest.mark.parametrize(
    ("effect_change", "payload", "reason"),
    [
        (
            {"risk": "destructive"},
            _payload(),
            "unsupported_publisher_article_reconcile_contract",
        ),
        (
            {},
            (
                b'{"articles":[],"canonical_feed_sha256":"'
                + FEED_SHA256.encode()
                + b'","schema_version":"publisher-article-reconcile.v1"}'
            ),
            "invalid_publisher_article_reconcile_payload",
        ),
        (
            {},
            (
                b'{"articles":[{"id":"mile_z"},{"id":"mile_a"}],'
                b'"canonical_feed_sha256":"'
                + FEED_SHA256.encode()
                + b'","schema_version":"publisher-article-reconcile.v1"}'
            ),
            "invalid_publisher_article_reconcile_payload",
        ),
    ],
)
def test_invalid_intent_is_terminal_before_projection_write(
    effect_change: dict,
    payload: bytes,
    reason: str,
) -> None:
    projection = _Projection()
    effect = replace(_effect(payload), **effect_change)

    outcome = PublisherArticleReconcileEffectAdapter(projection=projection).deliver(
        effect, payload
    )

    assert isinstance(outcome, FailedEffect)
    assert outcome.reason_code == reason
    assert outcome.retryable is False
    assert projection.upserts == []


class _Authority:
    def authorize(self, request):
        return EffectAuthorityGrant(
            request_sha256=request.request_sha256,
            outbox_claim_ref="effect-outbox:52:attempt-1",
            primary_authority_ref="primary-authority:epoch-9",
        )


class _PrimaryAuthority:
    def current_lease(self) -> PrimaryLease:
        return PrimaryLease(
            schema_version="primary-lease.v1",
            authority_key="operations-core-effects",
            holder_ref="host:primary",
            epoch=9,
            fencing_token="primary-token",
            lease_seconds=300,
            acquired_at="2026-07-25T00:00:00+00:00",
            expires_at="2026-07-25T00:05:00+00:00",
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
        assert effect_kinds == frozenset({"publisher.article.supabase.reconcile"})
        return EffectOutboxLease(
            sequence=52,
            effect_id=self.effect.id,
            token="outbox-token",
            claimed_by=worker_id,
            attempt_count=1,
            expires_at="2026-07-25T00:05:00+00:00",
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
            recorded_at="2026-07-25T00:00:01+00:00",
        )


def test_invalid_batch_is_durably_dead_lettered_by_effect_worker() -> None:
    payload = _payload()
    invalid = replace(_effect(payload), risk="destructive")
    store = _TerminalStore(invalid)
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
        provider=PublisherArticleReconcileEffectAdapter(projection=projection),
    )

    receipt = worker.run_once(
        EffectWorkerCommand(
            worker_id="effect-worker:publisher-reconcile",
            lease_seconds=300,
        )
    )

    assert receipt is not None
    assert receipt.disposition == "dead_lettered"
    assert store.outcome is not None
    assert store.outcome.reason_code == (
        "unsupported_publisher_article_reconcile_contract"
    )
    assert projection.upserts == []
