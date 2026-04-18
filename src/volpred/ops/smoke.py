from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from contextlib import ExitStack
from pathlib import Path
from typing import Any
from unittest.mock import patch

from .common import project_path, write_ops_snapshot
from .local_control_plane import create_task, get_task
from .scheduler import get_scheduler_state, scheduler_preview, scheduler_tick


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")


def _prepare_isolated_brief_templates(root: Path) -> Path:
    templates_root = root / "brief_templates"
    repo_root = str(project_path())
    ops_template = """
task_summary: "{{title}}"
goal: "{{description}}"
success_criteria:
  - "return a schema-valid JSON result"
  - "keep the repository read-only and files_touched empty"
repo_root: "__REPO_ROOT__"
required_files:
  - "docs/project_improvement_status.md"
recommended_files:
  - "docs/architecture.md"
forbidden_large_files:
  - "storage/reports/feed.json"
  - "storage/memory/knowledge.json"
relevant_commands:
  - "uv run python -m volpred.cli ops scheduler-preview"
why_this_agent: "executor smoke stays fully isolated"
""".replace("__REPO_ROOT__", repo_root)
    _write_text(
        templates_root / "ops.yaml",
        ops_template,
    )
    schedule_template = """
task_summary: "{{title}}"
goal: "{{description}}"
success_criteria:
  - "produce a valid coordinator brief"
repo_root: "__REPO_ROOT__"
required_files:
  - "config/runtime_schedules.json"
recommended_files:
  - "docs/project_improvement_status.md"
forbidden_large_files:
  - "storage/reports/feed.json"
  - "storage/memory/knowledge.json"
relevant_commands:
  - "uv run python -m volpred.cli ops schedule-report"
why_this_agent: "schedule governance remains with Claude"
""".replace("__REPO_ROOT__", repo_root)
    _write_text(
        templates_root / "schedule-governance.yaml",
        schedule_template,
    )
    return templates_root


def _prepare_isolated_prompts(root: Path) -> Path:
    prompts_root = root / "agent_prompts"
    _write_text(
        prompts_root / "claude_coordinator.txt",
        """
You are the isolated scheduler smoke coordinator.
Return one JSON object only that matches the schema.
Keep the brief minimal and read-only.
Task:
{{TASK_JSON}}
Repo:
{{REPO_ROOT}}
""",
    )
    _write_text(
        prompts_root / "claude_executor.txt",
        """
You are the isolated scheduler smoke executor.
Return one JSON object only that matches the schema.
Do not modify any repository file.
Do not run mutating commands.
Return "files_touched": [].
Task:
{{TASK_JSON}}
Brief:
{{BRIEF_JSON}}
Repo:
{{REPO_ROOT}}
""",
    )
    _write_text(
        prompts_root / "codex_executor.txt",
        """
You are the isolated scheduler smoke executor.
Return one JSON object only that matches the schema.
Do not modify any repository file.
Do not run mutating commands.
Return "files_touched": [].
Task:
{{TASK_JSON}}
Brief:
{{BRIEF_JSON}}
Repo:
{{REPO_ROOT}}
""",
    )
    return prompts_root


def _fake_brief_payload() -> dict[str, Any]:
    return {
        "task_summary": "Smoke coordinator brief",
        "goal": "Verify the scheduler can produce a valid execution brief without touching live storage.",
        "success_criteria": [
            "write a schema-valid brief",
            "keep task queued for downstream execution",
        ],
        "repo_root": str(project_path()),
        "required_files": [
            "docs/project_improvement_status.md",
            "config/runtime_schedules.json",
        ],
        "recommended_files": [
            "docs/architecture.md",
        ],
        "forbidden_large_files": [
            "storage/reports/feed.json",
            "storage/memory/knowledge.json",
        ],
        "relevant_commands": [
            "uv run python -m volpred.cli ops scheduler-preview",
        ],
        "prior_findings": [],
        "rollback_point_id": None,
        "why_this_agent": "schedule governance and orchestration stay with Claude coordinator",
    }


def _fake_executor_payload(agent_name: str) -> dict[str, Any]:
    return {
        "summary": f"smoke executor path completed by {agent_name}",
        "commands_run": [
            "uv run python -m volpred.cli ops health",
        ],
        "files_touched": [],
    }


def _fake_subprocess_run(args: list[str], *pargs: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
    if args[:2] == ["claude", "-p"]:
        schema_raw = args[args.index("--json-schema") + 1]
        schema = json.loads(schema_raw)
        title = str(schema.get("title") or "")
        if title == "BriefContent":
            return subprocess.CompletedProcess(args=args, returncode=0, stdout=json.dumps(_fake_brief_payload(), ensure_ascii=False), stderr="")
        if title == "ExecutorResult":
            return subprocess.CompletedProcess(args=args, returncode=0, stdout=json.dumps(_fake_executor_payload("claude"), ensure_ascii=False), stderr="")
    if len(args) >= 2 and args[0] == "codex" and args[1] == "exec":
        output_path = Path(args[args.index("--output-last-message") + 1])
        output_path.write_text(json.dumps(_fake_executor_payload("codex"), ensure_ascii=False), encoding="utf-8")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
    raise RuntimeError(f"unexpected smoke subprocess call: {args}")


def _run_coordinator_smoke(storage_dir: str) -> dict[str, Any]:
    task = create_task(
        title="Smoke schedule proposal",
        description="Isolated scheduler smoke for coordinator brief generation only.",
        source="agent",
        task_family="ops",
        priority=80,
        preferred_agent="auto",
        fallback_allowed=False,
        approval_mode="auto",
        risk_level="safe",
        public_effect="none",
        payload={
            "governance_area": "schedule",
            "schedule_proposal": {
                "action": "adjust_cron",
                "target": "publication_candidates_scan",
                "cron": "0 9 * * 1",
                "reason": "weekly editorial planning smoke",
            },
        },
        storage_dir=storage_dir,
    )
    preview = scheduler_preview(storage_dir=storage_dir)
    tick = scheduler_tick(storage_dir=storage_dir)
    task_state = get_task(task["id"], storage_dir=storage_dir)
    state = get_scheduler_state(storage_dir=storage_dir)
    return {
        "task_id": task["id"],
        "preview": preview,
        "tick": tick,
        "task": task_state,
        "scheduler_state": state,
    }


def _run_executor_smoke(storage_dir: str) -> dict[str, Any]:
    return _run_executor_agent_smoke(storage_dir, agent_name="codex")


def _run_executor_agent_smoke(storage_dir: str, *, agent_name: str) -> dict[str, Any]:
    task = create_task(
        title=f"Smoke {agent_name} executor task",
        description=f"Read-only isolated smoke for {agent_name} executor completion path.",
        source="agent",
        task_family="ops",
        priority=90,
        preferred_agent=agent_name,
        fallback_allowed=False,
        approval_mode="auto",
        risk_level="safe",
        public_effect="none",
        payload={},
        storage_dir=storage_dir,
    )
    preview = scheduler_preview(storage_dir=storage_dir)
    tick = scheduler_tick(storage_dir=storage_dir)
    task_state = get_task(task["id"], storage_dir=storage_dir)
    state = get_scheduler_state(storage_dir=storage_dir)
    return {
        "task_id": task["id"],
        "preview": preview,
        "tick": tick,
        "task": task_state,
        "scheduler_state": state,
    }


def _required_live_clis(mode: str) -> set[str]:
    required: set[str] = set()
    if mode in {"coordinator", "claude-executor", "all"}:
        required.add("claude")
    if mode in {"codex-executor", "all"}:
        required.add("codex")
    return required


def _resolve_cli_paths(cli_names: set[str]) -> dict[str, str]:
    paths: dict[str, str] = {}
    missing: list[str] = []
    for cli_name in sorted(cli_names):
        resolved = shutil.which(cli_name)
        if resolved is None:
            missing.append(cli_name)
            continue
        paths[cli_name] = resolved
    if missing:
        raise RuntimeError(f"missing_required_clis: {', '.join(missing)}")
    return paths


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _requested_live_paths(mode: str) -> list[str]:
    if mode == "coordinator":
        return ["coordinator"]
    if mode == "claude-executor":
        return ["claude_executor"]
    if mode == "codex-executor":
        return ["codex_executor"]
    return ["coordinator", "claude_executor", "codex_executor"]


def _path_agent(path_name: str) -> str:
    if path_name == "codex_executor":
        return "codex"
    return "claude"


def _path_role(path_name: str) -> str:
    return "coordinator" if path_name == "coordinator" else "executor"


def _extract_live_error(path_result: dict[str, Any]) -> str | None:
    tick = path_result.get("tick")
    if not isinstance(tick, dict):
        return None
    tick_result = tick.get("result")
    if not isinstance(tick_result, dict):
        return None
    direct_error = tick_result.get("error")
    if isinstance(direct_error, str) and direct_error.strip():
        return direct_error.strip()
    receipt = tick_result.get("receipt")
    if isinstance(receipt, dict):
        receipt_error = receipt.get("error")
        if isinstance(receipt_error, str) and receipt_error.strip():
            return receipt_error.strip()
    task = path_result.get("task")
    if isinstance(task, dict):
        last_error = task.get("last_error")
        if isinstance(last_error, str) and last_error.strip():
            return last_error.strip()
    return None


def _truncate_message(text: str | None, *, limit: int = 240) -> str | None:
    if text is None:
        return None
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[:limit]}..."


def _classify_live_path(path_name: str, path_result: dict[str, Any]) -> dict[str, Any]:
    tick = path_result.get("tick") if isinstance(path_result, dict) else {}
    tick_result = tick.get("result") if isinstance(tick, dict) else {}
    result_label = str(tick_result.get("result") or "")
    error_text = _extract_live_error(path_result)
    error_lower = (error_text or "").lower()

    readiness = "blocked"
    reason_code = "unknown"
    if result_label in {"brief_ready", "succeeded"}:
        readiness = "ready"
        reason_code = "ok"
    elif "not logged in" in error_lower or "/login" in error_lower:
        readiness = "blocked"
        reason_code = "auth_required"
    elif "timeout" in error_lower:
        readiness = "blocked"
        reason_code = "timeout"
    elif "schema" in error_lower or "validation error" in error_lower or "field required" in error_lower:
        readiness = "blocked"
        reason_code = "schema_mismatch"
    elif error_text:
        readiness = "blocked"
        reason_code = "free_text_response" if _path_agent(path_name) == "claude" else "runtime_error"

    task = path_result.get("task") if isinstance(path_result, dict) else {}
    return {
        "path": path_name,
        "agent": _path_agent(path_name),
        "role": _path_role(path_name),
        "task_id": path_result.get("task_id"),
        "scheduler_result": result_label or None,
        "task_status": task.get("status") if isinstance(task, dict) else None,
        "brief_status": task.get("brief_status") if isinstance(task, dict) else None,
        "readiness": readiness,
        "reason_code": reason_code,
        "message": _truncate_message(error_text),
    }


def _live_smoke_suggestions(summary_paths: dict[str, dict[str, Any]]) -> list[str]:
    suggestions: list[str] = []
    claude_paths = [
        item for item in summary_paths.values() if item.get("agent") == "claude"
    ]
    codex_paths = [
        item for item in summary_paths.values() if item.get("agent") == "codex"
    ]
    if any(item.get("reason_code") == "auth_required" for item in claude_paths):
        suggestions.append("Claude CLI 目前未登入；需先完成 Claude Code `/login`，否則所有需要 Claude coordinator / executor 的 live path 都會 blocked。")
    if any(item.get("reason_code") == "free_text_response" for item in claude_paths):
        suggestions.append("Claude live path 目前能執行，但 structured output contract 尚未穩定；需要優先處理 coordinator / executor 的 JSON 輸出相容性。")
    if any(item.get("readiness") == "ready" for item in codex_paths):
        suggestions.append("Codex live executor 已可用；code/review/ops 類、模板明確的任務可維持優先派給 Codex。")
    if not suggestions:
        suggestions.append("Agent CLI live smoke 路徑目前健康。")
    return suggestions


def _build_live_smoke_summary(*, mode: str, results: dict[str, Any], cli_paths: dict[str, str]) -> dict[str, Any]:
    requested = _requested_live_paths(mode)
    path_summaries = {
        path_name: _classify_live_path(path_name, results[path_name])
        for path_name in requested
        if path_name in results
    }
    readiness_values = [item.get("readiness") for item in path_summaries.values()]
    if readiness_values and all(value == "ready" for value in readiness_values):
        overall_status = "ready"
    elif any(value == "ready" for value in readiness_values):
        overall_status = "degraded"
    else:
        overall_status = "blocked"
    return {
        "generated_at": _utc_now(),
        "overall_status": overall_status,
        "requested_paths": requested,
        "paths": path_summaries,
        "cli_paths": cli_paths,
        "suggestions": _live_smoke_suggestions(path_summaries),
    }


def run_scheduler_smoke(
    *,
    mode: str = "both",
    base_dir: str | None = None,
    keep_artifacts: bool = True,
) -> dict[str, Any]:
    if mode not in {"coordinator", "executor", "both"}:
        raise ValueError("mode must be one of: coordinator, executor, both")

    created_temp = base_dir is None
    root = Path(base_dir) if base_dir else Path(tempfile.mkdtemp(prefix="volpred_scheduler_smoke."))
    root.mkdir(parents=True, exist_ok=True)

    results: dict[str, Any] = {
        "mode": mode,
        "root_dir": str(root),
        "artifacts_retained": keep_artifacts or not created_temp,
        "paths": {},
        "results": {},
    }

    try:
        with ExitStack() as stack:
            templates_root = _prepare_isolated_brief_templates(root / "config")
            prompts_root = _prepare_isolated_prompts(root / "config")
            results["paths"]["brief_templates_root"] = str(templates_root)
            results["paths"]["agent_prompts_root"] = str(prompts_root)

            stack.enter_context(patch("volpred.ops.execution_brief.subprocess.run", side_effect=_fake_subprocess_run))
            stack.enter_context(patch("volpred.ops.execution_brief.BRIEF_TEMPLATES_ROOT", templates_root))
            stack.enter_context(patch("volpred.ops.execution_brief.AGENT_PROMPTS_ROOT", prompts_root))

            if mode in {"coordinator", "both"}:
                coordinator_storage = root / "coordinator" / "storage"
                results["paths"]["coordinator_storage_dir"] = str(coordinator_storage)
                results["results"]["coordinator"] = _run_coordinator_smoke(str(coordinator_storage))

            if mode in {"executor", "both"}:
                executor_storage = root / "executor" / "storage"
                results["paths"]["executor_storage_dir"] = str(executor_storage)
                results["results"]["executor"] = _run_executor_smoke(str(executor_storage))

        return results
    finally:
        if created_temp and not keep_artifacts:
            shutil.rmtree(root, ignore_errors=True)


def run_scheduler_live_smoke(
    *,
    mode: str = "all",
    base_dir: str | None = None,
    keep_artifacts: bool = True,
    snapshot_storage_dir: str | None = None,
) -> dict[str, Any]:
    if mode not in {"coordinator", "claude-executor", "codex-executor", "all"}:
        raise ValueError("mode must be one of: coordinator, claude-executor, codex-executor, all")

    created_temp = base_dir is None
    root = Path(base_dir) if base_dir else Path(tempfile.mkdtemp(prefix="volpred_scheduler_live_smoke."))
    root.mkdir(parents=True, exist_ok=True)

    results: dict[str, Any] = {
        "mode": mode,
        "runner": "live",
        "root_dir": str(root),
        "artifacts_retained": keep_artifacts or not created_temp,
        "paths": {},
        "results": {},
        "timeouts": {
            "coordinator_seconds": 45,
            "executor_seconds": 60,
        },
        "cli_paths": _resolve_cli_paths(_required_live_clis(mode)),
    }

    try:
        with ExitStack() as stack:
            templates_root = _prepare_isolated_brief_templates(root / "config")
            prompts_root = _prepare_isolated_prompts(root / "config")
            results["paths"]["brief_templates_root"] = str(templates_root)
            results["paths"]["agent_prompts_root"] = str(prompts_root)

            stack.enter_context(patch("volpred.ops.execution_brief.BRIEF_TEMPLATES_ROOT", templates_root))
            stack.enter_context(patch("volpred.ops.execution_brief.AGENT_PROMPTS_ROOT", prompts_root))
            stack.enter_context(
                patch(
                    "volpred.ops.execution_brief.CLAUDE_PRINT_EXTRA_ARGS",
                    ("--no-session-persistence", "--tools", ""),
                )
            )
            stack.enter_context(
                patch(
                    "volpred.ops.execution_brief.CODEX_EXEC_EXTRA_ARGS",
                    ("--sandbox", "read-only", "--ephemeral"),
                )
            )
            stack.enter_context(patch("volpred.ops.execution_brief.COORDINATOR_TIMEOUT_SECONDS", 45))
            stack.enter_context(patch("volpred.ops.execution_brief.EXECUTOR_TIMEOUT_SECONDS", 60))

            if mode in {"coordinator", "all"}:
                coordinator_storage = root / "coordinator" / "storage"
                results["paths"]["coordinator_storage_dir"] = str(coordinator_storage)
                results["results"]["coordinator"] = _run_coordinator_smoke(str(coordinator_storage))

            if mode in {"claude-executor", "all"}:
                claude_storage = root / "claude_executor" / "storage"
                results["paths"]["claude_executor_storage_dir"] = str(claude_storage)
                results["results"]["claude_executor"] = _run_executor_agent_smoke(
                    str(claude_storage),
                    agent_name="claude",
                )

            if mode in {"codex-executor", "all"}:
                codex_storage = root / "codex_executor" / "storage"
                results["paths"]["codex_executor_storage_dir"] = str(codex_storage)
                results["results"]["codex_executor"] = _run_executor_agent_smoke(
                    str(codex_storage),
                    agent_name="codex",
                )

        summary = _build_live_smoke_summary(
            mode=mode,
            results=results["results"],
            cli_paths=results["cli_paths"],
        )
        results["summary"] = summary
        if snapshot_storage_dir:
            snapshot_path = write_ops_snapshot(
                "agent_cli_health",
                summary,
                storage_dir=snapshot_storage_dir,
            )
            results["snapshot_path"] = str(snapshot_path)
        return results
    finally:
        if created_temp and not keep_artifacts:
            shutil.rmtree(root, ignore_errors=True)
