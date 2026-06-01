#!/usr/bin/env python3
"""Consolidate fb_post_status to a single canonical source on feed entries.

Root cause (2026-06-01): feed.json carried TWO fb_post_status fields:
  - top-level  item["fb_post_status"]            <- written/read by all code
       (mark_fb_post_status.py, ops_dashboard.py, audit_fb_pipeline.py)
  - details    item["details"]["fb_post_status"] <- written only by paths that
       followed the (wrong) publishing.md schema + ad-hoc patches

They drifted (K1408/K1409 showed top=success but details=scheduled), and some
5/30 posts had success ONLY in details -> invisible to the dashboard/boss-report
which read top-level. Dual-source-of-truth.

Fix: top-level is canonical (all readers use it). This migration:
  1. If top-level fb_post_status is absent but details has one -> promote it.
  2. When both exist, top-level wins (it is what the verified writer sets).
  3. Delete the rogue details.fb_post_status everywhere.
  4. Preserve details.fb_post_url / fb_comment_url / fb_post_timestamp / note
     (those are legitimate per-post metadata, not the status flag).

Idempotent: re-running after consolidation is a no-op. Uses the publisher_feed
lock and re-reads inside the lock (no stale read-modify-write).

Usage:
  uv run python scripts/migrate_fb_post_status_single_source.py            # apply
  uv run python scripts/migrate_fb_post_status_single_source.py --dry-run  # report only
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from volpred.ops.shared_lock import shared_state_lock

FEED_PATH = ROOT / "storage" / "reports" / "feed.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def consolidate(feed: list, *, now_iso: str) -> list[dict]:
    """Mutate feed in place; return list of change records."""
    changes: list[dict] = []
    for item in feed:
        if not isinstance(item, dict):
            continue
        details = item.get("details")
        if not isinstance(details, dict) or "fb_post_status" not in details:
            continue
        det_status = details["fb_post_status"]
        top_status = item.get("fb_post_status")
        action = ""
        if top_status is None or str(top_status).strip() == "":
            # promote details -> top-level (canonical)
            item["fb_post_status"] = det_status
            item.setdefault("fb_post_status_updated_at", now_iso)
            action = f"promote details={det_status!r} -> top-level"
        elif str(top_status) != str(det_status):
            action = f"keep top-level={top_status!r} (canonical), drop stale details={det_status!r}"
        else:
            action = f"drop duplicate details={det_status!r} (== top-level)"
        del details["fb_post_status"]
        changes.append({"id": item.get("id"), "action": action})
    return changes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    now_iso = _now_iso()

    with shared_state_lock("publisher_feed", storage_dir="storage"):
        feed = json.loads(FEED_PATH.read_text(encoding="utf-8"))
        changes = consolidate(feed, now_iso=now_iso)
        if not args.dry_run:
            FEED_PATH.write_text(
                json.dumps(feed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )

    print(json.dumps(
        {"dry_run": args.dry_run, "changed": len(changes), "changes": changes},
        ensure_ascii=False, indent=2,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
