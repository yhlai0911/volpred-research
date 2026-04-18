from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from .agent_spec import check_agent_specs
from .local_control_plane import (
    claim_next_task,
    complete_task,
    fail_task,
    get_agent_session,
    get_agent_session_by_session_key,
    heartbeat_agent,
    resolve_session_key,
)
from .rollback import create_rollback_point
from .execution_brief import preflight_executor_task


def _utc_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _assert_actor(agent_name: str) -> str:
    actor = os.environ.get("VOLPRED_ACTOR")
    if actor != agent_name:
        raise RuntimeError(
            "VOLPRED_ACTOR mismatch: "
            f"expected '{agent_name}', got '{actor or 'unset'}'. "
            f"Run: export VOLPRED_ACTOR={agent_name}"
        )
    return actor


def _default_session_id(session_key: str) -> str:
    return f"{session_key}:{os.getpid()}"


def _bootstrap_point_id(session_key: str) -> str:
    return f"{session_key}_session_{_utc_compact()}_{os.getpid()}"


def _resolve_session(
    *,
    agent_name: str | None,
    session_key: str | None,
    role: str | None,
) -> tuple[str, str, str]:
    return resolve_session_key(
        session_key=session_key, agent_name=agent_name, role=role
    )


def _load_session_record(
    session_key: str, agent_name: str, *, storage_dir: str
) -> dict[str, Any] | None:
    payload = get_agent_session_by_session_key(session_key, storage_dir=storage_dir)
    if payload is not None:
        return payload
    # Legacy fallback: pre session-key records stored under agent_name only.
    return get_agent_session(agent_name, storage_dir=storage_dir)


def session_bootstrap(
    agent_name: str | None = None,
    *,
    session_key: str | None = None,
    role: str | None = None,
    terminal_label: str | None = None,
    storage_dir: str = "storage",
    session_id: str | None = None,
    rollback_point_id: str | None = None,
) -> dict[str, Any]:
    resolved_key, resolved_agent, resolved_role = _resolve_session(
        agent_name=agent_name, session_key=session_key, role=role
    )
    _assert_actor(resolved_agent)
    rollback = create_rollback_point(
        point_id=rollback_point_id or _bootstrap_point_id(resolved_key),
        storage_dir=storage_dir,
    )
    agent_spec = check_agent_specs()
    if not agent_spec["clean"]:
        issues = "; ".join(str(issue) for issue in agent_spec["issues"])
        raise RuntimeError(f"agent-spec drift detected: {issues}")
    current = _load_session_record(resolved_key, resolved_agent, storage_dir=storage_dir) or {}
    session = heartbeat_agent(
        session_key=resolved_key,
        role=resolved_role,
        terminal_label=terminal_label,
        status="idle",
        session_id=session_id or str(current.get("session_id") or _default_session_id(resolved_key)),
        session_rollback_point_id=str(rollback["point_id"]),
        storage_dir=storage_dir,
    )
    return {
        "agent": resolved_agent,
        "session_key": resolved_key,
        "role": resolved_role,
        "session": session,
        "rollback_point": rollback,
        "agent_spec": agent_spec,
    }


def _require_bootstrapped_session(
    resolved_key: str, resolved_agent: str, *, storage_dir: str
) -> dict[str, Any]:
    session = _load_session_record(resolved_key, resolved_agent, storage_dir=storage_dir)
    if session is None:
        raise RuntimeError(
            f"Agent session not found for {resolved_key}; run session-bootstrap first"
        )
    if not session.get("session_id") or not session.get("session_rollback_point_id"):
        raise RuntimeError(
            f"Agent session for {resolved_key} is missing bootstrap metadata; run session-bootstrap first"
        )
    return session


def session_next_task(
    agent_name: str | None = None,
    *,
    session_key: str | None = None,
    role: str | None = None,
    storage_dir: str = "storage",
    emit_brief: bool = False,
) -> dict[str, Any]:
    resolved_key, resolved_agent, resolved_role = _resolve_session(
        agent_name=agent_name, session_key=session_key, role=role
    )
    _assert_actor(resolved_agent)
    session = _require_bootstrapped_session(resolved_key, resolved_agent, storage_dir=storage_dir)
    heartbeat_agent(
        session_key=resolved_key,
        role=resolved_role,
        status="idle",
        session_id=str(session["session_id"]),
        session_rollback_point_id=str(session["session_rollback_point_id"]),
        storage_dir=storage_dir,
    )
    skipped_task_ids: set[str] = set()
    while True:
        task = claim_next_task(
            session_key=resolved_key,
            storage_dir=storage_dir,
            skip_task_ids=skipped_task_ids,
        )
        if task is None:
            return {
                "agent": resolved_agent,
                "session_key": resolved_key,
                "role": resolved_role,
                "task": None,
                "brief": None,
            }
        try:
            prepared = preflight_executor_task(
                task["id"], agent_name=resolved_agent, storage_dir=storage_dir
            )
        except RuntimeError as exc:
            if str(exc) in {"brief_missing_or_stale", "preconditions_not_met"}:
                skipped_task_ids.add(str(task["id"]))
                continue
            raise
        return {
            "agent": resolved_agent,
            "session_key": resolved_key,
            "role": resolved_role,
            "task": prepared["task"],
            "brief": prepared["brief"] if emit_brief else None,
        }


def session_finish_task(
    task_id: str,
    *,
    agent_name: str | None = None,
    session_key: str | None = None,
    role: str | None = None,
    summary: str | None = None,
    error: str | None = None,
    signal_payload: dict[str, Any] | None = None,
    commands_run: list[str] | None = None,
    files_touched: list[str] | None = None,
    subagent_count: int = 0,
    storage_dir: str = "storage",
) -> dict[str, Any]:
    resolved_key, resolved_agent, resolved_role = _resolve_session(
        agent_name=agent_name, session_key=session_key, role=role
    )
    _assert_actor(resolved_agent)
    _require_bootstrapped_session(resolved_key, resolved_agent, storage_dir=storage_dir)
    if error:
        return fail_task(
            task_id,
            session_key=resolved_key,
            role=resolved_role,
            error=error,
            summary=summary,
            signal_payload=signal_payload,
            commands_run=commands_run,
            files_touched=files_touched,
            subagent_count=subagent_count,
            storage_dir=storage_dir,
        )
    return complete_task(
        task_id,
        session_key=resolved_key,
        role=resolved_role,
        summary=summary,
        signal_payload=signal_payload,
        commands_run=commands_run,
        files_touched=files_touched,
        subagent_count=subagent_count,
        storage_dir=storage_dir,
    )


def session_shutdown(
    agent_name: str | None = None,
    *,
    session_key: str | None = None,
    role: str | None = None,
    storage_dir: str = "storage",
) -> dict[str, Any]:
    resolved_key, resolved_agent, resolved_role = _resolve_session(
        agent_name=agent_name, session_key=session_key, role=role
    )
    _assert_actor(resolved_agent)
    current = _load_session_record(resolved_key, resolved_agent, storage_dir=storage_dir) or {}
    session = heartbeat_agent(
        session_key=resolved_key,
        role=resolved_role,
        status="offline",
        session_id=str(current.get("session_id") or _default_session_id(resolved_key)),
        session_rollback_point_id=current.get("session_rollback_point_id"),
        claimed_task_id=None,
        storage_dir=storage_dir,
    )
    return {
        "agent": resolved_agent,
        "session_key": resolved_key,
        "role": resolved_role,
        "session": session,
    }
