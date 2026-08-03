"""Model-free article-pipeline continuity actuator.

The release scheduler and the agent dispatcher are separate control loops.  A
dry release pool therefore needs an explicit bridge: promote the existing
article backlog, nominate exactly one article for the next worker fire, and
leave the request pending while the single safe worker slot is occupied.
"""
from __future__ import annotations

import fcntl
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from volpred.canonical_write import guard_canonical_write
from volpred.ops.next_tasks import (
    normalize_task_type_value,
    task_type_payload_conflict,
    write_tasks_to_handle,
)

_ACTIVE_STATUSES = frozenset({"claimed", "in_progress"})
_CONTINUITY_FIELDS = (
    "dispatch_preempt",
    "dispatch_preempt_source",
    "dispatch_preempt_rank",
    "article_continuity_requested_at",
)


def _is_article(task: dict[str, Any]) -> bool:
    return (
        normalize_task_type_value(task.get("task_type")) == "daily_article"
        and task_type_payload_conflict(task) is None
    )


def _clear_continuity_marker(task: dict[str, Any]) -> bool:
    if task.get("dispatch_preempt_source") != "article_continuity":
        return False
    changed = False
    for field in _CONTINUITY_FIELDS:
        if field in task:
            task.pop(field, None)
            changed = True
    return changed


def maintain_article_continuity(
    *,
    queue_path: str | Path,
    releasable_count: int,
    request_fire: Callable[[str], None],
    now: datetime | None = None,
    floor: int = 6,
) -> dict[str, Any]:
    """Bridge a dry release pool to one exact dispatcher candidate.

    Queue mutation is one flock-protected transaction.  The fire request is
    written only after that transaction commits, so a worker can never wake to
    an unmarked generic queue.  Repeated calls are idempotent; an active article
    prevents parallel article nomination while unrelated in-flight work leaves
    the request pending for the next safe slot.
    """

    path = Path(queue_path)
    observed_at = now or datetime.now(timezone.utc)
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if releasable_count < 0:
        raise ValueError("releasable_count must be non-negative")
    if floor < 1:
        raise ValueError("floor must be positive")

    guard_canonical_write(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("[]\n", encoding="utf-8")

    selected_task_id: str | None = None
    promoted_count = 0
    cleared_count = 0
    reason = "no_pending_article"
    with path.open("r+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            tasks = json.load(handle)
            if not isinstance(tasks, list):
                raise ValueError("next_tasks queue root must be a list")
            changed = False

            if releasable_count > 0:
                for raw in tasks:
                    if isinstance(raw, dict) and _clear_continuity_marker(raw):
                        cleared_count += 1
                        changed = True
                reason = "release_pool_stocked"
            else:
                articles = [
                    task
                    for task in tasks
                    if isinstance(task, dict) and _is_article(task)
                ]
                pending = [
                    task
                    for task in articles
                    if str(task.get("status") or "pending").lower() == "pending"
                ]
                active = [
                    task
                    for task in articles
                    if str(task.get("status") or "").lower() in _ACTIVE_STATUSES
                ]

                for task in pending[:floor]:
                    try:
                        priority = int(task.get("priority") or 999)
                    except (TypeError, ValueError):
                        priority = 999
                    if priority > 1:
                        task["priority"] = 1
                        task["priority_note"] = (
                            "article continuity: releasable pool=0; batch-promoted "
                            "to the dispatch floor"
                        )
                        promoted_count += 1
                        changed = True

                if active:
                    reason = "article_in_flight"
                elif pending:
                    selected = min(
                        pending,
                        key=lambda task: (
                            str(task.get("created_at") or "9999"),
                            str(task.get("id") or task.get("task_id") or ""),
                        ),
                    )
                    selected_task_id = str(
                        selected.get("id") or selected.get("task_id") or ""
                    )
                    if not selected_task_id:
                        reason = "selected_article_missing_identity"
                    else:
                        for task in pending:
                            if task is not selected and _clear_continuity_marker(task):
                                changed = True
                                cleared_count += 1
                        marker = {
                            "dispatch_preempt": True,
                            "dispatch_preempt_source": "article_continuity",
                            # Human urgent/time-critical lanes remain outside this
                            # ranking.  Inside scheduled preemption, continuity
                            # beats recurring machine incidents for one fire.
                            "dispatch_preempt_rank": -100,
                            "article_continuity_requested_at": observed_at
                            .astimezone(timezone.utc)
                            .isoformat(),
                        }
                        if any(selected.get(k) != v for k, v in marker.items()):
                            selected.update(marker)
                            changed = True
                        reason = "fire_requested"

            if changed:
                write_tasks_to_handle(handle, tasks)
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    if selected_task_id is not None and reason == "fire_requested":
        request_fire(f"article_continuity:{selected_task_id}")

    return {
        "ok": True,
        "reason": reason,
        "releasable_count": releasable_count,
        "selected_task_id": selected_task_id,
        "promoted_count": promoted_count,
        "cleared_count": cleared_count,
    }


__all__ = ["maintain_article_continuity"]

