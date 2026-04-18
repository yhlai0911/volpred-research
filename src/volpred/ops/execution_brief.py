from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .agent_spec import check_agent_specs
from .common import project_path
from .local_control_plane import (
    ExecutionReceipt,
    _atomic_write_json,
    _close_agent_claim,
    _load_task,
    _plane_lock,
    _task_path,
    _write_execution,
    is_schedule_governance_task,
)

BRIEF_TEMPLATES_ROOT = project_path("config", "brief_templates")
AGENT_PROMPTS_ROOT = project_path("config", "agent_prompts")
DEFAULT_FORBIDDEN_LARGE_FILES = [
    "storage/reports/feed.json",
    "storage/memory/knowledge.json",
]
COORDINATOR_TIMEOUT_SECONDS = 90
EXECUTOR_TIMEOUT_SECONDS = 180
CLAUDE_PRINT_EXTRA_ARGS: tuple[str, ...] = ()
CODEX_EXEC_EXTRA_ARGS: tuple[str, ...] = ("--full-auto",)


class BriefContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_summary: str
    goal: str
    success_criteria: list[str] = Field(default_factory=list)
    repo_root: str
    required_files: list[str] = Field(default_factory=list)
    recommended_files: list[str] = Field(default_factory=list)
    forbidden_large_files: list[str] = Field(default_factory=list)
    relevant_commands: list[str] = Field(default_factory=list)
    prior_findings: list[str] = Field(default_factory=list)
    rollback_point_id: str | None = None
    why_this_agent: str


class ExecutorResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str
    commands_run: list[str] = Field(default_factory=list)
    files_touched: list[str] = Field(default_factory=list)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _template_path(template_name: str) -> Path:
    return BRIEF_TEMPLATES_ROOT / template_name


def _family_template_name(task: dict[str, Any]) -> str:
    payload = task.get("payload")
    if isinstance(payload, dict):
        explicit = str(payload.get("brief_template") or "").strip()
        if explicit:
            return explicit if explicit.endswith(".yaml") else f"{explicit}.yaml"
    if is_schedule_governance_task(task):
        return "schedule-governance.yaml"
    family = str(task.get("task_family") or "ops")
    return f"{family}.yaml"


def has_brief_template(task: dict[str, Any]) -> bool:
    return _load_template(_family_template_name(task)) is not None


def _load_template(template_name: str) -> dict[str, Any] | None:
    path = _template_path(template_name)
    if not path.exists():
        return None
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise RuntimeError(f"Invalid brief template: {path}")
    return payload


def _render_template_value(value: Any, mapping: dict[str, str]) -> Any:
    if isinstance(value, str):
        rendered = value
        for key, item in mapping.items():
            rendered = rendered.replace(f"{{{{{key}}}}}", item)
        return rendered
    if isinstance(value, list):
        return [_render_template_value(item, mapping) for item in value]
    if isinstance(value, dict):
        return {str(key): _render_template_value(item, mapping) for key, item in value.items()}
    return value


def _template_hash(template_payload: dict[str, Any]) -> str:
    encoded = json.dumps(template_payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _recent_receipts(task_id: str, storage_dir: str = "storage") -> list[dict[str, Any]]:
    execution_dir = project_path(storage_dir, "ops", "executions", task_id)
    receipts: list[dict[str, Any]] = []
    if execution_dir.exists():
        for path in sorted(execution_dir.glob("*.json")):
            receipts.append(json.loads(path.read_text(encoding="utf-8")))
    receipts.sort(key=lambda item: str(item.get("timestamp") or ""), reverse=True)
    return receipts


def _prior_findings(task_id: str, storage_dir: str = "storage") -> list[str]:
    findings: list[str] = []
    for receipt in _recent_receipts(task_id, storage_dir=storage_dir)[:3]:
        summary = str(receipt.get("summary") or "").strip()
        error = str(receipt.get("error") or "").strip()
        if summary:
            findings.append(summary)
        elif error:
            findings.append(f"error: {error}")
    return findings


def _template_mapping(task: dict[str, Any]) -> dict[str, str]:
    payload = task.get("payload")
    schedule_proposal = None
    governance_area = ""
    if isinstance(payload, dict):
        governance_area = str(payload.get("governance_area") or "").strip()
        if isinstance(payload.get("schedule_proposal"), dict):
            schedule_proposal = payload.get("schedule_proposal")
    return {
        "task_id": str(task.get("id") or ""),
        "title": str(task.get("title") or ""),
        "description": str(task.get("description") or ""),
        "task_family": str(task.get("task_family") or ""),
        "preferred_agent": str(task.get("preferred_agent") or ""),
        "public_effect": str(task.get("public_effect") or "none"),
        "governance_area": governance_area,
        "schedule_proposal_json": (
            json.dumps(schedule_proposal, ensure_ascii=False, indent=2)
            if isinstance(schedule_proposal, dict)
            else "{}"
        ),
    }


def _task_preconditions(task: dict[str, Any]) -> list[Any]:
    payload = task.get("payload")
    if not isinstance(payload, dict):
        return []
    preconditions = payload.get("preconditions")
    if not isinstance(preconditions, list):
        return []
    return list(preconditions)


def _precondition_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return project_path(value)


def task_unmet_preconditions(task: dict[str, Any]) -> list[str]:
    unmet: list[str] = []
    for item in _task_preconditions(task):
        if isinstance(item, str):
            if not _precondition_path(item).exists():
                unmet.append(item)
            continue
        if isinstance(item, dict):
            check_type = str(item.get("type") or item.get("kind") or "path_exists")
            path_value = str(item.get("path") or "").strip()
            if not path_value:
                unmet.append("invalid_precondition:missing_path")
                continue
            exists = _precondition_path(path_value).exists()
            if check_type in {"path_exists", "file_exists"}:
                if not exists:
                    unmet.append(path_value)
                continue
            if check_type == "path_missing":
                if exists:
                    unmet.append(f"expected_missing:{path_value}")
                continue
            unmet.append(f"invalid_precondition_type:{check_type}")
            continue
        unmet.append(f"invalid_precondition:{item!r}")
    return unmet


def _render_template_brief(task: dict[str, Any], template_name: str, template_payload: dict[str, Any], *, storage_dir: str) -> dict[str, Any]:
    rendered = _render_template_value(template_payload, _template_mapping(task))
    if not isinstance(rendered, dict):
        raise RuntimeError(f"Rendered brief template must be an object: {template_name}")
    rendered.setdefault("repo_root", str(project_path()))
    rendered.setdefault("forbidden_large_files", list(DEFAULT_FORBIDDEN_LARGE_FILES))
    rendered["prior_findings"] = _prior_findings(str(task.get("id")), storage_dir=storage_dir)
    rendered["rollback_point_id"] = task.get("rollback_point_id")
    validated = BriefContent.model_validate(rendered)
    return {
        "generated_at": _utc_now(),
        "source_type": "template",
        "template_id": template_name,
        "template_hash": _template_hash(template_payload),
        "coordinator_run_id": None,
        **validated.model_dump(),
    }


def _supervisor_brief_skeleton(task: dict[str, Any], *, storage_dir: str = "storage") -> dict[str, Any]:
    return {
        "task_summary": str(task.get("title") or ""),
        "goal": str(task.get("description") or ""),
        "success_criteria": [],
        "repo_root": str(project_path()),
        "required_files": [],
        "recommended_files": [],
        "forbidden_large_files": list(DEFAULT_FORBIDDEN_LARGE_FILES),
        "relevant_commands": [],
        "prior_findings": _prior_findings(str(task.get("id") or ""), storage_dir=storage_dir),
        "rollback_point_id": task.get("rollback_point_id"),
        "why_this_agent": (
            "Prepared by a supervisor Claude session for a VS Code worker terminal."
        ),
    }


def _brief_is_stale(task: dict[str, Any], template_name: str | None, template_payload: dict[str, Any] | None) -> bool:
    current = task.get("brief_payload")
    if not isinstance(current, dict):
        return True
    generated_at = str(current.get("generated_at") or "")
    updated_at = str(task.get("updated_at") or "")
    if generated_at and updated_at and updated_at > generated_at:
        return True
    if template_name and template_payload:
        if str(current.get("template_hash") or "") != _template_hash(template_payload):
            return True
    return False


def task_brief_is_stale(task: dict[str, Any]) -> bool:
    template_name = _family_template_name(task)
    template_payload = _load_template(template_name)
    return _brief_is_stale(task, template_name if template_payload else None, template_payload)


def task_brief_is_ready(task: dict[str, Any]) -> bool:
    current = task.get("brief_payload")
    return (
        str(task.get("brief_status") or "") == "ready"
        and isinstance(current, dict)
        and not task_brief_is_stale(task)
    )


def task_requires_coordinator(task: dict[str, Any]) -> bool:
    if str(task.get("brief_status") or "") == "needs_manual_review":
        return False
    if task_brief_is_ready(task):
        return False
    if is_schedule_governance_task(task):
        return True
    if has_brief_template(task):
        return False
    return True


def task_preconditions_met(task: dict[str, Any]) -> bool:
    return len(task_unmet_preconditions(task)) == 0


def _set_task_brief(task_id: str, *, brief_status: str, brief_payload: dict[str, Any] | None, storage_dir: str = "storage") -> dict[str, Any]:
    with _plane_lock(storage_dir):
        task = _load_task(task_id, storage_dir=storage_dir)
        if task is None:
            raise RuntimeError(f"Unknown task: {task_id}")
        updated_at = (
            str(brief_payload.get("generated_at") or "")
            if isinstance(brief_payload, dict)
            else ""
        ) or _utc_now()
        task["brief_status"] = brief_status
        task["brief_payload"] = brief_payload
        task["updated_at"] = updated_at
        _atomic_write_json(_task_path(task_id, storage_dir=storage_dir), task)
        return task


def _block_task(task_id: str, *, actor: str, error: str, brief_status: str | None = None, storage_dir: str = "storage") -> dict[str, Any]:
    with _plane_lock(storage_dir):
        task = _load_task(task_id, storage_dir=storage_dir)
        if task is None:
            raise RuntimeError(f"Unknown task: {task_id}")
        now = _utc_now()
        task["status"] = "blocked"
        task["last_error"] = error
        if brief_status is not None:
            task["brief_status"] = brief_status
        task["claimed_by"] = None
        task["claimed_at"] = None
        task["updated_at"] = now
        _atomic_write_json(_task_path(task_id, storage_dir=storage_dir), task)
        receipt = ExecutionReceipt(
            task_id=task_id,
            run_id=f"run_{uuid.uuid4().hex[:12]}",
            agent_name=actor,
            result_status="blocked_preflight",
            summary=error,
            commands_run=[],
            files_touched=[],
            subagent_count=0,
            session_id=task.get("session_id"),
            rollback_point_id=task.get("rollback_point_id"),
            timestamp=now,
            error=error,
        )
        _write_execution(task_id, receipt, storage_dir=storage_dir)
        if actor in {"claude", "codex"}:
            _close_agent_claim(actor, storage_dir=storage_dir)
        return task


def _fail_task_missing_files(task_id: str, *, actor: str, missing_files: list[str], storage_dir: str = "storage") -> dict[str, Any]:
    with _plane_lock(storage_dir):
        task = _load_task(task_id, storage_dir=storage_dir)
        if task is None:
            raise RuntimeError(f"Unknown task: {task_id}")
        now = _utc_now()
        error = f"required_files_missing: {', '.join(missing_files)}"
        task["status"] = "failed"
        task["last_error"] = error
        task["finished_at"] = now
        task["claimed_by"] = None
        task["claimed_at"] = None
        task["updated_at"] = now
        _atomic_write_json(_task_path(task_id, storage_dir=storage_dir), task)
        receipt = ExecutionReceipt(
            task_id=task_id,
            run_id=f"run_{uuid.uuid4().hex[:12]}",
            agent_name=actor,
            result_status="failed",
            summary=error,
            commands_run=[],
            files_touched=[],
            subagent_count=0,
            session_id=task.get("session_id"),
            rollback_point_id=task.get("rollback_point_id"),
            timestamp=now,
            error=error,
        )
        _write_execution(task_id, receipt, storage_dir=storage_dir)
        if actor in {"claude", "codex"}:
            _close_agent_claim(actor, storage_dir=storage_dir)
        return task


def _requeue_for_stale_brief(task_id: str, *, storage_dir: str = "storage") -> dict[str, Any]:
    with _plane_lock(storage_dir):
        task = _load_task(task_id, storage_dir=storage_dir)
        if task is None:
            raise RuntimeError(f"Unknown task: {task_id}")
        now = _utc_now()
        claimed_by = task.get("claimed_by")
        task["brief_status"] = "stale"
        task["status"] = "queued"
        task["claimed_by"] = None
        task["claimed_at"] = None
        task["updated_at"] = now
        _atomic_write_json(_task_path(task_id, storage_dir=storage_dir), task)
        if claimed_by in {"claude", "codex"}:
            _close_agent_claim(str(claimed_by), storage_dir=storage_dir)
        return task


def _requeue_for_unmet_preconditions(
    task_id: str,
    *,
    unmet_preconditions: list[str],
    storage_dir: str = "storage",
) -> dict[str, Any]:
    with _plane_lock(storage_dir):
        task = _load_task(task_id, storage_dir=storage_dir)
        if task is None:
            raise RuntimeError(f"Unknown task: {task_id}")
        now = _utc_now()
        claimed_by = task.get("claimed_by")
        task["status"] = "queued"
        task["last_error"] = f"preconditions_not_met: {', '.join(unmet_preconditions)}"
        task["claimed_by"] = None
        task["claimed_at"] = None
        task["updated_at"] = now
        _atomic_write_json(_task_path(task_id, storage_dir=storage_dir), task)
        if claimed_by in {"claude", "codex"}:
            _close_agent_claim(str(claimed_by), storage_dir=storage_dir)
        return task


def _extract_json_object(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if not text:
        raise RuntimeError("empty coordinator output")

    def _unwrap_candidate(candidate: Any) -> dict[str, Any]:
        if isinstance(candidate, dict):
            # `claude -p --output-format json` returns a result envelope. Pull the
            # actual model text out before validating against our schema.
            if "result" in candidate and any(
                key in candidate for key in ("type", "subtype", "is_error", "session_id", "duration_ms")
            ):
                if bool(candidate.get("is_error")):
                    detail = str(candidate.get("result") or candidate.get("error") or "claude_cli_error").strip()
                    raise RuntimeError(detail or "claude_cli_error")
                return _extract_json_object(str(candidate.get("result") or ""))
            return candidate
        if isinstance(candidate, str):
            return _extract_json_object(candidate)
        raise RuntimeError("unable to extract JSON object from coordinator output")

    try:
        payload = json.loads(text)
        return _unwrap_candidate(payload)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        snippet = text[start : end + 1]
        payload = json.loads(snippet)
        return _unwrap_candidate(payload)
    raise RuntimeError(text if len(text) <= 500 else f"{text[:500]}...")


def _load_prompt(name: str) -> str:
    path = AGENT_PROMPTS_ROOT / name
    return path.read_text(encoding="utf-8")


def _coordinator_prompt(task: dict[str, Any]) -> str:
    base = _load_prompt("claude_coordinator.txt")
    return base.replace("{{TASK_JSON}}", json.dumps(task, ensure_ascii=False, indent=2)).replace(
        "{{REPO_ROOT}}", str(project_path())
    )


def _executor_prompt(agent_name: str, task: dict[str, Any], brief: dict[str, Any]) -> str:
    prompt_name = "claude_executor.txt" if agent_name == "claude" else "codex_executor.txt"
    base = _load_prompt(prompt_name)
    return (
        base.replace("{{TASK_JSON}}", json.dumps(task, ensure_ascii=False, indent=2))
        .replace("{{BRIEF_JSON}}", json.dumps(brief, ensure_ascii=False, indent=2))
        .replace("{{REPO_ROOT}}", str(project_path()))
    )


def _coordinator_schema() -> dict[str, Any]:
    return BriefContent.model_json_schema()


def _codex_output_schema() -> dict[str, Any]:
    schema = ExecutorResult.model_json_schema()
    properties = schema.get("properties")
    if isinstance(properties, dict):
        schema["required"] = list(properties.keys())
        schema["additionalProperties"] = False
    return schema


def run_coordinator_brief(task_id: str, *, storage_dir: str = "storage") -> dict[str, Any]:
    task = _load_task(task_id, storage_dir=storage_dir)
    if task is None:
        raise RuntimeError(f"Unknown task: {task_id}")
    prompt = _coordinator_prompt(task)
    schema = json.dumps(_coordinator_schema(), ensure_ascii=False)
    last_error = "coordinator_failed"
    for _ in range(3):
        try:
            result = subprocess.run(
                ["claude", "-p", *CLAUDE_PRINT_EXTRA_ARGS, "--output-format", "json", "--json-schema", schema, prompt],
                cwd=project_path(),
                capture_output=True,
                text=True,
                timeout=COORDINATOR_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            last_error = f"coordinator_timeout_after_{COORDINATOR_TIMEOUT_SECONDS}s"
            continue
        if result.returncode != 0:
            last_error = result.stderr.strip() or result.stdout.strip() or "coordinator_process_failed"
            continue
        try:
            payload = _extract_json_object(result.stdout)
            validated = BriefContent.model_validate(payload)
        except (RuntimeError, ValidationError, json.JSONDecodeError) as exc:
            last_error = str(exc)
            continue
        brief_payload = {
            "generated_at": _utc_now(),
            "source_type": "coordinator",
            "template_id": None,
            "template_hash": None,
            "coordinator_run_id": f"coord_{uuid.uuid4().hex[:12]}",
            **validated.model_dump(),
        }
        _set_task_brief(task_id, brief_status="ready", brief_payload=brief_payload, storage_dir=storage_dir)
        return brief_payload
    _block_task(
        task_id,
        actor="claude",
        error=f"coordinator_failed: {last_error}",
        brief_status="needs_manual_review",
        storage_dir=storage_dir,
    )
    raise RuntimeError(last_error)


def ensure_execution_brief(task_id: str, *, storage_dir: str = "storage", allow_coordinator: bool = False) -> dict[str, Any] | None:
    task = _load_task(task_id, storage_dir=storage_dir)
    if task is None:
        raise RuntimeError(f"Unknown task: {task_id}")
    template_name = _family_template_name(task)
    template_payload = _load_template(template_name)
    if task.get("brief_status") == "ready" and not _brief_is_stale(task, template_name if template_payload else None, template_payload):
        current = task.get("brief_payload")
        if isinstance(current, dict):
            return current

    if template_payload is not None:
        brief = _render_template_brief(task, template_name, template_payload, storage_dir=storage_dir)
        _set_task_brief(task_id, brief_status="ready", brief_payload=brief, storage_dir=storage_dir)
        return brief

    if allow_coordinator:
        return run_coordinator_brief(task_id, storage_dir=storage_dir)

    _set_task_brief(task_id, brief_status="pending", brief_payload=task.get("brief_payload"), storage_dir=storage_dir)
    return None


def build_execution_brief(task_id: str, *, storage_dir: str = "storage", allow_coordinator: bool = False) -> dict[str, Any] | None:
    return ensure_execution_brief(task_id, storage_dir=storage_dir, allow_coordinator=allow_coordinator)


def preview_execution_brief(task_id: str, *, storage_dir: str = "storage") -> dict[str, Any]:
    task = _load_task(task_id, storage_dir=storage_dir)
    if task is None:
        raise RuntimeError(f"Unknown task: {task_id}")
    brief = build_execution_brief(task_id, storage_dir=storage_dir, allow_coordinator=False)
    task = _load_task(task_id, storage_dir=storage_dir)
    if task is None:
        raise RuntimeError(f"Unknown task: {task_id}")
    requires_supervisor = brief is None and task_requires_coordinator(task)
    return {
        "task_id": task_id,
        "task_status": task.get("status"),
        "brief_status": task.get("brief_status"),
        "requires_supervisor": requires_supervisor,
        "brief": brief,
        "suggested_brief": None if brief is not None else _supervisor_brief_skeleton(task, storage_dir=storage_dir),
    }


def set_execution_brief(
    task_id: str,
    *,
    brief_payload: dict[str, Any],
    actor: str,
    storage_dir: str = "storage",
) -> dict[str, Any]:
    task = _load_task(task_id, storage_dir=storage_dir)
    if task is None:
        raise RuntimeError(f"Unknown task: {task_id}")
    validated = BriefContent.model_validate(brief_payload)
    coordinator_run_id = None
    if isinstance(brief_payload, dict):
        raw_run_id = str(brief_payload.get("coordinator_run_id") or "").strip()
        coordinator_run_id = raw_run_id or None
    payload = {
        "generated_at": (
            str(brief_payload.get("generated_at") or "").strip()
            if isinstance(brief_payload, dict)
            else ""
        )
        or _utc_now(),
        "source_type": "supervisor",
        "template_id": None,
        "template_hash": None,
        "coordinator_run_id": coordinator_run_id or f"supervisor_{actor}_{uuid.uuid4().hex[:8]}",
        **validated.model_dump(),
    }
    _set_task_brief(task_id, brief_status="ready", brief_payload=payload, storage_dir=storage_dir)
    refreshed = _load_task(task_id, storage_dir=storage_dir)
    if refreshed is None:
        raise RuntimeError(f"Unknown task: {task_id}")
    return refreshed


def preflight_executor_task(task_id: str, *, agent_name: str, storage_dir: str = "storage") -> dict[str, Any]:
    task = _load_task(task_id, storage_dir=storage_dir)
    if task is None:
        raise RuntimeError(f"Unknown task: {task_id}")
    unmet_preconditions = task_unmet_preconditions(task)
    if unmet_preconditions:
        _requeue_for_unmet_preconditions(
            task_id,
            unmet_preconditions=unmet_preconditions,
            storage_dir=storage_dir,
        )
        raise RuntimeError("preconditions_not_met")
    brief = build_execution_brief(task_id, storage_dir=storage_dir, allow_coordinator=False)
    if brief is None:
        _requeue_for_stale_brief(task_id, storage_dir=storage_dir)
        raise RuntimeError("brief_missing_or_stale")
    task = _load_task(task_id, storage_dir=storage_dir)
    if task is None:
        raise RuntimeError(f"Unknown task: {task_id}")
    agent_spec = check_agent_specs()
    if not agent_spec["clean"]:
        _block_task(
            task_id,
            actor=agent_name,
            error="agent-spec drift detected",
            brief_status=task.get("brief_status"),
            storage_dir=storage_dir,
        )
        raise RuntimeError("agent_spec_drift")
    repo_root = Path(str(brief.get("repo_root") or project_path()))
    if repo_root != project_path():
        _block_task(
            task_id,
            actor=agent_name,
            error=f"repo_root mismatch: {repo_root}",
            brief_status=task.get("brief_status"),
            storage_dir=storage_dir,
        )
        raise RuntimeError("repo_root_mismatch")
    missing_files = [path for path in brief.get("required_files", []) if not project_path(path).exists()]
    if missing_files:
        _fail_task_missing_files(task_id, actor=agent_name, missing_files=missing_files, storage_dir=storage_dir)
        raise RuntimeError("required_files_missing")
    return {
        "task": task,
        "brief": brief,
    }


def run_executor_task(task_id: str, *, agent_name: str, storage_dir: str = "storage") -> dict[str, Any]:
    prepared = preflight_executor_task(task_id, agent_name=agent_name, storage_dir=storage_dir)
    task = prepared["task"]
    brief = prepared["brief"]
    prompt = _executor_prompt(agent_name, task, brief)

    if agent_name == "claude":
        schema = json.dumps(ExecutorResult.model_json_schema(), ensure_ascii=False)
        try:
            result = subprocess.run(
                ["claude", "-p", *CLAUDE_PRINT_EXTRA_ARGS, "--output-format", "json", "--json-schema", schema, prompt],
                cwd=project_path(),
                capture_output=True,
                text=True,
                timeout=EXECUTOR_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"claude_executor_timeout_after_{EXECUTOR_TIMEOUT_SECONDS}s"
            ) from exc
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "claude_executor_failed")
        payload = _extract_json_object(result.stdout)
    else:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as schema_file:
            json.dump(_codex_output_schema(), schema_file, ensure_ascii=False)
            schema_path = schema_file.name
        with tempfile.NamedTemporaryFile("w+", suffix=".json", delete=False) as output_file:
            output_path = output_file.name
        try:
            try:
                result = subprocess.run(
                    [
                        "codex",
                        "exec",
                        "--cd",
                        str(project_path()),
                        *CODEX_EXEC_EXTRA_ARGS,
                        "--output-schema",
                        schema_path,
                        "--output-last-message",
                        output_path,
                        prompt,
                    ],
                    cwd=project_path(),
                    capture_output=True,
                    text=True,
                    timeout=EXECUTOR_TIMEOUT_SECONDS,
                )
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError(
                    f"codex_executor_timeout_after_{EXECUTOR_TIMEOUT_SECONDS}s"
                ) from exc
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "codex_executor_failed")
            payload = _extract_json_object(Path(output_path).read_text(encoding="utf-8"))
        finally:
            Path(schema_path).unlink(missing_ok=True)
            Path(output_path).unlink(missing_ok=True)

    validated = ExecutorResult.model_validate(payload)
    return {
        "task": task,
        "brief": brief,
        "result": validated.model_dump(),
    }
