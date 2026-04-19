from pathlib import Path

import pytest

from volpred.ops.local_control_plane import create_task, get_agent_session, get_task
from volpred.ops.session import session_bootstrap, session_finish_task, session_next_task, session_shutdown


@pytest.fixture
def patched_session_bootstrap(monkeypatch):
    monkeypatch.setenv("VOLPRED_ACTOR", "claude")
    monkeypatch.setattr(
        "volpred.ops.session.create_rollback_point",
        lambda **kwargs: {"point_id": kwargs.get("point_id") or "rollback:test"},
    )
    monkeypatch.setattr("volpred.ops.execution_brief.check_agent_specs", lambda: {"clean": True, "issues": []})


def test_session_bootstrap_claim_finish_and_shutdown(tmp_path: Path, patched_session_bootstrap):
    storage_dir = str(tmp_path / "storage")

    bootstrap = session_bootstrap("claude", storage_dir=storage_dir, session_id="claude:test-session")
    assert bootstrap["session"]["session_id"] == "claude:test-session"
    assert bootstrap["session"]["session_rollback_point_id"] == bootstrap["rollback_point"]["point_id"]

    task = create_task(
        title="Session task",
        description="claim via session wrapper",
        task_family="research",
        preferred_agent="auto",
        storage_dir=storage_dir,
    )

    claimed = session_next_task("claude", storage_dir=storage_dir)
    assert claimed["task"] is not None
    assert claimed["task"]["id"] == task["id"]
    assert claimed["task"]["rollback_point_id"] == bootstrap["rollback_point"]["point_id"]

    finished = session_finish_task(
        task["id"],
        agent_name="claude",
        summary="session wrapper done",
        storage_dir=storage_dir,
    )
    assert finished["task"]["status"] == "succeeded"
    assert finished["receipt"]["session_id"] == "claude:test-session"
    assert finished["receipt"]["rollback_point_id"] == bootstrap["rollback_point"]["point_id"]

    task_state = get_task(task["id"], storage_dir=storage_dir)
    assert task_state is not None
    assert task_state["executions"][-1]["session_id"] == "claude:test-session"

    shutdown = session_shutdown("claude", storage_dir=storage_dir)
    assert shutdown["session"]["status"] == "offline"
    session = get_agent_session("claude", storage_dir=storage_dir)
    assert session is not None
    assert session["claimed_task_id"] is None


def test_session_bootstrap_requires_matching_actor(tmp_path: Path, monkeypatch):
    storage_dir = str(tmp_path / "storage")
    monkeypatch.delenv("VOLPRED_ACTOR", raising=False)
    with pytest.raises(RuntimeError, match="VOLPRED_ACTOR mismatch"):
        session_bootstrap("claude", storage_dir=storage_dir)


def test_session_next_task_skips_supervisor_gated_tasks_and_emits_brief(tmp_path: Path, monkeypatch):
    templates_root = tmp_path / "brief_templates"
    templates_root.mkdir(parents=True, exist_ok=True)
    (templates_root / "code.yaml").write_text(
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
why_this_agent: "code template"
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("VOLPRED_ACTOR", "codex")
    monkeypatch.setattr(
        "volpred.ops.session.create_rollback_point",
        lambda **kwargs: {"point_id": kwargs.get("point_id") or "rollback:test"},
    )
    monkeypatch.setattr("volpred.ops.execution_brief.BRIEF_TEMPLATES_ROOT", templates_root)
    monkeypatch.setattr("volpred.ops.execution_brief.check_agent_specs", lambda: {"clean": True, "issues": []})

    storage_dir = str(tmp_path / "storage")
    session_bootstrap("codex", storage_dir=storage_dir, session_id="codex:worker")

    supervisor_task = create_task(
        title="Supervisor brief required",
        description="no template should be claimed by a worker",
        task_family="code",
        preferred_agent="auto",
        payload={"brief_template": "missing.yaml"},
        storage_dir=storage_dir,
    )
    worker_task = create_task(
        title="Worker template task",
        description="template-backed task",
        task_family="code",
        preferred_agent="auto",
        storage_dir=storage_dir,
    )

    claimed = session_next_task("codex", storage_dir=storage_dir, emit_brief=True)
    assert claimed["task"] is not None
    assert claimed["task"]["id"] == worker_task["id"]
    assert claimed["brief"] is not None
    assert claimed["brief"]["source_type"] == "template"

    supervisor_state = get_task(supervisor_task["id"], storage_dir=storage_dir)
    assert supervisor_state is not None
    assert supervisor_state["status"] == "queued"
    assert supervisor_state["claimed_by"] is None
    assert supervisor_state["brief_status"] == "stale"


def test_session_bootstrap_prefers_legacy_agent_spec_path(tmp_path: Path, monkeypatch):
    storage_dir = str(tmp_path / "storage")
    legacy_root = tmp_path / "legacy-agent-specs"
    legacy_root.mkdir(parents=True, exist_ok=True)
    legacy_guide = legacy_root / "guide.md"
    legacy_guide.write_text("# Legacy Guide\n\nUse legacy path first.\n", encoding="utf-8")
    claude_rule = tmp_path / "agent-delegation.md"
    claude_rule.write_text("# Claude Rule\n\nShould not be used when legacy exists.\n", encoding="utf-8")

    monkeypatch.setenv("VOLPRED_ACTOR", "codex")
    monkeypatch.setattr(
        "volpred.ops.session.create_rollback_point",
        lambda **kwargs: {"point_id": kwargs.get("point_id") or "rollback:test"},
    )
    monkeypatch.setattr("volpred.ops.session.LEGACY_AGENT_SPEC_GUIDE", tmp_path / "missing-guide.md")
    monkeypatch.setattr("volpred.ops.session.CLAUDE_AGENT_DELEGATION_GUIDE", claude_rule)

    bootstrap = session_bootstrap(
        "codex",
        storage_dir=storage_dir,
        session_id="codex:legacy",
        agent_spec_path=str(legacy_root),
    )

    assert bootstrap["guide"]["source"] == "legacy_agent_spec"
    assert bootstrap["guide"]["path"] == str(legacy_guide)
    assert bootstrap["agent_spec"]["path"] == str(legacy_guide)
    assert bootstrap["agent_spec"]["exists"] is True


def test_session_bootstrap_falls_back_to_claude_rule(tmp_path: Path, monkeypatch):
    storage_dir = str(tmp_path / "storage")
    claude_rule = tmp_path / "agent-delegation.md"
    claude_rule.write_text("# Claude Rule\n\nFallback rule content.\n", encoding="utf-8")

    monkeypatch.setenv("VOLPRED_ACTOR", "codex")
    monkeypatch.setattr(
        "volpred.ops.session.create_rollback_point",
        lambda **kwargs: {"point_id": kwargs.get("point_id") or "rollback:test"},
    )
    monkeypatch.setattr("volpred.ops.session.LEGACY_AGENT_SPEC_GUIDE", tmp_path / "missing-guide.md")
    monkeypatch.setattr("volpred.ops.session.CLAUDE_AGENT_DELEGATION_GUIDE", claude_rule)

    bootstrap = session_bootstrap(
        "codex",
        storage_dir=storage_dir,
        session_id="codex:claude-rule",
    )

    assert bootstrap["guide"]["source"] == "claude_rule"
    assert bootstrap["guide"]["path"] == str(claude_rule)
    assert bootstrap["guide"]["preview"] == "# Claude Rule Fallback rule content."


def test_session_bootstrap_falls_back_to_inline_default_and_can_skip(tmp_path: Path, monkeypatch):
    storage_dir = str(tmp_path / "storage")
    missing_legacy = tmp_path / "missing-guide.md"
    missing_rule = tmp_path / "missing-agent-delegation.md"

    monkeypatch.setenv("VOLPRED_ACTOR", "codex")
    monkeypatch.setattr(
        "volpred.ops.session.create_rollback_point",
        lambda **kwargs: {"point_id": kwargs.get("point_id") or "rollback:test"},
    )
    monkeypatch.setattr("volpred.ops.session.LEGACY_AGENT_SPEC_GUIDE", missing_legacy)
    monkeypatch.setattr("volpred.ops.session.CLAUDE_AGENT_DELEGATION_GUIDE", missing_rule)

    fallback = session_bootstrap(
        "codex",
        storage_dir=storage_dir,
        session_id="codex:inline",
    )
    assert fallback["guide"]["source"] == "inline_default"
    assert "Volpred Session Bootstrap" in fallback["guide"]["preview"]
    assert fallback["agent_spec"]["exists"] is False

    skipped = session_bootstrap(
        "codex",
        storage_dir=storage_dir,
        session_id="codex:no-guide",
        no_guide=True,
    )
    assert skipped["guide"]["source"] == "skipped"
    assert skipped["guide"]["skipped"] is True
    assert skipped["guide"]["loaded"] is False
