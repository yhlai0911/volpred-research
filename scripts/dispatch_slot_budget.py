#!/usr/bin/env python3
"""Slot budget for one hourly dispatch fire — mechanical, not model discretion.

Until 2026-07-13 the cap lived as prose in `scripts/cron_hourly_dispatch_prompt.md`
("total slot cap=4"). A fixed 4 is wrong in both directions: it starves a P1
backlog, and it happily surges straight into a quota outage — and a quota outage
takes the whole loop down, not just one fire.

Rules (owner decision, Telegram msg 596/600):
  auth_blocked (supervisor saw an auth/quota block)  -> 2   ride it out, don't burn
  pending P1 >= P1_SURGE_AT                          -> 6   slots 5-6 reserved for P1/P2
  otherwise                                          -> 4   baseline

Usage:
    uv run python scripts/dispatch_slot_budget.py          # JSON
    uv run python scripts/dispatch_slot_budget.py --cap    # just the integer
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from volpred.ops.diagnostics import warn

REPO = Path(__file__).resolve().parent.parent
TASKS_PATH = REPO / "storage" / "next_tasks.json"
STATE_PATH = REPO / "storage" / "ops" / "dispatch_state.json"

BASE_CAP = 4
SURGE_CAP = 6
DERATE_CAP = 2
P1_SURGE_AT = 3


def _pending_by_priority(tasks_path: Path) -> Counter:
    try:
        tasks = json.loads(tasks_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        warn(f"slot-budget: 讀不到任務池 {tasks_path} ({exc}) — 退回 baseline cap")
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
        warn(f"slot-budget: 讀不到 supervisor state {state_path} ({exc}) — 當作未被擋")
        return False


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

    return {
        "cap": cap,
        "reason": reason,
        "p1_only_slots": max(0, cap - BASE_CAP),
        "auth_blocked": blocked,
        "pending_by_priority": {str(k): v for k, v in sorted(pending.items())},
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cap", action="store_true", help="只印 cap 整數")
    args = ap.parse_args()
    result = budget()
    print(result["cap"] if args.cap else json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
