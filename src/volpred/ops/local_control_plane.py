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
TASK_FAMILIES = {"research", "ops", "content", "code", "review", "member", "strategy"}
PREFERRED_AGENTS = {"claude", "codex", "auto"}
APPROVAL_MODES = {"auto", "needs_approval"}
RISK_LEVELS = {"safe", "elevated", "destructive"}
PUBLIC_EFFECTS = {"none", "draft_only", "published", "member_visible", "prod_runtime"}
BRIEF_STATUSES = {"pending", "ready", "stale", "needs_manual_review"}
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
ACTIVE_EXPERIMENT_STATUSES = {"claimed", "running", "awaiting_approval", "blocked"}
AGENT_STATUSES = {"online", "idle", "busy", "offline"}
AGENT_NAMES = {"claude", "codex"}
AGENT_ROLES = {"supervisor", "worker"}
SESSION_KEYS = {"claude-supervisor", "claude-worker", "codex-worker"}
SESSION_KEY_SPEC: dict[str, tuple[str, str]] = {
    "claude-supervisor": ("claude", "supervisor"),
    "claude-worker": ("claude", "worker"),
    "codex-worker": ("codex", "worker"),
}
APPROVAL_DECISIONS = {"approved", "rejected"}
AGENT_STALE_SECONDS = 300

AUTO_PREFERRED_AGENT = {
    "research": "claude",
    "content": "claude",
    "member": "claude",
    "code": "codex",
    "review": "codex",
    "ops": "codex",
    "strategy": "codex",
}

AUTO_PREFERRED_SESSION_KEY = {
    "claude": "claude-worker",
    "codex": "codex-worker",
}


def resolve_session_key(
    *,
    session_key: str | None = None,
    agent_name: str | None = None,
    role: str | None = None,
) -> tuple[str, str, str]:
    """Resolve (session_key, agent_name, role) from any combination of inputs.

    Accepts the canonical session_key (e.g. "claude-supervisor") as the
    highest-priority input, falling back to agent_name+role, and finally to
    the worker default for the given agent_name. Raises ValueError if the
    combination is inconsistent or incomplete.
    """
    if session_key is not None:
        if session_key not in SESSION_KEY_SPEC:
            allowed = ", ".join(sorted(SESSION_KEY_SPEC))
            raise ValueError(f"session_key must be one of: {allowed}")
        spec_agent, spec_role = SESSION_KEY_SPEC[session_key]
        if agent_name is not None and agent_name != spec_agent:
            raise ValueError(
                f"agent_name={agent_name!r} conflicts with session_key={session_key!r} (expects {spec_agent!r})"
            )
        if role is not None and role != spec_role:
            raise ValueError(
                f"role={role!r} conflicts with session_key={session_key!r} (expects {spec_role!r})"
            )
        return session_key, spec_agent, spec_role
    if agent_name is None:
        raise ValueError("either session_key or agent_name must be provided")
    if agent_name not in AGENT_NAMES:
        allowed = ", ".join(sorted(AGENT_NAMES))
        raise ValueError(f"agent_name must be one of: {allowed}")
    resolved_role = role if role is not None else "worker"
    if resolved_role not in AGENT_ROLES:
        allowed = ", ".join(sorted(AGENT_ROLES))
        raise ValueError(f"role must be one of: {allowed}")
    candidate_key = f"{agent_name}-{resolved_role}"
    if candidate_key not in SESSION_KEY_SPEC:
        raise ValueError(
            f"agent_name={agent_name!r} + role={resolved_role!r} is not a supported session"
        )
    return candidate_key, agent_name, resolved_role

SCHEDULE_GOVERNANCE_AREA = "schedule"


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


def _agent_path(session_key: str, storage_dir: str = "storage") -> Path:
    return _control_plane_paths(storage_dir)["agents"] / f"{session_key}.json"


def _legacy_agent_path(agent_name: str, storage_dir: str = "storage") -> Path:
    """Legacy filename keyed on agent_name (pre session-key schema)."""
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
    session_id: str | None = None
    rollback_point_id: str | None = None
    public_effect: str | None = None
    brief_status: str | None = None
    brief_payload: dict[str, Any] | None = None
    claimed_by: str | None = None
    claimed_by_session_key: str | None = None
    claimed_by_role: str | None = None
    claimed_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    approved_by: str | None = None
    approved_at: str | None = None
    rejected_by: str | None = None
    rejected_at: str | None = None
    result_summary: str | None = None
    signal_payload: dict[str, Any] | None = None
    curated_by: str | None = None
    curated_at: str | None = None
    curated_promoted: list[str] = field(default_factory=list)
    curated_notes: str | None = None
    last_error: str | None = None
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["payload"] = _json_safe(self.payload)
        payload["brief_payload"] = _json_safe(self.brief_payload)
        payload["signal_payload"] = _json_safe(self.signal_payload)
        payload["curated_promoted"] = _normalize_list(self.curated_promoted)
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
    session_rollback_point_id: str | None = None
    subagent_budget: int = 0
    role: str = "worker"
    session_key: str | None = None
    terminal_label: str | None = None
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
    session_id: str | None = None
    rollback_point_id: str | None = None
    session_key: str | None = None
    role: str | None = None
    signal_payload: dict[str, Any] | None = None
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
            "session_id": self.session_id,
            "rollback_point_id": self.rollback_point_id,
            "session_key": self.session_key,
            "role": self.role,
            "signal_payload": _json_safe(self.signal_payload),
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


def _governance_area(payload: dict[str, Any] | None) -> str | None:
    if not isinstance(payload, dict):
        return None
    raw = payload.get("governance_area")
    if raw is None:
        return None
    value = str(raw).strip()
    return value or None


def _is_schedule_governance_payload(payload: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    if _governance_area(payload) == SCHEDULE_GOVERNANCE_AREA:
        return True
    return isinstance(payload.get("schedule_proposal"), dict)


def task_governance_area(task: dict[str, Any] | None) -> str | None:
    if not isinstance(task, dict):
        return None
    payload = task.get("payload")
    if isinstance(payload, dict):
        area = _governance_area(payload)
        if area:
            return area
        if isinstance(payload.get("schedule_proposal"), dict):
            return SCHEDULE_GOVERNANCE_AREA
        return None
    return _governance_area(task)


def is_schedule_governance_task(task: dict[str, Any] | None) -> bool:
    return task_governance_area(task) == SCHEDULE_GOVERNANCE_AREA


def _resolve_preferred_agent(task_family: str, preferred_agent: str, *, payload: dict[str, Any] | None = None) -> str:
    if _is_schedule_governance_payload(payload):
        return "claude"
    if preferred_agent != "auto":
        return preferred_agent
    return AUTO_PREFERRED_AGENT.get(task_family, "auto")


def _requires_approval(approval_mode: str, risk_level: str) -> bool:
    return approval_mode == "needs_approval" or risk_level == "destructive"


def _load_task(task_id: str, storage_dir: str = "storage") -> dict[str, Any] | None:
    return _load_json(_task_path(task_id, storage_dir=storage_dir))


def _load_agent(session_key: str, storage_dir: str = "storage") -> dict[str, Any] | None:
    """Load an agent session by session_key, with fallbacks.

    Historically, agents were stored at `storage/ops/agents/{agent_name}.json`
    (claude.json / codex.json). After the session-identity refactor, canonical
    filenames are `storage/ops/agents/{session_key}.json` (e.g.
    claude-worker.json). This function accepts either form:

    1. Canonical session_key ("claude-worker") → direct lookup.
    2. Plain agent_name ("claude") → try default worker session_key
       ("claude-worker"), then legacy filename ("claude.json").
    """
    payload = _load_json(_agent_path(session_key, storage_dir=storage_dir))
    if payload is not None:
        return payload
    if session_key in AGENT_NAMES:
        default_key = AUTO_PREFERRED_SESSION_KEY.get(session_key)
        if default_key:
            via_default = _load_json(_agent_path(default_key, storage_dir=storage_dir))
            if via_default is not None:
                return via_default
        legacy = _load_json(_legacy_agent_path(session_key, storage_dir=storage_dir))
        return legacy
    return None


def _load_agent_for_agent_name(agent_name: str, storage_dir: str = "storage") -> dict[str, Any] | None:
    """Find the worker session for a given agent_name.

    Used by scheduler/fallback logic that operates at the agent_name level
    (does not care about supervisor vs worker roles).
    """
    default_key = AUTO_PREFERRED_SESSION_KEY.get(agent_name)
    if default_key:
        payload = _load_json(_agent_path(default_key, storage_dir=storage_dir))
        if payload is not None:
            return payload
    # Legacy fallback.
    return _load_json(_legacy_agent_path(agent_name, storage_dir=storage_dir))


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
    session_rollback_point_id: str | None = None,
    subagent_budget: int | None = None,
    role: str | None = None,
    session_key: str | None = None,
    terminal_label: str | None = None,
) -> AgentSession:
    defaults = DEFAULT_AGENT_PROFILES[agent_name]
    now = _utc_now()
    current = current or {}
    resolved_role = role if role is not None else str(current.get("role") or "worker")
    resolved_session_key = (
        session_key
        if session_key is not None
        else str(current.get("session_key") or f"{agent_name}-{resolved_role}")
    )
    resolved_terminal = (
        terminal_label if terminal_label is not None else current.get("terminal_label")
    )
    return AgentSession(
        agent_name=agent_name,
        provider=provider or str(current.get("provider") or defaults["provider"]),
        role_profile=role_profile or str(current.get("role_profile") or defaults["role_profile"]),
        status=status,
        capabilities=_normalize_list(capabilities or current.get("capabilities") or defaults["capabilities"]),
        heartbeat_at=now,
        claimed_task_id=claimed_task_id if claimed_task_id is not None else current.get("claimed_task_id"),
        session_id=session_id or str(current.get("session_id") or f"{resolved_session_key}:{os.getpid()}"),
        session_rollback_point_id=(
            session_rollback_point_id
            if session_rollback_point_id is not None
            else current.get("session_rollback_point_id")
        ),
        subagent_budget=int(
            subagent_budget
            if subagent_budget is not None
            else current.get("subagent_budget")
            or defaults["subagent_budget"]
        ),
        role=resolved_role,
        session_key=resolved_session_key,
        terminal_label=resolved_terminal,
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
    sessions = _list_json_payloads(ensure_control_plane_dirs(storage_dir)["agents"])
    # Ensure each session advertises a session_key / role for downstream
    # consumers (CLI display, scheduler). Legacy files (pre-refactor) may lack
    # these fields.
    for session in sessions:
        if not session.get("session_key"):
            agent_name = str(session.get("agent_name") or "")
            inferred_role = str(session.get("role") or "worker")
            if agent_name in AGENT_NAMES:
                session["session_key"] = f"{agent_name}-{inferred_role}"
            else:
                session["session_key"] = agent_name
        if not session.get("role"):
            session["role"] = "worker"
    return sessions


def get_agent_session(
    identifier: str, storage_dir: str = "storage"
) -> dict[str, Any] | None:
    """Fetch an agent session by session_key or (legacy) agent_name."""
    return _load_agent(identifier, storage_dir=storage_dir)


def get_agent_session_by_session_key(
    session_key: str, storage_dir: str = "storage"
) -> dict[str, Any] | None:
    return _load_json(_agent_path(session_key, storage_dir=storage_dir))


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
    public_effect: str | None = None,
    payload: dict[str, Any] | None = None,
    parent_task_id: str | None = None,
    created_by: str | None = None,
    session_id: str | None = None,
    rollback_point_id: str | None = None,
    brief_status: str | None = "pending",
    brief_payload: dict[str, Any] | None = None,
    storage_dir: str = "storage",
) -> dict[str, Any]:
    _validate_choice(source, choices=TASK_SOURCES, field_name="source")
    _validate_choice(task_family, choices=TASK_FAMILIES, field_name="task_family")
    _validate_choice(preferred_agent, choices=PREFERRED_AGENTS, field_name="preferred_agent")
    _validate_choice(approval_mode, choices=APPROVAL_MODES, field_name="approval_mode")
    _validate_choice(risk_level, choices=RISK_LEVELS, field_name="risk_level")
    if public_effect is not None:
        _validate_choice(public_effect, choices=PUBLIC_EFFECTS, field_name="public_effect")
    if brief_status is not None:
        _validate_choice(brief_status, choices=BRIEF_STATUSES, field_name="brief_status")
    if not title.strip():
        raise ValueError("title must not be empty")

    now = _utc_now()
    payload_obj = _json_safe(payload or {})
    if not isinstance(payload_obj, dict):
        raise ValueError("payload must decode to an object")
    if "schedule_proposal" in payload_obj and not isinstance(payload_obj.get("schedule_proposal"), dict):
        raise ValueError("payload.schedule_proposal must be an object when provided")

    resolved_preferred_agent = _resolve_preferred_agent(task_family, preferred_agent, payload=payload_obj)
    task = TaskRecord(
        id=f"task_{uuid.uuid4().hex[:12]}",
        title=title.strip(),
        description=description.strip(),
        source=source,
        task_family=task_family,
        priority=priority,
        preferred_agent=resolved_preferred_agent,
        fallback_allowed=fallback_allowed,
        approval_mode=approval_mode,
        risk_level=risk_level,
        status="awaiting_approval" if _requires_approval(approval_mode, risk_level) else "queued",
        payload=payload_obj,
        parent_task_id=parent_task_id,
        created_by=created_by,
        session_id=session_id,
        rollback_point_id=rollback_point_id,
        public_effect=public_effect or "none",
        brief_status=brief_status,
        brief_payload=_json_safe(brief_payload),
        created_at=now,
        updated_at=now,
    )
    with _plane_lock(storage_dir):
        _atomic_write_json(_task_path(task.id, storage_dir=storage_dir), task.to_dict())
    return task.to_dict()


def heartbeat_agent(
    *,
    agent_name: str | None = None,
    session_key: str | None = None,
    role: str | None = None,
    terminal_label: str | None = None,
    status: str = "idle",
    provider: str | None = None,
    claimed_task_id: str | None = None,
    capabilities: list[str] | None = None,
    role_profile: str | None = None,
    session_id: str | None = None,
    session_rollback_point_id: str | None = None,
    subagent_budget: int | None = None,
    storage_dir: str = "storage",
) -> dict[str, Any]:
    resolved_key, resolved_agent, resolved_role = resolve_session_key(
        session_key=session_key, agent_name=agent_name, role=role
    )
    _validate_choice(status, choices=AGENT_STATUSES, field_name="status")

    with _plane_lock(storage_dir):
        current = _load_json(_agent_path(resolved_key, storage_dir=storage_dir))
        if current is None and resolved_key in (f"{resolved_agent}-worker",):
            # Adopt legacy record if present so heartbeats don't lose history.
            legacy = _load_json(_legacy_agent_path(resolved_agent, storage_dir=storage_dir))
            if legacy is not None:
                current = legacy
        session = _build_agent_session(
            agent_name=resolved_agent,
            current=current,
            status=status,
            provider=provider,
            claimed_task_id=claimed_task_id,
            capabilities=capabilities,
            role_profile=role_profile,
            session_id=session_id,
            session_rollback_point_id=session_rollback_point_id,
            subagent_budget=subagent_budget,
            role=resolved_role,
            session_key=resolved_key,
            terminal_label=terminal_label,
        )
        _atomic_write_json(_agent_path(resolved_key, storage_dir=storage_dir), session.to_dict())
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


def _experiment_id_for_task(task: dict[str, Any]) -> str | None:
    payload = task.get("payload")
    if not isinstance(payload, dict):
        return None
    experiment_id = payload.get("experiment_id")
    if experiment_id is None:
        return None
    value = str(experiment_id).strip()
    return value or None


def _has_experiment_conflict(task: dict[str, Any], *, storage_dir: str) -> bool:
    experiment_id = _experiment_id_for_task(task)
    if not experiment_id:
        return False
    for other_task in list_tasks(storage_dir=storage_dir):
        if str(other_task.get("id")) == str(task.get("id")):
            continue
        if _experiment_id_for_task(other_task) != experiment_id:
            continue
        if str(other_task.get("status")) in ACTIVE_EXPERIMENT_STATUSES:
            return True
    return False


def _reclaim_stale_tasks(storage_dir: str) -> list[str]:
    """Release tasks whose claimed_by agent has gone stale.

    Must be called inside the plane lock. Returns list of reclaimed task IDs.
    """
    from .writer_log import append_writer_log

    reclaimed: list[str] = []
    # Check both claimed and running — an agent that crashed mid-run leaves
    # running tasks stuck with a stale heartbeat just as surely.
    for status in ("claimed", "running"):
        for task in list_tasks(status=status, storage_dir=storage_dir):
            claimed_by = task.get("claimed_by")
            if not claimed_by:
                continue
            claimed_by_session_key = str(
                task.get("claimed_by_session_key") or ""
            ) or None
            session_identifier = claimed_by_session_key or str(claimed_by)
            session = _load_agent(session_identifier, storage_dir=storage_dir)
            if not _agent_is_stale(session):
                continue
            now = _utc_now()
            prior_status = task.get("status")
            task["status"] = "queued"
            task["claimed_by"] = None
            task["claimed_by_session_key"] = None
            task["claimed_by_role"] = None
            task["claimed_at"] = None
            task["updated_at"] = now
            task["last_error"] = f"reclaimed_from_stale_{session_identifier}_at_{now}"
            _atomic_write_json(_task_path(str(task["id"]), storage_dir=storage_dir), task)
            # Also reset agent's claimed_task_id so the stale session doesn't still "own" it
            if session is not None:
                session["claimed_task_id"] = None
                session["updated_at"] = now
                reset_key = session.get("session_key") or session_identifier
                _atomic_write_json(
                    _agent_path(str(reset_key), storage_dir=storage_dir), session
                )
            reclaimed.append(str(task["id"]))
            append_writer_log(
                subsystem="control_plane",
                target=f"ops/tasks/{task['id']}",
                record_id=str(task["id"]),
                result=f"reclaimed_from_{prior_status}_{session_identifier}",
                actor="system",
                storage_dir=storage_dir,
            )
    return reclaimed


def claim_next_task(
    agent_name: str | None = None,
    storage_dir: str = "storage",
    skip_task_ids: set[str] | None = None,
    *,
    session_key: str | None = None,
    role: str | None = None,
) -> dict[str, Any] | None:
    resolved_key, resolved_agent, resolved_role = resolve_session_key(
        session_key=session_key, agent_name=agent_name, role=role
    )
    skipped = {str(task_id) for task_id in (skip_task_ids or set())}
    with _plane_lock(storage_dir):
        # Reclaim any tasks held by stale agents before matching; this also
        # prevents the current agent being blocked by its own stale previous
        # claim if its session clock expired.
        _reclaim_stale_tasks(storage_dir)

        current_session = _load_json(_agent_path(resolved_key, storage_dir=storage_dir))
        if current_session is None:
            # Legacy fallback so agents that haven't re-bootstrapped yet still
            # look up their own prior heartbeat.
            current_session = _load_json(
                _legacy_agent_path(resolved_agent, storage_dir=storage_dir)
            )
        if current_session:
            active_task_id = current_session.get("claimed_task_id")
            if active_task_id:
                active_task = _load_task(str(active_task_id), storage_dir=storage_dir)
                if active_task and str(active_task.get("status")) not in TERMINAL_TASK_STATUSES:
                    return None

        # Build agent→session map, preferring worker sessions so fallback logic
        # doesn't get confused by an idle supervisor while the worker is busy.
        sessions: dict[str, dict[str, Any]] = {}
        for session in list_agent_sessions(storage_dir):
            name = str(session.get("agent_name") or "")
            if not name:
                continue
            existing = sessions.get(name)
            if existing is None:
                sessions[name] = session
                continue
            if (
                str(session.get("role") or "worker") == "worker"
                and str(existing.get("role") or "worker") != "worker"
            ):
                sessions[name] = session
        tasks = list_tasks(status="queued", storage_dir=storage_dir)
        for task in tasks:
            if str(task.get("id") or "") in skipped:
                continue
            if not _agent_matches_task(
                task,
                agent_name=resolved_agent,
                sessions=sessions,
                storage_dir=storage_dir,
            ):
                continue
            if _has_experiment_conflict(task, storage_dir=storage_dir):
                continue
            now = _utc_now()
            task["status"] = "claimed"
            task["claimed_by"] = resolved_agent
            task["claimed_by_session_key"] = resolved_key
            task["claimed_by_role"] = resolved_role
            task["claimed_at"] = now
            if current_session and current_session.get("session_id"):
                task["session_id"] = current_session.get("session_id")
            if task.get("rollback_point_id") is None and current_session and current_session.get("session_rollback_point_id"):
                task["rollback_point_id"] = current_session.get("session_rollback_point_id")
            task["updated_at"] = now
            _atomic_write_json(_task_path(str(task["id"]), storage_dir=storage_dir), task)
            session = _build_agent_session(
                agent_name=resolved_agent,
                current=current_session,
                status="busy",
                claimed_task_id=str(task["id"]),
                role=resolved_role,
                session_key=resolved_key,
            )
            _atomic_write_json(
                _agent_path(resolved_key, storage_dir=storage_dir), session.to_dict()
            )
            return task
    return None


def admin_override_claim(
    task_id: str,
    *,
    agent_name: str | None = None,
    session_key: str | None = None,
    role: str | None = None,
    actor: str,
    storage_dir: str = "storage",
) -> dict[str, Any]:
    """Admin-side override: forcibly assign a specific queued task to an agent.

    Normal claim flow is agent-pull (claim_next_task). This is for the Ops
    console to explicitly assign on behalf of an operator, e.g. to recover a
    stuck task or pin a task to a specific agent.
    """
    from .writer_log import append_writer_log

    resolved_key, resolved_agent, resolved_role = resolve_session_key(
        session_key=session_key, agent_name=agent_name, role=role
    )
    with _plane_lock(storage_dir):
        task = _load_task(task_id, storage_dir=storage_dir)
        if task is None:
            raise ValueError(f"Unknown task: {task_id}")
        current_status = str(task.get("status"))
        if current_status in TERMINAL_TASK_STATUSES:
            raise ValueError(f"Cannot claim a {current_status} task")
        now = _utc_now()
        task["status"] = "claimed"
        task["claimed_by"] = resolved_agent
        task["claimed_by_session_key"] = resolved_key
        task["claimed_by_role"] = resolved_role
        task["claimed_at"] = now
        task["updated_at"] = now
        _atomic_write_json(_task_path(task_id, storage_dir=storage_dir), task)
        current_session = _load_json(_agent_path(resolved_key, storage_dir=storage_dir))
        session = _build_agent_session(
            agent_name=resolved_agent,
            current=current_session,
            status="busy",
            claimed_task_id=task_id,
            role=resolved_role,
            session_key=resolved_key,
        )
        _atomic_write_json(
            _agent_path(resolved_key, storage_dir=storage_dir), session.to_dict()
        )
        append_writer_log(
            subsystem="control_plane",
            target=f"ops/tasks/{task_id}",
            record_id=task_id,
            result=f"admin_override_claim_by_{resolved_key}",
            actor=actor,
            storage_dir=storage_dir,
        )
    return task


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


def _close_agent_claim(
    identifier: str | None = None,
    *,
    session_key: str | None = None,
    storage_dir: str = "storage",
) -> None:
    """Close an active claim for the given agent or session.

    Accepts either a canonical ``session_key`` (preferred) or a legacy
    ``identifier`` that may be an agent_name ("claude"/"codex") or a
    session_key. Agents names resolve to the default worker session_key.
    """
    key = session_key if session_key is not None else identifier
    if not key:
        return
    key = str(key)
    target_session_key = key
    if key in AGENT_NAMES:
        target_session_key = AUTO_PREFERRED_SESSION_KEY.get(key, key)
    session = _load_json(_agent_path(target_session_key, storage_dir=storage_dir))
    target_path = _agent_path(target_session_key, storage_dir=storage_dir)
    if session is None and key in AGENT_NAMES:
        legacy_path = _legacy_agent_path(key, storage_dir=storage_dir)
        session = _load_json(legacy_path)
        if session is None:
            return
        target_path = legacy_path
    if session is None:
        return
    session["status"] = "idle"
    session["claimed_task_id"] = None
    session["heartbeat_at"] = _utc_now()
    session["updated_at"] = _utc_now()
    _atomic_write_json(target_path, session)


def requeue_task(task_id: str, *, actor: str, reason: str, storage_dir: str = "storage") -> dict[str, Any]:
    with _plane_lock(storage_dir):
        task = _load_task(task_id, storage_dir=storage_dir)
        if task is None:
            raise ValueError(f"Unknown task: {task_id}")
        if str(task.get("status")) != "blocked":
            raise ValueError(f"Only blocked tasks can be requeued: {task_id}")
        now = _utc_now()
        task["status"] = "queued"
        task["claimed_by"] = None
        task["claimed_at"] = None
        task["updated_at"] = now
        _atomic_write_json(_task_path(task_id, storage_dir=storage_dir), task)
        receipt = ExecutionReceipt(
            task_id=task_id,
            run_id=f"run_{uuid.uuid4().hex[:12]}",
            agent_name=actor,
            result_status="requeued",
            summary=reason,
            commands_run=[],
            files_touched=[],
            subagent_count=0,
            session_id=task.get("session_id"),
            rollback_point_id=task.get("rollback_point_id"),
            timestamp=now,
        )
        _write_execution(task_id, receipt, storage_dir=storage_dir)
    return {"task": task, "receipt": receipt.to_dict()}


def complete_task(
    task_id: str,
    *,
    agent_name: str | None = None,
    session_key: str | None = None,
    role: str | None = None,
    summary: str | None = None,
    signal_payload: dict[str, Any] | None = None,
    commands_run: list[str] | None = None,
    files_touched: list[str] | None = None,
    subagent_count: int = 0,
    storage_dir: str = "storage",
) -> dict[str, Any]:
    resolved_key, resolved_agent, resolved_role = resolve_session_key(
        session_key=session_key, agent_name=agent_name, role=role
    )
    with _plane_lock(storage_dir):
        task = _load_task(task_id, storage_dir=storage_dir)
        if task is None:
            raise ValueError(f"Unknown task: {task_id}")
        now = _utc_now()
        task["status"] = "succeeded"
        task["finished_at"] = now
        task["updated_at"] = now
        task["claimed_by"] = resolved_agent
        task["claimed_by_session_key"] = resolved_key
        task["claimed_by_role"] = resolved_role
        task["result_summary"] = summary
        if signal_payload is not None:
            task["signal_payload"] = _json_safe(signal_payload)
        _atomic_write_json(_task_path(task_id, storage_dir=storage_dir), task)

        receipt = ExecutionReceipt(
            task_id=task_id,
            run_id=f"run_{uuid.uuid4().hex[:12]}",
            agent_name=resolved_agent,
            result_status="succeeded",
            summary=summary,
            commands_run=_normalize_list(commands_run),
            files_touched=_normalize_list(files_touched),
            subagent_count=subagent_count,
            session_id=task.get("session_id"),
            rollback_point_id=task.get("rollback_point_id"),
            session_key=resolved_key,
            role=resolved_role,
            signal_payload=signal_payload,
            timestamp=now,
        )
        _write_execution(task_id, receipt, storage_dir=storage_dir)
        _close_agent_claim(session_key=resolved_key, storage_dir=storage_dir)
    return {"task": task, "receipt": receipt.to_dict()}


def fail_task(
    task_id: str,
    *,
    agent_name: str | None = None,
    session_key: str | None = None,
    role: str | None = None,
    error: str,
    summary: str | None = None,
    signal_payload: dict[str, Any] | None = None,
    commands_run: list[str] | None = None,
    files_touched: list[str] | None = None,
    subagent_count: int = 0,
    storage_dir: str = "storage",
) -> dict[str, Any]:
    resolved_key, resolved_agent, resolved_role = resolve_session_key(
        session_key=session_key, agent_name=agent_name, role=role
    )
    with _plane_lock(storage_dir):
        task = _load_task(task_id, storage_dir=storage_dir)
        if task is None:
            raise ValueError(f"Unknown task: {task_id}")
        now = _utc_now()
        task["status"] = "failed"
        task["finished_at"] = now
        task["updated_at"] = now
        task["claimed_by"] = resolved_agent
        task["claimed_by_session_key"] = resolved_key
        task["claimed_by_role"] = resolved_role
        task["result_summary"] = summary
        task["last_error"] = error
        if signal_payload is not None:
            task["signal_payload"] = _json_safe(signal_payload)
        _atomic_write_json(_task_path(task_id, storage_dir=storage_dir), task)

        receipt = ExecutionReceipt(
            task_id=task_id,
            run_id=f"run_{uuid.uuid4().hex[:12]}",
            agent_name=resolved_agent,
            result_status="failed",
            summary=summary,
            commands_run=_normalize_list(commands_run),
            files_touched=_normalize_list(files_touched),
            subagent_count=subagent_count,
            session_id=task.get("session_id"),
            rollback_point_id=task.get("rollback_point_id"),
            session_key=resolved_key,
            role=resolved_role,
            signal_payload=signal_payload,
            timestamp=now,
            error=error,
        )
        _write_execution(task_id, receipt, storage_dir=storage_dir)
        _close_agent_claim(session_key=resolved_key, storage_dir=storage_dir)
    return {"task": task, "receipt": receipt.to_dict()}


def list_pending_curations(
    *, limit: int | None = None, storage_dir: str = "storage"
) -> list[dict[str, Any]]:
    """List succeeded tasks that haven't been curated yet (Phase B)."""
    tasks = list_tasks(status="succeeded", storage_dir=storage_dir)
    pending = [task for task in tasks if not task.get("curated_at")]
    pending.sort(key=lambda task: str(task.get("finished_at") or task.get("updated_at") or ""))
    if limit is not None:
        return pending[: max(limit, 0)]
    return pending


def curate_task(
    task_id: str,
    *,
    actor: str,
    promoted: list[str] | None = None,
    notes: str | None = None,
    storage_dir: str = "storage",
) -> dict[str, Any]:
    """Mark a succeeded task as curated by the supervisor.

    `promoted` enumerates canonical destinations where signal payloads were
    promoted (e.g. ["knowledge.json", "research_program.md"]). `notes` is free
    text for the supervisor's judgement trail.
    """
    from .writer_log import append_writer_log

    with _plane_lock(storage_dir):
        task = _load_task(task_id, storage_dir=storage_dir)
        if task is None:
            raise ValueError(f"Unknown task: {task_id}")
        status = str(task.get("status"))
        if status != "succeeded":
            raise ValueError(
                f"Only succeeded tasks can be curated (current status: {status})"
            )
        now = _utc_now()
        task["curated_by"] = actor
        task["curated_at"] = now
        task["curated_promoted"] = _normalize_list(promoted)
        task["curated_notes"] = notes
        task["updated_at"] = now
        _atomic_write_json(_task_path(task_id, storage_dir=storage_dir), task)
        append_writer_log(
            subsystem="control_plane",
            target=f"ops/tasks/{task_id}",
            record_id=task_id,
            result=f"curated_by_{actor}",
            actor=actor,
            storage_dir=storage_dir,
        )
    return task


def build_control_plane_snapshot(storage_dir: str = "storage") -> dict[str, Any]:
    from .scheduler import get_scheduler_state

    tasks = list_tasks(storage_dir=storage_dir)
    agents = list_agent_sessions(storage_dir=storage_dir)
    counts: dict[str, int] = {}
    brief_counts: dict[str, int] = {}
    for task in tasks:
        status = str(task.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
        brief_status = str(task.get("brief_status") or "pending")
        brief_counts[brief_status] = brief_counts.get(brief_status, 0) + 1
    rollback_dir = _control_plane_paths(storage_dir)["rollback_points"]
    rollback_points = sorted(rollback_dir.glob("*")) if rollback_dir.exists() else []
    latest_rollback = rollback_points[-1].name if rollback_points else None
    event_ledger_dir = _ops_root(storage_dir) / "event_ledger"
    return {
        "task_counts": counts,
        "brief_status_counts": brief_counts,
        "agents": agents,
        "pending_user_tasks": len(
            [task for task in tasks if task.get("source") == "user" and task.get("status") == "queued"]
        ),
        "discovery_allowed": not any(
            task.get("source") == "user" and task.get("status") == "queued" for task in tasks
        ),
        "latest_rollback_point": latest_rollback,
        "event_ledger_entries": len(list(event_ledger_dir.glob("*.json"))) if event_ledger_dir.exists() else 0,
        "scheduler": get_scheduler_state(storage_dir=storage_dir),
    }
