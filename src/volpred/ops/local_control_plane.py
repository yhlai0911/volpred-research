from __future__ import annotations

import json
import os
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import fcntl

from .common import project_path

TASK_SOURCES = {"user", "schedule", "agent"}
TASK_SOURCE_RANK = {"user": 0, "schedule": 1, "agent": 2}
TASK_FAMILIES = {"research", "ops", "content", "code", "review"}
PREFERRED_AGENTS = {"claude", "codex", "auto"}
APPROVAL_MODES = {"auto", "needs_approval"}
RISK_LEVELS = {"safe", "elevated", "destructive"}
TASK_STATUSES = {
    "queued",
    "claimed",
    "running",
    "awaiting_approval",
    "blocked",
    "succeeded",
    "failed",
    "cancelled",
}
TERMINAL_TASK_STATUSES = {"succeeded", "failed", "cancelled"}
AGENT_STATUSES = {"online", "idle", "busy", "offline"}
AGENT_NAMES = {"claude", "codex"}
APPROVAL_DECISIONS = {"approved", "rejected"}
AGENT_STALE_SECONDS = 300


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return str(value)


def _ops_root(storage_dir: str = "storage") -> Path:
    return project_path(storage_dir, "ops")


def _control_plane_paths(storage_dir: str = "storage") -> dict[str, Path]:
    root = _ops_root(storage_dir)
    return {
        "root": root,
        "lock": root / "control_plane.lock",
        "tasks": root / "tasks",
        "agents": root / "agents",
        "executions": root / "executions",
        "approvals": root / "approvals",
        "rollback_points": root / "rollback_points",
    }


def ensure_control_plane_dirs(storage_dir: str = "storage") -> dict[str, Path]:
    paths = _control_plane_paths(storage_dir)
    for key, path in paths.items():
        if key == "lock":
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.touch()
            continue
        path.mkdir(parents=True, exist_ok=True)
    return paths


@contextmanager
def _plane_lock(storage_dir: str = "storage") -> Iterable[None]:
    paths = ensure_control_plane_dirs(storage_dir)
    with paths["lock"].open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(f"{path.suffix}.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    tmp_path.replace(path)


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _task_path(task_id: str, storage_dir: str = "storage") -> Path:
    return _control_plane_paths(storage_dir)["tasks"] / f"{task_id}.json"


def _agent_path(agent_name: str, storage_dir: str = "storage") -> Path:
    return _control_plane_paths(storage_dir)["agents"] / f"{agent_name}.json"


def _approval_path(task_id: str, decision_id: str, storage_dir: str = "storage") -> Path:
    return _control_plane_paths(storage_dir)["approvals"] / task_id / f"{decision_id}.json"


def _execution_path(task_id: str, run_id: str, storage_dir: str = "storage") -> Path:
    return _control_plane_paths(storage_dir)["executions"] / task_id / f"{run_id}.json"


def _list_json_payloads(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    payloads: list[dict[str, Any]] = []
    for file_path in sorted(path.glob("*.json")):
        data = _load_json(file_path)
        if data is not None:
            payloads.append(data)
    return payloads


def _iso_to_ts(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        return datetime.fromisoformat(value).timestamp()
    except ValueError:
        return 0.0


def _normalize_list(raw: list[str] | tuple[str, ...] | None) -> list[str]:
    if not raw:
        return []
    return [str(item) for item in raw if str(item).strip()]


@dataclass
class TaskRecord:
    id: str
    title: str
    description: str
    source: str
    task_family: str
    priority: int
    preferred_agent: str
    fallback_allowed: bool
    approval_mode: str
    risk_level: str
    status: str
    payload: dict[str, Any] = field(default_factory=dict)
    parent_task_id: str | None = None
    created_by: str | None = None
    claimed_by: str | None = None
    claimed_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    approved_by: str | None = None
    approved_at: str | None = None
    rejected_by: str | None = None
    rejected_at: str | None = None
    result_summary: str | None = None
    last_error: str | None = None
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["payload"] = _json_safe(self.payload)
        return payload


@dataclass
class AgentSession:
    agent_name: str
    provider: str
    role_profile: str
    status: str
    capabilities: list[str]
    heartbeat_at: str
    claimed_task_id: str | None = None
    session_id: str | None = None
    subagent_budget: int = 0
    updated_at: str = field(default_factory=_utc_now)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["capabilities"] = _normalize_list(self.capabilities)
        return payload


@dataclass
class ApprovalDecision:
    task_id: str
    decision: str
    actor: str
    reason: str | None
    timestamp: str = field(default_factory=_utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ExecutionReceipt:
    task_id: str
    run_id: str
    agent_name: str
    result_status: str
    summary: str | None
    commands_run: list[str]
    files_touched: list[str]
    subagent_count: int
    timestamp: str = field(default_factory=_utc_now)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "run_id": self.run_id,
            "agent_name": self.agent_name,
            "result_status": self.result_status,
            "summary": self.summary,
            "commands_run": _normalize_list(self.commands_run),
            "files_touched": _normalize_list(self.files_touched),
            "subagent_count": self.subagent_count,
            "timestamp": self.timestamp,
            "error": self.error,
        }


DEFAULT_AGENT_PROFILES: dict[str, dict[str, Any]] = {
    "claude": {
        "provider": "claude_code",
        "role_profile": "research-content-synthesis",
        "capabilities": ["research", "content", "ops", "review"],
        "subagent_budget": 4,
    },
    "codex": {
        "provider": "codex",
        "role_profile": "code-review-control-plane",
        "capabilities": ["code", "review", "ops", "research"],
        "subagent_budget": 4,
    },
}


def _validate_choice(value: str, *, choices: set[str], field_name: str) -> None:
    if value not in choices:
        allowed = ", ".join(sorted(choices))
        raise ValueError(f"{field_name} must be one of: {allowed}")


def _requires_approval(approval_mode: str, risk_level: str) -> bool:
    return approval_mode == "needs_approval" or risk_level == "destructive"


def _load_task(task_id: str, storage_dir: str = "storage") -> dict[str, Any] | None:
    return _load_json(_task_path(task_id, storage_dir=storage_dir))


def _load_agent(agent_name: str, storage_dir: str = "storage") -> dict[str, Any] | None:
    return _load_json(_agent_path(agent_name, storage_dir=storage_dir))


def _build_agent_session(
    *,
    agent_name: str,
    current: dict[str, Any] | None,
    status: str,
    provider: str | None = None,
    claimed_task_id: str | None = None,
    capabilities: list[str] | None = None,
    role_profile: str | None = None,
    session_id: str | None = None,
    subagent_budget: int | None = None,
) -> AgentSession:
    defaults = DEFAULT_AGENT_PROFILES[agent_name]
    now = _utc_now()
    current = current or {}
    return AgentSession(
        agent_name=agent_name,
        provider=provider or str(current.get("provider") or defaults["provider"]),
        role_profile=role_profile or str(current.get("role_profile") or defaults["role_profile"]),
        status=status,
        capabilities=_normalize_list(capabilities or current.get("capabilities") or defaults["capabilities"]),
        heartbeat_at=now,
        claimed_task_id=claimed_task_id if claimed_task_id is not None else current.get("claimed_task_id"),
        session_id=session_id or str(current.get("session_id") or f"{agent_name}:{os.getpid()}"),
        subagent_budget=int(
            subagent_budget
            if subagent_budget is not None
            else current.get("subagent_budget")
            or defaults["subagent_budget"]
        ),
        updated_at=now,
    )


def list_tasks(
    *,
    status: str | None = None,
    source: str | None = None,
    limit: int | None = None,
    storage_dir: str = "storage",
) -> list[dict[str, Any]]:
    paths = ensure_control_plane_dirs(storage_dir)
    tasks = _list_json_payloads(paths["tasks"])
    if status:
        tasks = [task for task in tasks if task.get("status") == status]
    if source:
        tasks = [task for task in tasks if task.get("source") == source]
    tasks.sort(
        key=lambda task: (
            TASK_SOURCE_RANK.get(str(task.get("source")), 99),
            int(task.get("priority") or 100),
            str(task.get("created_at") or ""),
        )
    )
    if limit is not None:
        return tasks[: max(limit, 0)]
    return tasks


def get_task(task_id: str, storage_dir: str = "storage") -> dict[str, Any] | None:
    task = _load_task(task_id, storage_dir=storage_dir)
    if task is None:
        return None
    approval_dir = _control_plane_paths(storage_dir)["approvals"] / task_id
    execution_dir = _control_plane_paths(storage_dir)["executions"] / task_id
    task["approvals"] = _list_json_payloads(approval_dir)
    task["executions"] = _list_json_payloads(execution_dir)
    return task


def list_agent_sessions(storage_dir: str = "storage") -> list[dict[str, Any]]:
    return _list_json_payloads(ensure_control_plane_dirs(storage_dir)["agents"])


def get_agent_session(agent_name: str, storage_dir: str = "storage") -> dict[str, Any] | None:
    return _load_agent(agent_name, storage_dir=storage_dir)


def create_task(
    *,
    title: str,
    description: str,
    source: str = "user",
    task_family: str = "ops",
    priority: int = 100,
    preferred_agent: str = "auto",
    fallback_allowed: bool = False,
    approval_mode: str = "auto",
    risk_level: str = "safe",
    payload: dict[str, Any] | None = None,
    parent_task_id: str | None = None,
    created_by: str | None = None,
    storage_dir: str = "storage",
) -> dict[str, Any]:
    _validate_choice(source, choices=TASK_SOURCES, field_name="source")
    _validate_choice(task_family, choices=TASK_FAMILIES, field_name="task_family")
    _validate_choice(preferred_agent, choices=PREFERRED_AGENTS, field_name="preferred_agent")
    _validate_choice(approval_mode, choices=APPROVAL_MODES, field_name="approval_mode")
    _validate_choice(risk_level, choices=RISK_LEVELS, field_name="risk_level")
    if not title.strip():
        raise ValueError("title must not be empty")

    now = _utc_now()
    task = TaskRecord(
        id=f"task_{uuid.uuid4().hex[:12]}",
        title=title.strip(),
        description=description.strip(),
        source=source,
        task_family=task_family,
        priority=priority,
        preferred_agent=preferred_agent,
        fallback_allowed=fallback_allowed,
        approval_mode=approval_mode,
        risk_level=risk_level,
        status="awaiting_approval" if _requires_approval(approval_mode, risk_level) else "queued",
        payload=_json_safe(payload or {}),
        parent_task_id=parent_task_id,
        created_by=created_by,
        created_at=now,
        updated_at=now,
    )
    with _plane_lock(storage_dir):
        _atomic_write_json(_task_path(task.id, storage_dir=storage_dir), task.to_dict())
    return task.to_dict()


def heartbeat_agent(
    *,
    agent_name: str,
    status: str = "idle",
    provider: str | None = None,
    claimed_task_id: str | None = None,
    capabilities: list[str] | None = None,
    role_profile: str | None = None,
    session_id: str | None = None,
    subagent_budget: int | None = None,
    storage_dir: str = "storage",
) -> dict[str, Any]:
    _validate_choice(agent_name, choices=AGENT_NAMES, field_name="agent_name")
    _validate_choice(status, choices=AGENT_STATUSES, field_name="status")

    with _plane_lock(storage_dir):
        current = _load_agent(agent_name, storage_dir=storage_dir) or {}
        session = _build_agent_session(
            agent_name=agent_name,
            current=current,
            status=status,
            provider=provider,
            claimed_task_id=claimed_task_id,
            capabilities=capabilities,
            role_profile=role_profile,
            session_id=session_id,
            subagent_budget=subagent_budget,
        )
        _atomic_write_json(_agent_path(agent_name, storage_dir=storage_dir), session.to_dict())
    return session.to_dict()


def _agent_is_stale(agent: dict[str, Any] | None) -> bool:
    if not agent:
        return True
    heartbeat_at = _iso_to_ts(str(agent.get("heartbeat_at") or ""))
    if heartbeat_at == 0.0:
        return True
    return (datetime.now(timezone.utc).timestamp() - heartbeat_at) > AGENT_STALE_SECONDS


def _agent_matches_task(
    task: dict[str, Any],
    *,
    agent_name: str,
    sessions: dict[str, dict[str, Any]],
    storage_dir: str,
) -> bool:
    preferred_agent = str(task.get("preferred_agent") or "auto")
    if preferred_agent == "auto" or preferred_agent == agent_name:
        return True
    if not task.get("fallback_allowed"):
        return False
    preferred_session = sessions.get(preferred_agent)
    if preferred_session is None or _agent_is_stale(preferred_session):
        return True
    if preferred_session.get("status") == "offline":
        return True
    claimed_task_id = preferred_session.get("claimed_task_id")
    if claimed_task_id:
        claimed_task = _load_task(str(claimed_task_id), storage_dir=storage_dir)
        if claimed_task and str(claimed_task.get("status")) not in TERMINAL_TASK_STATUSES:
            return True
    return False


def claim_next_task(agent_name: str, storage_dir: str = "storage") -> dict[str, Any] | None:
    _validate_choice(agent_name, choices=AGENT_NAMES, field_name="agent_name")
    with _plane_lock(storage_dir):
        current_session = _load_agent(agent_name, storage_dir=storage_dir)
        if current_session:
            active_task_id = current_session.get("claimed_task_id")
            if active_task_id:
                active_task = _load_task(str(active_task_id), storage_dir=storage_dir)
                if active_task and str(active_task.get("status")) not in TERMINAL_TASK_STATUSES:
                    return None

        sessions = {session["agent_name"]: session for session in list_agent_sessions(storage_dir)}
        tasks = list_tasks(status="queued", storage_dir=storage_dir)
        for task in tasks:
            if not _agent_matches_task(
                task,
                agent_name=agent_name,
                sessions=sessions,
                storage_dir=storage_dir,
            ):
                continue
            now = _utc_now()
            task["status"] = "claimed"
            task["claimed_by"] = agent_name
            task["claimed_at"] = now
            task["updated_at"] = now
            _atomic_write_json(_task_path(str(task["id"]), storage_dir=storage_dir), task)
            session = _build_agent_session(
                agent_name=agent_name,
                current=current_session,
                status="busy",
                claimed_task_id=str(task["id"]),
            )
            _atomic_write_json(_agent_path(agent_name, storage_dir=storage_dir), session.to_dict())
            return task
    return None


def _write_approval(task_id: str, decision: ApprovalDecision, storage_dir: str = "storage") -> None:
    decision_id = f"{decision.timestamp.replace(':', '').replace('-', '')}_{decision.decision}"
    _atomic_write_json(
        _approval_path(task_id, decision_id, storage_dir=storage_dir),
        decision.to_dict(),
    )


def approve_task(task_id: str, *, actor: str, reason: str | None = None, storage_dir: str = "storage") -> dict[str, Any]:
    with _plane_lock(storage_dir):
        task = _load_task(task_id, storage_dir=storage_dir)
        if task is None:
            raise ValueError(f"Unknown task: {task_id}")
        now = _utc_now()
        decision = ApprovalDecision(task_id=task_id, decision="approved", actor=actor, reason=reason, timestamp=now)
        _write_approval(task_id, decision, storage_dir=storage_dir)
        task["status"] = "queued"
        task["approved_by"] = actor
        task["approved_at"] = now
        task["updated_at"] = now
        _atomic_write_json(_task_path(task_id, storage_dir=storage_dir), task)
    return task


def reject_task(task_id: str, *, actor: str, reason: str | None = None, storage_dir: str = "storage") -> dict[str, Any]:
    with _plane_lock(storage_dir):
        task = _load_task(task_id, storage_dir=storage_dir)
        if task is None:
            raise ValueError(f"Unknown task: {task_id}")
        now = _utc_now()
        decision = ApprovalDecision(task_id=task_id, decision="rejected", actor=actor, reason=reason, timestamp=now)
        _write_approval(task_id, decision, storage_dir=storage_dir)
        task["status"] = "cancelled"
        task["rejected_by"] = actor
        task["rejected_at"] = now
        task["updated_at"] = now
        _atomic_write_json(_task_path(task_id, storage_dir=storage_dir), task)
    return task


def _write_execution(task_id: str, receipt: ExecutionReceipt, storage_dir: str = "storage") -> None:
    _atomic_write_json(_execution_path(task_id, receipt.run_id, storage_dir=storage_dir), receipt.to_dict())


def _close_agent_claim(agent_name: str, storage_dir: str = "storage") -> None:
    session = _load_agent(agent_name, storage_dir=storage_dir)
    if session is None:
        return
    session["status"] = "idle"
    session["claimed_task_id"] = None
    session["heartbeat_at"] = _utc_now()
    session["updated_at"] = _utc_now()
    _atomic_write_json(_agent_path(agent_name, storage_dir=storage_dir), session)


def complete_task(
    task_id: str,
    *,
    agent_name: str,
    summary: str | None = None,
    commands_run: list[str] | None = None,
    files_touched: list[str] | None = None,
    subagent_count: int = 0,
    storage_dir: str = "storage",
) -> dict[str, Any]:
    _validate_choice(agent_name, choices=AGENT_NAMES, field_name="agent_name")
    with _plane_lock(storage_dir):
        task = _load_task(task_id, storage_dir=storage_dir)
        if task is None:
            raise ValueError(f"Unknown task: {task_id}")
        now = _utc_now()
        task["status"] = "succeeded"
        task["finished_at"] = now
        task["updated_at"] = now
        task["claimed_by"] = agent_name
        task["result_summary"] = summary
        _atomic_write_json(_task_path(task_id, storage_dir=storage_dir), task)

        receipt = ExecutionReceipt(
            task_id=task_id,
            run_id=f"run_{uuid.uuid4().hex[:12]}",
            agent_name=agent_name,
            result_status="succeeded",
            summary=summary,
            commands_run=_normalize_list(commands_run),
            files_touched=_normalize_list(files_touched),
            subagent_count=subagent_count,
            timestamp=now,
        )
        _write_execution(task_id, receipt, storage_dir=storage_dir)
        _close_agent_claim(agent_name, storage_dir=storage_dir)
    return {"task": task, "receipt": receipt.to_dict()}


def fail_task(
    task_id: str,
    *,
    agent_name: str,
    error: str,
    summary: str | None = None,
    commands_run: list[str] | None = None,
    files_touched: list[str] | None = None,
    subagent_count: int = 0,
    storage_dir: str = "storage",
) -> dict[str, Any]:
    _validate_choice(agent_name, choices=AGENT_NAMES, field_name="agent_name")
    with _plane_lock(storage_dir):
        task = _load_task(task_id, storage_dir=storage_dir)
        if task is None:
            raise ValueError(f"Unknown task: {task_id}")
        now = _utc_now()
        task["status"] = "failed"
        task["finished_at"] = now
        task["updated_at"] = now
        task["claimed_by"] = agent_name
        task["result_summary"] = summary
        task["last_error"] = error
        _atomic_write_json(_task_path(task_id, storage_dir=storage_dir), task)

        receipt = ExecutionReceipt(
            task_id=task_id,
            run_id=f"run_{uuid.uuid4().hex[:12]}",
            agent_name=agent_name,
            result_status="failed",
            summary=summary,
            commands_run=_normalize_list(commands_run),
            files_touched=_normalize_list(files_touched),
            subagent_count=subagent_count,
            timestamp=now,
            error=error,
        )
        _write_execution(task_id, receipt, storage_dir=storage_dir)
        _close_agent_claim(agent_name, storage_dir=storage_dir)
    return {"task": task, "receipt": receipt.to_dict()}


def build_control_plane_snapshot(storage_dir: str = "storage") -> dict[str, Any]:
    tasks = list_tasks(storage_dir=storage_dir)
    agents = list_agent_sessions(storage_dir=storage_dir)
    counts: dict[str, int] = {}
    for task in tasks:
        status = str(task.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    return {
        "task_counts": counts,
        "agents": agents,
        "pending_user_tasks": len(
            [task for task in tasks if task.get("source") == "user" and task.get("status") == "queued"]
        ),
        "discovery_allowed": not any(
            task.get("source") == "user" and task.get("status") == "queued" for task in tasks
        ),
    }
