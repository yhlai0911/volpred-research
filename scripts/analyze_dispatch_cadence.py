#!/usr/bin/env python3
"""Estimate what a dispatch cadence actually costs, from observed pool churn.

Owner question (2026-07-20, telegram-1198): "switch dispatch to every 15
minutes — does that cost 4x the tokens, or not much more?"

The honest answer depends entirely on the pregate. With a demand-only gate
("is there work?") it IS ~4x: the pool always holds P1/P2, so `high_prio` was
true on 164/164 fires over the preceding week and would_skip was 0 — every one
of the 4 fires/hour pays the full ~95K cold-load. With the novelty gate added
to scripts/hourly_dispatch_pregate.py the question becomes "how often does the
actionable world actually CHANGE?", and that is measurable from data we already
keep, without running a 2-hour live A/B.

Method: replay every transition that would move the agentable P1/P2 set —
task creation, and every status_history transition — bucket them into bins of
the candidate cadence, and count the bins containing at least one event. A bin
with no event is a fire the novelty gate would skip.

This DELIBERATELY ignores the capacity veto (free slots) and the absolute
demand signals (email / compute followup / drought), which pull in opposite
directions and are not reconstructable from history:
  - capacity would push the proceed rate DOWN (a fire with no free slot skips),
  - absolute demand would push it UP (those bypass novelty entirely).
So treat the output as an estimate of the novelty term alone, not a forecast.
Ground truth still comes from the shadow log once the gate has run a window.

Usage:
    uv run python scripts/analyze_dispatch_cadence.py
    uv run python scripts/analyze_dispatch_cadence.py --days 14 --cadence 15 30 60
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NEXT_TASKS = ROOT / "storage" / "next_tasks.json"
_HOST_TZ = timezone(timedelta(hours=8))


def _parse(s):
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        print(f"[cadence] unparseable timestamp dropped from replay: {s!r}", file=sys.stderr)
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=_HOST_TZ)


def churn_events(tasks: list, since: datetime) -> list[datetime]:
    """Timestamps at which the agentable P1/P2 set changed.

    Same population the pregate signature covers (P1/P2, not main-thread-only),
    so the estimate and the gate are talking about the same world.
    """
    sys.path.insert(0, str(ROOT / "scripts"))
    from continue_task_dispatch import is_main_thread_only  # type: ignore

    events: list[datetime] = []
    for t in tasks:
        if not isinstance(t, dict):
            continue
        try:
            prio = int(t.get("priority", 9))
        except (TypeError, ValueError):
            prio = 9
        if prio > 2 or is_main_thread_only(t):
            continue
        stamps = [_parse(t.get("created_at"))]
        stamps += [_parse(h.get("ts")) for h in (t.get("status_history") or [])
                   if isinstance(h, dict)]
        events.extend(ts for ts in stamps if ts and ts >= since)
    return events


def analyze(days: float, cadences: list[int]) -> dict:
    data = json.loads(NEXT_TASKS.read_text(encoding="utf-8"))
    tasks = data if isinstance(data, list) else data.get("tasks", [])
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    events = churn_events(tasks, since)

    rows = []
    for mins in sorted(cadences):
        bins = {int((e - since).total_seconds() // (mins * 60)) for e in events}
        total = max(1, int(days * 24 * 60 / mins))
        changed = len(bins)
        rows.append({
            "cadence_minutes": mins,
            "fires_per_day": round(24 * 60 / mins, 2),
            "bins_total": total,
            "bins_with_change": changed,
            "novelty_proceed_rate": round(changed / total, 4),
            # Relative cost vs one 60-min fire/hour that always proceeds
            # (today's behaviour), assuming a constant per-fire cold-load.
            "relative_cost_vs_hourly_always": round((60 / mins) * (changed / total), 2),
        })
    return {"days": days, "events": len(events), "window_start": since.isoformat(),
            "cadences": rows}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=float, default=7.0)
    ap.add_argument("--cadence", type=int, nargs="+", default=[15, 30, 60])
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    out = analyze(args.days, args.cadence)
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    print(f"Pool churn over {out['days']}d — {out['events']} agentable P1/P2 set-change events\n")
    print(f"{'cadence':>9} {'fires/day':>10} {'proceed rate':>13} {'cost vs hourly':>15}")
    for r in out["cadences"]:
        print(f"{r['cadence_minutes']:>7}min {r['fires_per_day']:>10} "
              f"{r['novelty_proceed_rate']:>12.1%} {r['relative_cost_vs_hourly_always']:>14}x")
    print("\nNovelty term only — capacity veto pushes cost down, absolute demand pushes it up.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
