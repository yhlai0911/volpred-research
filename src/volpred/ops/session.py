from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .common import project_path
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

LEGACY_AGENT_SPEC_GUIDE = project_path("agent-specs", "guide.md")
CLAUDE_AGENT_DELEGATION_GUIDE = project_path(".claude", "rules", "agent-delegation.md")
INLINE_MINIMAL_BOOTSTRAP_GUIDE = """# Volpred Session Bootstrap

- Use `uv run volpred ops next-task --session-key <session-key> --emit-brief` to fetch work.
- Complete claimed work with `uv run volpred ops finish-task <task_id> --session-key <session-key> --summary "..."`.
- Do not edit `storage/ops/` records manually; use the ops CLI for claim, finish, fail, and rollback flows.
- Preserve lag / no-lookahead discipline in any strategy or experiment code.
- If local guide files are unavailable, continue with the canonical CLI workflow above.
"""
_GUIDE_PREVIEW_CHARS = 160


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


def _resolve_guide_candidate(raw_path: str | None) -> Path | None:
    if raw_path is None:
        return None
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = project_path(str(candidate))
    if candidate.is_dir():
        return candidate / "guide.md"
    if candidate.name != "guide.md" and candidate.suffix == "":
        return candidate / "guide.md"
    return candidate


def _guide_preview(text: str) -> str:
    compact = " ".join(line.strip() for line in text.splitlines() if line.strip())
    if len(compact) <= _GUIDE_PREVIEW_CHARS:
        return compact
    return compact[: _GUIDE_PREVIEW_CHARS - 3] + "..."


def _load_bootstrap_guide(
    *,
    agent_spec_path: str | None = None,
    no_guide: bool = False,
) -> dict[str, Any]:
    if no_guide:
        return {
            "loaded": False,
            "skipped": True,
            "source": "skipped",
            "path": None,
            "chars": 0,
            "lines": 0,
            "preview": None,
            "issues": [],
        }

    issues: list[str] = []
    explicit_legacy = _resolve_guide_candidate(agent_spec_path)
    candidate_paths: list[tuple[str, Path]] = []
    if explicit_legacy is not None:
        candidate_paths.append(("legacy_agent_spec", explicit_legacy))
    if explicit_legacy != LEGACY_AGENT_SPEC_GUIDE:
        candidate_paths.append(("legacy_agent_spec", LEGACY_AGENT_SPEC_GUIDE))
    candidate_paths.append(("claude_rule", CLAUDE_AGENT_DELEGATION_GUIDE))

    seen_paths: set[Path] = set()
    for source, candidate in candidate_paths:
        if candidate in seen_paths:
            continue
        seen_paths.add(candidate)
        if not candidate.exists():
            continue
        try:
            guide_text = candidate.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            issues.append(f"{candidate}: {exc}")
            continue
        return {
            "loaded": True,
            "skipped": False,
            "source": source,
            "path": str(candidate),
            "chars": len(guide_text),
            "lines": len(guide_text.splitlines()),
            "preview": _guide_preview(guide_text),
            "issues": issues,
        }

    return {
        "loaded": True,
        "skipped": False,
        "source": "inline_default",
        "path": None,
        "chars": len(INLINE_MINIMAL_BOOTSTRAP_GUIDE),
        "lines": len(INLINE_MINIMAL_BOOTSTRAP_GUIDE.splitlines()),
        "preview": _guide_preview(INLINE_MINIMAL_BOOTSTRAP_GUIDE),
        "issues": issues,
    }


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
    agent_spec_path: str | None = None,
    no_guide: bool = False,
) -> dict[str, Any]:
    resolved_key, resolved_agent, resolved_role = _resolve_session(
        agent_name=agent_name, session_key=session_key, role=role
    )
    _assert_actor(resolved_agent)
    rollback = create_rollback_point(
        point_id=rollback_point_id or _bootstrap_point_id(resolved_key),
        storage_dir=storage_dir,
    )
    guide = _load_bootstrap_guide(
        agent_spec_path=agent_spec_path,
        no_guide=no_guide,
    )
    legacy_guide_path = _resolve_guide_candidate(agent_spec_path) or LEGACY_AGENT_SPEC_GUIDE
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
        "guide": guide,
        "agent_spec": {
            "optional": True,
            "checked": False,
            "clean": True,
            "issues": [],
            "path": str(legacy_guide_path),
            "exists": legacy_guide_path.exists(),
        },
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
