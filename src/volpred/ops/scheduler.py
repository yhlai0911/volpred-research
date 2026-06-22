from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from .common import project_path
from .event_jobs import expand_due_event_jobs, preview_event_jobs
from .execution_brief import task_requires_coordinator, task_unmet_preconditions
from .local_control_plane import (
    _agent_is_stale,
    get_agent_session,
    get_task,
    list_tasks,
)
from .shared_lock import shared_state_lock

LOGGER_NAME = "volpred.scheduler"


def _scheduler_log_path(storage_dir: str = "storage") -> Path:
    path = project_path(storage_dir, "ops", "scheduler.log")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _scheduler_state_path(storage_dir: str = "storage") -> Path:
    path = project_path(storage_dir, "ops", "scheduler_state.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _write_scheduler_state(payload: dict[str, Any], *, storage_dir: str = "storage") -> None:
    _scheduler_state_path(storage_dir).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_scheduler_state(*, storage_dir: str = "storage") -> dict[str, Any]:
    path = _scheduler_state_path(storage_dir)
    if not path.exists():
        return {
            "last_tick_at": None,
            "last_status": "never",
            "last_reason": None,
            "last_result": None,
        }
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        _logger(storage_dir).warning(
            "scheduler_state_read_failed path=%s error=%s: %s",
            path,
            type(exc).__name__,
            exc,
        )
        return {
            "last_tick_at": None,
            "last_status": "invalid_state",
            "last_reason": None,
            "last_result": None,
        }


def _logger(storage_dir: str = "storage") -> logging.Logger:
    logger = logging.getLogger(f"{LOGGER_NAME}.{storage_dir}")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(_scheduler_log_path(storage_dir), maxBytes=10 * 1024 * 1024, backupCount=5)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.propagate = False
    return logger


def _queued_tasks(storage_dir: str = "storage") -> list[dict[str, Any]]:
    return list_tasks(status="queued", storage_dir=storage_dir)


def _session_dispatch_state(agent_name: str, *, storage_dir: str) -> tuple[str, dict[str, Any] | None]:
    session = get_agent_session(agent_name, storage_dir=storage_dir)
    if session is None:
        return "missing", None
    if _agent_is_stale(session):
        return "stale", session
    status = str(session.get("status") or "offline")
    if status == "offline":
        return "offline", session
    session_id = str(session.get("session_id") or "")
    if session_id.startswith("scheduler:"):
        return "scheduler_owned", session
    return "live_manual", session


def _agent_available_for_scheduler(agent_name: str, *, storage_dir: str) -> bool:
    session_state, session = _session_dispatch_state(agent_name, storage_dir=storage_dir)
    if session_state in {"missing", "stale", "offline"}:
        return True
    if session_state == "scheduler_owned":
        claimed_task_id = str(session.get("claimed_task_id") or "")
        if str(session.get("status") or "offline") == "busy" and claimed_task_id:
            current_task = get_task(claimed_task_id, storage_dir=storage_dir)
            if current_task and str(current_task.get("status")) not in {"succeeded", "failed", "cancelled"}:
                return False
        return True
    return False


def _task_requires_coordinator(task: dict[str, Any], *, storage_dir: str) -> bool:
    _ = storage_dir
    return task_requires_coordinator(task)


def _select_task(storage_dir: str = "storage") -> tuple[dict[str, Any] | None, str | None]:
    for task in _queued_tasks(storage_dir):
        if str(task.get("brief_status") or "") == "needs_manual_review":
            continue
        if task_unmet_preconditions(task):
            continue
        requires_coordinator = _task_requires_coordinator(task, storage_dir=storage_dir)
        target_agent = "claude" if requires_coordinator else str(task.get("preferred_agent") or "claude")
        if not _agent_available_for_scheduler(target_agent, storage_dir=storage_dir):
            continue
        return task, target_agent
    return None, None


def scheduler_preview(*, storage_dir: str = "storage") -> dict[str, Any]:
    selected, target_agent = _select_task(storage_dir)
    decision: dict[str, Any] | None = None
    if selected is not None:
        requires_coordinator = _task_requires_coordinator(selected, storage_dir=storage_dir)
        dispatch_mode = "coordinator" if requires_coordinator else "executor_advisory"
        decision = {
            "task_id": selected.get("id"),
            "title": selected.get("title"),
            "mode": dispatch_mode,
            "agent": target_agent,
            "brief_status": selected.get("brief_status"),
            "advisory_only": not requires_coordinator,
            "would_write_claim": False if not requires_coordinator else None,
        }
    return {
        "events": preview_event_jobs(storage_dir=storage_dir),
        "queued_count": len(_queued_tasks(storage_dir)),
        "queue_snapshot": _queue_snapshot(storage_dir=storage_dir),
        "decision": decision,
    }


def _run_coordinator_round(task: dict[str, Any], *, storage_dir: str) -> dict[str, Any]:
    from .execution_brief import run_coordinator_brief

    logger = _logger(storage_dir)
    task_id = str(task["id"])
    logger.info("coordinator_round task_id=%s", task_id)
    try:
        brief = run_coordinator_brief(task_id, storage_dir=storage_dir)
        return {
            "mode": "coordinator",
            "task_id": task_id,
            "result": "brief_ready",
            "brief_status": "ready",
            "brief": brief,
        }
    except Exception as exc:  # pragma: no cover - exercised by scheduler tests via monkeypatch
        current = get_task(task_id, storage_dir=storage_dir) or {}
        logger.warning("coordinator_round_failed task_id=%s error=%s", task_id, exc)
        return {
            "mode": "coordinator",
            "task_id": task_id,
            "result": "blocked",
            "brief_status": current.get("brief_status"),
            "task_status": current.get("status"),
            "error": str(exc),
        }


def _queue_snapshot(*, storage_dir: str = "storage", limit: int = 5) -> list[dict[str, Any]]:
    snapshot: list[dict[str, Any]] = []
    for task in _queued_tasks(storage_dir)[: max(limit, 0)]:
        requires_coordinator = _task_requires_coordinator(task, storage_dir=storage_dir)
        target_agent = "claude" if requires_coordinator else str(task.get("preferred_agent") or "claude")
        unmet = task_unmet_preconditions(task)
        blocked_reason: str | None = None
        if str(task.get("brief_status") or "") == "needs_manual_review":
            blocked_reason = "needs_manual_review"
        elif unmet:
            blocked_reason = "waiting_on_preconditions"
        elif not _agent_available_for_scheduler(target_agent, storage_dir=storage_dir):
            blocked_reason = "agent_unavailable"
        snapshot.append(
            {
                "task_id": task.get("id"),
                "title": task.get("title"),
                "source": task.get("source"),
                "priority": task.get("priority"),
                "preferred_agent": task.get("preferred_agent"),
                "target_agent": target_agent,
                "brief_status": task.get("brief_status"),
                "dispatch_mode": "coordinator" if requires_coordinator else "executor_advisory",
                "runnable": blocked_reason is None,
                "blocked_reason": blocked_reason,
            }
        )
    return snapshot


def _build_executor_advisory(task: dict[str, Any], *, storage_dir: str) -> dict[str, Any]:
    logger = _logger(storage_dir)
    agent_name = str(task.get("preferred_agent") or "claude")
    task_id = str(task["id"])
    session_state, session = _session_dispatch_state(agent_name, storage_dir=storage_dir)
    logger.info(
        "executor_advisory task_id=%s agent=%s session_state=%s",
        task_id,
        agent_name,
        session_state,
    )
    return {
        "mode": "executor",
        "task_id": task_id,
        "agent": agent_name,
        "result": "would_dispatch",
        "dispatch_mode": "advisory_only",
        "claim_written": False,
        "task_status": task.get("status"),
        "brief_status": task.get("brief_status"),
        "session_state": session_state,
        "session_key": session.get("session_key") if session else None,
        "queued_count": len(_queued_tasks(storage_dir)),
    }


def scheduler_tick(*, storage_dir: str = "storage") -> dict[str, Any]:
    logger = _logger(storage_dir)
    with shared_state_lock("scheduler_tick", storage_dir=storage_dir, blocking=False) as acquired:
        if not acquired:
            logger.info("skip lock_busy")
            return {"status": "skipped", "reason": "lock_busy"}

        expanded = expand_due_event_jobs(storage_dir=storage_dir)
        selected, _target_agent = _select_task(storage_dir)
        if selected is None:
            queued_tasks = _queued_tasks(storage_dir)
            reason = "no_runnable_work" if queued_tasks else "no_work"
            logger.info("skip %s", reason)
            result = {
                "status": "skipped",
                "reason": reason,
                "event_expansion": expanded,
                "queue_snapshot": _queue_snapshot(storage_dir=storage_dir),
            }
            _write_scheduler_state(
                {
                    "last_tick_at": expanded["generated_at"],
                    "last_status": "skipped",
                    "last_reason": reason,
                    "last_result": result,
                },
                storage_dir=storage_dir,
            )
            return result

        if _task_requires_coordinator(selected, storage_dir=storage_dir):
            result = _run_coordinator_round(selected, storage_dir=storage_dir)
        else:
            result = _build_executor_advisory(selected, storage_dir=storage_dir)
        payload = {
            "status": "ok",
            "event_expansion": expanded,
            "result": result,
            "queue_snapshot": _queue_snapshot(storage_dir=storage_dir),
        }
        _write_scheduler_state(
            {
                "last_tick_at": expanded["generated_at"],
                "last_status": "ok",
                "last_reason": None,
                "last_result": {
                    "mode": result.get("mode"),
                    "task_id": result.get("task_id"),
                    "agent": result.get("agent"),
                    "result": result.get("result"),
                    "task_status": result.get("task_status"),
                    "brief_status": result.get("brief_status"),
                    "dispatch_mode": result.get("dispatch_mode"),
                    "claim_written": result.get("claim_written"),
                },
            },
            storage_dir=storage_dir,
        )
        return payload
