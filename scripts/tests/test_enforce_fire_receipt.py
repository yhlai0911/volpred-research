#!/usr/bin/env python3
"""Regression tests for the fire-receipt Stop gate.

Guards the 2026-07-17 fix for boss msg 886 (~70% of dispatch commits carried a
generated message because the receipt was pure agent self-discipline). Two halves:

  - `fire_output_needs_receipt` — the read-only verdict, in phase_z
  - `enforce_fire_receipt.py`   — the Stop hook that acts on it

The property that must never regress: the gate blocks a fire that produced output
without a receipt, and **fails open on absolutely everything else** — a gate that
traps an agent costs a whole fire (3000s cap → SIGKILL), while a gate that misses
one costs an ugly commit subject.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from dispatch_supervisor.phase_z import (  # noqa: E402
    _generated_subject,
    _receipt_path,
    _snapshot_path,
    fire_output_needs_receipt,
    write_fire_receipt,
)

HOOK = REPO_ROOT / "scripts" / "hooks" / "enforce_fire_receipt.py"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True,
                   capture_output=True, text=True)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "t@t.t")
    _git(r, "config", "user.name", "t")
    (r / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git(r, "add", "seed.txt")
    _git(r, "commit", "-qm", "seed")
    return r


def _start_fire(repo: Path, baseline: list[str] | None = None) -> None:
    """Write the fire-start snapshot the pre-fire guard would have written."""
    from dispatch_supervisor.phase_z import _write_pre_fire_snapshot
    assert _write_pre_fire_snapshot(repo, set(baseline or []), subprocess.run)


def _run_hook(repo: Path, *, stop_hook_active: bool = False) -> dict:
    """Run the real hook, probing the temp repo via its --repo-root test seam."""
    proc = subprocess.run(
        [sys.executable, str(HOOK), "--repo-root", str(repo)],
        input=json.dumps({"stop_hook_active": stop_hook_active}),
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, f"hook must always exit 0: {proc.stderr}"
    return json.loads(proc.stdout) if proc.stdout.strip() else {}


# ── the verdict ──────────────────────────────────────────────────────────────

def test_output_without_receipt_needs_one(repo: Path) -> None:
    _start_fire(repo)
    (repo / "new_work.py").write_text("x = 1\n", encoding="utf-8")
    verdict = fire_output_needs_receipt(repo)
    assert verdict["needs_receipt"] is True
    assert "new_work.py" in verdict["owned"]


def test_receipt_present_is_satisfied(repo: Path) -> None:
    _start_fire(repo)
    (repo / "new_work.py").write_text("x = 1\n", encoding="utf-8")
    assert write_fire_receipt(repo, subject="did a thing | because reasons")
    verdict = fire_output_needs_receipt(repo)
    assert verdict["needs_receipt"] is False
    assert verdict["reason"] == "receipt_present"


def test_verdict_never_consumes_the_receipt(repo: Path) -> None:
    """PHASE-Z runs after the agent exits and must still find the receipt."""
    _start_fire(repo)
    (repo / "new_work.py").write_text("x = 1\n", encoding="utf-8")
    write_fire_receipt(repo, subject="s")
    for _ in range(3):
        fire_output_needs_receipt(repo)
    assert _receipt_path(repo, subprocess.run).exists()
    assert _snapshot_path(repo, subprocess.run).exists()


def test_foreign_dirty_path_is_not_our_output(repo: Path) -> None:
    """Dirty at fire start = another session's edit; this fire owes nothing."""
    (repo / "someone_else.py").write_text("y = 2\n", encoding="utf-8")
    _start_fire(repo, baseline=["someone_else.py"])
    verdict = fire_output_needs_receipt(repo)
    assert verdict["needs_receipt"] is False
    assert verdict["reason"] == "nothing_owned"


def test_clean_tree_needs_no_receipt(repo: Path) -> None:
    _start_fire(repo)
    assert fire_output_needs_receipt(repo)["reason"] == "clean"


def test_no_snapshot_means_not_a_fire(repo: Path) -> None:
    """An interactive session in this repo must never be gated."""
    (repo / "whatever.py").write_text("z = 3\n", encoding="utf-8")
    assert fire_output_needs_receipt(repo)["reason"] == "not_a_fire"


def test_machine_churn_alone_needs_no_receipt(repo: Path) -> None:
    """Daemon-written state has no 'why' — it is not an agent decision."""
    _start_fire(repo)
    (repo / "storage").mkdir()
    (repo / "storage" / "work_log.json").write_text("[]\n", encoding="utf-8")
    verdict = fire_output_needs_receipt(repo)
    assert verdict["needs_receipt"] is False, verdict


# ── the hook ─────────────────────────────────────────────────────────────────

def test_hook_blocks_output_without_receipt(repo: Path) -> None:
    _start_fire(repo)
    (repo / "new_work.py").write_text("x = 1\n", encoding="utf-8")
    out = _run_hook(repo)
    assert out.get("decision") == "block"
    assert "fire_receipt.py" in out["reason"]
    assert "new_work.py" in out["reason"]


def test_hook_allows_when_receipt_written(repo: Path) -> None:
    _start_fire(repo)
    (repo / "new_work.py").write_text("x = 1\n", encoding="utf-8")
    write_fire_receipt(repo, subject="did a thing | because reasons")
    assert _run_hook(repo) == {}


def test_hook_never_loops(repo: Path) -> None:
    """Second Stop in the same turn must pass — a trapped fire burns the cap."""
    _start_fire(repo)
    (repo / "new_work.py").write_text("x = 1\n", encoding="utf-8")
    assert _run_hook(repo, stop_hook_active=True) == {}


def test_hook_fails_open_outside_a_repo(tmp_path: Path) -> None:
    assert _run_hook(tmp_path) == {}


# ── the degraded fallback ────────────────────────────────────────────────────

def test_generated_subject_names_what_moved(repo: Path) -> None:
    subject = _generated_subject(
        ["experiments/k1/a.py", "experiments/k1/b.py", "scripts/hooks/c.py"])
    assert "experiments/k1/" in subject
    assert "未留 receipt" in subject


def test_generated_subject_is_never_blank() -> None:
    assert _generated_subject(["README.md"]).strip()
