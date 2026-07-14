#!/usr/bin/env python3
"""Backfill current arc-dedup metadata onto existing feed entries.

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

from volpred.publisher.arc_dedup import (  # noqa: E402
    ARC_SIGNATURE_SCHEMA_VERSION,
    arc_signature_from_feed_item,
)
from volpred.canonical_write import guard_canonical_write  # noqa: E402
from volpred.ops.shared_lock import shared_state_lock  # noqa: E402


def build_backfill_plan(feed: list[dict], ids: set[str] | None = None) -> dict:
    entries: list[dict] = []
    for item in feed:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id") or "")
        if ids is not None and item_id not in ids:
            continue
        title = str(item.get("title") or "")
        desired = arc_signature_from_feed_item(item)
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
        "schema_version": ARC_SIGNATURE_SCHEMA_VERSION,
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
            "reason": "arc_dedup_v4_scope_entity_and_input_upgrade",
            "script": "scripts/backfill_arc_dedup_metadata.py",
            "applied_at": now,
        }
        item["details"] = details
        patched += 1
    return {"patched_feed_entries": patched}


def _write_json_atomic(path: Path, payload: object) -> None:
    """Guarded atomic JSON replacement for feed and existing single files."""
    guard_canonical_write(path)
    tmp = path.with_name(f".{path.name}.arc_backfill.{os.getpid()}.tmp")
    try:
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        json.loads(tmp.read_text(encoding="utf-8"))
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _write_feed_atomic(feed: list[dict]) -> None:
    _write_json_atomic(FEED_PATH, feed)


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
        _write_json_atomic(single, item)
        written += 1
    return written


def _load_feed() -> list[dict]:
    feed = json.loads(FEED_PATH.read_text(encoding="utf-8"))
    if not isinstance(feed, list):
        raise SystemExit("feed.json is not a list")
    return feed


def _print_plan(plan: dict, *, apply: bool, limit: int) -> None:
    print(f"[backfill_arc_dedup_metadata] mode={'apply' if apply else 'dry-run'}")
    print(f"[backfill_arc_dedup_metadata] changed={plan['count']}")
    for entry in plan["entries"][:limit]:
        sig = entry["arc_signature"]
        print(
            f"  - {entry['id']}: mechanisms={sig['mechanisms']} "
            f"horizon={sig['time_horizon']} title={entry['title'][:70]}"
        )


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

    ids = set(args.ids) if args.ids else None
    if not args.apply:
        feed = _load_feed()
        plan = build_backfill_plan(feed, ids=ids)
        _print_plan(plan, apply=False, limit=args.limit)
        print("  (dry-run; add --apply to write metadata)")
        return 0

    # A v4 rollout can touch the entire feed. Hold the same lock as Publisher
    # across the authoritative re-read, plan, mutation, and atomic replacements;
    # planning outside this lock would overwrite articles published meanwhile.
    storage_dir = str(FEED_PATH.parent.parent)
    with shared_state_lock("publisher_feed", storage_dir=storage_dir) as acquired:
        if not acquired:  # blocking=True should make this unreachable, but stay loud.
            raise RuntimeError("publisher_feed lock was not acquired")
        feed = _load_feed()
        plan = build_backfill_plan(feed, ids=ids)
        _print_plan(plan, apply=True, limit=args.limit)
        if plan["count"]:
            result = apply_backfill(feed, plan)
            _write_feed_atomic(feed)
            single_written = _write_existing_single_files(
                feed,
                {entry["id"] for entry in plan.get("entries", [])},
            )
            print(
                f"[backfill_arc_dedup_metadata] "
                f"patched={result['patched_feed_entries']}"
            )
            if single_written:
                print(f"[backfill_arc_dedup_metadata] single_files={single_written}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
