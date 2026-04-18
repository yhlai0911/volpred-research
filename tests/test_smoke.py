from __future__ import annotations

from pathlib import Path

from volpred.ops.smoke import _fake_subprocess_run, run_scheduler_live_smoke, run_scheduler_smoke


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


def test_run_scheduler_live_smoke_exercises_real_paths_with_safe_overrides(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: f"/tmp/{name}")
    monkeypatch.setattr("volpred.ops.execution_brief.subprocess.run", _fake_subprocess_run)

    result = run_scheduler_live_smoke(
        mode="all",
        base_dir=str(tmp_path / "scheduler-live-smoke"),
        keep_artifacts=True,
        snapshot_storage_dir=str(tmp_path / "snapshot-storage"),
    )

    assert result["runner"] == "live"
    assert result["cli_paths"]["claude"] == "/tmp/claude"
    assert result["cli_paths"]["codex"] == "/tmp/codex"
    assert result["summary"]["overall_status"] == "ready"
    assert result["summary"]["paths"]["coordinator"]["readiness"] == "ready"
    assert result["summary"]["paths"]["claude_executor"]["readiness"] == "ready"
    assert result["summary"]["paths"]["codex_executor"]["readiness"] == "ready"
    assert Path(result["snapshot_path"]).exists()

    coordinator = result["results"]["coordinator"]
    assert coordinator["tick"]["status"] == "ok"
    assert coordinator["tick"]["result"]["result"] == "brief_ready"

    claude_executor = result["results"]["claude_executor"]
    assert claude_executor["preview"]["decision"]["agent"] == "claude"
    assert claude_executor["tick"]["status"] == "ok"
    assert claude_executor["tick"]["result"]["result"] == "succeeded"

    codex_executor = result["results"]["codex_executor"]
    assert codex_executor["preview"]["decision"]["agent"] == "codex"
    assert codex_executor["tick"]["status"] == "ok"
    assert codex_executor["tick"]["result"]["result"] == "succeeded"


def test_run_scheduler_live_smoke_requires_installed_cli(tmp_path: Path, monkeypatch):
    def _which(name: str) -> str | None:
        return None if name == "codex" else f"/tmp/{name}"

    monkeypatch.setattr("shutil.which", _which)

    try:
        run_scheduler_live_smoke(
            mode="codex-executor",
            base_dir=str(tmp_path / "scheduler-live-smoke-missing-cli"),
            keep_artifacts=True,
        )
    except RuntimeError as exc:
        assert str(exc) == "missing_required_clis: codex"
    else:
        raise AssertionError("live smoke should fail when required CLI is missing")


def test_run_scheduler_live_smoke_classifies_claude_auth_gap(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: f"/tmp/{name}")

    def _fake_run_with_auth_gap(*args, **kwargs):
        call = args[0]
        if call[:2] == ["claude", "-p"]:
            return __import__("subprocess").CompletedProcess(
                args=call,
                returncode=0,
                stdout="Not logged in · Please run /login",
                stderr="",
            )
        return _fake_subprocess_run(*args, **kwargs)

    monkeypatch.setattr("volpred.ops.execution_brief.subprocess.run", _fake_run_with_auth_gap)

    result = run_scheduler_live_smoke(
        mode="all",
        base_dir=str(tmp_path / "scheduler-live-smoke-auth-gap"),
        keep_artifacts=True,
    )

    assert result["summary"]["overall_status"] == "degraded"
    assert result["summary"]["paths"]["coordinator"]["reason_code"] == "auth_required"
    assert result["summary"]["paths"]["claude_executor"]["reason_code"] == "auth_required"
    assert result["summary"]["paths"]["codex_executor"]["readiness"] == "ready"
