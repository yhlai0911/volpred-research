"""Read-back-verified provider for one publisher article projection.

The module accepts one narrow effect contract:
``publisher.article.supabase.sync`` targeting one ``articles`` slug.  A
replay reads the projection before writing, so an already-converged row is
acknowledged without another upsert.  Retry and dead-letter policy remain
inside Effect Delivery's durable outbox implementation.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Protocol

from ._effect import (
    AcknowledgedEffect,
    AcknowledgementExpectation,
    EffectAttemptOutcome,
    EffectView,
    FailedEffect,
)


_PAYLOAD_SCHEMA = "publisher-article-sync.v1"
_EFFECT_KIND = "publisher.article.supabase.sync"
_ACKNOWLEDGEMENT_KIND = "publisher.article.supabase.readback"
_TARGET_PREFIX = "supabase:articles/"
_SLUG = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")
_SHA256 = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class PublisherArticleProjectionReadback:
    """Independent downstream evidence for one expected article projection."""

    matches: bool
    evidence_ref: str
    evidence_sha256: str


class PublisherArticleProjection(Protocol):
    """True-external projection port used by the effect provider."""

    def readback(
        self,
        article: dict,
    ) -> PublisherArticleProjectionReadback | None: ...

    def upsert(self, article: dict) -> bool: ...


def encode_publisher_article_sync_payload(article: Mapping[str, object]) -> bytes:
    """Encode one immutable, payload-bound publisher sync request."""

    normalized = _normalize_article(article)
    return json.dumps(
        {
            "schema_version": _PAYLOAD_SCHEMA,
            "article": normalized,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


class PublisherArticleSyncEffectAdapter:
    """Deliver one safe article projection and require exact read-back."""

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
                "invalid_publisher_article_sync_payload",
                retryable=False,
            )
        if hashlib.sha256(payload).hexdigest() != effect.payload_sha256:
            return _failure(
                effect,
                "publisher_article_sync_payload_hash_mismatch",
                retryable=False,
            )
        if not _base_contract_matches(effect):
            return _failure(
                effect,
                "unsupported_publisher_article_sync_contract",
                retryable=False,
            )
        try:
            article = _decode_payload(payload)
        except (UnicodeError, ValueError, json.JSONDecodeError):
            return _failure(
                effect,
                "invalid_publisher_article_sync_payload",
                retryable=False,
            )
        expected_target = f"{_TARGET_PREFIX}{article['id']}"
        if (
            effect.target_ref != expected_target
            or effect.acknowledgement.target_ref != expected_target
        ):
            return _failure(
                effect,
                "unsupported_publisher_article_sync_contract",
                retryable=False,
            )

        try:
            existing = self._projection.readback(article)
        except Exception:
            return _failure(
                effect,
                "publisher_article_sync_provider_error",
                retryable=True,
            )
        acknowledged = _acknowledged(effect, existing)
        if acknowledged is not None:
            return acknowledged

        if authorize_mutation is not None:
            # The initial projection read is a true external boundary.  An
            # owned caller revalidates its exact Primary Authority epoch here
            # so a stale attempt cannot write after a blocked read-back.
            authorize_mutation()
        try:
            written = self._projection.upsert(article)
        except Exception:
            written = False
        if not written:
            return _failure(
                effect,
                "publisher_article_sync_provider_error",
                retryable=True,
            )

        try:
            observed = self._projection.readback(article)
        except Exception:
            return _failure(
                effect,
                "publisher_article_sync_provider_error",
                retryable=True,
            )
        acknowledged = _acknowledged(effect, observed)
        if acknowledged is not None:
            return acknowledged
        return _failure(
            effect,
            (
                "publisher_article_sync_readback_missing"
                if observed is None
                else "publisher_article_sync_readback_mismatch"
            ),
            retryable=True,
        )


class SupabaseArticleProjectionAdapter:
    """Production adapter for direct Supabase upsert plus exact row/tag read-back."""

    def __init__(self, *, storage_dir: str | Path = "storage") -> None:
        self._storage_dir = Path(storage_dir)

    def upsert(self, article: dict) -> bool:
        sync = _supabase_sync_module()
        return bool(
            sync.sync_article_projection(
                article,
                storage_dir=self._storage_dir,
            )
        )

    def readback(
        self,
        article: dict,
    ) -> PublisherArticleProjectionReadback | None:
        sync = _supabase_sync_module()
        slug = article["id"]
        expected_row = sync.projected_article_row(article, verbose=False)
        rows = sync._select_rows(
            "articles",
            select=(
                "id,slug,title,content,excerpt,audience,phase,status,category,"
                "proposer,author_id,details,published_at"
            ),
            slug=slug,
        )
        if not rows:
            return None

        requested_tags = (
            _normalized_tags(article.get("tags"))
            if "tags" in article
            else None
        )
        expected = _canonical_projection(
            expected_row,
            requested_tags or [],
            server_resident_keys=sync.SERVER_RESIDENT_DETAILS_KEYS,
        )
        if len(rows) != 1:
            actual = {"duplicate_rows": len(rows), "slug": slug}
        else:
            row = dict(rows[0])
            article_id = row.pop("id", None)
            tag_names = _read_tag_names(sync, article_id)
            if requested_tags is None:
                # Missing tags means the immutable command did not include
                # that projection field. The writer deliberately preserves
                # existing links in this case, so read-back must keep them
                # outside the requested comparison scope too.
                expected = _canonical_projection(
                    expected_row,
                    tag_names,
                    server_resident_keys=(
                        sync.SERVER_RESIDENT_DETAILS_KEYS
                    ),
                )
            actual = _canonical_projection(
                row,
                tag_names,
                server_resident_keys=sync.SERVER_RESIDENT_DETAILS_KEYS,
            )
        evidence = _canonical_json(actual)
        return PublisherArticleProjectionReadback(
            matches=actual == expected,
            evidence_ref=f"supabase:articles/{slug}",
            evidence_sha256=hashlib.sha256(evidence).hexdigest(),
        )


def _supabase_sync_module():
    return importlib.import_module("scripts.supabase_sync")


def _normalize_article(article: Mapping[str, object]) -> dict:
    if not isinstance(article, Mapping):
        raise ValueError("publisher article must be an object")
    try:
        encoded = json.dumps(
            dict(article),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        normalized = json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise ValueError("publisher article must contain JSON values") from exc
    if not isinstance(normalized, dict):
        raise ValueError("publisher article must be an object")
    slug = normalized.get("id")
    if not isinstance(slug, str) or _SLUG.fullmatch(slug) is None:
        raise ValueError("publisher article id must be a safe slug")
    if "tags" in normalized:
        tags = normalized["tags"]
        if not isinstance(tags, list) or any(
            not isinstance(tag, str) for tag in tags
        ):
            raise ValueError(
                "publisher article tags must be a list of strings"
            )
    return normalized


def _decode_payload(payload: bytes) -> dict:
    decoded = json.loads(payload.decode("utf-8"))
    if not isinstance(decoded, Mapping):
        raise ValueError("publisher sync payload must be an object")
    if set(decoded) != {"schema_version", "article"}:
        raise ValueError("publisher sync payload fields do not match schema")
    if decoded.get("schema_version") != _PAYLOAD_SCHEMA:
        raise ValueError("unsupported publisher sync payload schema")
    article = decoded.get("article")
    if not isinstance(article, Mapping):
        raise ValueError("publisher sync payload article must be an object")
    return _normalize_article(article)


def _base_contract_matches(effect: EffectView) -> bool:
    acknowledgement = effect.acknowledgement
    return (
        effect.schema_version == "effect-request.v1"
        and effect.effect_kind == _EFFECT_KIND
        and effect.risk == "safe"
        and effect.target_ref.startswith(_TARGET_PREFIX)
        and acknowledgement.kind == _ACKNOWLEDGEMENT_KIND
        and acknowledgement.target_ref == effect.target_ref
    )


def _acknowledged(
    effect: EffectView,
    readback: PublisherArticleProjectionReadback | None,
) -> AcknowledgedEffect | None:
    if readback is None or readback.matches is not True:
        return None
    if (
        not isinstance(readback.evidence_ref, str)
        or not readback.evidence_ref.strip()
        or not isinstance(readback.evidence_sha256, str)
        or _SHA256.fullmatch(readback.evidence_sha256) is None
    ):
        return None
    return AcknowledgedEffect(
        acknowledgement=AcknowledgementExpectation(
            kind=_ACKNOWLEDGEMENT_KIND,
            target_ref=effect.target_ref,
        ),
        evidence_ref=readback.evidence_ref.strip(),
        evidence_sha256=readback.evidence_sha256,
    )


def _read_tag_names(sync, article_id: object) -> list[str]:
    if not isinstance(article_id, (str, int)) or isinstance(article_id, bool):
        raise ValueError("Supabase article read-back omitted id")
    links = sync._select_rows(
        "article_tags",
        select="tag_id",
        article_id=article_id,
    )
    tag_ids = sorted(
        {
            str(row["tag_id"])
            for row in links
            if isinstance(row, Mapping) and row.get("tag_id") is not None
        }
    )
    if not tag_ids:
        return []
    tags = sync._select_rows_in(
        "tags",
        "id",
        tag_ids,
        select="id,name",
    )
    return _normalized_tags(
        row.get("name")
        for row in tags
        if isinstance(row, Mapping)
    )


def _normalized_tags(raw: object) -> list[str]:
    if isinstance(raw, (str, bytes)) or not hasattr(raw, "__iter__"):
        raise ValueError("publisher article tags must be a list")
    return sorted(
        {
            item.strip()
            for item in raw
            if isinstance(item, str) and item.strip()
        }
    )


def _canonical_projection(
    row: Mapping[str, object],
    tags: list[str],
    *,
    server_resident_keys: tuple[str, ...],
) -> dict:
    normalized = dict(row)
    details = normalized.get("details")
    if isinstance(details, Mapping):
        normalized["details"] = {
            key: value
            for key, value in details.items()
            if key not in server_resident_keys
        }
    normalized["published_at"] = _normalize_timestamp(
        normalized.get("published_at")
    )
    return {"article": normalized, "tags": tags}


def _normalize_timestamp(value: object) -> object:
    if not isinstance(value, str) or not value:
        return value
    try:
        observed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    if observed.tzinfo is None:
        return observed.isoformat()
    return observed.astimezone(timezone.utc).isoformat()


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


__all__ = [
    "PublisherArticleProjection",
    "PublisherArticleProjectionReadback",
    "PublisherArticleSyncEffectAdapter",
    "SupabaseArticleProjectionAdapter",
    "encode_publisher_article_sync_payload",
]
