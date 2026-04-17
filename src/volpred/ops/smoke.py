from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from contextlib import ExitStack
from pathlib import Path
from typing import Any
from unittest.mock import patch

from .common import project_path
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
  - "complete smoke task safely"
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
Return one JSON object only.
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
Return one JSON object only.
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
Return one JSON object only.
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
    task = create_task(
        title="Smoke executor task",
        description="Read-only isolated smoke for executor completion path.",
        source="agent",
        task_family="ops",
        priority=90,
        preferred_agent="auto",
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
