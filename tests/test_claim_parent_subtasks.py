from pathlib import Path

# 2026-07-04: this file used to hand-load local_control_plane via importlib and
# OVERWRITE sys.modules["volpred.ops.local_control_plane"] with a fresh module
# object at import time — a permanent, never-reverted global side effect. Any
# later test that `monkeypatch.setattr("volpred.ops.local_control_plane.X", ...)`
# then patched a DIFFERENT module object than the app code imported, so the
# patch silently missed (e.g. test_dreaming_review's create_task stub → the
# REAL create_task ran, dispatching a real task, failing the assertion — only
# in the full suite, never in isolation). conftest.py already puts src/ on the
# path, so the module imports normally; use the canonical import and stop
# polluting sys.modules for every subsequently-collected test.
from volpred.ops.local_control_plane import (  # noqa: E402
    claim_next_task,
    create_task,
    get_task,
    heartbeat_agent,
)


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
