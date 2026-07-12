"""CI wiring for the pre-commit staged-scope regression suite.

The suite proper lives in ``test_pre_commit_staged_scope.sh`` (a git hook is most
honestly tested by driving a real ``git commit`` in a real throwaway repo). pytest
only collects ``test_*.py``, so without this wrapper the suite would never run in
CI — the same rot this repo's other hook suite exists to prevent.

``testpaths = ["tests", "scripts/tests"]`` (pyproject.toml) picks this up in
.github/workflows/pytest.yml automatically.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

SUITE = Path(__file__).resolve().parent / "test_pre_commit_staged_scope.sh"


@pytest.mark.skipif(shutil.which("git") is None, reason="git is required to drive the hook")
def test_pre_commit_gate_audits_staged_files_not_working_tree() -> None:
    """The gate must judge the files this commit stages, not the shared tree.

    Case 1 is the 2026-07-13 incident: a concurrent codex_loop's half-written file
    blocked an unrelated author's commit. Cases 2 and 4 pin that the scoping did
    not open a hole — a violation in a *staged* file is still rejected.
    """
    proc = subprocess.run(
        ["bash", str(SUITE)],
        capture_output=True,
        text=True,
        timeout=900,
    )
    assert proc.returncode == 0, (
        "pre-commit staged-scope regression suite failed\n"
        f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    )
