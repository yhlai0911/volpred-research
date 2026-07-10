"""CI wiring for the pre-push pushed-tree gate regression suite.

The suite proper lives in ``test_pre_push_pushed_tree.sh`` (a git hook is most
honestly tested by driving a real ``git push`` at a real bare remote). pytest
only collects ``test_*.py``, and nothing else in this repo invokes the ``.sh``
regression tests — so without this wrapper the suite would never run in CI and
would rot into exactly the "mechanism exists, nobody asks it" defect that the
gate under test exists to prevent.

``testpaths = ["tests", "scripts/tests"]`` (pyproject.toml) means this file is
picked up by .github/workflows/pytest.yml automatically. The shell suite builds
its own throwaway repo, so it is indifferent to CI's shallow checkout.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

SUITE = Path(__file__).resolve().parent / "test_pre_push_pushed_tree.sh"


@pytest.mark.skipif(shutil.which("git") is None, reason="git is required to drive the hook")
def test_pre_push_gate_audits_pushed_commits_not_working_tree() -> None:
    """A commit carrying a new silent fallback must be rejected on push.

    Rejection must happen even when the working tree is clean, and the hook must
    leave the shared checkout (index, worktree, in-progress merge) untouched.
    """
    proc = subprocess.run(
        ["bash", str(SUITE)],
        capture_output=True,
        text=True,
        timeout=900,
    )
    assert proc.returncode == 0, (
        "pre-push pushed-tree gate regression suite failed\n"
        f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    )
