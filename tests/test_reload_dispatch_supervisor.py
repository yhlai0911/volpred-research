from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "reload_dispatch_supervisor.sh"


def _check(tmp_path: Path, payload: str | dict) -> subprocess.CompletedProcess[str]:
    state = tmp_path / "dispatch_state.json"
    state.write_text(payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8")
    return subprocess.run(
        ["bash", str(SCRIPT)], cwd=ROOT, capture_output=True, text=True,
        env={
            **os.environ,
            "DISPATCH_STATE_PATH": str(state),
            "VOLPRED_RELOAD_CHECK_ONLY": "1",
        },
        check=False,
    )


def test_reload_guard_sees_legacy_job_when_new_list_is_empty(tmp_path: Path) -> None:
    result = _check(tmp_path, {"current_jobs": [], "current_job": {"pid": 123}})
    assert result.returncode == 1
    assert "in-flight worker" in result.stderr


def test_reload_guard_accepts_fully_drained_state(tmp_path: Path) -> None:
    result = _check(tmp_path, {"current_jobs": [], "current_job": None, "phase_z_pending": []})
    assert result.returncode == 0
    assert "SAFE" in result.stdout


def test_reload_guard_fails_closed_on_malformed_state(tmp_path: Path) -> None:
    result = _check(tmp_path, "{not-json")
    assert result.returncode == 1
    assert "in-flight worker" in result.stderr


def test_defer_and_force_remain_mutually_exclusive(tmp_path: Path) -> None:
    state = tmp_path / "dispatch_state.json"
    state.write_text(
        json.dumps({"current_jobs": [], "phase_z_pending": []}),
        encoding="utf-8",
    )
    result = subprocess.run(
        ["bash", str(SCRIPT), "--defer", "--force"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={**os.environ, "DISPATCH_STATE_PATH": str(state)},
        check=False,
    )
    assert result.returncode == 2
    assert "mutually exclusive" in result.stderr
