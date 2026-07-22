"""Canonical article-retraction writer.

``storage/reports/feed.json`` is the source of truth for published articles.
Retractions used to be hand-edited into that shared file, which left successor
and errata metadata optional in practice.  This module owns the mutation and
keeps the read/modify/write transaction under the publisher feed lock.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from volpred.canonical_write import guard_canonical_write
from volpred.ops.common import project_path
from volpred.ops.shared_lock import shared_state_lock
from volpred.ops.writer_log import append_writer_log


RETRACTION_SCHEMA_VERSION = 1
RETRACTION_FIELDS = frozenset(
    {
        "retracted_reason",
        "retracted_superseded_by",
        "retracted_errata_ref",
        "retracted_no_successor_reason",
    }
)


class RetractionError(ValueError):
    """Raised when a retraction request would create ambiguous metadata."""


def _required_text(value: str | None, flag: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise RetractionError(f"{flag} requires a non-empty value")
    return text


def _storage_root(storage_dir: str | Path) -> Path:
    path = Path(storage_dir)
    return path if path.is_absolute() else project_path(str(path))


def _feed_path(storage_dir: str | Path) -> Path:
    return _storage_root(storage_dir) / "reports" / "feed.json"


def _load_feed(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RetractionError(f"canonical feed does not exist: {path}") from exc
    if not isinstance(payload, list) or not all(isinstance(row, dict) for row in payload):
        raise RetractionError("canonical feed must be a list of article objects")
    return payload


def _write_feed_atomic(path: Path, feed: list[dict[str, Any]]) -> None:
    guard_canonical_write(path)
    tmp = path.with_name(f".{path.name}.retraction.{os.getpid()}.tmp")
    try:
        tmp.write_text(
            json.dumps(feed, indent=2, ensure_ascii=False, default=str) + "\n",
            encoding="utf-8",
        )
        parsed = json.loads(tmp.read_text(encoding="utf-8"))
        if not isinstance(parsed, list):
            raise RetractionError("temporary feed failed list-schema validation")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _normalized_successors(values: list[str] | tuple[str, ...] | None) -> list[str]:
    successors: list[str] = []
    for raw in values or []:
        value = _required_text(raw, "--superseded-by")
        if value not in successors:
            successors.append(value)
    return successors


def _desired_metadata(
    *,
    reason: str,
    successors: list[str],
    errata_ref: str | None,
    no_successor_reason: str | None,
) -> dict[str, Any]:
    reason = _required_text(reason, "--reason")
    errata = str(errata_ref).strip() if errata_ref is not None else None
    if errata_ref is not None and not errata:
        raise RetractionError("--errata-ref requires a non-empty value")
    no_successor = (
        _required_text(no_successor_reason, "--no-successor")
        if no_successor_reason is not None
        else None
    )
    if bool(successors) == bool(no_successor):
        raise RetractionError(
            "choose exactly one: one or more --superseded-by values, or "
            "--no-successor with an explicit reason"
        )
    return {
        "retracted_reason": reason,
        "retracted_superseded_by": successors,
        "retracted_errata_ref": errata,
        "retracted_no_successor_reason": no_successor,
        "retraction_schema_version": RETRACTION_SCHEMA_VERSION,
    }


def _validate_successors(
    article_id: str,
    successors: list[str],
    feed: list[dict[str, Any]],
) -> None:
    if article_id in successors:
        raise RetractionError("an article cannot supersede itself")
    shipped_ids = {str(row.get("id") or "") for row in feed}
    missing = [successor for successor in successors if successor not in shipped_ids]
    if missing:
        raise RetractionError(f"successor article ids do not exist in feed: {missing}")


def _assert_no_metadata_rewrite(article: dict[str, Any], desired: dict[str, Any]) -> None:
    """Allow missing-field backfills, but reject silent provenance rewrites."""
    if article.get("status") != "retracted":
        return
    conflicts = {
        key: {"existing": article.get(key), "requested": desired[key]}
        for key in RETRACTION_FIELDS
        if key in article and article.get(key) is not None and article.get(key) != desired[key]
    }
    if conflicts:
        raise RetractionError(
            "existing retraction metadata conflicts with the request; "
            f"refusing silent rewrite: {conflicts}"
        )


def retract_article(
    article_id: str,
    *,
    reason: str,
    superseded_by: list[str] | tuple[str, ...] | None = None,
    errata_ref: str | None = None,
    no_successor_reason: str | None = None,
    storage_dir: str | Path = "storage",
    actor: str | None = None,
) -> dict[str, Any]:
    """Retract one feed article and return a read-back-verified receipt.

    Existing incomplete retractions may be normalized, but populated audit
    metadata cannot be changed through this path.  A future correction to the
    provenance therefore needs an explicit migration instead of masquerading as
    an idempotent retraction.
    """
    article_id = _required_text(article_id, "--id")
    successors = _normalized_successors(superseded_by)
    desired = _desired_metadata(
        reason=reason,
        successors=successors,
        errata_ref=errata_ref,
        no_successor_reason=no_successor_reason,
    )
    storage_root = _storage_root(storage_dir)
    feed_path = _feed_path(storage_root)
    result_label = "ok"
    try:
        with shared_state_lock("publisher_feed", storage_dir=str(storage_root)) as acquired:
            # Blocking mode currently always acquires; fail closed if that changes.
            if not acquired:
                raise RetractionError("publisher_feed lock was not acquired")
            feed = _load_feed(feed_path)
            matches = [index for index, row in enumerate(feed) if row.get("id") == article_id]
            if len(matches) != 1:
                raise RetractionError(
                    f"expected exactly one feed article id={article_id!r}; found {len(matches)}"
                )
            _validate_successors(article_id, successors, feed)
            index = matches[0]
            current = feed[index]
            _assert_no_metadata_rewrite(current, desired)
            updated = dict(current)
            updated["status"] = "retracted"
            updated.update(desired)
            changed = updated != current
            if changed:
                feed[index] = updated
                _write_feed_atomic(feed_path, feed)

            persisted_feed = _load_feed(feed_path)
            persisted = next(
                (row for row in persisted_feed if row.get("id") == article_id), None
            )
            if persisted is None or persisted.get("status") != "retracted":
                raise RuntimeError(f"retraction read-back failed for {article_id}")
            if any(persisted.get(key) != value for key, value in desired.items()):
                raise RuntimeError(f"retraction metadata read-back failed for {article_id}")
            return {
                "ok": True,
                "id": article_id,
                "changed": changed,
                "status": "retracted",
                **desired,
            }
    except Exception as exc:
        result_label = f"error: {type(exc).__name__}: {exc}"[:200]
        raise
    finally:
        append_writer_log(
            subsystem="publisher",
            target="reports/feed.json",
            record_id=article_id,
            result=result_label,
            actor=actor,
            storage_dir=str(storage_root),
        )
