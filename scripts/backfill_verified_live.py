"""One-shot backfill for `verified_live_at` on already-published feed entries.

Created 2026-05-19 as part of the Three-Strike post-publish verify gate fix.
5 articles this session were published locally + Supabase-synced but were
never live-verified; downstream FB push picked up the wrong URL pattern.

Usage:
    uv run python scripts/backfill_verified_live.py [--id mile_xxx ...]
    (no --id args defaults to the 5 affected mile_ids)
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from volpred.publisher.live_verify import (  # noqa: E402
    public_url,
    verify_article_live,
)

DEFAULT_IDS = [
    "mile_ba1dc7f8",
    "mile_207d3750",
    "mile_dda1e670",
    "mile_50f44a46",
    "mile_dab6cc06",
]

FEED_PATH = REPO_ROOT / "storage" / "reports" / "feed.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id", action="append", default=None, help="mile_id to backfill (repeatable)")
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="skip HTTP check, stamp blindly (emergency only)",
    )
    parser.add_argument("--max-wait-s", type=int, default=30, help="per-id verify timeout (default 30s)")
    args = parser.parse_args()

    target_ids = args.id or DEFAULT_IDS
    feed = json.loads(FEED_PATH.read_text())

    stamped = 0
    failed = 0
    not_found = 0
    for mid in target_ids:
        entry = next((e for e in feed if e.get("id") == mid), None)
        if entry is None:
            print(f"  [skip] {mid}: not in feed.json")
            not_found += 1
            continue

        if args.no_verify:
            live_ok = True
            print(f"  [bypass] {mid}: --no-verify, stamping without HTTP check")
        else:
            url = public_url(mid)
            live_ok = verify_article_live(mid, max_wait_s=args.max_wait_s, poll_interval_s=5)
            print(f"  [{('OK' if live_ok else 'FAIL')}] {mid} → {url}")

        if live_ok:
            entry["verified_live_at"] = datetime.now(timezone.utc).isoformat()
            entry["live_verify_failed"] = False
            stamped += 1
        else:
            entry["live_verify_failed"] = True
            failed += 1

    tmp = FEED_PATH.with_name(f".{FEED_PATH.name}.tmp")
    tmp.write_text(json.dumps(feed, indent=2, ensure_ascii=False))
    json.loads(tmp.read_text())  # sanity
    tmp.replace(FEED_PATH)

    print(f"\nbackfilled stamped={stamped} failed={failed} not_found={not_found}")
    return 0 if failed == 0 and not_found == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
