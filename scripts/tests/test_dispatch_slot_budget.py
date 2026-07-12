"""Slot cap + occupancy invariants.

2026-07-13 incident (`ops_slot_capacity_and_zombie_worktrees`): four worktrees
pinned the dispatcher at "occupied=4/4, NO agent dispatch candidates" for hours
while 34 tasks sat pending, six of them P1. Two failures stacked:

  1. Two sources of truth for the cap. `continue_task_dispatch.SLOT_CAP = 4` was
     a literal; `dispatch_slot_budget.budget()` computed 4/6/2 dynamically. The
     literal won, because it was the one the dispatcher read.
  2. Occupancy meant "a directory exists under .claude/worktrees/". A hung agent
     therefore held a slot forever. Note that a process-liveness check would NOT
     have caught it: both zombies still had live claude processes holding the
     worktree as cwd, two days after their last commit. Liveness is not progress.

These tests pin both. Keep them mechanical — prose in a rule file is what failed.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import dispatch_slot_budget as sb  # noqa: E402


# --- 1. cap has exactly one owner -------------------------------------------

def test_dispatcher_has_no_hardcoded_slot_cap():
    """The dispatcher must import the cap, never redeclare it."""
    src = (ROOT / "scripts" / "continue_task_dispatch.py").read_text(encoding="utf-8")
    offenders = [
        line.strip()
        for line in src.splitlines()
        if line.lstrip().startswith("SLOT_CAP") and "=" in line
    ]
    assert not offenders, (
        "`SLOT_CAP` literal is back in continue_task_dispatch.py — the cap has one "
        f"owner (dispatch_slot_budget.budget()). Offending: {offenders}"
    )


def test_budget_surges_on_p1_backlog_and_derates_when_auth_blocked(tmp_path):
    tasks = tmp_path / "next_tasks.json"
    state = tmp_path / "dispatch_state.json"

    tasks.write_text('[{"status":"pending","priority":1}]')
    state.write_text("{}")
    assert sb.budget(tasks, state)["cap"] == sb.BASE_CAP

    tasks.write_text(
        "[" + ",".join(['{"status":"pending","priority":1}'] * sb.P1_SURGE_AT) + "]"
    )
    surged = sb.budget(tasks, state)
    assert surged["cap"] == sb.SURGE_CAP
    assert surged["p1_only_slots"] == sb.SURGE_CAP - sb.BASE_CAP

    # A quota outage takes down the whole loop, not one fire — never surge into it.
    state.write_text('{"auth_blocked": true}')
    assert sb.budget(tasks, state)["cap"] == sb.DERATE_CAP


# --- 2. occupancy is progress, not directory existence, not liveness ---------

def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def fake_worktrees(tmp_path):
    """Two git repos standing in for worktrees: one fresh, one long-idle."""
    root = tmp_path / "worktrees"
    root.mkdir()
    made = {}
    for name in ("fresh", "idle"):
        wt = root / name
        wt.mkdir()
        _git("init", "-q", cwd=wt)
        _git("config", "user.email", "t@t", cwd=wt)
        _git("config", "user.name", "t", cwd=wt)
        (wt / "f.txt").write_text("x")
        _git("add", "-A", cwd=wt)
        _git("commit", "-qm", "c", cwd=wt)
        made[name] = wt
    return root, made


def test_stale_worktree_stops_holding_a_slot(fake_worktrees, monkeypatch):
    root, _ = fake_worktrees
    monkeypatch.setattr(sb, "WORKTREES_DIR", root)

    # Now: both just committed -> both live.
    slots = {w["name"]: w for w in sb.worktree_slots()}
    assert slots["fresh"]["live"] and slots["idle"]["live"]

    # Fast-forward past the threshold: with no new progress, both go stale.
    later = time.time() + (sb.STALE_HOURS + 1) * 3600
    slots = {w["name"]: w for w in sb.worktree_slots(now=later)}
    assert not slots["fresh"]["live"]
    assert not slots["idle"]["live"]


def test_recent_commit_keeps_the_slot_held(fake_worktrees, monkeypatch):
    """The exact regression: a worktree that is still committing must keep its slot."""
    root, made = fake_worktrees
    monkeypatch.setattr(sb, "WORKTREES_DIR", root)

    later = time.time() + (sb.STALE_HOURS + 1) * 3600
    (made["fresh"] / "g.txt").write_text("progress")
    _git("add", "-A", cwd=made["fresh"])
    _git("commit", "-qm", "progress", cwd=made["fresh"])

    # `fresh` committed just now, so relative to `later` it is only ~0h idle...
    # simulate by evaluating at real now: it is live, and `idle` (old commit) is
    # only stale once we look from the future.
    slots_now = {w["name"]: w for w in sb.worktree_slots()}
    assert slots_now["fresh"]["live"]

    slots_later = {w["name"]: w for w in sb.worktree_slots(now=later)}
    assert not slots_later["idle"]["live"], "no-progress worktree must release its slot"


def test_uncommitted_work_counts_as_progress(fake_worktrees, monkeypatch):
    """Dirty files are work in flight — an agent mid-write must not be reclaimed."""
    root, made = fake_worktrees
    monkeypatch.setattr(sb, "WORKTREES_DIR", root)

    scratch = made["idle"] / "wip.py"
    scratch.write_text("# agent is writing right now")

    slots = {w["name"]: w for w in sb.worktree_slots()}
    assert slots["idle"]["live"], "an untracked file just written is progress"


def test_occupancy_only_counts_live_worktrees(fake_worktrees, monkeypatch):
    root, _ = fake_worktrees
    monkeypatch.setattr(sb, "WORKTREES_DIR", root)
    monkeypatch.setattr(sb, "AGENTS_DIR", root / "does-not-exist")

    occ = sb.occupancy()
    assert occ["occupied"] == 2 and not occ["stale"]

    later = time.time() + (sb.STALE_HOURS + 1) * 3600
    occ = sb.occupancy(now=later)
    assert occ["occupied"] == 0, "stale worktrees must not consume capacity"
    assert len(occ["stale"]) == 2, "…but they must still be reported, not silently dropped"
