import json
from pathlib import Path

from volpred.ops.local_control_plane import (
    approve_task,
    build_control_plane_snapshot,
    claim_next_task,
    complete_task,
    create_task,
    fail_task,
    get_task,
    heartbeat_agent,
    requeue_task,
)


def test_claim_complete_and_execution_receipt(tmp_path: Path):
    storage_dir = str(tmp_path / "storage")

    task = create_task(
        title="Smoke task",
        description="verify claim flow",
        source="user",
        task_family="ops",
        preferred_agent="claude",
        created_by="pytest",
        storage_dir=storage_dir,
    )
    heartbeat_agent(
        agent_name="claude",
        status="idle",
        provider="anthropic",
        role_profile="research",
        session_id="claude:test-session",
        session_rollback_point_id="rollback:test",
        storage_dir=storage_dir,
    )

    claimed = claim_next_task("claude", storage_dir=storage_dir)
    assert claimed is not None
    assert claimed["id"] == task["id"]
    assert claimed["status"] == "claimed"

    result = complete_task(
        task["id"],
        agent_name="claude",
        summary="done",
        commands_run=["uv run volpred ops claim-next --agent claude"],
        files_touched=["src/volpred/ops/local_control_plane.py"],
        storage_dir=storage_dir,
    )
    assert result["task"]["status"] == "succeeded"
    assert result["receipt"]["result_status"] == "succeeded"

    task_state = get_task(task["id"], storage_dir=storage_dir)
    assert task_state is not None
    assert task_state["status"] == "succeeded"
    assert task_state["session_id"] == "claude:test-session"
    assert task_state["rollback_point_id"] == "rollback:test"
    assert len(task_state["executions"]) == 1
    assert task_state["executions"][0]["agent_name"] == "claude"
    assert task_state["executions"][0]["session_id"] == "claude:test-session"
    assert task_state["executions"][0]["rollback_point_id"] == "rollback:test"

    snapshot = build_control_plane_snapshot(storage_dir=storage_dir)
    assert snapshot["task_counts"]["succeeded"] == 1
    assert snapshot["brief_status_counts"]["pending"] == 1
    assert snapshot["agents"][0]["status"] == "idle"
    assert snapshot["agents"][0]["claimed_task_id"] is None
    assert snapshot["scheduler"]["last_status"] == "never"


def test_fallback_and_approval_flow(tmp_path: Path):
    storage_dir = str(tmp_path / "storage")

    blocking_task = create_task(
        title="Claude primary task",
        description="occupy preferred agent",
        source="schedule",
        task_family="research",
        preferred_agent="claude",
        storage_dir=storage_dir,
    )
    fallback_task = create_task(
        title="Codex fallback task",
        description="may be claimed by codex when claude is busy",
        source="agent",
        task_family="ops",
        preferred_agent="claude",
        fallback_allowed=True,
        storage_dir=storage_dir,
    )
    gated_task = create_task(
        title="Needs approval",
        description="destructive action should wait for approval",
        source="user",
        task_family="ops",
        preferred_agent="claude",
        approval_mode="needs_approval",
        risk_level="destructive",
        storage_dir=storage_dir,
    )
    assert gated_task["status"] == "awaiting_approval"

    heartbeat_agent(
        agent_name="claude",
        status="busy",
        claimed_task_id=blocking_task["id"],
        storage_dir=storage_dir,
    )
    heartbeat_agent(agent_name="codex", status="idle", storage_dir=storage_dir)

    claimed_by_codex = claim_next_task("codex", storage_dir=storage_dir)
    assert claimed_by_codex is not None
    assert claimed_by_codex["id"] == fallback_task["id"]
    assert claimed_by_codex["claimed_by"] == "codex"

    approved = approve_task(gated_task["id"], actor="owner", reason="approved for test", storage_dir=storage_dir)
    assert approved["status"] == "queued"
    assert approved["approved_by"] == "owner"

    failed = fail_task(
        fallback_task["id"],
        agent_name="codex",
        error="expected test failure",
        summary="simulate failure path",
        storage_dir=storage_dir,
    )
    assert failed["task"]["status"] == "failed"

    fallback_state = get_task(fallback_task["id"], storage_dir=storage_dir)
    assert fallback_state is not None
    assert fallback_state["executions"][0]["result_status"] == "failed"


def test_auto_routing_prefers_expected_agent(tmp_path: Path):
    storage_dir = str(tmp_path / "storage")

    research_task = create_task(
        title="Research auto task",
        description="route to claude",
        task_family="research",
        preferred_agent="auto",
        storage_dir=storage_dir,
    )
    code_task = create_task(
        title="Code auto task",
        description="route to codex",
        task_family="code",
        preferred_agent="auto",
        storage_dir=storage_dir,
    )
    strategy_task = create_task(
        title="Strategy auto task",
        description="route to codex",
        task_family="strategy",
        preferred_agent="auto",
        storage_dir=storage_dir,
    )

    assert research_task["preferred_agent"] == "claude"
    assert code_task["preferred_agent"] == "codex"
    assert strategy_task["preferred_agent"] == "codex"


def test_schedule_governance_tasks_always_route_to_claude(tmp_path: Path):
    storage_dir = str(tmp_path / "storage")

    auto_task = create_task(
        title="Schedule proposal",
        description="propose a new recurring cadence",
        task_family="ops",
        preferred_agent="auto",
        payload={
            "governance_area": "schedule",
            "schedule_proposal": {
                "action": "add_recurring",
                "cron": "*/10 * * * *",
            },
        },
        storage_dir=storage_dir,
    )
    explicit_codex_task = create_task(
        title="Codex asks for cron change",
        description="should still route to claude governance owner",
        task_family="ops",
        preferred_agent="codex",
        payload={
            "governance_area": "schedule",
            "schedule_proposal": {
                "action": "adjust_cron",
                "cron": "*/20 * * * *",
            },
        },
        storage_dir=storage_dir,
    )

    assert auto_task["preferred_agent"] == "claude"
    assert explicit_codex_task["preferred_agent"] == "claude"


def test_requeue_blocked_task_records_receipt(tmp_path: Path):
    storage_dir = str(tmp_path / "storage")
    task = create_task(
        title="Blocked task",
        description="will be requeued",
        task_family="ops",
        storage_dir=storage_dir,
    )
    task_path = tmp_path / "storage" / "ops" / "tasks" / f"{task['id']}.json"
    payload = json.loads(task_path.read_text(encoding="utf-8"))
    payload["status"] = "blocked"
    payload["last_error"] = "manual block for test"
    task_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    result = requeue_task(task["id"], actor="owner", reason="fixed underlying issue", storage_dir=storage_dir)

    assert result["task"]["status"] == "queued"
    state = get_task(task["id"], storage_dir=storage_dir)
    assert state is not None
    assert state["status"] == "queued"
    assert state["executions"][-1]["result_status"] == "requeued"
    assert state["executions"][-1]["summary"] == "fixed underlying issue"


def test_experiment_id_conflict_blocks_second_claim(tmp_path: Path):
    storage_dir = str(tmp_path / "storage")

    heartbeat_agent(
        agent_name="claude",
        status="idle",
        session_id="claude:exp",
        session_rollback_point_id="rollback:claude",
        storage_dir=storage_dir,
    )
    heartbeat_agent(
        agent_name="codex",
        status="idle",
        session_id="codex:exp",
        session_rollback_point_id="rollback:codex",
        storage_dir=storage_dir,
    )

    claude_task = create_task(
        title="Experiment research task",
        description="first task on experiment",
        task_family="research",
        preferred_agent="claude",
        payload={"experiment_id": "k999"},
        storage_dir=storage_dir,
    )
    codex_task = create_task(
        title="Experiment code task",
        description="second task on same experiment",
        task_family="code",
        preferred_agent="codex",
        payload={"experiment_id": "k999"},
        storage_dir=storage_dir,
    )

    claimed = claim_next_task("claude", storage_dir=storage_dir)
    assert claimed is not None
    assert claimed["id"] == claude_task["id"]

    blocked = claim_next_task("codex", storage_dir=storage_dir)
    assert blocked is None

    complete_task(claude_task["id"], agent_name="claude", summary="done", storage_dir=storage_dir)
    claimed_after = claim_next_task("codex", storage_dir=storage_dir)
    assert claimed_after is not None
    assert claimed_after["id"] == codex_task["id"]
