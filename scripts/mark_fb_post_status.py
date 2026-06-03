#!/usr/bin/env python3
"""Mark FB posting state on feed + trending_repost_log in one place.

Use this instead of hand-editing feed.json / trending_repost_log.json when an
article enters a known FB pipeline state such as interactive-session handoff.
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
TRENDING_LOG_PATH = ROOT / "storage" / "reports" / "trending_repost_log.json"
VALID_STATUSES = {
    "pending",
    "success",
    "wont_fix",
    "fb_silent_reject",
    "awaiting_interactive_session",
    "expired_skip",
}


def _load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def update_fb_status(mile_id: str, *, status: str, note: str | None = None) -> dict[str, int | str]:
    updated_feed = 0
    updated_log = 0
    now_iso = _now_iso()

    with shared_state_lock("publisher_feed", storage_dir="storage"):
        feed = _load_json(FEED_PATH, [])
        for item in feed:
            if isinstance(item, dict) and item.get("id") == mile_id:
                item["fb_post_status"] = status
                item["fb_post_status_updated_at"] = now_iso
                if note:
                    item["fb_post_note"] = note
                updated_feed += 1
        _write_json(FEED_PATH, feed)

    with shared_state_lock("fb_pipeline_log", storage_dir="storage"):
        log = _load_json(TRENDING_LOG_PATH, [])
        for item in log:
            if isinstance(item, dict) and item.get("mile_id") == mile_id:
                item["fb_post_status"] = status
                item["fb_post_status_updated_at"] = now_iso
                if note:
                    item["fb_post_note"] = note
                updated_log += 1
        _write_json(TRENDING_LOG_PATH, log)

    return {
        "mile_id": mile_id,
        "status": status,
        "updated_feed": updated_feed,
        "updated_log": updated_log,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mile-id", required=True)
    parser.add_argument("--status", required=True, choices=sorted(VALID_STATUSES))
    parser.add_argument("--note")
    args = parser.parse_args()

    result = update_fb_status(args.mile_id, status=args.status, note=args.note)
    if result["updated_feed"] == 0 and result["updated_log"] == 0:
        print(json.dumps({"ok": False, **result}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
