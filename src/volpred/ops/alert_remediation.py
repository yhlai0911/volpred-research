"""Turn breached alerts into work the platform does, not chores the owner does.

2026-07-13, owner (two replies, same hour): 「你要立即處理 不是只建議我」/
「是你要立刻處理 不是叫我」. The `member_qa_stale` alert had emailed him an hourly
to-do list — *"主線程立即跑 question-ranking-workflow…"* — for 25 hours straight.
A sweep of `alerts.py` found the same shape in 24 of 27 alert bodies: a `## 建議行動`
section addressed to a human. Only three alerts remediated themselves.

The framing was the bug. On a platform whose premise is that the AI runs it, an
alert nobody but the owner can act on is a design failure, not a notification.
An alert *is* a task. So that is the default here, and the registry below only
names the exceptions:

* `SELF_REMEDIATING` — the alert already fixed it before emailing; a task would
  duplicate the work. Its body must say what it did.
* `OWNER_DECISION` — genuinely the owner's call (irreversible, or a policy /
  research-direction judgment). These may legitimately ask him for something.

Everything else auto-enqueues a task into the canonical pool and the email
reports what was queued. There is no "unclassified" branch that quietly falls
back to nagging: a newly added alert gets a task whether or not anyone
remembered to think about it.

Pairs with the starvation lockout in `scripts/continue_task_dispatch.py`. The
tasks created here are worthless if dispatch can skip them forever — which is
exactly what happened to the P1 `member_qa` task that sat pending for 17 hours
while this alert fired. Queuing work and guaranteeing it gets picked up are two
halves of one fix; neither works alone.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from volpred.canonical_write import guard_canonical_write
from volpred.ops.diagnostics import warn
from volpred.ops.next_tasks import normalize_task_priority, write_tasks_to_handle

# The alert repaired the breach itself before sending. Its body reports the
# repair; enqueuing a task on top would double-book the work.
SELF_REMEDIATING: dict[str, str] = {
    "publishing_freshness": "scripts/remediate_publish_drought.py ladder runs in check_alerts before the email",
    "lazypack_render_stuck": "render retry is wired into the alert path",
    "series_registry": "series drift is reconciled against config/article_series.json",
    "draft_pool_low": "continue_task_dispatch._maybe_refill_draft_pool tops the pool up each fire",
}

# Genuinely the owner's call. Keep this set small and justified — every entry is
# a standing admission that the platform cannot run itself here.
OWNER_DECISION: dict[str, str] = {
    "disk_usage": "freeing or buying disk is irreversible/hardware — the platform must not delete the owner's data on its own",
}

# Which lane the auto-created task belongs in. Default platform_ops.
ALERT_TASK_TYPE: dict[str, str] = {
    "member_qa_stale": "member_qa",
    "knowledge_stale": "experiment",
    "paper_stale": "paper_review",
    "paper_website_drift": "paper_review",
    "paper_adjudication_gap": "paper_review",  # 2026-07-14 K1686 incident: gating task done, ruling missing — main-thread adjudication
    "content_quality": "governance",
    "cluster_cap_drift": "governance",
    "loop_health": "governance",
}

_LEVEL_PRIORITY = {"critical": 1, "warn": 2, "info": 3}

# Internally-remediable alerts are a different contract from ordinary alert
# notifications: the first signal creates P1 work and stays out of the owner's
# inbox.  Only a *completed* repair task followed by the same signal counts as a
# failed attempt.  A still-pending/claimed task is work in flight, not failure.
_INTERNAL_ACTIVE_STATUSES = frozenset({"", "pending", "pending_main_thread", "claimed", "in_progress"})
_INTERNAL_ATTEMPT_HISTORY_LIMIT = 8

_SUGGEST_HEADING = "## 建議行動"
_AUDIT_HEADING = "## 處理步驟（任務已自動建立，以下供執行者稽核）"


def _tasks_path(storage_dir: str) -> Path:
    root = Path(storage_dir)
    if not root.is_absolute():
        root = Path(__file__).resolve().parents[3] / storage_dir
    return root / "next_tasks.json"


def task_id_for(alert_id: str, now: datetime) -> str:
    """One task per alert per day — an hourly alert must not mint 24 tasks."""
    return f"alert_{alert_id}_{now.strftime('%Y%m%d')}"


def task_id_for_alert_key(alert_key: str) -> str:
    """Stable task-id prefix for one root-cause alert identity.

    Titles often carry counts or timestamps.  Hashing the explicit alert key,
    rather than the presentation title, prevents those changing tokens from
    minting a parallel remediation task every fire.  Individual completed
    attempts add episode/attempt suffixes so stale completion receipts cannot
    terminalise a newer worker (ABA).
    """

    normalized = str(alert_key or "").strip().lower()
    if not normalized:
        raise ValueError("alert_key must not be empty")
    slug = re.sub(r"[^a-z0-9]+", "_", normalized).strip("_") or "alert"
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:10]
    return f"alert_internal_{slug[:48]}_{digest}"


def _parse_timestamp(value: Any, *, field: str, task_id: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        warn(
            "alert_remediation",
            "invalid task timestamp; ordering proof unavailable",
            task_id=task_id,
            field=field,
            raw=str(value)[:120],
            err=str(exc),
        )
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _state_timestamp(task: dict[str, Any], field: str) -> datetime | None:
    return _parse_timestamp(
        _internal_state(task).get(field),
        field=field,
        task_id=str(task.get("id") or ""),
    )


def _internal_task_description(condition: dict[str, Any], alert_key: str) -> str:
    return (
        f"由內部可自癒 alert_key `{alert_key}` 自動建立（固定 P1）。\n"
        "這是系統自己的修復工作；首次與修復進行中都不通知老闆。"
        "只有同一 alert_key 的修復任務連續完成但警報仍存在 >=2 次才升級。\n\n"
        f"{condition.get('body') or ''}"
    )


def _terminal_failure_reason(task: dict[str, Any], status: str) -> str:
    detail = (
        task.get("failure_reason")
        or task.get("last_error")
        or task.get("result")
        or ""
    )
    compact = " ".join(str(detail).split())[:500]
    if status == "succeeded":
        suffix = f"；上次結果：{compact}" if compact else ""
        return f"任務回報 succeeded，但同一 alert_key 仍觸發{suffix}"
    return compact or f"修復任務以 status={status or 'unknown'} 結束"


def _append_router_status_history(
    task: dict[str, Any],
    *,
    old_status: str,
    new_status: str,
    now: datetime,
    note: str,
) -> None:
    history = task.get("status_history")
    if not isinstance(history, list):
        history = []
        task["status_history"] = history
    history.append(
        {
            "ts": now.isoformat(),
            "from": old_status or "unknown",
            "to": new_status,
            "by": "alert_remediation_router",
            "note": note,
        }
    )


def _internal_state(task: dict[str, Any]) -> dict[str, Any]:
    state = task.get("internal_alert_state")
    if not isinstance(state, dict):
        state = {}
        task["internal_alert_state"] = state
    return state


def _internal_rows(tasks: list[Any], alert_key: str) -> list[dict[str, Any]]:
    return [
        task
        for task in tasks
        if isinstance(task, dict)
        and task.get("internal_remediable") is True
        and str(task.get("alert_key") or "") == alert_key
        and not task.get("tombstone")
    ]


def _internal_sort_key(task: dict[str, Any]) -> tuple[int, str, str]:
    state = _internal_state(task)
    return (
        int(state.get("attempt_number") or 0),
        str(task.get("created_at") or ""),
        str(task.get("id") or ""),
    )


def _new_episode_id(rows: list[dict[str, Any]], now: datetime) -> str:
    base = now.strftime("%Y%m%dT%H%M%S%fZ")
    used = {
        str(_internal_state(task).get("episode_id") or "")
        for task in rows
    }
    if base not in used:
        return base
    serial = 2
    while f"{base}_{serial}" in used:
        serial += 1
    return f"{base}_{serial}"


def _build_internal_attempt(
    condition: dict[str, Any],
    *,
    alert_key: str,
    episode_id: str,
    episode_started_at: str,
    attempt_number: int,
    consecutive_failures: int,
    attempt_history: list[dict[str, Any]],
    now: datetime,
    last_failure_reason: str | None = None,
) -> dict[str, Any]:
    task = {
        "id": f"{task_id_for_alert_key(alert_key)}_{episode_id}_a{attempt_number}",
        "title": f"[internal alert] {condition.get('title') or alert_key}",
        "description": _internal_task_description(condition, alert_key),
        "task_type": "platform_ops",
        "dispatch_lane": "agent",
        "priority": 1,
        "status": "pending",
        "created_at": now.isoformat(),
        "source": "internal_alert_remediation_router",
        "tags": ["alert", "internal-remediable", alert_key],
        "alert_key": alert_key,
        "internal_remediable": True,
        "internal_alert_state": {
            "episode_id": episode_id,
            "episode_started_at": episode_started_at,
            "attempt_number": attempt_number,
            "last_seen_at": now.isoformat(),
            "consecutive_remediation_failures": consecutive_failures,
            "attempt_history": attempt_history[-_INTERNAL_ATTEMPT_HISTORY_LIMIT:],
            "escalation_due": consecutive_failures >= 2,
        },
    }
    if last_failure_reason:
        task["internal_alert_state"]["last_failure_reason"] = last_failure_reason
    normalize_task_priority(task)
    return task


def _upsert_internal_clean_watermark(
    tasks: list[Any],
    *,
    alert_key: str,
    observed_at: datetime,
) -> tuple[dict[str, Any], bool]:
    watermark_id = f"{task_id_for_alert_key(alert_key)}_clean_watermark"
    existing = next(
        (
            task
            for task in tasks
            if isinstance(task, dict) and task.get("id") == watermark_id
        ),
        None,
    )
    if existing is None:
        existing = {
            "id": watermark_id,
            "title": f"[internal alert watermark] {alert_key}",
            "description": "Monotonic clean-observation receipt; never dispatched.",
            "task_type": "platform_ops",
            "priority": 1,
            "status": "succeeded",
            "source": "internal_alert_remediation_router",
            "created_at": observed_at.isoformat(),
            "completed_at": observed_at.isoformat(),
            "alert_key": alert_key,
            "internal_remediable": True,
            "internal_alert_watermark": True,
            "internal_alert_state": {
                "resolved_at": observed_at.isoformat(),
                "last_clean_observed_at": observed_at.isoformat(),
            },
        }
        normalize_task_priority(existing)
        tasks.append(existing)
        return existing, True

    state = _internal_state(existing)
    previous = _state_timestamp(existing, "resolved_at")
    if previous is not None and observed_at <= previous:
        return existing, False
    state["resolved_at"] = observed_at.isoformat()
    state["last_clean_observed_at"] = observed_at.isoformat()
    existing["completed_at"] = observed_at.isoformat()
    return existing, True


def _route_internal_task(
    tasks: list[Any],
    condition: dict[str, Any],
    *,
    alert_key: str,
    now: datetime,
) -> dict[str, Any]:
    """Ensure one active attempt per key without reusing a completed task id.

    A fresh task id per attempt prevents a late completion receipt for attempt A
    from terminalising a newer in-progress attempt B (the task-pool complete CLI
    intentionally has no generation CAS).  Idempotency lives in the stable
    ``alert_key`` and the locked one-active-attempt scan.
    """

    rows = _internal_rows(tasks, alert_key)
    unresolved = [
        task for task in rows if not _internal_state(task).get("resolved_at")
    ]
    if not unresolved and rows:
        resolved_stamps = [
            stamp
            for task in rows
            if (stamp := _state_timestamp(task, "resolved_at")) is not None
        ]
        if resolved_stamps and now <= max(resolved_stamps):
            latest = max(rows, key=_internal_sort_key)
            return {
                "created": False,
                "reason": "stale_breach_observation",
                "task_id": latest.get("id"),
                "consecutive_remediation_failures": 0,
                "escalate": False,
            }
    active = [
        task
        for task in unresolved
        if str(task.get("status") or "").strip().lower() in _INTERNAL_ACTIVE_STATUSES
    ]
    if active:
        task = max(active, key=_internal_sort_key)
        state = _internal_state(task)
        task["title"] = f"[internal alert] {condition.get('title') or alert_key}"
        task["description"] = _internal_task_description(condition, alert_key)
        task["priority"] = 1
        task["task_type"] = "platform_ops"
        task["dispatch_lane"] = "agent"
        task["tags"] = ["alert", "internal-remediable", alert_key]
        prior_seen = _state_timestamp(task, "last_seen_at")
        if prior_seen is None or now > prior_seen:
            state["last_seen_at"] = now.isoformat()
        if not task.get("status"):
            task["status"] = "pending"
        return {
            "created": False,
            "reason": "remediation_active",
            "task_id": task.get("id"),
            "task_type": "platform_ops",
            "dispatch_lane": "agent",
            "priority": 1,
            "episode_id": state.get("episode_id"),
            "attempt_number": int(state.get("attempt_number") or 1),
            "consecutive_remediation_failures": int(
                state.get("consecutive_remediation_failures") or 0
            ),
            "last_failure_reason": state.get("last_failure_reason"),
            "escalate": bool(
                (state.get("escalation_due") or int(
                    state.get("consecutive_remediation_failures") or 0
                ) >= 2)
                and not state.get("escalation_sent_at")
            ),
        }

    if unresolved:
        previous = max(unresolved, key=_internal_sort_key)
        state = _internal_state(previous)
        status = str(previous.get("status") or "").strip().lower()
        completed_at = _parse_timestamp(
            previous.get("completed_at")
            or previous.get("failed_at")
            or previous.get("blocked_at"),
            field="completed_at",
            task_id=str(previous.get("id") or ""),
        )
        if completed_at is None or now <= completed_at:
            prior_seen = _state_timestamp(previous, "last_seen_at")
            if prior_seen is None or now > prior_seen:
                state["last_seen_at"] = now.isoformat()
            return {
                "created": False,
                "reason": "awaiting_post_completion_observation",
                "task_id": previous.get("id"),
                "task_type": "platform_ops",
                "dispatch_lane": "agent",
                "priority": 1,
                "attempt_number": int(state.get("attempt_number") or 1),
                "consecutive_remediation_failures": int(
                    state.get("consecutive_remediation_failures") or 0
                ),
                "escalate": False,
            }
        failure_reason = _terminal_failure_reason(previous, status)
        consecutive = int(state.get("consecutive_remediation_failures") or 0)
        history = state.get("attempt_history")
        if not isinstance(history, list):
            history = []
        if not state.get("counted_as_failure_at"):
            consecutive += 1
            history.append(
                {
                    "observed_at": now.isoformat(),
                    "completed_at": previous.get("completed_at"),
                    "status": status or "unknown",
                    "failure_reason": failure_reason,
                }
            )
            state["counted_as_failure_at"] = now.isoformat()
            state["consecutive_remediation_failures"] = consecutive
            state["last_failure_reason"] = failure_reason

        episode_id = str(state.get("episode_id") or _new_episode_id(rows, now))
        episode_started_at = str(state.get("episode_started_at") or now.isoformat())
        attempt_number = int(state.get("attempt_number") or 1) + 1
        task = _build_internal_attempt(
            condition,
            alert_key=alert_key,
            episode_id=episode_id,
            episode_started_at=episode_started_at,
            attempt_number=attempt_number,
            consecutive_failures=consecutive,
            attempt_history=history,
            now=now,
            last_failure_reason=failure_reason,
        )
        tasks.append(task)
        return {
            "created": True,
            "requeued": True,
            "reason": "remediation_requeued",
            "task_id": task["id"],
            "task_type": "platform_ops",
            "dispatch_lane": "agent",
            "priority": 1,
            "episode_id": episode_id,
            "attempt_number": attempt_number,
            "consecutive_remediation_failures": consecutive,
            "last_failure_reason": failure_reason,
            "escalate": consecutive >= 2,
        }

    episode_id = _new_episode_id(rows, now)
    task = _build_internal_attempt(
        condition,
        alert_key=alert_key,
        episode_id=episode_id,
        episode_started_at=now.isoformat(),
        attempt_number=1,
        consecutive_failures=0,
        attempt_history=[],
        now=now,
    )
    tasks.append(task)
    return {
        "created": True,
        "task_id": task["id"],
        "task_type": "platform_ops",
        "dispatch_lane": "agent",
        "priority": 1,
        "episode_id": episode_id,
        "attempt_number": 1,
        "consecutive_remediation_failures": 0,
        "escalate": False,
    }


def _resolve_internal_tasks(
    tasks: list[Any],
    *,
    alert_key: str,
    now: datetime,
) -> dict[str, Any]:
    """Close the current episode without clobbering a claimed worker."""

    rows = _internal_rows(tasks, alert_key)
    unresolved = [
        task for task in rows if not _internal_state(task).get("resolved_at")
    ]
    if not unresolved:
        watermark, changed = _upsert_internal_clean_watermark(
            tasks,
            alert_key=alert_key,
            observed_at=now,
        )
        return {
            "resolved": True,
            "changed": changed,
            "task_id": watermark.get("id"),
            "status": watermark.get("status"),
        }

    latest = max(unresolved, key=_internal_sort_key)
    latest_state = _internal_state(latest)
    episode_id = str(latest_state.get("episode_id") or "")
    episode_rows = [
        task
        for task in unresolved
        if not episode_id or str(_internal_state(task).get("episode_id") or "") == episode_id
    ]
    last_seen_stamps = [
        stamp
        for task in episode_rows
        if (stamp := _state_timestamp(task, "last_seen_at")) is not None
    ]
    if last_seen_stamps and now < max(last_seen_stamps):
        return {
            "resolved": False,
            "changed": False,
            "reason": "stale_resolution_observation",
            "task_id": latest.get("id"),
            "status": latest.get("status"),
        }
    for task in episode_rows:
        state = _internal_state(task)
        state["resolved_at"] = now.isoformat()
        state["final_consecutive_remediation_failures"] = int(
            state.get("consecutive_remediation_failures") or 0
        )
        state["consecutive_remediation_failures"] = 0
        state.pop("last_failure_reason", None)
        status = str(task.get("status") or "").strip().lower()
        if status in {"", "pending", "pending_main_thread"}:
            task["status"] = "succeeded"
            task["completed_at"] = now.isoformat()
            task["result"] = "internal alert cleared before dispatch"
            _append_router_status_history(
                task,
                old_status=status,
                new_status="succeeded",
                now=now,
                note="condition_cleared_automatically",
            )
    _upsert_internal_clean_watermark(
        tasks,
        alert_key=alert_key,
        observed_at=now,
    )
    return {
        "resolved": True,
        "changed": True,
        "task_id": latest.get("id"),
        "status": latest.get("status"),
    }


def _mark_internal_escalation_sent(
    tasks: list[Any],
    *,
    alert_key: str,
    task_id: str,
    now: datetime,
    notification_id: str | None,
) -> dict[str, Any]:
    task = next(
        (
            row
            for row in _internal_rows(tasks, alert_key)
            if str(row.get("id") or "") == task_id
        ),
        None,
    )
    if task is None:
        return {"recorded": False, "reason": "task_not_found", "task_id": task_id}
    state = _internal_state(task)
    if state.get("escalation_sent_at"):
        return {"recorded": True, "changed": False, "task_id": task_id}
    state["escalation_sent_at"] = now.isoformat()
    if notification_id:
        state["escalation_notification_id"] = notification_id
    return {"recorded": True, "changed": True, "task_id": task_id}


def _enqueue(
    condition: dict[str, Any],
    storage_dir: str,
    now: datetime,
    *,
    alert_key: str | None = None,
    resolve_only: bool = False,
    escalation_ack_task_id: str | None = None,
    notification_id: str | None = None,
) -> dict[str, Any]:
    alert_id = str(condition.get("id") or "")
    tid = task_id_for(alert_id, now)
    level = str(condition.get("level") or "warn")
    path = _tasks_path(storage_dir)

    task = {
        "id": tid,
        "title": f"[alert] {condition.get('title') or alert_id}",
        "description": (
            f"由 alert `{alert_id}` 自動建立（level={level}）。\n"
            f"這是系統自己要做的事，不是老闆的待辦。做完後下一輪巡檢會自動解除警報。\n\n"
            f"{condition.get('body') or ''}"
        ),
        "task_type": ALERT_TASK_TYPE.get(alert_id, "platform_ops"),
        "priority": _LEVEL_PRIORITY.get(level, 2),
        "status": "pending",
        "created_at": now.isoformat(),
        "source": "alert_remediation_bridge",
        "tags": ["alert", alert_id],
    }
    normalize_task_priority(task)

    # The governance guard must not be swallowed by the operational fallback:
    # candidate/pre-commit contexts deliberately forbid canonical writes.
    guard_canonical_write(path)
    try:
        if escalation_ack_task_id and not path.exists():
            return {
                "recorded": False,
                "reason": "task_not_found",
                "task_id": escalation_ack_task_id,
            }
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("[]\n", encoding="utf-8")
        with path.open("r+", encoding="utf-8") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                payload = json.load(fh)
                if not isinstance(payload, list):
                    warn("alert_remediation", "next_tasks.json is not a list", alert_id=alert_id)
                    return {"created": False, "reason": "next_tasks_not_a_list"}
                tasks = payload

                if alert_key and escalation_ack_task_id:
                    outcome = _mark_internal_escalation_sent(
                        tasks,
                        alert_key=alert_key,
                        task_id=escalation_ack_task_id,
                        now=now,
                        notification_id=notification_id,
                    )
                    if outcome.get("changed"):
                        write_tasks_to_handle(fh, tasks)
                    return outcome
                if alert_key and resolve_only:
                    outcome = _resolve_internal_tasks(
                        tasks,
                        alert_key=alert_key,
                        now=now,
                    )
                    if not outcome.get("changed"):
                        return outcome
                    write_tasks_to_handle(fh, tasks)
                    return outcome
                if alert_key:
                    outcome = _route_internal_task(
                        tasks,
                        condition,
                        alert_key=alert_key,
                        now=now,
                    )
                    write_tasks_to_handle(fh, tasks)
                    return outcome
                existing = next(
                    (t for t in tasks if isinstance(t, dict) and t.get("id") == tid),
                    None,
                )
                if existing is not None:
                    return {"created": False, "reason": "already_queued_today", "task_id": tid}

                tasks.append(task)
                write_tasks_to_handle(fh, tasks)
                return {
                    "created": True,
                    "task_id": tid,
                    "task_type": task["task_type"],
                    "priority": task["priority"],
                }
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    except Exception as exc:  # noqa: BLE001 — caller decides whether escalation is earned
        warn("alert_remediation", "enqueue failed", alert_id=alert_id, err=str(exc))
        return {"created": False, "reason": "enqueue_failed", "error": str(exc)}


def remediate_internal_alert(
    condition: dict[str, Any],
    *,
    alert_key: str,
    storage_dir: str = "storage",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Queue/requeue one internal repair without deciding notification delivery."""

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    outcome = _enqueue(condition, storage_dir, current, alert_key=alert_key)
    return {
        "disposition": "internal_remediation",
        "alert_id": str(condition.get("id") or ""),
        "alert_key": alert_key,
        **outcome,
    }


def mark_internal_alert_escalated(
    *,
    alert_key: str,
    task_id: str,
    storage_dir: str = "storage",
    notification_id: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Persist delivery acknowledgement for a due escalation.

    The due bit is written with the next attempt before transport.  If the
    process crashes during delivery, the next detector signal sees the active
    task plus an unacknowledged due bit and retries instead of losing the page.
    """

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    condition = {"id": alert_key, "level": "info", "title": alert_key, "body": ""}
    outcome = _enqueue(
        condition,
        storage_dir,
        current,
        alert_key=alert_key,
        escalation_ack_task_id=task_id,
        notification_id=notification_id,
    )
    if outcome.get("reason") in {"enqueue_failed", "next_tasks_not_a_list"}:
        warn(
            "alert_remediation",
            "escalation acknowledgement failed; delivery remains due",
            alert_key=alert_key,
            task_id=task_id,
            err=str(outcome.get("error") or outcome.get("reason")),
        )
    return outcome


def resolve_internal_alert(
    *,
    alert_key: str,
    storage_dir: str = "storage",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Mark an internal incident resolved so a later episode starts at zero."""

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    condition = {"id": alert_key, "level": "info", "title": alert_key, "body": ""}
    return {
        "alert_key": alert_key,
        **_enqueue(
            condition,
            storage_dir,
            current,
            alert_key=alert_key,
            resolve_only=True,
        ),
    }


def _rewrite_body(body: str, outcome: dict[str, Any]) -> str:
    """Lead with what the platform did; demote the human-addressed steps to audit."""
    if outcome.get("created"):
        header = (
            "## 已自動處理\n"
            f"已建立任務 `{outcome['task_id']}`（{outcome['task_type']}, P{outcome['priority']}），"
            "下一班 dispatch 會認領執行。任務逾時未被認領時，dispatcher 的 starvation lockout "
            "會強制把它推上候選清單。**老闆無需動作。**\n"
        )
    elif outcome.get("reason") == "already_queued_today":
        header = (
            "## 已自動處理\n"
            f"任務 `{outcome['task_id']}` 今日稍早已建立，仍在處理中。**老闆無需動作。**\n"
        )
    else:
        header = (
            "## ⚠️ 自動建任務失敗\n"
            f"原因：`{outcome.get('reason') or outcome.get('error')}`。"
            "此警報暫時退回人工，這本身是一個要修的 bug。\n"
        )

    demoted = body.replace(_SUGGEST_HEADING, _AUDIT_HEADING) if _SUGGEST_HEADING in body else body
    return f"{header}\n{demoted}"


def remediate_condition(
    condition: dict[str, Any],
    *,
    storage_dir: str = "storage",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Apply the disposition for one breached condition, mutating its body in place."""
    now = now or datetime.now(timezone.utc)
    alert_id = str(condition.get("id") or "")

    if not condition.get("breached"):
        return {"disposition": "not_breached", "alert_id": alert_id}

    if alert_id in SELF_REMEDIATING:
        return {"disposition": "self_remediating", "alert_id": alert_id, "why": SELF_REMEDIATING[alert_id]}

    if alert_id in OWNER_DECISION:
        return {"disposition": "owner_decision", "alert_id": alert_id, "why": OWNER_DECISION[alert_id]}

    outcome = _enqueue(condition, storage_dir, now)
    condition["body"] = _rewrite_body(str(condition.get("body") or ""), outcome)
    condition["remediation"] = outcome
    return {"disposition": "task", "alert_id": alert_id, **outcome}


def remediate_report(
    report: dict[str, Any],
    *,
    storage_dir: str = "storage",
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Run dispositions across every breached condition. Call before sending."""
    return [
        remediate_condition(c, storage_dir=storage_dir, now=now)
        for c in report.get("conditions", [])
        if c.get("breached")
    ]
