from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from volpred.ops.delivery import (
    AcknowledgedEffect,
    AcknowledgementExpectation,
    EffectDelivery,
    EffectRequestConflict,
    FailedEffect,
    PublisherArticleDeleteApprovalReadback,
    PublisherArticleDeleteAuthorization,
    PublisherArticleDeleteCandidateReadback,
    PublisherArticleDeleteEffectAdapter,
    plan_publisher_article_delete,
    prepare_publisher_article_delete,
)


def _feed(count: int = 3) -> bytes:
    return json.dumps(
        [{"id": f"mile_canonical_{index}"} for index in range(count)],
        separators=(",", ":"),
    ).encode()


def _candidate(slug: str, article_id: str) -> dict:
    return {
        "article": {
            "id": article_id,
            "slug": slug,
            "title": f"Ghost {slug}",
            "status": "published",
        },
        "dependents": {
            "article_impressions": [
                {"article_id": article_id, "viewed_at": "2026-07-25T00:00:00Z"}
            ],
            "article_reactions": [],
            "article_relations": [
                {
                    "id": f"relation-{article_id}",
                    "source_id": article_id,
                    "target_id": "article-canonical",
                }
            ],
            "article_tags": [{"article_id": article_id, "tag_id": "tag-spy"}],
            "comments": [],
            "question_articles": [],
        },
    }


def _plan():
    return plan_publisher_article_delete(
        canonical_feed=_feed(),
        candidates=[
            _candidate("mile_ghost_b", "article-b"),
            _candidate("mile_ghost_a", "article-a"),
        ],
        recovery_artifact_ref="artifact:publisher/delete/recovery.jsonl",
        minimum_canonical_articles=3,
        maximum_deletes=2,
    )


def _authorization(scope_sha256: str) -> PublisherArticleDeleteAuthorization:
    return PublisherArticleDeleteAuthorization(
        approval_ref="approval:publisher-delete/42",
        approver_ref="owner:telegram/1329",
        approved_at="2026-07-25T06:45:00+08:00",
        scope_sha256=scope_sha256,
    )


def _prepare(plan=None, authorization=None):
    actual_plan = plan or _plan()
    return prepare_publisher_article_delete(
        plan=actual_plan,
        authorization=authorization or _authorization(actual_plan.scope_sha256),
        idempotency_key=f"publisher:delete:{actual_plan.scope_sha256}",
        work_item_id="work-publisher-delete-1",
        work_item_version=1,
        payload_ref="artifact:publisher/delete/intent.json",
        requester_ref="publisher:delete-operator",
    )


def _effect(prepared=None):
    actual = prepared or _prepare()
    return EffectDelivery(
        clock=lambda: datetime(2026, 7, 25, tzinfo=UTC),
        id_factory=lambda: "effect-publisher-delete-1",
    ).request(actual.request)


class _ApprovalVerifier:
    def __init__(
        self,
        *,
        active: list[bool] | None = None,
        events: list[str] | None = None,
    ) -> None:
        self._active = list(active or [True])
        self.events = events if events is not None else []
        self.calls = 0

    def readback(
        self,
        authorization: PublisherArticleDeleteAuthorization,
    ) -> PublisherArticleDeleteApprovalReadback:
        self.events.append("approval")
        active = self._active[min(self.calls, len(self._active) - 1)]
        self.calls += 1
        return PublisherArticleDeleteApprovalReadback(
            authorization=authorization,
            active=active,
            evidence_ref=f"approval-readback:{authorization.approval_ref}",
            evidence_sha256=hashlib.sha256(
                f"{authorization.approval_ref}:{active}".encode()
            ).hexdigest(),
        )


class _DeleteProjection:
    def __init__(
        self,
        candidates: list[dict],
        *,
        events: list[str] | None = None,
        delete_applies: bool = True,
    ) -> None:
        self.rows = {
            candidate["article"]["id"]: json.loads(json.dumps(candidate))
            for candidate in candidates
        }
        self.events = events if events is not None else []
        self.delete_applies = delete_applies
        self.delete_calls: list[str] = []

    def readback(
        self,
        expected_candidate: dict,
    ) -> PublisherArticleDeleteCandidateReadback:
        article_id = expected_candidate["article"]["id"]
        self.events.append(f"read:{article_id}")
        candidate = self.rows[article_id]
        snapshot = (
            None if candidate is None else json.loads(json.dumps(candidate))
        )
        evidence = json.dumps(
            {"article_id": article_id, "candidate": snapshot},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return PublisherArticleDeleteCandidateReadback(
            article_id=article_id,
            candidate=snapshot,
            evidence_ref=f"supabase:articles:{article_id}",
            evidence_sha256=hashlib.sha256(evidence).hexdigest(),
        )

    def delete(self, expected_candidate: dict) -> bool:
        article_id = expected_candidate["article"]["id"]
        self.events.append(f"delete:{article_id}")
        self.delete_calls.append(article_id)
        if self.rows[article_id] != expected_candidate:
            return False
        if self.delete_applies:
            self.rows[article_id] = None
        return True


def test_plan_freezes_guards_scope_and_complete_recovery_rows() -> None:
    plan = _plan()

    scope = json.loads(plan.scope)
    recovery = [
        json.loads(line) for line in plan.recovery_dump.splitlines()
    ]

    assert plan.canonical_feed_sha256 == hashlib.sha256(_feed()).hexdigest()
    assert plan.canonical_article_count == 3
    assert plan.delete_count == 2
    assert hashlib.sha256(plan.scope).hexdigest() == plan.scope_sha256
    assert (
        hashlib.sha256(plan.recovery_dump).hexdigest()
        == plan.recovery_dump_sha256
    )
    assert scope["guards"] == {
        "maximum_deletes": 2,
        "minimum_canonical_articles": 3,
    }
    assert [row["article"]["slug"] for row in recovery] == [
        "mile_ghost_a",
        "mile_ghost_b",
    ]
    assert set(recovery[0]["dependents"]) == {
        "article_impressions",
        "article_reactions",
        "article_relations",
        "article_tags",
        "comments",
        "question_articles",
    }


def test_plan_is_deterministic_across_candidate_and_dependent_row_order() -> None:
    first_candidate = _candidate("mile_ghost_a", "article-a")
    first_candidate["dependents"]["comments"] = [
        {"id": "comment-z", "article_id": "article-a"},
        {"id": "comment-a", "article_id": "article-a"},
    ]
    second_candidate = _candidate("mile_ghost_b", "article-b")
    first = plan_publisher_article_delete(
        canonical_feed=_feed(),
        candidates=[first_candidate, second_candidate],
        recovery_artifact_ref="artifact:publisher/delete/recovery.jsonl",
        minimum_canonical_articles=3,
        maximum_deletes=2,
    )
    first_candidate["dependents"]["comments"].reverse()
    second = plan_publisher_article_delete(
        canonical_feed=_feed(),
        candidates=[second_candidate, first_candidate],
        recovery_artifact_ref="artifact:publisher/delete/recovery.jsonl",
        minimum_canonical_articles=3,
        maximum_deletes=2,
    )

    assert second == first


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        (
            {
                "canonical_feed": _feed(2),
                "candidates": [_candidate("mile_ghost", "article-ghost")],
                "minimum_canonical_articles": 3,
                "maximum_deletes": 2,
            },
            "below the configured floor",
        ),
        (
            {
                "canonical_feed": _feed(3),
                "candidates": [
                    _candidate("mile_ghost_a", "article-a"),
                    _candidate("mile_ghost_b", "article-b"),
                ],
                "minimum_canonical_articles": 3,
                "maximum_deletes": 1,
            },
            "exceeds the configured cap",
        ),
        (
            {
                "canonical_feed": _feed(3),
                "candidates": [
                    _candidate("mile_canonical_1", "article-canonical")
                ],
                "minimum_canonical_articles": 3,
                "maximum_deletes": 1,
            },
            "still exist in the canonical feed",
        ),
    ],
)
def test_plan_fails_closed_before_authorization(kwargs: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        plan_publisher_article_delete(
            recovery_artifact_ref="artifact:publisher/delete/recovery.jsonl",
            **kwargs,
        )


def test_plan_requires_every_cascade_family_for_exact_rollback() -> None:
    candidate = _candidate("mile_ghost", "article-ghost")
    candidate["dependents"].pop("comments")

    with pytest.raises(ValueError, match="every cascade table"):
        plan_publisher_article_delete(
            canonical_feed=_feed(),
            candidates=[candidate],
            recovery_artifact_ref="artifact:publisher/delete/recovery.jsonl",
            minimum_canonical_articles=3,
            maximum_deletes=1,
        )


def test_plan_rejects_cascade_rows_for_a_different_article() -> None:
    candidate = _candidate("mile_ghost", "article-ghost")
    candidate["dependents"]["article_tags"][0]["article_id"] = "article-other"

    with pytest.raises(ValueError, match="bound to a different article"):
        plan_publisher_article_delete(
            canonical_feed=_feed(),
            candidates=[candidate],
            recovery_artifact_ref="artifact:publisher/delete/recovery.jsonl",
            minimum_canonical_articles=3,
            maximum_deletes=1,
        )


def test_plan_rejects_relation_when_neither_endpoint_is_the_article() -> None:
    candidate = _candidate("mile_ghost", "article-ghost")
    candidate["dependents"]["article_relations"][0].update(
        {
            "source_id": "article-other-a",
            "target_id": "article-other-b",
        }
    )

    with pytest.raises(ValueError, match="bound to a different article"):
        plan_publisher_article_delete(
            canonical_feed=_feed(),
            candidates=[candidate],
            recovery_artifact_ref="artifact:publisher/delete/recovery.jsonl",
            minimum_canonical_articles=3,
            maximum_deletes=1,
        )


def test_prepare_rejects_approval_for_a_different_scope() -> None:
    plan = _plan()
    authorization = replace(
        _authorization(plan.scope_sha256),
        scope_sha256="0" * 64,
    )

    with pytest.raises(ValueError, match="not bound to this exact scope"):
        _prepare(plan, authorization)


def test_prepare_materializes_destructive_effect_without_provider_io() -> None:
    plan = _plan()
    prepared = _prepare(plan)
    payload = json.loads(prepared.payload)
    delivery = EffectDelivery(
        clock=lambda: datetime(2026, 7, 25, tzinfo=UTC),
        id_factory=lambda: "effect-publisher-delete-1",
    )

    first = delivery.request(prepared.request)
    replay = delivery.request(prepared.request)

    assert replay == first
    assert first.effect_kind == "publisher.article.supabase.delete"
    assert first.risk == "destructive"
    assert first.acknowledgement == AcknowledgementExpectation(
        kind="publisher.article.supabase.delete.readback",
        target_ref="supabase:articles",
    )
    assert payload["scope_sha256"] == plan.scope_sha256
    assert payload["authorization"]["scope_sha256"] == plan.scope_sha256
    assert prepared.recovery_dump == plan.recovery_dump


def test_changed_approval_cannot_reuse_effect_idempotency_key() -> None:
    plan = _plan()
    first = _prepare(plan)
    changed = _prepare(
        plan,
        replace(
            _authorization(plan.scope_sha256),
            approval_ref="approval:publisher-delete/43",
        ),
    )
    delivery = EffectDelivery(
        clock=lambda: datetime(2026, 7, 25, tzinfo=UTC),
        id_factory=lambda: "effect-publisher-delete-1",
    )

    delivery.request(first.request)
    with pytest.raises(EffectRequestConflict):
        delivery.request(changed.request)


def test_tampered_plan_is_rejected_before_effect_request() -> None:
    plan = _plan()
    tampered = replace(plan, recovery_dump=plan.recovery_dump + b"{}\\n")

    with pytest.raises(ValueError, match="recovery hash"):
        _prepare(tampered)


def test_delete_adapter_requires_exact_scope_then_typed_absence() -> None:
    prepared = _prepare()
    payload = json.loads(prepared.payload)
    candidates = payload["scope"]["candidates"]
    events: list[str] = []
    approval = _ApprovalVerifier(events=events)
    projection = _DeleteProjection(candidates, events=events)
    authority_calls = 0

    def authorize() -> None:
        nonlocal authority_calls
        authority_calls += 1
        events.append("authority")

    outcome = PublisherArticleDeleteEffectAdapter(
        approval=approval,
        projection=projection,
    ).deliver(
        _effect(prepared),
        prepared.payload,
        authorize_mutation=authorize,
    )

    assert isinstance(outcome, AcknowledgedEffect)
    assert outcome.acknowledgement == prepared.request.acknowledgement
    assert projection.delete_calls == ["article-a", "article-b"]
    assert approval.calls == 3
    assert authority_calls == 2
    assert events.index("authority") < events.index("delete:article-a")
    assert events.index("delete:article-a") < events.index("delete:article-b")
    assert all(row is None for row in projection.rows.values())


def test_delete_adapter_preflights_all_candidates_before_first_write() -> None:
    prepared = _prepare()
    candidates = json.loads(prepared.payload)["scope"]["candidates"]
    projection = _DeleteProjection(candidates)
    projection.rows["article-b"]["article"]["title"] = "Changed remotely"

    outcome = PublisherArticleDeleteEffectAdapter(
        approval=_ApprovalVerifier(),
        projection=projection,
    ).deliver(_effect(prepared), prepared.payload)

    assert isinstance(outcome, FailedEffect)
    assert outcome.reason_code == "publisher_article_delete_scope_drift"
    assert outcome.retryable is False
    assert projection.delete_calls == []


def test_delete_adapter_reports_malformed_provider_readback() -> None:
    prepared = _prepare()
    candidates = json.loads(prepared.payload)["scope"]["candidates"]
    projection = _DeleteProjection(candidates)
    projection.rows["article-b"] = {"article": {"id": "article-b"}}

    outcome = PublisherArticleDeleteEffectAdapter(
        approval=_ApprovalVerifier(),
        projection=projection,
    ).deliver(_effect(prepared), prepared.payload)

    assert isinstance(outcome, FailedEffect)
    assert outcome.reason_code == "publisher_article_delete_provider_error"
    assert outcome.retryable is True
    assert projection.delete_calls == []


def test_delete_adapter_rechecks_durable_approval_at_mutation_boundary() -> None:
    prepared = _prepare()
    candidates = json.loads(prepared.payload)["scope"]["candidates"]
    projection = _DeleteProjection(candidates)

    outcome = PublisherArticleDeleteEffectAdapter(
        approval=_ApprovalVerifier(active=[True, False]),
        projection=projection,
    ).deliver(_effect(prepared), prepared.payload)

    assert isinstance(outcome, FailedEffect)
    assert outcome.reason_code == "publisher_article_delete_approval_not_active"
    assert outcome.retryable is False
    assert projection.delete_calls == []


def test_delete_adapter_authority_loss_escapes_without_mutation() -> None:
    prepared = _prepare()
    candidates = json.loads(prepared.payload)["scope"]["candidates"]
    projection = _DeleteProjection(candidates)

    def replaced_authority() -> None:
        raise RuntimeError("primary authority lease replaced")

    with pytest.raises(RuntimeError, match="lease replaced"):
        PublisherArticleDeleteEffectAdapter(
            approval=_ApprovalVerifier(),
            projection=projection,
        ).deliver(
            _effect(prepared),
            prepared.payload,
            authorize_mutation=replaced_authority,
        )

    assert projection.delete_calls == []


def test_delete_adapter_replay_accepts_only_typed_absence_evidence() -> None:
    prepared = _prepare()
    candidates = json.loads(prepared.payload)["scope"]["candidates"]
    projection = _DeleteProjection(candidates)
    projection.rows = {article_id: None for article_id in projection.rows}
    authority_calls: list[None] = []

    outcome = PublisherArticleDeleteEffectAdapter(
        approval=_ApprovalVerifier(),
        projection=projection,
    ).deliver(
        _effect(prepared),
        prepared.payload,
        authorize_mutation=lambda: authority_calls.append(None),
    )

    assert isinstance(outcome, AcknowledgedEffect)
    assert projection.delete_calls == []
    assert authority_calls == []


def test_delete_adapter_fails_when_delete_lacks_absence_readback() -> None:
    prepared = _prepare()
    candidates = json.loads(prepared.payload)["scope"]["candidates"]
    projection = _DeleteProjection(candidates, delete_applies=False)

    outcome = PublisherArticleDeleteEffectAdapter(
        approval=_ApprovalVerifier(),
        projection=projection,
    ).deliver(_effect(prepared), prepared.payload)

    assert isinstance(outcome, FailedEffect)
    assert outcome.reason_code == "publisher_article_delete_absence_mismatch"
    assert outcome.retryable is True
