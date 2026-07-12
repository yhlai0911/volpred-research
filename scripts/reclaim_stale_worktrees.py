#!/usr/bin/env python3
"""Clean up worktrees that stopped making progress. HYGIENE, not capacity.

Capacity is already handled: `dispatch_slot_budget.occupancy()` stops counting a
stale worktree the moment it goes quiet, so the dispatcher is unblocked whether
or not this script ever runs. That separation is deliberate — reclaiming capacity
must not depend on a destructive cleanup succeeding. What this script does is
stop the hung agent from burning CPU/RAM and get the directory out of the way.

Staleness is defined in one place (`dispatch_slot_budget.STALE_HOURS`, measured
by progress, not by process liveness — the 2026-07-13 zombies both had live
processes and zero output for two days).

Safety rules, in order:
  - The branch is ALWAYS preserved. Every worktree is a git branch; removing the
    checkout throws nothing away, and the work is recoverable via the branch.
  - A DIRTY worktree is never removed. Uncommitted work is work. It is reported
    and left alone for a human/main-thread decision.
  - `git worktree remove --force` is BANNED repo-wide (CLAUDE.md) and is not
    used here, not even as a fallback.
  - Default is dry-run. `--apply` is required to kill or remove anything.

Usage:
    uv run python scripts/reclaim_stale_worktrees.py            # dry-run
    uv run python scripts/reclaim_stale_worktrees.py --apply
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

import dispatch_slot_budget as slot_budget  # noqa: E402

from volpred.ops.diagnostics import warn  # noqa: E402


def _holder_pids(worktree: Path) -> list[int]:
    """PIDs whose cwd is inside this worktree."""
    try:
        out = subprocess.run(
            ["lsof", "-t", "-a", "-d", "cwd", f"+D{worktree}"],
            capture_output=True, text=True, timeout=30,
        ).stdout
    except (subprocess.SubprocessError, OSError) as exc:
        warn("reclaim", f"lsof 失敗 {worktree.name} ({exc}) — 當作無持有 process")
        return []
    pids = []
    for line in out.split():
        try:
            pids.append(int(line))
        except ValueError:
            continue  # silent-ok: lsof noise line, not a pid
    return [p for p in pids if p != os.getpid()]


def _is_dirty(worktree: Path) -> bool:
    try:
        out = subprocess.run(
            ["git", "-C", str(worktree), "status", "--porcelain"],
            capture_output=True, text=True, timeout=20, check=True,
        ).stdout.strip()
        return bool(out)
    except (subprocess.SubprocessError, OSError) as exc:
        # Fail closed: if we cannot prove it is clean, we do not touch it.
        warn("reclaim", f"git status 失敗 {worktree.name} ({exc}) — 保守視為 dirty，不移除")
        return True


def _branch_of(worktree: Path) -> str | None:
    try:
        return subprocess.run(
            ["git", "-C", str(worktree), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=10, check=True,
        ).stdout.strip() or None
    except (subprocess.SubprocessError, OSError) as exc:
        warn("reclaim", f"讀不到 {worktree.name} 的 branch ({exc})")
        return None


def reclaim(apply: bool) -> dict:
    results = []
    for wt in slot_budget.worktree_slots():
        if wt["live"]:
            continue

        path = slot_budget.WORKTREES_DIR / wt["name"]
        branch = _branch_of(path)
        dirty = _is_dirty(path)
        pids = _holder_pids(path)
        action = {
            "worktree": wt["name"],
            "branch": branch,
            "idle_hours": wt["idle_hours"],
            "dirty": dirty,
            "holder_pids": pids,
            "killed": [],
            "removed": False,
        }

        if dirty:
            action["skipped"] = "dirty — 有未提交工作，保留待人工裁決"
            results.append(action)
            continue

        if apply:
            for pid in pids:
                try:
                    os.kill(pid, signal.SIGTERM)
                    action["killed"].append(pid)
                except OSError as exc:
                    warn("reclaim", f"kill {pid} 失敗 ({exc}) — worktree 仍會嘗試移除")
            try:
                # No --force, ever (CLAUDE.md hard rule). Clean tree => plain remove
                # succeeds; the branch survives, so nothing is lost.
                subprocess.run(
                    ["git", "-C", str(REPO), "worktree", "remove", str(path)],
                    capture_output=True, text=True, timeout=60, check=True,
                )
                action["removed"] = True
            except subprocess.CalledProcessError as exc:
                action["skipped"] = f"worktree remove 失敗（不 --force）: {exc.stderr.strip()[:160]}"
            except (subprocess.SubprocessError, OSError) as exc:
                action["skipped"] = f"worktree remove 失敗: {exc}"

        results.append(action)

    return {"apply": apply, "stale_count": len(results), "actions": results}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真的 kill + remove（預設 dry-run）")
    args = ap.parse_args()
    out = reclaim(apply=args.apply)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    if not args.apply and out["stale_count"]:
        print("\n[dry-run] 加 --apply 才會實際 kill + remove（branch 一律保留）")


if __name__ == "__main__":
    main()
