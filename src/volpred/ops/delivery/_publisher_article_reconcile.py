"""Outbox-ready provider for a non-destructive publisher reconcile batch.

The payload embeds the exact article projections selected by the caller.
Workers therefore never rebuild a plan from a mutable ``feed.json`` after the
EffectRequest has been recorded.  Delete reconciliation remains a separate
destructive concern and is deliberately outside this safe effect family.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Callable

from ._effect import (
    AcknowledgedEffect,
    AcknowledgementExpectation,
    EffectAttemptOutcome,
    EffectRequest,
    EffectView,
    FailedEffect,
)
from ._publisher_article_sync import (
    PublisherArticleProjection,
    PublisherArticleProjectionReadback,
    _normalize_article,
)

_PAYLOAD_SCHEMA = "publisher-article-reconcile.v1"
_EFFECT_KIND = "publisher.article.supabase.reconcile"
_ACKNOWLEDGEMENT_KIND = "publisher.article.supabase.reconcile.readback"
_TARGET_REF = "supabase:articles"
_SHA256 = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class PublisherArticleReconcilePlan:
    """Immutable, non-destructive projection changes for one feed snapshot."""

    canonical_feed_sha256: str
    articles: tuple[dict, ...]


@dataclass(frozen=True)
class PreparedPublisherArticleReconcile:
    """Payload plus its complete formal EffectRequest intent."""

    request: EffectRequest
    payload: bytes


def prepare_publisher_article_reconcile(
    *,
    idempotency_key: str,
    work_item_id: str,
    work_item_version: int,
    payload_ref: str,
    canonical_feed_sha256: str,
    articles: Iterable[Mapping[str, object]],
    requester_ref: str,
) -> PreparedPublisherArticleReconcile:
    """Prepare one safe batch without exposing effect-contract constants."""

    payload = encode_publisher_article_reconcile_payload(
        canonical_feed_sha256=canonical_feed_sha256,
        articles=articles,
    )
    request = EffectRequest(
        idempotency_key=idempotency_key,
        work_item_id=work_item_id,
        work_item_version=work_item_version,
        effect_kind=_EFFECT_KIND,
        target_ref=_TARGET_REF,
        payload_ref=payload_ref,
        payload_sha256=hashlib.sha256(payload).hexdigest(),
        risk="safe",
        acknowledgement=AcknowledgementExpectation(
            kind=_ACKNOWLEDGEMENT_KIND,
            target_ref=_TARGET_REF,
        ),
        requester_ref=requester_ref,
    )
    return PreparedPublisherArticleReconcile(
        request=request,
        payload=payload,
    )


def encode_publisher_article_reconcile_payload(
    *,
    canonical_feed_sha256: str,
    articles: Iterable[Mapping[str, object]],
) -> bytes:
    """Encode a deterministic batch plan for durable payload storage."""

    plan = _normalize_plan(
        canonical_feed_sha256=canonical_feed_sha256,
        articles=articles,
    )
    return _canonical_json(
        {
            "schema_version": _PAYLOAD_SCHEMA,
            "canonical_feed_sha256": plan.canonical_feed_sha256,
            "articles": list(plan.articles),
        }
    )


class PublisherArticleReconcileEffectAdapter:
    """Converge one immutable safe batch and require exact per-row read-back."""

    effect_kinds = frozenset({_EFFECT_KIND})

    def __init__(self, *, projection: PublisherArticleProjection) -> None:
        self._projection = projection

    def deliver(
        self,
        effect: EffectView,
        payload: bytes,
        *,
        authorize_mutation: Callable[[], None] | None = None,
    ) -> EffectAttemptOutcome:
        if not isinstance(payload, bytes):
            return _failure(
                effect,
                "invalid_publisher_article_reconcile_payload",
                retryable=False,
            )
        if hashlib.sha256(payload).hexdigest() != effect.payload_sha256:
            return _failure(
                effect,
                "publisher_article_reconcile_payload_hash_mismatch",
                retryable=False,
            )
        if not _base_contract_matches(effect):
            return _failure(
                effect,
                "unsupported_publisher_article_reconcile_contract",
                retryable=False,
            )
        try:
            plan = _decode_payload(payload)
        except (TypeError, UnicodeError, ValueError, json.JSONDecodeError):
            return _failure(
                effect,
                "invalid_publisher_article_reconcile_payload",
                retryable=False,
            )

        try:
            before = self._readback(plan)
        except Exception:  # noqa: BLE001 - provider errors become evidence.
            return _failure(
                effect,
                "publisher_article_reconcile_provider_error",
                retryable=True,
            )
        acknowledged = _acknowledged(effect, plan, before)
        if acknowledged is not None:
            return acknowledged

        current_readbacks = list(before)
        for index, (article, observed) in enumerate(
            zip(plan.articles, before, strict=True)
        ):
            if _readback_matches(observed):
                continue
            if authorize_mutation is not None:
                # Read-back is a true external boundary and may block long
                # enough for the host authority lease to be replaced.  The
                # owner-fenced caller supplies an exact-epoch revalidation
                # here so a stale attempt cannot write after that boundary.
                # Authority failures deliberately escape instead of becoming
                # provider retries: the durable attempt must expire without a
                # settlement from the stale host.
                authorize_mutation()
            try:
                written = self._projection.upsert(article)
            except Exception:  # noqa: BLE001 - provider errors become evidence.
                written = False
            if not written:
                failure_observation = _projection_failure_evidence(
                    self._projection,
                    article,
                )
                return _failure(
                    effect,
                    "publisher_article_reconcile_provider_error",
                    retryable=True,
                    evidence=_batch_failure_evidence(
                        effect=effect,
                        plan=plan,
                        readbacks=current_readbacks,
                        failed_slug=article["id"],
                        failed_observation=failure_observation,
                    ),
                )
            try:
                post_write = self._projection.readback(article)
            except Exception:  # noqa: BLE001 - provider errors are evidence.
                return _failure(
                    effect,
                    "publisher_article_reconcile_provider_error",
                    retryable=True,
                    evidence=_batch_failure_evidence(
                        effect=effect,
                        plan=plan,
                        readbacks=current_readbacks,
                        failed_slug=article["id"],
                        failed_observation=None,
                    ),
                )
            current_readbacks[index] = post_write
            if not _readback_matches(post_write):
                return _failure(
                    effect,
                    "publisher_article_reconcile_readback_mismatch",
                    retryable=True,
                    evidence=_batch_failure_evidence(
                        effect=effect,
                        plan=plan,
                        readbacks=current_readbacks,
                        failed_slug=article["id"],
                        failed_observation=post_write,
                    ),
                )

        after = tuple(current_readbacks)
        acknowledged = _acknowledged(effect, plan, after)
        if acknowledged is not None:
            return acknowledged
        return _failure(
            effect,
            "publisher_article_reconcile_readback_mismatch",
            retryable=True,
        )

    def _readback(
        self,
        plan: PublisherArticleReconcilePlan,
    ) -> tuple[PublisherArticleProjectionReadback | None, ...]:
        return tuple(self._projection.readback(article) for article in plan.articles)


def _normalize_plan(
    *,
    canonical_feed_sha256: str,
    articles: Iterable[Mapping[str, object]],
) -> PublisherArticleReconcilePlan:
    if (
        not isinstance(canonical_feed_sha256, str)
        or _SHA256.fullmatch(canonical_feed_sha256) is None
    ):
        raise ValueError(
            "canonical feed SHA-256 must be 64 lowercase hexadecimal characters"
        )
    if isinstance(articles, (str, bytes, Mapping)):
        raise TypeError("publisher reconcile articles must be an iterable")
    normalized = tuple(_normalize_article(article) for article in articles)
    if not normalized:
        raise ValueError("publisher reconcile plan must contain an article")
    slugs = [article["id"] for article in normalized]
    if len(slugs) != len(set(slugs)):
        raise ValueError("publisher reconcile plan contains duplicate slugs")
    ordered = tuple(sorted(normalized, key=lambda article: article["id"]))
    return PublisherArticleReconcilePlan(
        canonical_feed_sha256=canonical_feed_sha256,
        articles=ordered,
    )


def _decode_payload(payload: bytes) -> PublisherArticleReconcilePlan:
    decoded = json.loads(payload.decode("utf-8"))
    if not isinstance(decoded, Mapping):
        raise TypeError("publisher reconcile payload must be an object")
    if set(decoded) != {
        "schema_version",
        "canonical_feed_sha256",
        "articles",
    }:
        raise ValueError("publisher reconcile payload fields do not match schema")
    if decoded.get("schema_version") != _PAYLOAD_SCHEMA:
        raise ValueError("unsupported publisher reconcile payload schema")
    articles = decoded.get("articles")
    if not isinstance(articles, list):
        raise TypeError("publisher reconcile payload articles must be a list")
    plan = _normalize_plan(
        canonical_feed_sha256=decoded.get("canonical_feed_sha256"),
        articles=articles,
    )
    if list(plan.articles) != articles:
        raise ValueError("publisher reconcile payload articles are not canonical")
    return plan


def _base_contract_matches(effect: EffectView) -> bool:
    acknowledgement = effect.acknowledgement
    return (
        effect.schema_version == "effect-request.v1"
        and effect.effect_kind == _EFFECT_KIND
        and effect.risk == "safe"
        and effect.target_ref == _TARGET_REF
        and acknowledgement.kind == _ACKNOWLEDGEMENT_KIND
        and acknowledgement.target_ref == _TARGET_REF
    )


def _acknowledged(
    effect: EffectView,
    plan: PublisherArticleReconcilePlan,
    readbacks: tuple[PublisherArticleProjectionReadback | None, ...],
) -> AcknowledgedEffect | None:
    if len(readbacks) != len(plan.articles) or not all(
        _readback_matches(readback) for readback in readbacks
    ):
        return None
    evidence_rows = [
        {
            "slug": article["id"],
            "evidence_ref": readback.evidence_ref.strip(),
            "evidence_sha256": readback.evidence_sha256,
        }
        for article, readback in zip(plan.articles, readbacks, strict=True)
        if readback is not None
    ]
    evidence = _canonical_json(
        {
            "schema_version": "publisher-article-reconcile-readback.v1",
            "canonical_feed_sha256": plan.canonical_feed_sha256,
            "articles": evidence_rows,
        }
    )
    return AcknowledgedEffect(
        acknowledgement=AcknowledgementExpectation(
            kind=_ACKNOWLEDGEMENT_KIND,
            target_ref=_TARGET_REF,
        ),
        evidence_ref="|".join(
            [
                (
                    "supabase:articles:reconcile:"
                    f"{plan.canonical_feed_sha256}"
                ),
                *[
                    str(row["evidence_ref"])
                    for row in evidence_rows
                ],
            ]
        ),
        evidence_sha256=hashlib.sha256(evidence).hexdigest(),
    )


def _readback_matches(
    readback: PublisherArticleProjectionReadback | None,
) -> bool:
    return bool(
        readback is not None
        and readback.matches is True
        and isinstance(readback.evidence_ref, str)
        and readback.evidence_ref.strip()
        and isinstance(readback.evidence_sha256, str)
        and _SHA256.fullmatch(readback.evidence_sha256) is not None
    )


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _failure(
    effect: EffectView,
    reason_code: str,
    *,
    retryable: bool,
    evidence: PublisherArticleProjectionReadback | None = None,
) -> FailedEffect:
    evidence_payload = _canonical_json(
        {
            "effect_id": effect.id,
            "request_sha256": effect.request_sha256,
            "reason_code": reason_code,
            "retryable": retryable,
        }
    )
    return FailedEffect(
        reason_code=reason_code,
        evidence_ref=(
            evidence.evidence_ref
            if _readback_evidence_is_valid(evidence)
            else f"effect-attempt:{effect.id}:{reason_code}"
        ),
        evidence_sha256=(
            evidence.evidence_sha256
            if _readback_evidence_is_valid(evidence)
            else hashlib.sha256(evidence_payload).hexdigest()
        ),
        retryable=retryable,
    )


def _projection_failure_evidence(
    projection: PublisherArticleProjection,
    article: dict,
) -> PublisherArticleProjectionReadback | None:
    reader = getattr(projection, "failure_evidence", None)
    if not callable(reader):
        return None
    observed = reader(article)
    return observed if _readback_evidence_is_valid(observed) else None


def _batch_failure_evidence(
    *,
    effect: EffectView,
    plan: PublisherArticleReconcilePlan,
    readbacks: list[PublisherArticleProjectionReadback | None],
    failed_slug: str,
    failed_observation: PublisherArticleProjectionReadback | None,
) -> PublisherArticleProjectionReadback:
    rows = [
        {
            "slug": article["id"],
            "matches": observed.matches,
            "evidence_ref": observed.evidence_ref,
            "evidence_sha256": observed.evidence_sha256,
        }
        for article, observed in zip(
            plan.articles,
            readbacks,
            strict=True,
        )
        if _readback_evidence_is_valid(observed)
    ]
    if (
        _readback_evidence_is_valid(failed_observation)
        and not any(
            row["slug"] == failed_slug
            and row["evidence_sha256"]
            == failed_observation.evidence_sha256
            for row in rows
        )
    ):
        rows.append(
            {
                "slug": failed_slug,
                "matches": failed_observation.matches,
                "evidence_ref": failed_observation.evidence_ref,
                "evidence_sha256": (
                    failed_observation.evidence_sha256
                ),
            }
        )
    payload = _canonical_json(
        {
            "schema_version": (
                "publisher-article-reconcile-failure-evidence.v1"
            ),
            "effect_id": effect.id,
            "canonical_feed_sha256": plan.canonical_feed_sha256,
            "failed_slug": failed_slug,
            "observations": rows,
        }
    )
    refs = [
        str(row["evidence_ref"])
        for row in rows
        if isinstance(row.get("evidence_ref"), str)
    ]
    return PublisherArticleProjectionReadback(
        matches=False,
        evidence_ref="|".join(
            [
                f"effect-attempt:{effect.id}:partial",
                *refs,
            ]
        ),
        evidence_sha256=hashlib.sha256(payload).hexdigest(),
    )


def _readback_evidence_is_valid(
    readback: PublisherArticleProjectionReadback | None,
) -> bool:
    return bool(
        readback is not None
        and isinstance(readback.evidence_ref, str)
        and readback.evidence_ref.strip()
        and isinstance(readback.evidence_sha256, str)
        and _SHA256.fullmatch(readback.evidence_sha256) is not None
    )


__all__ = [
    "PreparedPublisherArticleReconcile",
    "PublisherArticleReconcileEffectAdapter",
    "PublisherArticleReconcilePlan",
    "encode_publisher_article_reconcile_payload",
    "prepare_publisher_article_reconcile",
]
