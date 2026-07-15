#!/usr/bin/env python3
"""Guarded, auditable correction for historical feed audience drift.

Dry-run is the default.  Apply mode re-reads the canonical feed while holding
the same ``publisher_feed`` lock as Publisher, validates every mismatch against
an explicit review plan, then performs one guarded atomic replacement.  It
never writes deprecated ``storage/reports/<mile_id>.json`` files.

Entries marked ``rewrite_general`` also materialize one idempotent
``daily_article`` replacement task through the canonical task-queue lock.  The
original evidence-rich article remains available as research while a genuinely
reader-facing companion is produced.
"""
from __future__ import annotations

import argparse
import copy
import fcntl
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from volpred.canonical_write import guard_canonical_write  # noqa: E402
from volpred.ops.next_tasks import (  # noqa: E402
    normalize_task_priority,
    validate_task_status,
    write_tasks_to_handle,
)
from volpred.ops.shared_lock import shared_state_lock  # noqa: E402
from volpred.publisher.publisher import (  # noqa: E402
    _AUDIENCE_TAG_ALL_ALIASES,
    _AUDIENCE_TAG_CANONICAL,
    _academic_keyword_hits,
    _infer_audience,
)


DEFAULT_FEED = ROOT / "storage" / "reports" / "feed.json"
DEFAULT_TASKS = ROOT / "storage" / "next_tasks.json"
DEFAULT_PLAN = ROOT / "storage" / "ops" / "audience_correction_plan_20260715.json"
NON_VISIBLE = frozenset({"unpublished", "archived", "retracted"})
VALID_DISPOSITIONS = frozenset({"research_only", "rewrite_general", "type_correction"})


def _content_type(entry: dict[str, Any]) -> str | None:
    details = entry.get("details")
    detail_type = details.get("content_type") if isinstance(details, dict) else None
    value = detail_type or entry.get("content_type") or entry.get("category")
    value = str(value or "").strip()
    return value or None


def _inferred_audience(entry: dict[str, Any]) -> str:
    tags = entry.get("tags") if isinstance(entry.get("tags"), list) else []
    return _infer_audience(
        str(entry.get("title") or ""),
        str(entry.get("content") or entry.get("description") or ""),
        [str(tag) for tag in tags if tag is not None],
        content_type=_content_type(entry),
    )


def _is_visible_general_mismatch(entry: dict[str, Any]) -> bool:
    if entry.get("audience") != "general":
        return False
    if str(entry.get("status") or "").lower() in NON_VISIBLE:
        return False
    return _inferred_audience(entry) != "general"


def load_review_plan(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("audience correction plan must be a schema_version=1 object")
    rows = payload.get("corrections")
    if not isinstance(rows, list) or not rows:
        raise ValueError("audience correction plan must contain corrections[]")
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("every correction row must be an object")
        article_id = str(row.get("id") or "").strip()
        if not article_id or article_id in seen:
            raise ValueError(f"missing/duplicate correction id: {article_id!r}")
        seen.add(article_id)
        disposition = str(row.get("disposition") or "")
        if disposition not in VALID_DISPOSITIONS:
            raise ValueError(f"{article_id}: invalid disposition {disposition!r}")
        expected = str(row.get("expected_audience") or "")
        if expected not in {"research", "daily", "member_qa", "event"}:
            raise ValueError(f"{article_id}: invalid expected_audience {expected!r}")
        refs = row.get("experiment_refs", [])
        if not isinstance(refs, list):
            raise ValueError(f"{article_id}: experiment_refs must be a list")
    return payload


def validate_plan_against_feed(
    feed: list[dict[str, Any]],
    plan: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Fail if current mismatches and the reviewed corpus have drifted."""
    plan_by_id = {str(row["id"]): row for row in plan["corrections"]}
    feed_by_id = {
        str(row.get("id") or ""): row
        for row in feed
        if isinstance(row, dict) and row.get("id")
    }

    current_mismatches = {
        article_id
        for article_id, row in feed_by_id.items()
        if _is_visible_general_mismatch(row)
    }
    unreviewed = sorted(current_mismatches - set(plan_by_id))
    if unreviewed:
        raise ValueError(
            "unreviewed audience mismatch(es); regenerate/review the plan first: "
            + ", ".join(unreviewed)
        )

    for article_id, review in plan_by_id.items():
        entry = feed_by_id.get(article_id)
        if entry is None:
            raise ValueError(f"reviewed article missing from feed: {article_id}")
        expected = str(review["expected_audience"])
        inferred = _inferred_audience(entry)
        if inferred != expected:
            raise ValueError(
                f"{article_id}: reviewed expected={expected}, current inference={inferred}"
            )
        declared = str(entry.get("audience") or "")
        if declared not in {"general", expected}:
            raise ValueError(
                f"{article_id}: expected idempotent declared audience general/{expected}, "
                f"got {declared!r}"
            )
    return feed_by_id


def _normalize_audience_tags(tags: Any, expected: str) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in tags if isinstance(tags, list) else []:
        tag = str(raw).strip()
        if not tag or tag in _AUDIENCE_TAG_ALL_ALIASES or tag in seen:
            continue
        cleaned.append(tag)
        seen.add(tag)
    canonical = _AUDIENCE_TAG_CANONICAL.get(expected)
    return ([canonical] if canonical else []) + cleaned


def _entry_experiment_refs(entry: dict[str, Any]) -> set[str]:
    """Best-effort K refs using the same structured-first legacy fallbacks."""
    refs: set[str] = set()
    details = entry.get("details")
    structured = details.get("experiment_refs") if isinstance(details, dict) else []
    if isinstance(structured, list):
        refs.update(str(ref).strip().upper() for ref in structured if str(ref).strip())
    legacy_text = " ".join(
        [
            str(entry.get("title") or ""),
            str(entry.get("content") or ""),
            str(entry.get("description") or ""),
        ]
    )
    refs.update(match.upper() for match in re.findall(r"\bK\d{2,5}[A-Za-z0-9_]*\b", legacy_text))
    return refs


def _projected_general_coverage(
    feed: list[dict[str, Any]],
    plan: dict[str, Any],
) -> dict[str, list[str]]:
    """Map K ref -> other rows that remain general after this correction."""
    expected_by_id = {
        str(review["id"]): str(review["expected_audience"])
        for review in plan["corrections"]
    }
    coverage: dict[str, list[str]] = {}
    for entry in feed:
        if not isinstance(entry, dict):
            continue
        article_id = str(entry.get("id") or "")
        projected = expected_by_id.get(article_id, str(entry.get("audience") or ""))
        if projected != "general":
            continue
        if str(entry.get("status") or "").lower() in {"unpublished", "retracted"}:
            continue
        for ref in _entry_experiment_refs(entry):
            coverage.setdefault(ref, []).append(article_id)
    return coverage


def apply_reviewed_corrections(
    feed: list[dict[str, Any]],
    plan: dict[str, Any],
    *,
    applied_at: str,
) -> list[str]:
    """Mutate ``feed`` in memory and return ids whose payload changed."""
    feed_by_id = validate_plan_against_feed(feed, plan)
    general_coverage = _projected_general_coverage(feed, plan)
    changed: list[str] = []
    task_id = str(plan.get("task_id") or "content_audience_mislabel_backlog_45")

    for review in plan["corrections"]:
        article_id = str(review["id"])
        entry = feed_by_id[article_id]
        expected = str(review["expected_audience"])
        disposition = str(review["disposition"])
        before = json.dumps(entry, ensure_ascii=False, sort_keys=True)

        previous_audience = str(entry.get("audience") or "general")
        entry["audience"] = expected
        entry["tags"] = _normalize_audience_tags(entry.get("tags"), expected)

        details = entry.get("details")
        if not isinstance(details, dict):
            details = {}
            entry["details"] = details
        details["audience"] = expected

        reviewed_refs = [str(ref).strip().upper() for ref in review.get("experiment_refs", []) if str(ref).strip()]
        old_refs = details.get("experiment_refs")
        old_refs = old_refs if isinstance(old_refs, list) else []
        merged_refs: list[str] = []
        for ref in [*old_refs, *reviewed_refs]:
            normalized = str(ref).strip()
            if normalized and normalized not in merged_refs:
                merged_refs.append(normalized)
        if merged_refs:
            details["experiment_refs"] = merged_refs

        prior_marker = details.get("audience_correction")
        prior_applied_at = (
            prior_marker.get("applied_at")
            if isinstance(prior_marker, dict)
            and prior_marker.get("task_id") == task_id
            else None
        )
        content = str(entry.get("content") or entry.get("description") or "")
        raw_tags = entry.get("tags") if isinstance(entry.get("tags"), list) else []
        uncovered_refs = [ref for ref in reviewed_refs if not general_coverage.get(ref)]
        needs_rewrite = disposition == "rewrite_general" and (
            not reviewed_refs or bool(uncovered_refs)
        )
        details["audience_correction"] = {
            "task_id": task_id,
            "applied_at": prior_applied_at or applied_at,
            "previous_audience": (
                prior_marker.get("previous_audience", "general")
                if isinstance(prior_marker, dict)
                else previous_audience
            ),
            "corrected_audience": expected,
            "publisher_inference": expected,
            "disposition": disposition,
            "requires_general_rewrite": needs_rewrite,
            "general_coverage_elsewhere": {
                ref: general_coverage.get(ref, []) for ref in reviewed_refs
            },
            "uncovered_experiment_refs": uncovered_refs,
            "academic_signals": _academic_keyword_hits(
                str(entry.get("title") or ""), content, [str(t) for t in raw_tags]
            ),
            "script": "scripts/backfill_feed_audience.py",
        }

        if expected == "research":
            entry["category"] = "milestone"
            details["content_type"] = "research_article"
        elif expected == "daily":
            details["content_type"] = "daily_update"
        elif expected == "member_qa":
            entry["category"] = "member_qa"
            details["content_type"] = "member_qa"
        elif expected == "event":
            entry["category"] = "event_article"
            details["content_type"] = "event_article"

        after = json.dumps(entry, ensure_ascii=False, sort_keys=True)
        if after != before:
            entry["last_updated_at"] = applied_at
            changed.append(article_id)
    return changed


def _rewrite_task_id(review: dict[str, Any]) -> str:
    refs = review.get("experiment_refs") or []
    primary = str(refs[0]).upper() if refs else "audience"
    suffix = str(review["id"]).removeprefix("mile_")
    return f"{primary}_article_general_audience_rewrite_{suffix}"


def build_rewrite_task(
    review: dict[str, Any],
    article: dict[str, Any],
    *,
    task_id: str,
    created_at: str,
) -> dict[str, Any]:
    refs = [str(ref).upper() for ref in review.get("experiment_refs", [])]
    source_id = str(review["id"])
    source_title = " ".join(str(article.get("title") or source_id).split())
    row: dict[str, Any] = {
        "id": _rewrite_task_id(review),
        "title": f"Audience correction: rewrite a true general companion for {source_title[:90]}",
        "description": (
            f"parent_task_id={task_id}; source_article={source_id}. The source was corrected "
            "from general to research because canonical publisher inference found reader-visible "
            "academic density. Produce a NEW general-audience companion through publish_draft.py; "
            "do not relabel or weaken the corrected research source. Read feed-publisher and "
            "anti-ai-style skills; preserve every source number, null result, limitation, lookahead "
            "caveat, and errata in plain language. Use structured experiment refs "
            f"{refs or '[missing: reconstruct provenance before writing]'}; publish status=draft, "
            "audience=general, and require sanitize_applied=0. If evidence/provenance is insufficient, "
            "block with the exact missing source instead of inventing content."
        ),
        "priority": 3,
        "status": "pending",
        "task_type": "daily_article",
        "dispatch_lane": "agent",
        "source": "audience_correction_backfill",
        "article_id": source_id,
        "experiment_refs": refs,
        "parent_task_id": task_id,
        "tags": ["audience-correction", "rewrite-general", "content-quality"],
        "created_at": created_at,
    }
    if refs:
        row["k_id"] = refs[0]
    if len(refs) > 1:
        row["experiment_id"] = refs[1]
    validate_task_status(row["status"])
    normalize_task_priority(row)
    return row


def reconcile_rewrite_tasks(
    tasks_path: Path,
    feed_by_id: dict[str, dict[str, Any]],
    plan: dict[str, Any],
    *,
    created_at: str,
) -> dict[str, list[str]]:
    """Create needed rewrite tasks and supersede now-redundant pending ones."""
    guard_canonical_write(tasks_path)
    tasks_path.parent.mkdir(parents=True, exist_ok=True)
    if not tasks_path.exists():
        tasks_path.write_text("[]\n", encoding="utf-8")
    task_id = str(plan.get("task_id") or "content_audience_mislabel_backlog_45")
    with tasks_path.open("r+", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            tasks = json.load(fh)
            if not isinstance(tasks, list):
                raise ValueError("next_tasks.json must be a list")
            changes = preview_rewrite_task_changes(tasks, feed_by_id, plan)
            create_ids = set(changes["created"])
            supersede_ids = set(changes["superseded"])
            for review in plan["corrections"]:
                if review.get("disposition") != "rewrite_general":
                    continue
                rewrite_id = _rewrite_task_id(review)
                article = feed_by_id[str(review["id"])]
                if rewrite_id in create_ids:
                    tasks.append(
                        build_rewrite_task(
                            review,
                            article,
                            task_id=task_id,
                            created_at=created_at,
                        )
                    )
                if rewrite_id not in supersede_ids:
                    continue
                prior_task = next(
                    task
                    for task in tasks
                    if isinstance(task, dict) and str(task.get("id")) == rewrite_id
                )
                prior_status = str(prior_task.get("status") or "")
                prior_task["status"] = "superseded"
                prior_task["completed_at"] = created_at
                prior_task["result"] = (
                    "Superseded: canonical feed already has other valid general-audience "
                    "coverage for every reviewed experiment ref."
                )
                history = prior_task.get("status_history")
                if not isinstance(history, list):
                    history = []
                history.append(
                    {
                        "ts": created_at,
                        "from": prior_status,
                        "to": "superseded",
                        "by": "backfill_feed_audience",
                    }
                )
                prior_task["status_history"] = history
            if changes["created"] or changes["superseded"]:
                write_tasks_to_handle(fh, tasks)
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    return changes


def preview_rewrite_task_changes(
    tasks: list[Any],
    feed_by_id: dict[str, dict[str, Any]],
    plan: dict[str, Any],
) -> dict[str, list[str]]:
    """Return the exact idempotent queue delta without mutating task state."""
    existing = {
        str(task.get("id")): task
        for task in tasks
        if isinstance(task, dict) and task.get("id")
    }
    created: list[str] = []
    superseded: list[str] = []
    conflicts: list[str] = []
    for review in plan["corrections"]:
        if review.get("disposition") != "rewrite_general":
            continue
        rewrite_id = _rewrite_task_id(review)
        article = feed_by_id[str(review["id"])]
        details = article.get("details") if isinstance(article.get("details"), dict) else {}
        marker = details.get("audience_correction") if isinstance(details, dict) else {}
        required = bool(
            isinstance(marker, dict)
            and marker.get("requires_general_rewrite") is True
        )
        prior_task = existing.get(rewrite_id)
        if required and prior_task is None:
            created.append(rewrite_id)
            continue
        if required or not isinstance(prior_task, dict):
            continue
        prior_status = str(prior_task.get("status") or "")
        if (
            prior_status == "pending"
            and prior_task.get("source") == "audience_correction_backfill"
        ):
            superseded.append(rewrite_id)
        elif prior_status not in {"superseded", "succeeded", "cancelled"}:
            conflicts.append(f"{rewrite_id}:{prior_status}")
    return {"created": created, "superseded": superseded, "conflicts": conflicts}


def _atomic_write_feed(path: Path, feed: list[dict[str, Any]]) -> None:
    guard_canonical_write(path)
    payload = json.dumps(feed, ensure_ascii=False, indent=2) + "\n"
    tmp = path.with_name(f".{path.name}.audience-{os.getpid()}.tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, path)


def run(
    *,
    feed_path: Path,
    tasks_path: Path,
    plan_path: Path,
    apply: bool,
    enqueue_rewrites: bool,
) -> dict[str, Any]:
    plan = load_review_plan(plan_path)
    now = datetime.now(timezone.utc).isoformat()

    if not apply:
        feed = json.loads(feed_path.read_text(encoding="utf-8"))
        if not isinstance(feed, list):
            raise ValueError("feed.json must be a list")
        feed_by_id = validate_plan_against_feed(feed, plan)
        mismatches = [row for row in feed if _is_visible_general_mismatch(row)]
        preview_feed = copy.deepcopy(feed)
        would_correct = sum(
            feed_by_id[str(row["id"])].get("audience") == "general"
            for row in plan["corrections"]
        )
        apply_reviewed_corrections(preview_feed, plan, applied_at=now)
        preview_by_id = {
            str(row.get("id")): row
            for row in preview_feed
            if isinstance(row, dict) and row.get("id")
        }
        tasks = (
            json.loads(tasks_path.read_text(encoding="utf-8"))
            if tasks_path.exists()
            else []
        )
        if not isinstance(tasks, list):
            raise ValueError("next_tasks.json must be a list")
        task_changes = preview_rewrite_task_changes(tasks, preview_by_id, plan)
        return {
            "mode": "dry_run",
            "reviewed": len(plan["corrections"]),
            "current_mismatches": len(mismatches),
            "would_correct": would_correct,
            "would_enqueue_rewrites": (
                len(task_changes["created"]) if enqueue_rewrites else 0
            ),
            "would_supersede_rewrites": (
                len(task_changes["superseded"]) if enqueue_rewrites else 0
            ),
            "rewrite_task_conflicts": (
                task_changes["conflicts"] if enqueue_rewrites else []
            ),
        }

    storage_dir = feed_path.parent.parent
    with shared_state_lock("publisher_feed", storage_dir=str(storage_dir)):
        feed = json.loads(feed_path.read_text(encoding="utf-8"))
        if not isinstance(feed, list):
            raise ValueError("feed.json must be a list")
        changed = apply_reviewed_corrections(feed, plan, applied_at=now)
        if changed:
            _atomic_write_feed(feed_path, feed)
        feed_by_id = {
            str(row.get("id")): row
            for row in feed
            if isinstance(row, dict) and row.get("id")
        }

    task_changes = (
        reconcile_rewrite_tasks(tasks_path, feed_by_id, plan, created_at=now)
        if enqueue_rewrites
        else {"created": [], "superseded": [], "conflicts": []}
    )
    return {
        "mode": "apply",
        "reviewed": len(plan["corrections"]),
        "corrected": len(changed),
        "corrected_ids": changed,
        "rewrite_tasks_created": len(task_changes["created"]),
        "rewrite_task_ids": task_changes["created"],
        "rewrite_tasks_superseded": len(task_changes["superseded"]),
        "superseded_rewrite_task_ids": task_changes["superseded"],
        "rewrite_task_conflicts": task_changes["conflicts"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feed", type=Path, default=DEFAULT_FEED)
    parser.add_argument("--tasks", type=Path, default=DEFAULT_TASKS)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--apply", action="store_true", help="apply reviewed corrections")
    parser.add_argument(
        "--no-enqueue-rewrites",
        action="store_true",
        help="correct feed only; do not materialize rewrite_general tasks",
    )
    args = parser.parse_args()
    try:
        result = run(
            feed_path=args.feed,
            tasks_path=args.tasks,
            plan_path=args.plan,
            apply=args.apply,
            enqueue_rewrites=not args.no_enqueue_rewrites,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[backfill_feed_audience] ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
