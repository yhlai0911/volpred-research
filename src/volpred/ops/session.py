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
    heartbeat_agent,
)
from .rollback import create_rollback_point


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


def _default_session_id(agent_name: str) -> str:
    return f"{agent_name}:{os.getpid()}"


def _bootstrap_point_id(agent_name: str) -> str:
    return f"{agent_name}_session_{_utc_compact()}_{os.getpid()}"


def session_bootstrap(
    agent_name: str,
    *,
    storage_dir: str = "storage",
    session_id: str | None = None,
    rollback_point_id: str | None = None,
) -> dict[str, Any]:
    _assert_actor(agent_name)
    rollback = create_rollback_point(
        point_id=rollback_point_id or _bootstrap_point_id(agent_name),
        storage_dir=storage_dir,
    )
    agent_spec = check_agent_specs()
    if not agent_spec["clean"]:
        issues = "; ".join(str(issue) for issue in agent_spec["issues"])
        raise RuntimeError(f"agent-spec drift detected: {issues}")
    current = get_agent_session(agent_name, storage_dir=storage_dir) or {}
    session = heartbeat_agent(
        agent_name=agent_name,
        status="idle",
        session_id=session_id or str(current.get("session_id") or _default_session_id(agent_name)),
        session_rollback_point_id=str(rollback["point_id"]),
        storage_dir=storage_dir,
    )
    return {
        "agent": agent_name,
        "session": session,
        "rollback_point": rollback,
        "agent_spec": agent_spec,
    }


def _require_bootstrapped_session(agent_name: str, *, storage_dir: str = "storage") -> dict[str, Any]:
    session = get_agent_session(agent_name, storage_dir=storage_dir)
    if session is None:
        raise RuntimeError(f"Agent session not found for {agent_name}; run session-bootstrap first")
    if not session.get("session_id") or not session.get("session_rollback_point_id"):
        raise RuntimeError(
            f"Agent session for {agent_name} is missing bootstrap metadata; run session-bootstrap first"
        )
    return session


def session_next_task(
    agent_name: str,
    *,
    storage_dir: str = "storage",
    emit_brief: bool = False,
) -> dict[str, Any]:
    _assert_actor(agent_name)
    session = _require_bootstrapped_session(agent_name, storage_dir=storage_dir)
    heartbeat_agent(
        agent_name=agent_name,
        status="idle",
        session_id=str(session["session_id"]),
        session_rollback_point_id=str(session["session_rollback_point_id"]),
        storage_dir=storage_dir,
    )
    task = claim_next_task(agent_name, storage_dir=storage_dir)
    return {
        "agent": agent_name,
        "task": task,
        "brief": None if emit_brief else None,
    }


def session_finish_task(
    task_id: str,
    *,
    agent_name: str,
    summary: str | None = None,
    error: str | None = None,
    commands_run: list[str] | None = None,
    files_touched: list[str] | None = None,
    subagent_count: int = 0,
    storage_dir: str = "storage",
) -> dict[str, Any]:
    _assert_actor(agent_name)
    _require_bootstrapped_session(agent_name, storage_dir=storage_dir)
    if error:
        return fail_task(
            task_id,
            agent_name=agent_name,
            error=error,
            summary=summary,
            commands_run=commands_run,
            files_touched=files_touched,
            subagent_count=subagent_count,
            storage_dir=storage_dir,
        )
    return complete_task(
        task_id,
        agent_name=agent_name,
        summary=summary,
        commands_run=commands_run,
        files_touched=files_touched,
        subagent_count=subagent_count,
        storage_dir=storage_dir,
    )


def session_shutdown(agent_name: str, *, storage_dir: str = "storage") -> dict[str, Any]:
    _assert_actor(agent_name)
    current = get_agent_session(agent_name, storage_dir=storage_dir) or {}
    session = heartbeat_agent(
        agent_name=agent_name,
        status="offline",
        session_id=str(current.get("session_id") or _default_session_id(agent_name)),
        session_rollback_point_id=current.get("session_rollback_point_id"),
        claimed_task_id=None,
        storage_dir=storage_dir,
    )
    return {"agent": agent_name, "session": session}
