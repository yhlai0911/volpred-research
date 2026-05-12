#!/usr/bin/env python3
"""Estimate weekly quota % used for Claude Max 20x plan.

Anthropic doesn't expose plan-usage % via API or local file — Claude Desktop
queries it server-side. We anchor on a user-provided screenshot value and
project forward from token_usage_report.py's billable token delta.

Anchor (2026-05-12 13:18 CST):
  - User reported 42% used (Settings → Usage → All models)
  - Weekly billable at that time: 39,511,265 tokens
  - Implied weekly cap: 94.1M billable tokens / Max 20x

Caveats:
  - Anchor based on single screenshot; need re-calibration every 2-3 days
  - Anthropic plan caps not officially published — this is empirical estimate
  - Reset cadence: weekly, Sun 3:59 PM user-local (per screenshot)

Usage:
    uv run python scripts/weekly_quota_estimate.py        # print %
    uv run python scripts/weekly_quota_estimate.py --raw  # JSON output
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Anchor from 2026-05-12 13:18 CST screenshot
ANCHOR_PCT = 42.0
ANCHOR_BILLABLE = 39_511_265
WEEKLY_CAP_BILLABLE = int(ANCHOR_BILLABLE / (ANCHOR_PCT / 100.0))  # ≈ 94.07M


def get_weekly_billable() -> int:
    """Run token_usage_report.py --weekly and parse out billable token total."""
    result = subprocess.run(
        ["uv", "run", "python", "scripts/token_usage_report.py", "--weekly"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"token_usage_report failed: {result.stderr[:200]}")
    # Parse "| **Billable** | **6,263,815** |"
    for line in result.stdout.splitlines():
        if "**Billable**" in line and "|" in line:
            parts = [p.strip() for p in line.split("|")]
            for p in parts:
                clean = p.replace("**", "").replace(",", "").strip()
                if clean.isdigit():
                    return int(clean)
    raise RuntimeError("Could not parse Billable token total from weekly report")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", action="store_true", help="JSON output")
    args = parser.parse_args()

    weekly_billable = get_weekly_billable()
    pct = round(weekly_billable / WEEKLY_CAP_BILLABLE * 100, 1)
    remaining_pct = round(100 - pct, 1)
    remaining_tokens = WEEKLY_CAP_BILLABLE - weekly_billable

    if args.raw:
        print(json.dumps({
            "weekly_billable": weekly_billable,
            "estimated_cap_billable": WEEKLY_CAP_BILLABLE,
            "pct_used": pct,
            "pct_remaining": remaining_pct,
            "tokens_remaining": remaining_tokens,
            "anchor": {"pct": ANCHOR_PCT, "billable": ANCHOR_BILLABLE, "date": "2026-05-12T13:18+08:00"},
        }, ensure_ascii=False, indent=2))
    else:
        print(f"本週 Max 20x quota 推估：{pct}% used / {remaining_pct}% remaining")
        print(f"  Weekly billable:  {weekly_billable:>14,} tokens")
        print(f"  Estimated cap:    {WEEKLY_CAP_BILLABLE:>14,} tokens")
        print(f"  Tokens remaining: {remaining_tokens:>14,} tokens")
        print(f"  Anchor: {ANCHOR_PCT}% at 2026-05-12 13:18 CST ({ANCHOR_BILLABLE:,} billable)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
