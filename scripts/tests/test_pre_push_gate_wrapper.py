"""Run the pre-push gate's shell suite under pytest so CI actually executes it.

`scripts/tests/test_pre_push_gate.sh` is the real suite. pytest's testpaths cover
`scripts/tests`, but only collect `test_*.py` — a bare .sh regression gate would
sit there never running, which is precisely the failure this whole 2026-07-10
thread is about (a gate nobody executes is not a gate). This wrapper wires it in.

The shell suite operates entirely inside a throwaway repo pair under TMPDIR; it
never touches this checkout.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


SUITE = Path(__file__).resolve().parents[1] / "tests" / "test_pre_push_gate.sh"


@pytest.mark.skipif(shutil.which("git") is None, reason="git not on PATH")
@pytest.mark.skipif(shutil.which("python3") is None, reason="python3 not on PATH")
def test_pre_push_gate_shell_suite() -> None:
    result = subprocess.run(
        ["bash", str(SUITE)],
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert result.returncode == 0, (
        f"pre-push gate suite failed (rc={result.returncode})\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )
