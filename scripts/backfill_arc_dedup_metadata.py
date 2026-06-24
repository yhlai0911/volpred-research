#!/usr/bin/env python3
"""Backfill arc-dedup v3 metadata onto existing feed entries.

Dry-run by default:
    uv run python scripts/backfill_arc_dedup_metadata.py

Apply locally (no remote sync):
    uv run python scripts/backfill_arc_dedup_metadata.py --apply

Apply one article only:
    uv run python scripts/backfill_arc_dedup_metadata.py --apply --id mile_xxxxxxxx

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
REPORTS_DIR = ROOT / "storage" / "reports"
sys.path.insert(0, str(ROOT / "src"))

from volpred.publisher.arc_dedup import arc_signature  # noqa: E402


def _article_text(item: dict) -> str:
    return str(item.get("content") or item.get("description") or "")


def build_backfill_plan(feed: list[dict], ids: set[str] | None = None) -> dict:
    entries: list[dict] = []
    for item in feed:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id") or "")
        if ids is not None and item_id not in ids:
            continue
        title = str(item.get("title") or "")
        desired = arc_signature(title, _article_text(item))
        details = item.get("details") if isinstance(item.get("details"), dict) else {}
        existing = details.get("arc_signature") if isinstance(details, dict) else None
        if existing == desired:
            continue
        entries.append(
            {
                "id": item_id or "?",
                "title": title,
                "had_arc_signature": isinstance(existing, dict),
                "arc_signature": desired,
            }
        )
    return {
        "schema_version": "arc_dedup_v3",
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


def _write_existing_single_files(feed: list[dict], ids: set[str]) -> int:
    """Keep storage/reports/<id>.json in sync when it already exists."""
    written = 0
    for item in feed:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id") or "")
        if item_id not in ids:
            continue
        single = REPORTS_DIR / f"{item_id}.json"
        if not single.exists():
            continue
        single.write_text(
            json.dumps(item, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        written += 1
    return written


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="write metadata back to feed.json")
    ap.add_argument("--limit", type=int, default=10, help="number of changed ids to print")
    ap.add_argument(
        "--id",
        action="append",
        dest="ids",
        help="only backfill this article id; repeatable",
    )
    args = ap.parse_args()

    feed = json.loads(FEED_PATH.read_text(encoding="utf-8"))
    if not isinstance(feed, list):
        raise SystemExit("feed.json is not a list")

    ids = set(args.ids) if args.ids else None
    plan = build_backfill_plan(feed, ids=ids)
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
        single_written = _write_existing_single_files(
            feed,
            {entry["id"] for entry in plan.get("entries", [])},
        )
        print(f"[backfill_arc_dedup_metadata] patched={result['patched_feed_entries']}")
        if single_written:
            print(f"[backfill_arc_dedup_metadata] single_files={single_written}")
    elif not args.apply:
        print("  (dry-run; add --apply to write metadata)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
