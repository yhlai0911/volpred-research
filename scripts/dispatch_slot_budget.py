#!/usr/bin/env python3
"""Slot budget for one hourly dispatch fire — mechanical, not model discretion.

This module is the SINGLE owner of both halves of the slot question:
"how many slots exist" (cap) and "how many are taken" (occupancy). Do not
re-derive either one anywhere else — that is exactly what broke.

## Cap

Until 2026-07-13 the cap lived as prose in `scripts/cron_hourly_dispatch_prompt.md`
("total slot cap=4"). A fixed 4 is wrong in both directions: it starves a P1
backlog, and it happily surges straight into a quota outage — and a quota outage
takes the whole loop down, not just one fire.

Rules (owner decision, Telegram msg 596/600):
  auth_blocked (supervisor saw an auth/quota block)  -> 2   ride it out, don't burn
  pending P1 >= P1_SURGE_AT                          -> 6   slots 5-6 reserved for P1/P2
  otherwise                                          -> 4   baseline

## Occupancy (2026-07-13, task `ops_slot_capacity_and_zombie_worktrees`)

Occupancy used to mean "a directory exists under .claude/worktrees/", counted by
`continue_task_dispatch.count_active_slots`. A directory is an ARTIFACT of work,
not a LEASE on capacity: it has no holder, no heartbeat, and no expiry, so a hung
agent holds a slot forever and silently. On 2026-07-13 02:00 four worktrees held
4/4 slots while only two were doing anything; the dispatcher printed "NO agent
dispatch candidates" for hours with 34 tasks pending, six of them P1.

The obvious fix — "check whether the agent process is still alive" — DOES NOT
WORK, and this is the part worth remembering. Both hung agents (`fervent-payne`,
`wizardly-mirzakhani`) still had live claude processes holding the worktree as
cwd, 2 days after their last commit. Liveness is not progress. A slot is held
only while work is PROGRESSING, so progress is what we measure:

    progress_at = max(HEAD commit time, mtime of any dirty/untracked file)

No progress for STALE_HOURS -> the worktree stops counting against capacity. It
is NOT deleted here: reclaiming capacity must not depend on a destructive cleanup
succeeding. Hygiene (kill the holder, remove the worktree, keep the branch) is a
separate explicit step — `scripts/reclaim_stale_worktrees.py`.

The same "artifact nobody expires" bug applies to `storage/ops/agents/*.json`
records stuck at status=running, so the same staleness rule is applied to them.

Usage:
    uv run python scripts/dispatch_slot_budget.py          # JSON
    uv run python scripts/dispatch_slot_budget.py --cap    # just the integer
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from collections import Counter
from pathlib import Path

from volpred.ops.diagnostics import warn

REPO = Path(__file__).resolve().parent.parent
TASKS_PATH = REPO / "storage" / "next_tasks.json"
STATE_PATH = REPO / "storage" / "ops" / "dispatch_state.json"
WORKTREES_DIR = REPO / ".claude" / "worktrees"
AGENTS_DIR = REPO / "storage" / "ops" / "agents"

BASE_CAP = 4
SURGE_CAP = 6
DERATE_CAP = 2
P1_SURGE_AT = 3

# Hours a worktree may show zero progress before it stops holding a slot.
# Agent runs are scoped to <=50min (fire cap); queued research agents run longer
# but commit as they go. 4h clears every real run with room to spare, and both
# 2026-07-13 zombies were 48h+ stale — the threshold is not a close call.
STALE_HOURS = 4.0
ACTIVE_AGENT_STATUSES = {"running", "active", "in_progress", "claimed"}
# Bound the stat() cost on a worktree with a large untracked tree.
_MAX_DIRTY_FILES_STATTED = 200


def _pending_by_priority(tasks_path: Path) -> Counter:
    try:
        tasks = json.loads(tasks_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        warn("slot-budget", f"讀不到任務池 {tasks_path} ({exc}) — 退回 baseline cap")
        return Counter()
    if isinstance(tasks, dict):
        tasks = tasks.get("tasks", [])
    return Counter(
        int(t.get("priority", 4)) for t in tasks if t.get("status") == "pending"
    )


def _auth_blocked(state_path: Path) -> bool:
    try:
        return bool(json.loads(state_path.read_text()).get("auth_blocked"))
    except (OSError, json.JSONDecodeError) as exc:
        warn("slot-budget", f"讀不到 supervisor state {state_path} ({exc}) — 當作未被擋")
        return False


def _last_commit_epoch(worktree: Path) -> float:
    try:
        out = subprocess.run(
            ["git", "-C", str(worktree), "log", "-1", "--format=%ct"],
            capture_output=True, text=True, timeout=10, check=True,
        ).stdout.strip()
        return float(out) if out else 0.0
    except (subprocess.SubprocessError, OSError, ValueError) as exc:
        warn("slot-budget", f"讀不到 {worktree.name} 的 HEAD commit time ({exc}) — 當作無 commit 進度")
        return 0.0


def _last_dirty_mtime(worktree: Path) -> float:
    """Newest mtime among dirty/untracked files — uncommitted work in flight."""
    try:
        out = subprocess.run(
            ["git", "-C", str(worktree), "status", "--porcelain"],
            capture_output=True, text=True, timeout=20, check=True,
        ).stdout
    except (subprocess.SubprocessError, OSError) as exc:
        warn("slot-budget", f"讀不到 {worktree.name} 的 git status ({exc}) — 當作無未提交進度")
        return 0.0

    newest = 0.0
    for line in out.splitlines()[:_MAX_DIRTY_FILES_STATTED]:
        rel = line[3:].strip().strip('"')
        if " -> " in rel:  # rename: take the destination
            rel = rel.split(" -> ", 1)[1]
        try:
            newest = max(newest, (worktree / rel).stat().st_mtime)
        except OSError:
            continue  # silent-ok: path vanished mid-scan (agent still writing)
    return newest


def worktree_slots(now: float | None = None, worktrees_dir: Path | None = None) -> list[dict]:
    """Classify each worktree as live (holds a slot) or stale (does not).

    Progress, not process liveness — see module docstring.
    """
    now = time.time() if now is None else now
    # Resolved at call time, not bound as a default: a default arg freezes the
    # module constant and makes the dir un-injectable in tests.
    worktrees_dir = WORKTREES_DIR if worktrees_dir is None else worktrees_dir
    slots: list[dict] = []
    if not worktrees_dir.exists():
        return slots

    for path in sorted(worktrees_dir.iterdir()):
        if not path.is_dir() or path.name.startswith("."):
            continue
        progress_at = max(_last_commit_epoch(path), _last_dirty_mtime(path))
        idle_hours = (now - progress_at) / 3600.0 if progress_at else float("inf")
        slots.append({
            "name": path.name,
            "progress_at": progress_at or None,
            "idle_hours": None if idle_hours == float("inf") else round(idle_hours, 1),
            "live": idle_hours < STALE_HOURS,
        })
    return slots


def agent_slots(now: float | None = None, agents_dir: Path | None = None) -> list[dict]:
    """Agent records claiming to be running. A record whose file has not been
    touched in STALE_HOURS is the same 'artifact nobody expires' bug as a hung
    worktree, so it stops holding a slot too."""
    now = time.time() if now is None else now
    agents_dir = AGENTS_DIR if agents_dir is None else agents_dir
    slots: list[dict] = []
    if not agents_dir.exists():
        return slots

    for f in sorted(agents_dir.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            warn("slot-budget", f"agent record 讀不到 {f.name} ({exc}) — 不計入佔用")
            continue
        if (data.get("status") or "").lower() not in ACTIVE_AGENT_STATUSES:
            continue
        try:
            idle_hours = (now - f.stat().st_mtime) / 3600.0
        except OSError as exc:
            warn("slot-budget", f"agent record stat 失敗 {f.name} ({exc}) — 不計入佔用")
            continue
        slots.append({
            "name": f.stem,
            "idle_hours": round(idle_hours, 1),
            "live": idle_hours < STALE_HOURS,
        })
    return slots


def occupancy(now: float | None = None) -> dict:
    """How many slots are actually held. Single owner — do not re-derive."""
    wts = worktree_slots(now=now)
    agents = agent_slots(now=now)
    live_wt = [w["name"] for w in wts if w["live"]]
    live_agents = [a["name"] for a in agents if a["live"]]
    stale = [w for w in wts if not w["live"]] + [a for a in agents if not a["live"]]

    return {
        # Keys `worktrees` / `active_agents` / `occupied` are the legacy shape
        # `continue_task_dispatch` and its report consumers already read.
        "worktrees": live_wt,
        "active_agents": live_agents,
        "occupied": len(live_wt) + len(live_agents),
        "stale": stale,
        "worktree_detail": wts,
    }


def budget(tasks_path: Path = TASKS_PATH, state_path: Path = STATE_PATH) -> dict:
    pending = _pending_by_priority(tasks_path)
    blocked = _auth_blocked(state_path)
    p1 = pending.get(1, 0)

    if blocked:
        cap, reason = DERATE_CAP, "auth/quota blocked — de-rated, 先保住 loop 存活"
    elif p1 >= P1_SURGE_AT:
        cap, reason = SURGE_CAP, f"P1 backlog={p1} — surge；slot 5-6 只給 P1/P2"
    else:
        cap, reason = BASE_CAP, f"baseline（P1 backlog={p1}）"

    occ = occupancy()
    return {
        "cap": cap,
        "reason": reason,
        "p1_only_slots": max(0, cap - BASE_CAP),
        "auth_blocked": blocked,
        "pending_by_priority": {str(k): v for k, v in sorted(pending.items())},
        "occupied": occ["occupied"],
        "free": max(0, cap - occ["occupied"]),
        "occupancy": occ,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cap", action="store_true", help="只印 cap 整數")
    args = ap.parse_args()
    result = budget()
    print(result["cap"] if args.cap else json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
