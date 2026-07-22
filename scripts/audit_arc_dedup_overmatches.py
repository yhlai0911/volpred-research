#!/usr/bin/env python3
"""Audit recent arc-dedup skips for likely narrative-axis over-matches.

This is a read-only helper for the 2026-06-24 arc-dedup incident. It scans
drafts that release_pool skipped as arc duplicates and reports cases where the
candidate and the blocker have different known narrative axes. Those are
dup-waiver / rewrite candidates for an interactive session to review.

This CLI is a report adapter. The same verdict is consumed automatically by
``volpred.ops.content_quality`` and therefore reaches the hourly alert/task
actuator; it is no longer a terminal-only audit.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FEED_PATH = ROOT / "storage" / "reports" / "feed.json"
sys.path.insert(0, str(ROOT / "src"))

from volpred.ops.content_actuator_audits import (  # noqa: E402
    find_overmatches as _actuated_find_overmatches,
)

# One decision owner: CLI/tests and the hourly actuator consume the same code.
find_overmatches = _actuated_find_overmatches


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--feed", type=Path, default=FEED_PATH)
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--limit", type=int, default=50)
    args = ap.parse_args()

    feed = json.loads(args.feed.read_text(encoding="utf-8"))
    if not isinstance(feed, list):
        raise SystemExit(f"{args.feed} is not a list")
    candidates = find_overmatches(feed, days=args.days)
    payload = {
        "schema_version": "arc_dedup_overmatch_audit_v1",
        "days": args.days,
        "count": len(candidates),
        "candidates": candidates[: args.limit],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
