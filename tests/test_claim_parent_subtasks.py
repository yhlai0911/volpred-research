import importlib.util
import sys
import types
from pathlib import Path


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


def test_claim_next_skips_queued_parent_until_queued_subtasks_are_claimed(tmp_path: Path):
    storage_dir = str(tmp_path / "storage")
    heartbeat_agent(session_key="codex-worker", storage_dir=storage_dir)

    parent = create_task(
        title="Parent meta task",
        description="should not be directly claim-executed while queued subs exist",
        source="user",
        task_family="ops",
        priority=12,
        preferred_agent="codex",
        storage_dir=storage_dir,
    )
    subtask = create_task(
        title="Concrete queued subtask",
        description="should be claimed before its queued parent",
        source="user",
        task_family="ops",
        priority=17,
        preferred_agent="codex",
        parent_task_id=parent["id"],
        storage_dir=storage_dir,
    )

    claimed = claim_next_task(session_key="codex-worker", storage_dir=storage_dir)

    assert claimed is not None
    assert claimed["id"] == subtask["id"]
    assert claimed["parent_task_id"] == parent["id"]
    assert get_task(parent["id"], storage_dir=storage_dir)["status"] == "queued"
