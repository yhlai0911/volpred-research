"""Immutable intent contract for guarded publisher article deletion.

Deletion is deliberately separate from the unattended safe reconcile family.
This module performs no provider I/O.  It freezes the canonical feed identity,
the exact remote rows selected for deletion, every cascade-affected row needed
for rollback, the floor/cap guards, and a scope-bound operator approval into
one destructive EffectRequest.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Protocol

from ._effect import (
    AcknowledgedEffect,
    AcknowledgementExpectation,
    EffectAttemptOutcome,
    EffectRequest,
    EffectView,
    FailedEffect,
)

_SCOPE_SCHEMA = "publisher-article-delete-scope.v1"
_PAYLOAD_SCHEMA = "publisher-article-delete.v1"
_RECOVERY_SCHEMA = "publisher-article-delete-recovery.v1"
_EFFECT_KIND = "publisher.article.supabase.delete"
_ACKNOWLEDGEMENT_KIND = "publisher.article.supabase.delete.readback"
_TARGET_REF = "supabase:articles"
_SHA256 = re.compile(r"[0-9a-f]{64}")
PUBLISHER_ARTICLE_DELETE_CASCADE_COLUMNS = (
    ("article_impressions", ("article_id",)),
    ("article_reactions", ("article_id",)),
    ("article_relations", ("source_id", "target_id")),
    ("article_tags", ("article_id",)),
    ("comments", ("article_id",)),
    ("question_articles", ("article_id",)),
)
_CASCADE_COLUMNS = dict(PUBLISHER_ARTICLE_DELETE_CASCADE_COLUMNS)
_CASCADE_TABLES = frozenset(_CASCADE_COLUMNS)


@dataclass(frozen=True)
class PublisherArticleDeletePlan:
    """Immutable destructive scope plus its complete rollback artifact."""

    scope: bytes
    scope_sha256: str
    recovery_dump: bytes
    recovery_dump_sha256: str
    canonical_feed_sha256: str
    canonical_article_count: int
    delete_count: int


@dataclass(frozen=True)
class PublisherArticleDeleteAuthorization:
    """Opaque durable approval bound to exactly one delete scope."""

    approval_ref: str
    approver_ref: str
    approved_at: str
    scope_sha256: str


@dataclass(frozen=True)
class PreparedPublisherArticleDelete:
    """Payload, recovery bytes, and complete formal EffectRequest intent."""

    request: EffectRequest
    payload: bytes
    recovery_dump: bytes
    scope_sha256: str


@dataclass(frozen=True)
class PublisherArticleDeleteApprovalReadback:
    """Typed evidence that the scope-bound durable approval remains active."""

    authorization: PublisherArticleDeleteAuthorization
    active: bool
    evidence_ref: str
    evidence_sha256: str


@dataclass(frozen=True)
class PublisherArticleDeleteCandidateReadback:
    """Complete candidate/cascade state, or typed evidence of its absence."""

    article_id: str
    candidate: Mapping[str, object] | None
    evidence_ref: str
    evidence_sha256: str

    @property
    def absent(self) -> bool:
        return self.candidate is None


class _PublisherArticleDeleteApprovalVerifier(Protocol):
    def readback(
        self,
        authorization: PublisherArticleDeleteAuthorization,
    ) -> PublisherArticleDeleteApprovalReadback: ...


class _PublisherArticleDeleteProjection(Protocol):
    def readback(
        self,
        expected_candidate: Mapping[str, object],
    ) -> PublisherArticleDeleteCandidateReadback: ...

    def delete(
        self,
        expected_candidate: Mapping[str, object],
    ) -> bool:
        """Atomically compare the complete expected candidate and delete it."""
        ...


@dataclass(frozen=True)
class _PublisherArticleDeleteExecution:
    scope_sha256: str
    canonical_feed_sha256: str
    recovery_dump_sha256: str
    authorization: PublisherArticleDeleteAuthorization
    candidates: tuple[dict, ...]


class PublisherArticleDeleteEffectAdapter:
    """Delete one approved immutable scope and require typed absence read-back."""

    effect_kinds = frozenset({_EFFECT_KIND})

    def __init__(
        self,
        *,
        approval: _PublisherArticleDeleteApprovalVerifier,
        projection: _PublisherArticleDeleteProjection,
    ) -> None:
        self._approval = approval
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
                "invalid_publisher_article_delete_payload",
                retryable=False,
            )
        if hashlib.sha256(payload).hexdigest() != effect.payload_sha256:
            return _failure(
                effect,
                "publisher_article_delete_payload_hash_mismatch",
                retryable=False,
            )
        if not _base_contract_matches(effect):
            return _failure(
                effect,
                "unsupported_publisher_article_delete_contract",
                retryable=False,
            )
        try:
            execution = _decode_payload(payload)
        except (TypeError, UnicodeError, ValueError, json.JSONDecodeError):
            return _failure(
                effect,
                "invalid_publisher_article_delete_payload",
                retryable=False,
            )

        approval_failure = self._verify_approval(effect, execution.authorization)
        if approval_failure is not None:
            return approval_failure

        before: list[PublisherArticleDeleteCandidateReadback] = []
        for candidate in execution.candidates:
            observed = self._readback(effect, candidate)
            if isinstance(observed, FailedEffect):
                return observed
            if not observed.absent:
                try:
                    matches = _candidate_readback_matches(observed, candidate)
                except (TypeError, ValueError):
                    return _failure(
                        effect,
                        "publisher_article_delete_provider_error",
                        retryable=True,
                    )
                if matches:
                    before.append(observed)
                    continue
                return _failure(
                    effect,
                    "publisher_article_delete_scope_drift",
                    retryable=False,
                )
            before.append(observed)

        acknowledged = _acknowledged(effect, execution, tuple(before))
        if acknowledged is not None:
            return acknowledged

        for candidate, observed in zip(
            execution.candidates,
            before,
            strict=True,
        ):
            if observed.absent:
                continue
            boundary_readback = self._readback(effect, candidate)
            if isinstance(boundary_readback, FailedEffect):
                return boundary_readback
            try:
                boundary_matches = _candidate_readback_matches(
                    boundary_readback,
                    candidate,
                )
            except (TypeError, ValueError):
                return _failure(
                    effect,
                    "publisher_article_delete_provider_error",
                    retryable=True,
                )
            if not boundary_matches:
                return _failure(
                    effect,
                    "publisher_article_delete_scope_drift",
                    retryable=False,
                )
            approval_failure = self._verify_approval(
                effect,
                execution.authorization,
            )
            if approval_failure is not None:
                return approval_failure
            if authorize_mutation is not None:
                # Approval and remote read-back are external boundaries. The
                # owner-fenced caller revalidates its exact authority epoch
                # immediately before every destructive mutation.
                authorize_mutation()
            try:
                deleted = self._projection.delete(candidate)
            except Exception:  # noqa: BLE001 - provider failures are evidence.
                deleted = False
            if not deleted:
                return _failure(
                    effect,
                    "publisher_article_delete_provider_error",
                    retryable=True,
                )

        after: list[PublisherArticleDeleteCandidateReadback] = []
        for candidate in execution.candidates:
            observed = self._readback(effect, candidate)
            if isinstance(observed, FailedEffect):
                return observed
            after.append(observed)
        acknowledged = _acknowledged(effect, execution, tuple(after))
        if acknowledged is not None:
            return acknowledged
        return _failure(
            effect,
            "publisher_article_delete_absence_mismatch",
            retryable=True,
        )

    def _verify_approval(
        self,
        effect: EffectView,
        authorization: PublisherArticleDeleteAuthorization,
    ) -> FailedEffect | None:
        try:
            readback = self._approval.readback(authorization)
        except Exception:  # noqa: BLE001 - provider failures are evidence.
            return _failure(
                effect,
                "publisher_article_delete_approval_provider_error",
                retryable=True,
            )
        if not _approval_readback_matches(readback, authorization):
            return _failure(
                effect,
                "publisher_article_delete_approval_not_active",
                retryable=False,
            )
        return None

    def _readback(
        self,
        effect: EffectView,
        candidate: Mapping[str, object],
    ) -> PublisherArticleDeleteCandidateReadback | FailedEffect:
        try:
            readback = self._projection.readback(candidate)
        except Exception:  # noqa: BLE001 - provider failures are evidence.
            return _failure(
                effect,
                "publisher_article_delete_provider_error",
                retryable=True,
            )
        article = candidate["article"]
        article_id = article["id"]
        if (
            not isinstance(readback, PublisherArticleDeleteCandidateReadback)
            or readback.article_id != article_id
            or not _valid_evidence(
                readback.evidence_ref,
                readback.evidence_sha256,
            )
        ):
            return _failure(
                effect,
                "publisher_article_delete_provider_error",
                retryable=True,
            )
        return readback


def plan_publisher_article_delete(
    *,
    canonical_feed: bytes,
    candidates: Iterable[Mapping[str, object]],
    recovery_artifact_ref: str,
    minimum_canonical_articles: int = 500,
    maximum_deletes: int = 300,
) -> PublisherArticleDeletePlan:
    """Freeze a guarded delete scope without authorizing or executing it.

    Each candidate must contain the complete remote ``article`` row and an
    exact ``dependents`` mapping for every cascade-affected table.  The
    generated recovery JSONL therefore contains enough bytes for a later
    adapter to restore the pre-delete projection exactly.
    """

    if not isinstance(canonical_feed, bytes):
        raise TypeError("publisher delete canonical feed must be bytes")
    minimum = _positive_int(
        minimum_canonical_articles,
        field="minimum_canonical_articles",
    )
    maximum = _positive_int(maximum_deletes, field="maximum_deletes")
    artifact_ref = _required_text(
        recovery_artifact_ref,
        field="recovery_artifact_ref",
    )

    feed_slugs = _canonical_feed_slugs(canonical_feed)
    if len(feed_slugs) < minimum:
        raise ValueError(
            "publisher delete canonical article count is below the configured "
            f"floor ({len(feed_slugs)}<{minimum})"
        )

    normalized_candidates = _normalize_candidates(candidates)
    if len(normalized_candidates) > maximum:
        raise ValueError(
            "publisher delete candidate count exceeds the configured cap "
            f"({len(normalized_candidates)}>{maximum})"
        )
    overlap = sorted(
        candidate["article"]["slug"]
        for candidate in normalized_candidates
        if candidate["article"]["slug"] in feed_slugs
    )
    if overlap:
        raise ValueError(
            "publisher delete candidates still exist in the canonical feed: "
            + ", ".join(overlap)
        )

    recovery_dump = b"".join(
        _canonical_json(
            {
                "schema_version": _RECOVERY_SCHEMA,
                "article": candidate["article"],
                "dependents": candidate["dependents"],
            }
        )
        + b"\n"
        for candidate in normalized_candidates
    )
    recovery_sha256 = hashlib.sha256(recovery_dump).hexdigest()
    feed_sha256 = hashlib.sha256(canonical_feed).hexdigest()
    scope = _canonical_json(
        {
            "schema_version": _SCOPE_SCHEMA,
            "canonical_feed_sha256": feed_sha256,
            "canonical_article_count": len(feed_slugs),
            "guards": {
                "minimum_canonical_articles": minimum,
                "maximum_deletes": maximum,
            },
            "candidates": list(normalized_candidates),
            "recovery": {
                "artifact_ref": artifact_ref,
                "sha256": recovery_sha256,
            },
        }
    )
    return PublisherArticleDeletePlan(
        scope=scope,
        scope_sha256=hashlib.sha256(scope).hexdigest(),
        recovery_dump=recovery_dump,
        recovery_dump_sha256=recovery_sha256,
        canonical_feed_sha256=feed_sha256,
        canonical_article_count=len(feed_slugs),
        delete_count=len(normalized_candidates),
    )


def prepare_publisher_article_delete(
    *,
    plan: PublisherArticleDeletePlan,
    authorization: PublisherArticleDeleteAuthorization,
    idempotency_key: str,
    work_item_id: str,
    work_item_version: int,
    payload_ref: str,
    requester_ref: str,
) -> PreparedPublisherArticleDelete:
    """Bind one explicit approval to a destructive EffectRequest."""

    _validate_plan(plan)
    normalized_authorization = _normalize_authorization(authorization)
    if normalized_authorization.scope_sha256 != plan.scope_sha256:
        raise ValueError(
            "publisher delete authorization is not bound to this exact scope"
        )
    payload = _canonical_json(
        {
            "schema_version": _PAYLOAD_SCHEMA,
            "scope_sha256": plan.scope_sha256,
            "scope": json.loads(plan.scope),
            "authorization": {
                "approval_ref": normalized_authorization.approval_ref,
                "approver_ref": normalized_authorization.approver_ref,
                "approved_at": normalized_authorization.approved_at,
                "scope_sha256": normalized_authorization.scope_sha256,
            },
        }
    )
    request = EffectRequest(
        idempotency_key=idempotency_key,
        work_item_id=work_item_id,
        work_item_version=work_item_version,
        effect_kind=_EFFECT_KIND,
        target_ref=_TARGET_REF,
        payload_ref=payload_ref,
        payload_sha256=hashlib.sha256(payload).hexdigest(),
        risk="destructive",
        acknowledgement=AcknowledgementExpectation(
            kind=_ACKNOWLEDGEMENT_KIND,
            target_ref=_TARGET_REF,
        ),
        requester_ref=requester_ref,
    )
    return PreparedPublisherArticleDelete(
        request=request,
        payload=payload,
        recovery_dump=plan.recovery_dump,
        scope_sha256=plan.scope_sha256,
    )


def _canonical_feed_slugs(canonical_feed: bytes) -> frozenset[str]:
    try:
        decoded = json.loads(canonical_feed.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("publisher delete canonical feed is invalid JSON") from exc
    if isinstance(decoded, Mapping):
        if set(decoded) != {"items"}:
            raise ValueError(
                "publisher delete canonical feed wrapper must contain only items"
            )
        decoded = decoded["items"]
    if not isinstance(decoded, list):
        raise TypeError("publisher delete canonical feed must be a list")
    slugs: list[str] = []
    for article in decoded:
        if not isinstance(article, Mapping):
            raise TypeError("publisher delete canonical feed rows must be objects")
        slugs.append(
            _required_text(article.get("id"), field="canonical article id")
        )
    if len(slugs) != len(set(slugs)):
        raise ValueError("publisher delete canonical feed contains duplicate ids")
    return frozenset(slugs)


def _normalize_candidates(
    candidates: Iterable[Mapping[str, object]],
) -> tuple[dict, ...]:
    if isinstance(candidates, (str, bytes, Mapping)):
        raise TypeError("publisher delete candidates must be an iterable")
    normalized: list[dict] = []
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            raise TypeError("publisher delete candidates must be objects")
        if set(candidate) != {"article", "dependents"}:
            raise ValueError(
                "publisher delete candidate fields do not match schema"
            )
        article = _json_mapping(candidate["article"], field="candidate article")
        article_id = _required_text(article.get("id"), field="candidate article id")
        slug = _required_text(article.get("slug"), field="candidate article slug")
        article["id"] = article_id
        article["slug"] = slug

        dependents = candidate["dependents"]
        if not isinstance(dependents, Mapping):
            raise TypeError("publisher delete dependents must be an object")
        if set(dependents) != _CASCADE_TABLES:
            raise ValueError(
                "publisher delete dependents must cover every cascade table"
            )
        normalized_dependents: dict[str, list[dict]] = {}
        for table in sorted(_CASCADE_TABLES):
            rows = dependents[table]
            if not isinstance(rows, list):
                raise TypeError(
                    f"publisher delete dependent rows for {table} must be a list"
                )
            normalized_rows = sorted(
                (
                    _json_mapping(row, field=f"{table} recovery row")
                    for row in rows
                ),
                key=_canonical_json,
            )
            relation_columns = _CASCADE_COLUMNS[table]
            if any(
                not any(
                    row.get(column) == article_id
                    for column in relation_columns
                )
                for row in normalized_rows
            ):
                raise ValueError(
                    f"publisher delete {table} recovery row is bound to "
                    "a different article"
                )
            normalized_dependents[table] = normalized_rows
        normalized.append(
            {
                "article": article,
                "dependents": normalized_dependents,
            }
        )
    if not normalized:
        raise ValueError("publisher delete plan must contain a candidate")
    slugs = [candidate["article"]["slug"] for candidate in normalized]
    article_ids = [candidate["article"]["id"] for candidate in normalized]
    if len(slugs) != len(set(slugs)):
        raise ValueError("publisher delete plan contains duplicate slugs")
    if len(article_ids) != len(set(article_ids)):
        raise ValueError("publisher delete plan contains duplicate article ids")
    return tuple(sorted(normalized, key=lambda row: row["article"]["slug"]))


def _validate_plan(plan: PublisherArticleDeletePlan) -> None:
    if not isinstance(plan, PublisherArticleDeletePlan):
        raise TypeError("publisher delete plan is required")
    if hashlib.sha256(plan.scope).hexdigest() != plan.scope_sha256:
        raise ValueError("publisher delete scope hash does not match its bytes")
    if hashlib.sha256(plan.recovery_dump).hexdigest() != plan.recovery_dump_sha256:
        raise ValueError("publisher delete recovery hash does not match its bytes")
    try:
        scope = json.loads(plan.scope)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("publisher delete scope is invalid JSON") from exc
    candidates = scope.get("candidates") if isinstance(scope, Mapping) else None
    recovery = scope.get("recovery") if isinstance(scope, Mapping) else None
    if (
        not isinstance(scope, Mapping)
        or scope.get("schema_version") != _SCOPE_SCHEMA
        or scope.get("canonical_feed_sha256") != plan.canonical_feed_sha256
        or scope.get("canonical_article_count") != plan.canonical_article_count
        or not isinstance(candidates, list)
        or len(candidates) != plan.delete_count
        or not isinstance(recovery, Mapping)
        or recovery.get("sha256") != plan.recovery_dump_sha256
    ):
        raise ValueError("publisher delete plan metadata does not match its scope")


def _normalize_authorization(
    authorization: PublisherArticleDeleteAuthorization,
) -> PublisherArticleDeleteAuthorization:
    if not isinstance(authorization, PublisherArticleDeleteAuthorization):
        raise TypeError("publisher delete authorization is required")
    approved_at = _required_text(
        authorization.approved_at,
        field="publisher delete approved_at",
    )
    try:
        observed_at = datetime.fromisoformat(approved_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(
            "publisher delete approved_at must be an ISO-8601 timestamp"
        ) from exc
    if observed_at.tzinfo is None:
        raise ValueError("publisher delete approved_at must include a timezone")
    if (
        not isinstance(authorization.scope_sha256, str)
        or _SHA256.fullmatch(authorization.scope_sha256) is None
    ):
        raise ValueError(
            "publisher delete authorization scope SHA-256 must be lowercase hex"
        )
    return PublisherArticleDeleteAuthorization(
        approval_ref=_required_text(
            authorization.approval_ref,
            field="publisher delete approval_ref",
        ),
        approver_ref=_required_text(
            authorization.approver_ref,
            field="publisher delete approver_ref",
        ),
        approved_at=observed_at.isoformat(),
        scope_sha256=authorization.scope_sha256,
    )


def _decode_payload(payload: bytes) -> _PublisherArticleDeleteExecution:
    decoded = json.loads(payload.decode("utf-8"))
    if not isinstance(decoded, Mapping):
        raise TypeError("publisher delete payload must be an object")
    if set(decoded) != {
        "schema_version",
        "scope_sha256",
        "scope",
        "authorization",
    }:
        raise ValueError("publisher delete payload fields do not match schema")
    if decoded.get("schema_version") != _PAYLOAD_SCHEMA:
        raise ValueError("unsupported publisher delete payload schema")
    if _canonical_json(decoded) != payload:
        raise ValueError("publisher delete payload is not canonical")

    scope = decoded["scope"]
    if not isinstance(scope, Mapping):
        raise TypeError("publisher delete scope must be an object")
    if set(scope) != {
        "schema_version",
        "canonical_feed_sha256",
        "canonical_article_count",
        "guards",
        "candidates",
        "recovery",
    }:
        raise ValueError("publisher delete scope fields do not match schema")
    if scope.get("schema_version") != _SCOPE_SCHEMA:
        raise ValueError("unsupported publisher delete scope schema")
    scope_sha256 = decoded["scope_sha256"]
    if (
        not isinstance(scope_sha256, str)
        or _SHA256.fullmatch(scope_sha256) is None
        or hashlib.sha256(_canonical_json(scope)).hexdigest() != scope_sha256
    ):
        raise ValueError("publisher delete scope hash does not match its bytes")

    candidates = scope["candidates"]
    normalized_candidates = _normalize_candidates(candidates)
    if list(normalized_candidates) != candidates:
        raise ValueError("publisher delete candidates are not canonical")
    guards = scope["guards"]
    recovery = scope["recovery"]
    if (
        not isinstance(guards, Mapping)
        or set(guards) != {
            "minimum_canonical_articles",
            "maximum_deletes",
        }
        or not isinstance(recovery, Mapping)
        or set(recovery) != {"artifact_ref", "sha256"}
    ):
        raise ValueError("publisher delete scope guards or recovery are invalid")
    minimum = _positive_int(
        guards["minimum_canonical_articles"],
        field="minimum_canonical_articles",
    )
    maximum = _positive_int(
        guards["maximum_deletes"],
        field="maximum_deletes",
    )
    canonical_count = _positive_int(
        scope["canonical_article_count"],
        field="canonical_article_count",
    )
    if canonical_count < minimum or len(normalized_candidates) > maximum:
        raise ValueError("publisher delete scope violates its guards")
    canonical_feed_sha256 = scope["canonical_feed_sha256"]
    recovery_dump_sha256 = recovery["sha256"]
    if (
        not isinstance(canonical_feed_sha256, str)
        or _SHA256.fullmatch(canonical_feed_sha256) is None
        or not isinstance(recovery_dump_sha256, str)
        or _SHA256.fullmatch(recovery_dump_sha256) is None
    ):
        raise ValueError("publisher delete scope hashes are invalid")
    _required_text(recovery["artifact_ref"], field="recovery artifact_ref")

    authorization_payload = decoded["authorization"]
    if not isinstance(authorization_payload, Mapping) or set(
        authorization_payload
    ) != {
        "approval_ref",
        "approver_ref",
        "approved_at",
        "scope_sha256",
    }:
        raise ValueError("publisher delete authorization fields do not match schema")
    authorization = _normalize_authorization(
        PublisherArticleDeleteAuthorization(**authorization_payload)
    )
    if authorization.scope_sha256 != scope_sha256:
        raise ValueError("publisher delete authorization scope drifted")
    return _PublisherArticleDeleteExecution(
        scope_sha256=scope_sha256,
        canonical_feed_sha256=canonical_feed_sha256,
        recovery_dump_sha256=recovery_dump_sha256,
        authorization=authorization,
        candidates=normalized_candidates,
    )


def _base_contract_matches(effect: EffectView) -> bool:
    acknowledgement = effect.acknowledgement
    return (
        effect.schema_version == "effect-request.v1"
        and effect.effect_kind == _EFFECT_KIND
        and effect.risk == "destructive"
        and effect.target_ref == _TARGET_REF
        and acknowledgement.kind == _ACKNOWLEDGEMENT_KIND
        and acknowledgement.target_ref == _TARGET_REF
    )


def _approval_readback_matches(
    readback: object,
    authorization: PublisherArticleDeleteAuthorization,
) -> bool:
    return bool(
        isinstance(readback, PublisherArticleDeleteApprovalReadback)
        and readback.active is True
        and readback.authorization == authorization
        and _valid_evidence(readback.evidence_ref, readback.evidence_sha256)
    )


def _candidate_readback_matches(
    readback: PublisherArticleDeleteCandidateReadback,
    expected: Mapping[str, object],
) -> bool:
    if readback.absent:
        return False
    normalized = _normalize_candidates([readback.candidate])
    return len(normalized) == 1 and normalized[0] == expected


def _acknowledged(
    effect: EffectView,
    execution: _PublisherArticleDeleteExecution,
    readbacks: tuple[PublisherArticleDeleteCandidateReadback, ...],
) -> AcknowledgedEffect | None:
    if len(readbacks) != len(execution.candidates) or not all(
        readback.absent for readback in readbacks
    ):
        return None
    evidence = _canonical_json(
        {
            "schema_version": "publisher-article-delete-readback.v1",
            "scope_sha256": execution.scope_sha256,
            "canonical_feed_sha256": execution.canonical_feed_sha256,
            "recovery_dump_sha256": execution.recovery_dump_sha256,
            "articles": [
                {
                    "article_id": readback.article_id,
                    "evidence_ref": readback.evidence_ref.strip(),
                    "evidence_sha256": readback.evidence_sha256,
                    "absent": True,
                }
                for readback in readbacks
            ],
        }
    )
    return AcknowledgedEffect(
        acknowledgement=AcknowledgementExpectation(
            kind=_ACKNOWLEDGEMENT_KIND,
            target_ref=_TARGET_REF,
        ),
        evidence_ref=f"supabase:articles:delete:{execution.scope_sha256}",
        evidence_sha256=hashlib.sha256(evidence).hexdigest(),
    )


def _valid_evidence(evidence_ref: object, evidence_sha256: object) -> bool:
    return bool(
        isinstance(evidence_ref, str)
        and evidence_ref.strip()
        and isinstance(evidence_sha256, str)
        and _SHA256.fullmatch(evidence_sha256) is not None
    )


def _failure(
    effect: EffectView,
    reason_code: str,
    *,
    retryable: bool,
) -> FailedEffect:
    evidence = _canonical_json(
        {
            "effect_id": effect.id,
            "request_sha256": effect.request_sha256,
            "reason_code": reason_code,
            "retryable": retryable,
        }
    )
    return FailedEffect(
        reason_code=reason_code,
        evidence_ref=f"effect-attempt:{effect.id}:{reason_code}",
        evidence_sha256=hashlib.sha256(evidence).hexdigest(),
        retryable=retryable,
    )


def _json_mapping(value: object, *, field: str) -> dict:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field} must be an object")
    try:
        encoded = _canonical_json(value)
        decoded = json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must contain canonical JSON values") from exc
    if not isinstance(decoded, dict):
        raise TypeError(f"{field} must be an object")
    return decoded


def _positive_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _required_text(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    return value.strip()


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


__all__ = [
    "PUBLISHER_ARTICLE_DELETE_CASCADE_COLUMNS",
    "PreparedPublisherArticleDelete",
    "PublisherArticleDeleteApprovalReadback",
    "PublisherArticleDeleteAuthorization",
    "PublisherArticleDeleteCandidateReadback",
    "PublisherArticleDeleteEffectAdapter",
    "PublisherArticleDeletePlan",
    "plan_publisher_article_delete",
    "prepare_publisher_article_delete",
]
