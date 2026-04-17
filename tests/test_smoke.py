from __future__ import annotations

from pathlib import Path

from volpred.ops.smoke import run_scheduler_smoke


def test_run_scheduler_smoke_exercises_coordinator_and_executor_paths(tmp_path: Path):
    result = run_scheduler_smoke(
        mode="both",
        base_dir=str(tmp_path / "scheduler-smoke"),
        keep_artifacts=True,
    )

    assert result["mode"] == "both"
    assert Path(result["root_dir"]).exists()
    assert Path(result["paths"]["brief_templates_root"]).exists()
    assert Path(result["paths"]["agent_prompts_root"]).exists()

    coordinator = result["results"]["coordinator"]
    assert coordinator["preview"]["decision"] is not None
    assert coordinator["preview"]["decision"]["mode"] == "coordinator"
    assert coordinator["preview"]["decision"]["agent"] == "claude"
    assert coordinator["tick"]["status"] == "ok"
    assert coordinator["tick"]["result"]["result"] == "brief_ready"
    assert coordinator["task"]["status"] == "queued"
    assert coordinator["task"]["brief_status"] == "ready"

    executor = result["results"]["executor"]
    assert executor["preview"]["decision"] is not None
    assert executor["preview"]["decision"]["mode"] == "executor"
    assert executor["preview"]["decision"]["agent"] == "codex"
    assert executor["tick"]["status"] == "ok"
    assert executor["tick"]["result"]["result"] == "succeeded"
    assert executor["task"]["status"] == "succeeded"
    assert executor["scheduler_state"]["last_status"] == "ok"


def test_run_scheduler_smoke_cleanup_removes_temp_directory():
    result = run_scheduler_smoke(mode="coordinator", keep_artifacts=False)
    assert result["artifacts_retained"] is False
    assert not Path(result["root_dir"]).exists()

