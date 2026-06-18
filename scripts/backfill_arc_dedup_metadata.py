#!/usr/bin/env python3
"""Backfill arc-dedup v2 metadata onto existing feed entries.

Dry-run by default:
    uv run python scripts/backfill_arc_dedup_metadata.py

Apply locally (no remote sync):
    uv run python scripts/backfill_arc_dedup_metadata.py --apply

This is a deterministic metadata backfill. It does not change article content,
status, audience, or publication timestamps.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FEED_PATH = ROOT / "storage" / "reports" / "feed.json"
sys.path.insert(0, str(ROOT / "src"))

from volpred.publisher.arc_dedup import arc_signature  # noqa: E402


def _article_text(item: dict) -> str:
    return str(item.get("content") or item.get("description") or "")


def build_backfill_plan(feed: list[dict]) -> dict:
    entries: list[dict] = []
    for item in feed:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "")
        desired = arc_signature(title, _article_text(item))
        details = item.get("details") if isinstance(item.get("details"), dict) else {}
        existing = details.get("arc_signature") if isinstance(details, dict) else None
        if existing == desired:
            continue
        entries.append(
            {
                "id": item.get("id", "?"),
                "title": title,
                "had_arc_signature": isinstance(existing, dict),
                "arc_signature": desired,
            }
        )
    return {
        "schema_version": "arc_dedup_v2",
        "count": len(entries),
        "entries": entries,
    }


def apply_backfill(feed: list[dict], plan: dict) -> dict:
    by_id = {entry["id"]: entry for entry in plan.get("entries", [])}
    now = datetime.now(timezone.utc).isoformat()
    patched = 0
    for item in feed:
        if not isinstance(item, dict):
            continue
        entry = by_id.get(item.get("id"))
        if not entry:
            continue
        details = item.get("details")
        if not isinstance(details, dict):
            details = {}
        details["arc_signature"] = entry["arc_signature"]
        details["arc_signature_backfill"] = {
            "reason": "release_layer_arc_upgrade_a1",
            "script": "scripts/backfill_arc_dedup_metadata.py",
            "applied_at": now,
        }
        item["details"] = details
        patched += 1
    return {"patched_feed_entries": patched}


def _write_feed_atomic(feed: list[dict]) -> None:
    tmp = FEED_PATH.with_name(f".{FEED_PATH.name}.arc_backfill.tmp")
    tmp.write_text(json.dumps(feed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, FEED_PATH)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="write metadata back to feed.json")
    ap.add_argument("--limit", type=int, default=10, help="number of changed ids to print")
    args = ap.parse_args()

    feed = json.loads(FEED_PATH.read_text(encoding="utf-8"))
    if not isinstance(feed, list):
        raise SystemExit("feed.json is not a list")

    plan = build_backfill_plan(feed)
    print(f"[backfill_arc_dedup_metadata] mode={'apply' if args.apply else 'dry-run'}")
    print(f"[backfill_arc_dedup_metadata] changed={plan['count']}")
    for entry in plan["entries"][: args.limit]:
        sig = entry["arc_signature"]
        print(
            f"  - {entry['id']}: mechanisms={sig['mechanisms']} "
            f"horizon={sig['time_horizon']} title={entry['title'][:70]}"
        )

    if args.apply and plan["count"]:
        result = apply_backfill(feed, plan)
        _write_feed_atomic(feed)
        print(f"[backfill_arc_dedup_metadata] patched={result['patched_feed_entries']}")
    elif not args.apply:
        print("  (dry-run; add --apply to write metadata)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
