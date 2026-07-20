"""Weekly/ad-hoc audit of the dedup gate decision trail (rule §4).

Promised by `.claude/rules/dedup-gate-audit.md` §4; the adjudication itself
lives in ``volpred.ops.dedup_gate_audit.audit_dedup_decisions`` so the hourly
alert condition (``volpred.ops.alerts._parse_dedup_gate_health_state``) and
this CLI share one brain. This wrapper only parses args and prints JSON.

Alert egress is owned by check_alerts (`.claude/rules/alert.md` single-owner
rule) — this script never sends mail, so running it twice can't double-page.

Usage:
    uv run python scripts/audit_dedup_gate_decisions.py [--storage-dir storage]
        [--lookback-days 7] [--no-pass-hours 24]

Exit code: 0 on a healthy verdict, 1 when any §4 condition breached (so a
cron/CI caller can gate on it); the JSON verdict goes to stdout either way.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from volpred.ops.dedup_gate_audit import (  # noqa: E402
    ARC_REPEAT_BLOCK_THRESHOLD,
    BLOCK_RATE_MIN_DECISIONS,
    BLOCK_RATE_THRESHOLD,
    LOOKBACK_DAYS,
    NO_PASS_CRITICAL_HOURS,
    audit_dedup_decisions,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--storage-dir", default="storage")
    parser.add_argument("--lookback-days", type=int, default=LOOKBACK_DAYS)
    parser.add_argument("--no-pass-hours", type=float, default=NO_PASS_CRITICAL_HOURS)
    parser.add_argument("--block-rate-threshold", type=float, default=BLOCK_RATE_THRESHOLD)
    parser.add_argument("--min-decisions", type=int, default=BLOCK_RATE_MIN_DECISIONS)
    parser.add_argument("--arc-block-threshold", type=int, default=ARC_REPEAT_BLOCK_THRESHOLD)
    args = parser.parse_args(argv)

    verdict = audit_dedup_decisions(
        storage_dir=args.storage_dir,
        lookback_days=args.lookback_days,
        no_pass_hours=args.no_pass_hours,
        block_rate_threshold=args.block_rate_threshold,
        block_rate_min_decisions=args.min_decisions,
        arc_block_threshold=args.arc_block_threshold,
    )
    print(json.dumps(verdict, ensure_ascii=False, indent=2))
    return 0 if verdict.get("healthy") else 1


if __name__ == "__main__":
    raise SystemExit(main())
