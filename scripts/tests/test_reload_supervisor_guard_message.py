"""The reload guard must explain a refusal in terms that match its own count.

`read_active_count` sums two independent blockers: worker jobs and pending
PHASE-Z items. The refusal message used to report only the first and then print
a worker list, so a PHASE-Z-only block rendered as:

    REFUSED: current_jobs has 1 in-flight worker(s):
    []

A count of one with an empty list reads like a broken guard, and the very next
line offers `--force` — the one option that kills in-flight work. The decision
was right; the explanation pointed the operator at the dangerous escape hatch.
Observed 2026-08-04 while landing the index.lock fix.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "reload_dispatch_supervisor.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("jq") is None, reason="guard parses state with jq"
)


def _run(state_path: Path) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "DISPATCH_STATE_PATH": str(state_path),
        "PATH": f"/opt/homebrew/bin:{os.environ.get('PATH', '')}",
    }
    return subprocess.run(
        ["bash", str(SCRIPT), "--reason", "test"],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(ROOT),
        timeout=120,
    )


def _write_state(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "dispatch_state.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_phase_z_only_block_is_not_reported_as_a_phantom_worker(
    tmp_path: Path,
) -> None:
    state = _write_state(
        tmp_path,
        {"current_jobs": [], "current_job": None, "phase_z_pending": ["foreign-abc"]},
    )

    result = _run(state)

    assert result.returncode == 1
    err = result.stderr
    # The count must be attributed, and the attribution must be the true one.
    assert "0 worker job(s)" in err
    assert "1 pending PHASE-Z item(s)" in err
    assert "foreign-abc" in err
    # The old, misleading rendering must not come back.
    assert "current_jobs has 1 in-flight worker(s)" not in err


def test_worker_block_still_names_and_lists_the_worker(tmp_path: Path) -> None:
    state = _write_state(
        tmp_path,
        {"current_jobs": [{"job_id": "job-live"}], "phase_z_pending": []},
    )

    result = _run(state)

    assert result.returncode == 1
    err = result.stderr
    assert "1 worker job(s)" in err
    assert "0 pending PHASE-Z item(s)" in err
    assert "job-live" in err


def test_both_blockers_are_reported_together(tmp_path: Path) -> None:
    state = _write_state(
        tmp_path,
        {
            "current_jobs": [{"job_id": "job-live"}],
            "phase_z_pending": ["foreign-abc"],
        },
    )

    result = _run(state)

    assert result.returncode == 1
    err = result.stderr
    assert "1 worker job(s)" in err
    assert "1 pending PHASE-Z item(s)" in err
    assert "job-live" in err and "foreign-abc" in err


def test_clean_state_reports_safe_under_check_only(tmp_path: Path) -> None:
    state = _write_state(
        tmp_path, {"current_jobs": [], "current_job": None, "phase_z_pending": []}
    )
    env = {
        **os.environ,
        "DISPATCH_STATE_PATH": str(state),
        "VOLPRED_RELOAD_CHECK_ONLY": "1",
        "PATH": f"/opt/homebrew/bin:{os.environ.get('PATH', '')}",
    }

    result = subprocess.run(
        ["bash", str(SCRIPT), "--reason", "test"],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(ROOT),
        timeout=120,
    )

    assert result.returncode == 0
    assert "SAFE" in result.stdout
