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
    assert len(task_state["executions"]) == 1
    assert task_state["executions"][0]["agent_name"] == "claude"

    snapshot = build_control_plane_snapshot(storage_dir=storage_dir)
    assert snapshot["task_counts"]["succeeded"] == 1
    assert snapshot["agents"][0]["status"] == "idle"
    assert snapshot["agents"][0]["claimed_task_id"] is None


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
