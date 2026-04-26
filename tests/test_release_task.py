import importlib.util
import sys
import types
from pathlib import Path

import pytest


def _load_local_control_plane():
    repo_root = Path(__file__).resolve().parents[1]
    src_root = repo_root / "src" / "volpred"
    ops_root = src_root / "ops"

    if "volpred" not in sys.modules:
        volpred_pkg = types.ModuleType("volpred")
        volpred_pkg.__path__ = [str(src_root)]
        sys.modules["volpred"] = volpred_pkg
    if "volpred.ops" not in sys.modules:
        ops_pkg = types.ModuleType("volpred.ops")
        ops_pkg.__path__ = [str(ops_root)]
        sys.modules["volpred.ops"] = ops_pkg

    common_spec = importlib.util.spec_from_file_location(
        "volpred.ops.common", ops_root / "common.py"
    )
    assert common_spec is not None and common_spec.loader is not None
    common_module = importlib.util.module_from_spec(common_spec)
    sys.modules["volpred.ops.common"] = common_module
    common_spec.loader.exec_module(common_module)

    plane_spec = importlib.util.spec_from_file_location(
        "volpred.ops.local_control_plane", ops_root / "local_control_plane.py"
    )
    assert plane_spec is not None and plane_spec.loader is not None
    plane_module = importlib.util.module_from_spec(plane_spec)
    sys.modules["volpred.ops.local_control_plane"] = plane_module
    plane_spec.loader.exec_module(plane_module)
    return plane_module


local_control_plane = _load_local_control_plane()
claim_next_task = local_control_plane.claim_next_task
create_task = local_control_plane.create_task
get_task = local_control_plane.get_task
heartbeat_agent = local_control_plane.heartbeat_agent
release_task = local_control_plane.release_task


def test_release_task_returns_claimed_task_to_queue(tmp_path: Path):
    storage_dir = str(tmp_path / "storage")
    heartbeat_agent(session_key="claude-worker", storage_dir=storage_dir)

    task = create_task(
        title="Test task to release",
        description="Will be claimed then released",
        source="user",
        task_family="ops",
        priority=42,
        preferred_agent="claude",
        fallback_allowed=False,
        approval_mode="auto",
        risk_level="safe",
        storage_dir=storage_dir,
    )

    claimed = claim_next_task(
        agent_name="claude",
        session_key="claude-worker",
        role="worker",
        storage_dir=storage_dir,
    )
    assert claimed is not None
    assert claimed["status"] == "claimed"
    assert claimed["claimed_by"] == "claude"
    assert claimed["claimed_by_session_key"] == "claude-worker"
    original_priority = claimed["priority"]
    assert original_priority == 42

    released = release_task(
        task["id"],
        reason="codex CLI is offline; pivot to manual implementation",
        actor="supervisor",
        storage_dir=storage_dir,
    )

    assert released["status"] == "queued"
    assert released["claimed_by"] is None
    assert released["claimed_by_session_key"] is None
    assert released["claimed_by_role"] is None
    assert released["claimed_at"] is None
    # Priority preserved (the central regression this CLI exists to fix)
    assert released["priority"] == original_priority
    # Audit trail in last_error
    assert "released_from_claimed" in (released["last_error"] or "")
    assert "codex CLI is offline" in (released["last_error"] or "")


def test_release_task_rejects_terminal_status(tmp_path: Path):
    storage_dir = str(tmp_path / "storage")
    heartbeat_agent(session_key="claude-worker", storage_dir=storage_dir)
    task = create_task(
        title="Already queued task",
        description="Should not be releasable while still queued",
        source="user",
        task_family="ops",
        priority=10,
        preferred_agent="claude",
        fallback_allowed=False,
        approval_mode="auto",
        risk_level="safe",
        storage_dir=storage_dir,
    )

    with pytest.raises(ValueError, match="Cannot release"):
        release_task(
            task["id"],
            reason="should be rejected",
            actor="supervisor",
            storage_dir=storage_dir,
        )


def test_released_task_can_be_reclaimed(tmp_path: Path):
    storage_dir = str(tmp_path / "storage")
    heartbeat_agent(session_key="claude-worker", storage_dir=storage_dir)
    task = create_task(
        title="Re-claimable after release",
        description="claim -> release -> claim cycle",
        source="user",
        task_family="ops",
        priority=99,
        preferred_agent="claude",
        fallback_allowed=False,
        approval_mode="auto",
        risk_level="safe",
        storage_dir=storage_dir,
    )

    first = claim_next_task(
        agent_name="claude",
        session_key="claude-worker",
        role="worker",
        storage_dir=storage_dir,
    )
    assert first is not None and first["id"] == task["id"]

    release_task(
        task["id"],
        reason="pivot",
        actor="supervisor",
        storage_dir=storage_dir,
    )

    # Worker that was busy with the released task should be free again, so the
    # next heartbeat-and-claim cycle can re-acquire it.
    heartbeat_agent(session_key="claude-worker", storage_dir=storage_dir)
    second = claim_next_task(
        agent_name="claude",
        session_key="claude-worker",
        role="worker",
        storage_dir=storage_dir,
    )
    assert second is not None
    assert second["id"] == task["id"]
    assert second["status"] == "claimed"
    assert second["priority"] == 99
