#!/usr/bin/env python3
"""Drain (retry) the .failed_supabase_syncs.json dead-letter queue.

Root cause (2026-06-02): `.failed_supabase_syncs.json` was a WRITE-ONLY
dead-letter queue. publisher.py / ops/content.py / daily_update.py append a
mile_id whenever a Supabase sync fails (often a transient network/Supabase
blip); health.py/alerts.py only COUNT it (WARN when >=2). Nothing ever retried
or drained it, so a transient failure became a permanent stale-divergence entry
that accumulated and required manual `sync_article` intervention every time.

This script is the missing consumer. It re-syncs each queued article and
removes the ones that now succeed, leaving only genuinely-persistent failures
(which keep triggering the existing WARN alert -> human escalation).

Wired to a cron (config/runtime_schedules.json: supabase_sync_drain) so transient
failures self-heal without manual action.

Race tolerance: writers append without a lock. We snapshot the queue, attempt
syncs, then RE-READ the queue before writing back and only remove ids we
successfully synced (or whose article no longer exists in feed) — any ids
appended concurrently during the drain are preserved.

Usage:
  uv run python scripts/drain_failed_supabase_syncs.py            # drain
  uv run python scripts/drain_failed_supabase_syncs.py --dry-run  # report only
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

QUEUE_PATH = ROOT / "storage" / ".failed_supabase_syncs.json"
FEED_PATH = ROOT / "storage" / "reports" / "feed.json"


def _load_list(path: Path) -> list:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    queue = _load_list(QUEUE_PATH)
    if not queue:
        print("[drain] queue empty — nothing to do")
        return 0

    from supabase_sync import sync_article  # noqa: E402

    feed = json.loads(FEED_PATH.read_text(encoding="utf-8"))
    by_id = {it.get("id"): it for it in feed if isinstance(it, dict)}

    synced: list[str] = []
    not_found: list[str] = []
    still_failing: list[str] = []

    for mile_id in list(dict.fromkeys(queue)):  # dedup, preserve order
        art = by_id.get(mile_id)
        if art is None:
            # article no longer in feed (deleted/retracted) — can't sync; drop it
            not_found.append(mile_id)
            continue
        if args.dry_run:
            still_failing.append(mile_id)  # would attempt; report as pending
            continue
        try:
            ok = bool(sync_article(art, storage_dir="storage"))
        except Exception as e:  # noqa: BLE001
            print(f"[drain] {mile_id} sync exception: {type(e).__name__}: {str(e)[:200]}")
            ok = False
        if ok:
            synced.append(mile_id)
        else:
            still_failing.append(mile_id)

    if not args.dry_run:
        # race-tolerant write-back: re-read current queue, remove only the ids
        # we resolved (synced or not_found); preserve any concurrent appends.
        resolved = set(synced) | set(not_found)
        current = _load_list(QUEUE_PATH)
        remaining = [mid for mid in current if mid not in resolved]
        QUEUE_PATH.write_text(json.dumps(remaining), encoding="utf-8")

    print(json.dumps({
        "dry_run": args.dry_run,
        "queue_before": len(queue),
        "synced": synced,
        "dropped_not_in_feed": not_found,
        "still_failing": still_failing,
        "queue_after": (len(still_failing) if args.dry_run else len(_load_list(QUEUE_PATH))),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
