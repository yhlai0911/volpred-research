from __future__ import annotations

from pathlib import Path

from volpred.ops.local_control_plane import create_task, get_task, heartbeat_agent
from volpred.ops.scheduler import get_scheduler_state, scheduler_preview, scheduler_tick
from volpred.ops.shared_lock import shared_state_lock


def _write_template(root: Path, name: str, body: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / name).write_text(body, encoding="utf-8")


def test_scheduler_tick_skips_when_no_work(tmp_path: Path):
    storage_dir = str(tmp_path / "storage")
    result = scheduler_tick(storage_dir=storage_dir)
    assert result["status"] == "skipped"
    assert result["reason"] == "no_work"
    state = get_scheduler_state(storage_dir=storage_dir)
    assert state["last_status"] == "skipped"
    assert state["last_reason"] == "no_work"


def test_scheduler_tick_skips_when_lock_busy(tmp_path: Path):
    storage_dir = str(tmp_path / "storage")
    with shared_state_lock("scheduler_tick", storage_dir=storage_dir):
        result = scheduler_tick(storage_dir=storage_dir)
    assert result["status"] == "skipped"
    assert result["reason"] == "lock_busy"


def test_scheduler_preview_is_read_only_for_template_tasks(tmp_path: Path, monkeypatch):
    templates_root = tmp_path / "brief_templates"
    _write_template(
        templates_root,
        "ops.yaml",
        """
task_summary: "{{title}}"
goal: "{{description}}"
success_criteria:
  - "done"
repo_root: "/Users/yhlai0911/Desktop/volpred-research"
required_files:
  - "docs/project_improvement_status.md"
recommended_files: []
forbidden_large_files: []
relevant_commands: []
why_this_agent: "ops template"
""".strip(),
    )
    monkeypatch.setattr("volpred.ops.execution_brief.BRIEF_TEMPLATES_ROOT", templates_root)

    storage_dir = str(tmp_path / "storage")
    task = create_task(
        title="Preview task",
        description="preview only",
        task_family="ops",
        preferred_agent="auto",
        storage_dir=storage_dir,
    )

    preview = scheduler_preview(storage_dir=storage_dir)
    assert preview["decision"] is not None
    assert preview["decision"]["task_id"] == task["id"]
    assert preview["decision"]["mode"] == "executor"
    assert preview["decision"]["agent"] == "codex"

    task_state = get_task(task["id"], storage_dir=storage_dir)
    assert task_state is not None
    assert task_state["brief_status"] == "pending"
    assert task_state["brief_payload"] is None


def test_scheduler_tick_executor_path_completes_task(tmp_path: Path, monkeypatch):
    templates_root = tmp_path / "brief_templates"
    _write_template(
        templates_root,
        "ops.yaml",
        """
task_summary: "{{title}}"
goal: "{{description}}"
success_criteria:
  - "done"
repo_root: "/Users/yhlai0911/Desktop/volpred-research"
required_files:
  - "docs/project_improvement_status.md"
recommended_files: []
forbidden_large_files: []
relevant_commands: []
why_this_agent: "ops template"
""".strip(),
    )
    monkeypatch.setattr("volpred.ops.execution_brief.BRIEF_TEMPLATES_ROOT", templates_root)
    monkeypatch.setattr(
        "volpred.ops.scheduler.run_executor_task",
        lambda task_id, *, agent_name, storage_dir: {
            "task": {"id": task_id},
            "brief": {"task_summary": "patched"},
            "result": {
                "summary": f"done by {agent_name}",
                "commands_run": ["uv run volpred ops health"],
                "files_touched": ["src/volpred/ops/scheduler.py"],
            },
        },
    )

    storage_dir = str(tmp_path / "storage")
    task = create_task(
        title="Executor task",
        description="should complete",
        task_family="ops",
        preferred_agent="auto",
        storage_dir=storage_dir,
    )

    result = scheduler_tick(storage_dir=storage_dir)
    assert result["status"] == "ok"
    assert result["result"]["mode"] == "executor"
    assert result["result"]["result"] == "succeeded"
    assert result["result"]["task_id"] == task["id"]

    task_state = get_task(task["id"], storage_dir=storage_dir)
    assert task_state is not None
    assert task_state["status"] == "succeeded"


def test_scheduler_tick_routes_missing_template_to_coordinator(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "volpred.ops.scheduler._run_coordinator_round",
        lambda task, *, storage_dir: {
            "mode": "coordinator",
            "task_id": task["id"],
            "result": "brief_ready",
        },
    )

    storage_dir = str(tmp_path / "storage")
    task = create_task(
        title="Coordinator task",
        description="needs coordinator",
        task_family="research",
        preferred_agent="auto",
        payload={"brief_template": "missing.yaml"},
        storage_dir=storage_dir,
    )

    result = scheduler_tick(storage_dir=storage_dir)
    assert result["status"] == "ok"
    assert result["result"]["mode"] == "coordinator"
    assert result["result"]["task_id"] == task["id"]


def test_scheduler_routes_schedule_governance_tasks_to_claude_coordinator(tmp_path: Path, monkeypatch):
    templates_root = tmp_path / "brief_templates"
    _write_template(
        templates_root,
        "schedule-governance.yaml",
        """
task_summary: "{{title}}"
goal: "{{description}}"
success_criteria:
  - "done"
repo_root: "/Users/yhlai0911/Desktop/volpred-research"
required_files:
  - "config/runtime_schedules.json"
recommended_files: []
forbidden_large_files: []
relevant_commands: []
why_this_agent: "schedule governance"
""".strip(),
    )
    monkeypatch.setattr("volpred.ops.execution_brief.BRIEF_TEMPLATES_ROOT", templates_root)
    monkeypatch.setattr(
        "volpred.ops.scheduler._run_coordinator_round",
        lambda task, *, storage_dir: {
            "mode": "coordinator",
            "task_id": task["id"],
            "result": "brief_ready",
        },
    )

    storage_dir = str(tmp_path / "storage")
    task = create_task(
        title="Schedule proposal",
        description="codex proposes a new cron cadence",
        task_family="ops",
        preferred_agent="codex",
        payload={
            "governance_area": "schedule",
            "schedule_proposal": {"action": "adjust_cron", "cron": "*/15 * * * *"},
        },
        storage_dir=storage_dir,
    )

    preview = scheduler_preview(storage_dir=storage_dir)
    assert preview["decision"] is not None
    assert preview["decision"]["task_id"] == task["id"]
    assert preview["decision"]["mode"] == "coordinator"
    assert preview["decision"]["agent"] == "claude"

    result = scheduler_tick(storage_dir=storage_dir)
    assert result["status"] == "ok"
    assert result["result"]["mode"] == "coordinator"
    assert result["result"]["task_id"] == task["id"]


def test_scheduler_tick_skips_when_live_manual_agent_session_owns_target(tmp_path: Path, monkeypatch):
    templates_root = tmp_path / "brief_templates"
    _write_template(
        templates_root,
        "ops.yaml",
        """
task_summary: "{{title}}"
goal: "{{description}}"
success_criteria:
  - "done"
repo_root: "/Users/yhlai0911/Desktop/volpred-research"
required_files:
  - "docs/project_improvement_status.md"
recommended_files: []
forbidden_large_files: []
relevant_commands: []
why_this_agent: "ops template"
""".strip(),
    )
    monkeypatch.setattr("volpred.ops.execution_brief.BRIEF_TEMPLATES_ROOT", templates_root)

    storage_dir = str(tmp_path / "storage")
    heartbeat_agent(
        agent_name="codex",
        status="idle",
        session_id="manual:codex",
        storage_dir=storage_dir,
    )
    task = create_task(
        title="Codex busy elsewhere",
        description="scheduler should not steal codex",
        task_family="ops",
        preferred_agent="auto",
        storage_dir=storage_dir,
    )

    preview = scheduler_preview(storage_dir=storage_dir)
    assert preview["queued_count"] == 1
    assert preview["decision"] is None

    result = scheduler_tick(storage_dir=storage_dir)
    assert result["status"] == "skipped"
    assert result["reason"] == "no_runnable_work"

    task_state = get_task(task["id"], storage_dir=storage_dir)
    assert task_state is not None
    assert task_state["status"] == "queued"


def test_scheduler_tick_preflight_fail_does_not_double_fail(tmp_path: Path, monkeypatch):
    templates_root = tmp_path / "brief_templates"
    _write_template(
        templates_root,
        "ops.yaml",
        """
task_summary: "{{title}}"
goal: "{{description}}"
success_criteria:
  - "done"
repo_root: "/Users/yhlai0911/Desktop/volpred-research"
required_files:
  - "missing/required.txt"
recommended_files: []
forbidden_large_files: []
relevant_commands: []
why_this_agent: "ops template"
""".strip(),
    )
    monkeypatch.setattr("volpred.ops.execution_brief.BRIEF_TEMPLATES_ROOT", templates_root)
    monkeypatch.setattr("volpred.ops.execution_brief.check_agent_specs", lambda: {"clean": True, "issues": []})

    storage_dir = str(tmp_path / "storage")
    task = create_task(
        title="Fail closed task",
        description="missing file should fail once",
        task_family="ops",
        preferred_agent="auto",
        storage_dir=storage_dir,
    )

    result = scheduler_tick(storage_dir=storage_dir)
    assert result["status"] == "ok"
    assert result["result"]["mode"] == "executor"
    assert result["result"]["result"] == "preflight_failed"
    assert result["result"]["task_status"] == "failed"

    task_state = get_task(task["id"], storage_dir=storage_dir)
    assert task_state is not None
    assert task_state["status"] == "failed"
    assert len(task_state["executions"]) == 1
    assert task_state["executions"][0]["result_status"] == "failed"


def test_scheduler_skips_task_until_preconditions_exist(tmp_path: Path, monkeypatch):
    templates_root = tmp_path / "brief_templates"
    _write_template(
        templates_root,
        "ops.yaml",
        """
task_summary: "{{title}}"
goal: "{{description}}"
success_criteria:
  - "done"
repo_root: "/Users/yhlai0911/Desktop/volpred-research"
required_files:
  - "docs/project_improvement_status.md"
recommended_files: []
forbidden_large_files: []
relevant_commands: []
why_this_agent: "ops template"
""".strip(),
    )
    monkeypatch.setattr("volpred.ops.execution_brief.BRIEF_TEMPLATES_ROOT", templates_root)

    storage_dir = str(tmp_path / "storage")
    task = create_task(
        title="Event gated task",
        description="wait until source file arrives",
        task_family="ops",
        preferred_agent="auto",
        payload={"preconditions": ["storage/macro/cpi.json"]},
        storage_dir=storage_dir,
    )

    preview = scheduler_preview(storage_dir=storage_dir)
    assert preview["decision"] is None

    result = scheduler_tick(storage_dir=storage_dir)
    assert result["status"] == "skipped"
    assert result["reason"] == "no_runnable_work"

    task_state = get_task(task["id"], storage_dir=storage_dir)
    assert task_state is not None
    assert task_state["status"] == "queued"
