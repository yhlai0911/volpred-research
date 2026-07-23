"""The artifact gate must resolve a relative --path against the CALLER's checkout.

Regression for 2026-07-21 `artifacts_gate_worktree_relpath_abstain`: an agent
standing in `.claude/worktrees/<name>` ran

    python scripts/check_experiment_artifacts.py check --path experiments/kXXXX

and got `PASS — no experiment directory added or modified` (exit 0) for a
directory that plainly existed in its worktree. REPO_ROOT is derived from the
script's own location, so the relative path was resolved against the canonical
checkout, where the directory did not exist yet; targets came back empty and the
empty case prints PASS. compute-queue follow-up briefs routinely spell the call
exactly that way, so the green light was reachable by following instructions.

Two properties are locked here:
  1. a relative --path resolves against cwd, so the gate actually runs
  2. a --path that resolves to nothing exits 2, not 0 — a gate that cannot find
     its target has not checked anything, and must not answer PASS
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "check_experiment_artifacts.py"
EXCLUSIONS_MARKER = "experiment_artifact_exclusions.json"


def _run(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "check", *args],
        cwd=str(cwd), capture_output=True, text=True, timeout=120,
    )


def _make_checkout(root: Path) -> None:
    """A git checkout that is NOT the one the script lives in."""
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=str(root), check=True)


def test_relative_path_resolves_against_caller_checkout(tmp_path: Path) -> None:
    other = tmp_path / "elsewhere"
    _make_checkout(other)
    exp = other / "experiments" / "k_relpath_probe"
    exp.mkdir(parents=True)
    # An archived result with no knowledge entry and no reproduce_spec.json is
    # precisely what the gate exists to catch.
    (exp / "k_relpath_probe_results.json").write_text('{"experiment_id": "k_relpath_probe"}')

    res = _run(other, "--path", "experiments/k_relpath_probe")

    assert res.returncode != 0, (
        "gate abstained on a directory that exists in the caller's checkout.\n"
        f"stdout:\n{res.stdout}\nstderr:\n{res.stderr}"
    )
    assert "no experiment directory added or modified" not in res.stdout, (
        "gate reported the empty-targets PASS while the target was right there"
    )
    # It found the directory and audited it: the gate printed the copy-pasteable
    # remediation block, which only a real audit emits. (Asserting on the exact
    # BLOCKED banner would couple this test to which stream it lands on; the
    # remediation text is the durable evidence that the audit ran.)
    # (The BLOCKED report goes to stderr; stdout stays empty on this path.)
    both = res.stdout + res.stderr
    assert "BLOCKED" in both, f"stdout:\n{res.stdout}\nstderr:\n{res.stderr}"
    assert EXCLUSIONS_MARKER in both


def test_unresolvable_explicit_path_exits_2_rather_than_passing(tmp_path: Path) -> None:
    other = tmp_path / "elsewhere2"
    _make_checkout(other)

    res = _run(other, "--path", "experiments/definitely_not_here")

    assert res.returncode == 2, (
        f"expected exit 2 for an unresolvable --path, got {res.returncode}.\n"
        f"stdout:\n{res.stdout}\nstderr:\n{res.stderr}"
    )
    assert "PASS" not in res.stdout


def test_no_arguments_still_passes_quietly(tmp_path: Path) -> None:
    """Guard the fix's blast radius: 'nothing to check' is still a clean PASS."""
    other = tmp_path / "elsewhere3"
    _make_checkout(other)

    res = _run(other)

    assert res.returncode == 0
    assert "PASS" in res.stdout
