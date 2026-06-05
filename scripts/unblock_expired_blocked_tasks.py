#!/usr/bin/env python3
"""Sweep storage/next_tasks.json: blocked tasks whose blocked_until is in the
past → status="pending"; clears blocked_reason/blocked_at/blocked_until/
blocked_note and appends an audit entry to status_history.

Why: dispatcher (continue_task_dispatch.py:102) only treats status=="pending"
as candidates. The categorize() blocked_until check at line 161-166 only
gates *runtime* dispatch, but never flips status back. Result: expired-block
tasks (e.g. event_article NFP T+0 with blocked_until=event_date) stay
status=blocked forever → never reach agentable pool.

Usage:
    uv run python scripts/unblock_expired_blocked_tasks.py            # dry-run
    uv run python scripts/unblock_expired_blocked_tasks.py --apply    # write
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PATH = Path("storage/next_tasks.json")
BLOCKED_FIELDS = ("blocked_reason", "blocked_at", "blocked_until", "blocked_note")


def main(apply: bool) -> int:
    tasks = json.loads(PATH.read_text())
    now = datetime.now(timezone.utc)
    swept: list[dict] = []

    for t in tasks:
        if (t.get("status") or "").lower() != "blocked":
            continue
        until = t.get("blocked_until")
        if not until:
            continue
        # Prefer strict ISO datetime compare so `2026-06-05T21:30:00+08:00`
        # is honored to the minute. Fall back to date-string compare for the
        # plain `YYYY-MM-DD` form (treated as UTC end-of-day-start).
        try:
            until_dt = datetime.fromisoformat(str(until).replace("Z", "+00:00"))
            if until_dt.tzinfo is None:
                until_dt = until_dt.replace(tzinfo=timezone.utc)
            if until_dt > now:
                continue
        except Exception:
            if str(until)[:10] > now.date().isoformat():
                continue
        swept.append(
            {
                "id": t.get("id"),
                "task_type": t.get("task_type"),
                "blocked_reason": t.get("blocked_reason"),
                "blocked_until": until,
            }
        )
        if apply:
            t["status"] = "pending"
            t.setdefault("status_history", []).append(
                {
                    "at": datetime.now(timezone.utc).isoformat(),
                    "from": "blocked",
                    "to": "pending",
                    "reason": f"blocked_until_expired ({until})",
                }
            )
            for k in BLOCKED_FIELDS:
                t.pop(k, None)

    if apply:
        PATH.write_text(json.dumps(tasks, indent=2, ensure_ascii=False) + "\n")
        print(f"[unblock] applied: {len(swept)} tasks → status=pending")
    else:
        print(f"[unblock] dry-run: would unblock {len(swept)} tasks")
    for s in swept:
        print(
            f"  - {s['id']} ({s['task_type']}) "
            f"reason={s['blocked_reason']} until={s['blocked_until']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(apply=("--apply" in sys.argv)))
