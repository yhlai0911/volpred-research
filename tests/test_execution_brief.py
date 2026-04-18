from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from volpred.ops.execution_brief import (
    BriefContent,
    ExecutorResult,
    _codex_output_schema,
    build_execution_brief,
    preview_execution_brief,
    preflight_executor_task,
    run_coordinator_brief,
    run_executor_task,
    set_execution_brief,
    task_brief_is_ready,
    task_brief_is_stale,
    task_unmet_preconditions,
)
from volpred.ops.local_control_plane import create_task, get_task


def _write_template(root: Path, name: str, body: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / name).write_text(body, encoding="utf-8")


def _task_path(storage_dir: Path, task_id: str) -> Path:
    return storage_dir / "ops" / "tasks" / f"{task_id}.json"


def _execution_dir(storage_dir: Path, task_id: str) -> Path:
    path = storage_dir / "ops" / "executions" / task_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_template_brief_includes_recent_findings(tmp_path: Path, monkeypatch):
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
recommended_files:
  - "AGENTS.md"
forbidden_large_files:
  - "storage/reports/feed.json"
relevant_commands:
  - "uv run volpred ops health"
why_this_agent: "ops template"
""".strip(),
    )
    monkeypatch.setattr("volpred.ops.execution_brief.BRIEF_TEMPLATES_ROOT", templates_root)

    storage_dir = tmp_path / "storage"
    task = create_task(
        title="Ops brief task",
        description="collect recent findings",
        task_family="ops",
        preferred_agent="auto",
        storage_dir=str(storage_dir),
    )

    execution_dir = _execution_dir(storage_dir, task["id"])
    base = datetime(2026, 4, 17, 8, 0, tzinfo=timezone.utc)
    receipts = [
        ("run_old", "older summary", None, base),
        ("run_mid", None, "mid error", base + timedelta(minutes=1)),
        ("run_new", "new summary", None, base + timedelta(minutes=2)),
        ("run_latest", "latest summary", None, base + timedelta(minutes=3)),
    ]
    for run_id, summary, error, timestamp in receipts:
        (execution_dir / f"{run_id}.json").write_text(
            json.dumps(
                {
                    "task_id": task["id"],
                    "run_id": run_id,
                    "agent_name": "claude",
                    "result_status": "failed" if error else "succeeded",
                    "summary": summary,
                    "commands_run": [],
                    "files_touched": [],
                    "subagent_count": 0,
                    "session_id": None,
                    "rollback_point_id": None,
                    "timestamp": timestamp.isoformat(),
                    "error": error,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    brief = build_execution_brief(task["id"], storage_dir=str(storage_dir))
    assert brief is not None
    assert brief["source_type"] == "template"
    assert brief["prior_findings"] == [
        "latest summary",
        "new summary",
        "error: mid error",
    ]

    task_state = get_task(task["id"], storage_dir=str(storage_dir))
    assert task_state is not None
    assert task_state["brief_status"] == "ready"


def test_task_brief_stale_when_task_updated_or_template_changes(tmp_path: Path, monkeypatch):
    templates_root = tmp_path / "brief_templates"
    template_path = templates_root / "ops.yaml"
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

    storage_dir = tmp_path / "storage"
    task = create_task(
        title="Stale brief task",
        description="check staleness",
        task_family="ops",
        preferred_agent="auto",
        storage_dir=str(storage_dir),
    )

    brief = build_execution_brief(task["id"], storage_dir=str(storage_dir))
    assert brief is not None

    task_state = get_task(task["id"], storage_dir=str(storage_dir))
    assert task_state is not None
    assert task_brief_is_ready(task_state) is True
    assert task_brief_is_stale(task_state) is False

    task_file = _task_path(storage_dir, task["id"])
    payload = json.loads(task_file.read_text(encoding="utf-8"))
    payload["updated_at"] = (datetime.fromisoformat(brief["generated_at"]) + timedelta(seconds=1)).isoformat()
    task_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    task_state = get_task(task["id"], storage_dir=str(storage_dir))
    assert task_state is not None
    assert task_brief_is_stale(task_state) is True
    assert task_brief_is_ready(task_state) is False

    payload["updated_at"] = brief["generated_at"]
    task_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    template_path.write_text(
        """
task_summary: "{{title}}"
goal: "{{description}}"
success_criteria:
  - "changed"
repo_root: "/Users/yhlai0911/Desktop/volpred-research"
required_files:
  - "docs/project_improvement_status.md"
recommended_files: []
forbidden_large_files: []
relevant_commands: []
why_this_agent: "ops template"
""".strip(),
        encoding="utf-8",
    )

    task_state = get_task(task["id"], storage_dir=str(storage_dir))
    assert task_state is not None
    assert task_brief_is_stale(task_state) is True


def test_preflight_marks_missing_required_files_failed(tmp_path: Path, monkeypatch):
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
  - "missing/file.txt"
recommended_files: []
forbidden_large_files: []
relevant_commands: []
why_this_agent: "ops template"
""".strip(),
    )
    monkeypatch.setattr("volpred.ops.execution_brief.BRIEF_TEMPLATES_ROOT", templates_root)
    monkeypatch.setattr("volpred.ops.execution_brief.check_agent_specs", lambda: {"clean": True, "issues": []})

    storage_dir = tmp_path / "storage"
    task = create_task(
        title="Missing files task",
        description="should fail preflight",
        task_family="ops",
        preferred_agent="auto",
        storage_dir=str(storage_dir),
    )

    try:
        preflight_executor_task(task["id"], agent_name="codex", storage_dir=str(storage_dir))
    except RuntimeError as exc:
        assert str(exc) == "required_files_missing"
    else:  # pragma: no cover
        raise AssertionError("preflight should have failed")

    task_state = get_task(task["id"], storage_dir=str(storage_dir))
    assert task_state is not None
    assert task_state["status"] == "failed"
    assert task_state["last_error"] == "required_files_missing: missing/file.txt"
    assert len(task_state["executions"]) == 1
    assert task_state["executions"][0]["result_status"] == "failed"


def test_schedule_governance_tasks_use_schedule_template(tmp_path: Path, monkeypatch):
    templates_root = tmp_path / "brief_templates"
    _write_template(
        templates_root,
        "ops.yaml",
        """
task_summary: "generic ops"
goal: "generic ops"
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
    _write_template(
        templates_root,
        "schedule-governance.yaml",
        """
task_summary: "{{title}}"
goal: "govern schedule changes for {{description}}\\n{{schedule_proposal_json}}"
success_criteria:
  - "keep canonical schedule clean"
repo_root: "/Users/yhlai0911/Desktop/volpred-research"
required_files:
  - "config/runtime_schedules.json"
recommended_files:
  - "scripts/install_scheduler_cron.sh"
forbidden_large_files:
  - "storage/reports/feed.json"
relevant_commands:
  - "uv run volpred ops scheduler-preview"
why_this_agent: "claude governs schedule"
""".strip(),
    )
    monkeypatch.setattr("volpred.ops.execution_brief.BRIEF_TEMPLATES_ROOT", templates_root)

    storage_dir = tmp_path / "storage"
    task = create_task(
        title="Schedule governance task",
        description="adjust cron cadence",
        task_family="ops",
        preferred_agent="auto",
        payload={
            "governance_area": "schedule",
            "schedule_proposal": {"action": "adjust_cron", "cron": "*/20 * * * *"},
        },
        storage_dir=str(storage_dir),
    )

    brief = build_execution_brief(task["id"], storage_dir=str(storage_dir))
    assert brief is not None
    assert brief["template_id"] == "schedule-governance.yaml"
    assert brief["required_files"] == ["config/runtime_schedules.json"]
    assert "\"action\": \"adjust_cron\"" in brief["goal"]


def test_preflight_requeues_when_preconditions_are_not_met(tmp_path: Path, monkeypatch):
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

    storage_dir = tmp_path / "storage"
    task = create_task(
        title="Precondition gated task",
        description="wait for upstream artifact",
        task_family="ops",
        preferred_agent="auto",
        payload={"preconditions": ["storage/macro/cpi.json"]},
        storage_dir=str(storage_dir),
    )

    assert task_unmet_preconditions(task) == ["storage/macro/cpi.json"]

    try:
        preflight_executor_task(task["id"], agent_name="codex", storage_dir=str(storage_dir))
    except RuntimeError as exc:
        assert str(exc) == "preconditions_not_met"
    else:  # pragma: no cover
        raise AssertionError("preflight should have requeued task")

    task_state = get_task(task["id"], storage_dir=str(storage_dir))
    assert task_state is not None
    assert task_state["status"] == "queued"
    assert task_state["last_error"] == "preconditions_not_met: storage/macro/cpi.json"


def test_supervisor_can_preview_and_set_manual_brief(tmp_path: Path, monkeypatch):
    templates_root = tmp_path / "brief_templates"
    templates_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("volpred.ops.execution_brief.BRIEF_TEMPLATES_ROOT", templates_root)

    storage_dir = tmp_path / "storage"
    task = create_task(
        title="Manual brief task",
        description="needs supervisor-authored brief",
        task_family="research",
        preferred_agent="auto",
        payload={"brief_template": "missing.yaml"},
        storage_dir=str(storage_dir),
    )

    preview = preview_execution_brief(task["id"], storage_dir=str(storage_dir))
    assert preview["requires_supervisor"] is True
    assert preview["brief"] is None
    assert preview["suggested_brief"]["task_summary"] == "Manual brief task"

    stored = set_execution_brief(
        task["id"],
        actor="claude-supervisor",
        brief_payload={
            **preview["suggested_brief"],
            "success_criteria": ["task completed in VS Code worker terminal"],
            "required_files": ["docs/project_improvement_status.md"],
            "why_this_agent": "supervisor assigned this to a worker terminal",
        },
        storage_dir=str(storage_dir),
    )
    assert stored["brief_status"] == "ready"
    assert stored["brief_payload"]["source_type"] == "supervisor"

    task_state = get_task(task["id"], storage_dir=str(storage_dir))
    assert task_state is not None
    assert task_state["brief_status"] == "ready"
    assert task_state["brief_payload"]["source_type"] == "supervisor"


def test_run_coordinator_brief_timeout_blocks_task(tmp_path: Path, monkeypatch):
    storage_dir = tmp_path / "storage"
    task = create_task(
        title="Coordinator timeout task",
        description="should fail closed when claude hangs",
        task_family="research",
        preferred_agent="auto",
        payload={"brief_template": "missing.yaml"},
        storage_dir=str(storage_dir),
    )

    def _timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs.get("timeout", 0))

    monkeypatch.setattr("volpred.ops.execution_brief.subprocess.run", _timeout)

    try:
        run_coordinator_brief(task["id"], storage_dir=str(storage_dir))
    except RuntimeError as exc:
        assert str(exc) == "coordinator_timeout_after_90s"
    else:  # pragma: no cover
        raise AssertionError("coordinator timeout should fail")

    task_state = get_task(task["id"], storage_dir=str(storage_dir))
    assert task_state is not None
    assert task_state["status"] == "blocked"
    assert task_state["brief_status"] == "needs_manual_review"
    assert "coordinator_timeout_after_90s" in str(task_state["last_error"])
    assert len(task_state["executions"]) == 1
    assert task_state["executions"][0]["result_status"] == "blocked_preflight"


def test_run_executor_task_timeout_raises_runtime_error(tmp_path: Path, monkeypatch):
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
    monkeypatch.setattr("volpred.ops.execution_brief.check_agent_specs", lambda: {"clean": True, "issues": []})

    storage_dir = tmp_path / "storage"
    task = create_task(
        title="Executor timeout task",
        description="read only timeout smoke",
        task_family="ops",
        preferred_agent="claude",
        storage_dir=str(storage_dir),
    )

    def _timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs.get("timeout", 0))

    monkeypatch.setattr("volpred.ops.execution_brief.subprocess.run", _timeout)

    try:
        run_executor_task(task["id"], agent_name="claude", storage_dir=str(storage_dir))
    except RuntimeError as exc:
        assert str(exc) == "claude_executor_timeout_after_180s"
    else:  # pragma: no cover
        raise AssertionError("executor timeout should fail")


def test_pydantic_schemas_forbid_additional_properties():
    brief_schema = BriefContent.model_json_schema()
    executor_schema = ExecutorResult.model_json_schema()
    codex_schema = _codex_output_schema()

    assert brief_schema["additionalProperties"] is False
    assert executor_schema["additionalProperties"] is False
    assert codex_schema["additionalProperties"] is False
    assert codex_schema["required"] == ["summary", "commands_run", "files_touched"]


def test_run_coordinator_brief_unwraps_claude_json_envelope(tmp_path: Path, monkeypatch):
    storage_dir = tmp_path / "storage"
    task = create_task(
        title="Coordinator envelope task",
        description="should unwrap Claude result envelope",
        task_family="research",
        preferred_agent="auto",
        payload={"brief_template": "missing.yaml"},
        storage_dir=str(storage_dir),
    )

    payload = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": json.dumps(
            {
                "task_summary": "Envelope brief",
                "goal": "Confirm envelope parsing works",
                "success_criteria": ["return valid JSON"],
                "repo_root": "/Users/yhlai0911/Desktop/volpred-research",
                "required_files": ["docs/project_improvement_status.md"],
                "recommended_files": [],
                "forbidden_large_files": [],
                "relevant_commands": [],
                "prior_findings": [],
                "rollback_point_id": None,
                "why_this_agent": "Claude coordinator",
            },
            ensure_ascii=False,
        ),
    }

    monkeypatch.setattr(
        "volpred.ops.execution_brief.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout=json.dumps(payload, ensure_ascii=False),
            stderr="",
        ),
    )

    brief = run_coordinator_brief(task["id"], storage_dir=str(storage_dir))
    assert brief["task_summary"] == "Envelope brief"


def test_run_coordinator_brief_surfaces_claude_json_envelope_errors(tmp_path: Path, monkeypatch):
    storage_dir = tmp_path / "storage"
    task = create_task(
        title="Coordinator envelope error task",
        description="should surface Claude auth error",
        task_family="research",
        preferred_agent="auto",
        payload={"brief_template": "missing.yaml"},
        storage_dir=str(storage_dir),
    )

    payload = {
        "type": "result",
        "subtype": "success",
        "is_error": True,
        "result": "Not logged in · Please run /login",
    }

    monkeypatch.setattr(
        "volpred.ops.execution_brief.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout=json.dumps(payload, ensure_ascii=False),
            stderr="",
        ),
    )

    try:
        run_coordinator_brief(task["id"], storage_dir=str(storage_dir))
    except RuntimeError as exc:
        assert str(exc) == "Not logged in · Please run /login"
    else:  # pragma: no cover
        raise AssertionError("coordinator envelope error should fail")


def test_run_coordinator_brief_surfaces_plain_text_errors(tmp_path: Path, monkeypatch):
    storage_dir = tmp_path / "storage"
    task = create_task(
        title="Coordinator plain text error task",
        description="should surface plain text cli errors",
        task_family="research",
        preferred_agent="auto",
        payload={"brief_template": "missing.yaml"},
        storage_dir=str(storage_dir),
    )

    monkeypatch.setattr(
        "volpred.ops.execution_brief.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout="Not logged in · Please run /login",
            stderr="",
        ),
    )

    try:
        run_coordinator_brief(task["id"], storage_dir=str(storage_dir))
    except RuntimeError as exc:
        assert str(exc) == "Not logged in · Please run /login"
    else:  # pragma: no cover
        raise AssertionError("plain text coordinator errors should fail")
