#!/usr/bin/env python3
"""Model-roster staleness + baseline reporter.

Why: we cannot auto-detect Anthropic model additions/removals from a cron
(no ANTHROPIC_API_KEY; a script also can't read the in-session Agent tool
`model` enum). So detection is a MAIN-THREAD session-start discipline. This
script is the *reminder* half: it prints the current baseline and warns when
the roster hasn't been reconciled against the live tool enum recently, so the
reconcile doesn't silently rely on memory.

Reconcile (main-thread, when this warns or at session start):
  1. Look at the Agent/Workflow tool `model` enum in the current tool schema.
  2. Compare its alias set to available_aliases in config/models.json.
  3. If an alias was added/removed (or the main-loop model id changed), update
     config/models.json + the agent-delegation.md table. WebSearch a NEW alias's
     positioning before assigning a tier — do not guess.
  4. Bump _meta.last_reconciled to today.

Exit code: 0 = fresh; 1 = reconcile due (age > threshold) — lets a cron alert.

Usage: uv run python scripts/check_model_roster.py [--max-age-days 30] [--json]
"""
from __future__ import annotations
import argparse
import json
import sys
from datetime import date
from pathlib import Path

CONFIG = Path(__file__).resolve().parent.parent / "config" / "models.json"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-age-days", type=int, default=30)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--today", default=None, help="ISO date override (tests); default = date.today()")
    args = ap.parse_args(argv)

    try:
        cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"model-roster: cannot read {CONFIG}: {e}", file=sys.stderr)
        return 1

    meta = cfg.get("_meta", {})
    last = meta.get("last_reconciled")
    aliases = cfg.get("dispatchable_now", [])
    unavailable = cfg.get("known_but_unavailable", [])
    versions = {k: v.get("display", v.get("id")) if isinstance(v, dict) else v
                for k, v in cfg.get("models", {}).items()}

    today = date.fromisoformat(args.today) if args.today else date.today()
    age_days = None
    stale = False
    if last:
        try:
            age_days = (today - date.fromisoformat(last)).days
            stale = age_days > args.max_age_days
        except ValueError:
            stale = True  # unparseable date -> treat as stale

    report = {
        "dispatchable_now": aliases,
        "known_but_unavailable": unavailable,
        "versions": versions,
        "last_reconciled": last,
        "age_days": age_days,
        "max_age_days": args.max_age_days,
        "reconcile_due": stale,
        "how": "Authoritative availability = Claude Desktop model selector (owner screenshot). Compare vs config/models.json; update config + agent-delegation.md on drift; WebSearch a new model before assigning a tier; route around available=false.",
    }

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"model roster: dispatchable={aliases} unavailable={unavailable} versions={versions}")
        print(f"  last_reconciled={last} (age {age_days}d, threshold {args.max_age_days}d)")
        if stale:
            print("  ⚠ RECONCILE DUE — compare live tool `model` enum vs config/models.json; "
                  "update config + agent-delegation.md on drift (WebSearch new aliases first).")
        else:
            print("  ✓ fresh")
    return 1 if stale else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
