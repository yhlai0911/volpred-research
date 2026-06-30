#!/usr/bin/env python3
"""Estimate weekly quota % used for Claude Max 20x plan.

Anthropic doesn't expose plan-usage % via API or local file — Claude Desktop
queries it server-side. We anchor on a user-provided screenshot value and
project forward from token_usage_report.py's billable token delta.

Anchor (RE-CALIBRATED 2026-06-30 17:00 +08:00):
  - User reported 54% used (Settings → Usage → Weekly · all models, resets Jul 5)
  - Weekly billable at that time: 115,179,056 tokens
  - Implied weekly cap: ≈213.3M billable tokens / Max 20x
  - 舊 anchor（2026-05-12, 42% @ 39.5M → cap 94M）漂移 7 週未校準 → 估出 122.4%
    但實際 54%（cap 低估 2.26x）。教訓：cap 是經驗值，須每 ≤10 天用新 screenshot 校準。

Caveats:
  - Anchor based on single screenshot; ANCHOR_STALE_DAYS=10 後印再校準警告
  - Anthropic plan caps not officially published + 會隨官方調整 limit 漂移 — empirical
  - Reset cadence: weekly（screenshot 顯示 resets Jul 5）

Usage:
    uv run python scripts/weekly_quota_estimate.py        # print %
    uv run python scripts/weekly_quota_estimate.py --raw  # JSON output
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Anchor RE-CALIBRATED 2026-06-30 17:00 (boss screenshot, Settings → Usage →
# Weekly · all models）。舊 anchor（2026-05-12, 42% @ 39.5M → cap 94M）已漂移 7 週
# 從未重新校準 → 估出 122.4% 但實際僅 54%（cap 被低估 2.26x；Anthropic 可能在這
# 期間調高 Max 20x weekly limit）。新 anchor 反推 cap ≈ 213M。
ANCHOR_PCT = 54.0
ANCHOR_BILLABLE = 116_120_599  # Sunday-aligned quota week（週日16:00→週日，boss 確認的邊界）
ANCHOR_DATE = "2026-06-30T17:00+08:00"
ANCHOR_STALE_DAYS = 10  # 超過此天數印再校準警告（防再漂 7 週）
WEEKLY_CAP_BILLABLE = int(ANCHOR_BILLABLE / (ANCHOR_PCT / 100.0))  # ≈ 213.3M


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

    # Anchor staleness：cap 是經驗值、會隨 Anthropic 調整 limit 漂移（舊 anchor 漂 7 週
    # 估出 122% 但實際 54%）。超過 ANCHOR_STALE_DAYS 提示重新校準（用 boss 最新 screenshot）。
    stale_days = None
    try:
        anchor_dt = datetime.fromisoformat(ANCHOR_DATE)
        stale_days = (datetime.now(anchor_dt.tzinfo) - anchor_dt).days
    except (ValueError, TypeError) as exc:
        print(f"  (anchor date parse failed: {exc})", file=sys.stderr)  # silent-ok handled: logged
    stale = stale_days is not None and stale_days > ANCHOR_STALE_DAYS

    if args.raw:
        print(json.dumps({
            "weekly_billable": weekly_billable,
            "estimated_cap_billable": WEEKLY_CAP_BILLABLE,
            "pct_used": pct,
            "pct_remaining": remaining_pct,
            "tokens_remaining": remaining_tokens,
            "anchor": {"pct": ANCHOR_PCT, "billable": ANCHOR_BILLABLE, "date": ANCHOR_DATE},
            "anchor_age_days": stale_days,
            "anchor_stale": stale,
        }, ensure_ascii=False, indent=2))
    else:
        print(f"本週 Max 20x quota 推估：{pct}% used / {remaining_pct}% remaining")
        print(f"  Weekly billable:  {weekly_billable:>14,} tokens")
        print(f"  Estimated cap:    {WEEKLY_CAP_BILLABLE:>14,} tokens")
        print(f"  Tokens remaining: {remaining_tokens:>14,} tokens")
        print(f"  Anchor: {ANCHOR_PCT}% at {ANCHOR_DATE} ({ANCHOR_BILLABLE:,} billable)")
        if stale:
            print(f"  ⚠️ anchor 已 {stale_days} 天未校準（> {ANCHOR_STALE_DAYS}）— 請用最新 "
                  f"Settings→Usage→Weekly screenshot 重設 ANCHOR_PCT/ANCHOR_BILLABLE/ANCHOR_DATE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
