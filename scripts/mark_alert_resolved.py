#!/usr/bin/env python3
"""Mark notification_log entries as resolved.

Usage:
  uv run python scripts/mark_alert_resolved.py --subject-contains "hourly-dispatch" --note "hotfix c4d64725"
  uv run python scripts/mark_alert_resolved.py --since 2026-05-27T02:00:00 --until 2026-05-27T04:00:00 --note "..."
  uv run python scripts/mark_alert_resolved.py --ts 2026-05-27T03:11:00 --note "..."

Sets `resolved_at` (UTC ISO) + `resolved_note` on matching entries. Dashboard
L4 (`health_alerts_unhandled`) skips entries with `resolved_at` set so already-
fixed incidents stop being counted as unhandled within the 6h window.

Filters can be combined; multiple matches all get marked. Already-resolved
entries are skipped unless --force.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

LOG = Path(__file__).resolve().parent.parent / "storage" / "notifications" / "notification_log.json"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--subject-contains", help="Match entries whose subject contains this substring (case-insensitive)")
    ap.add_argument("--level", choices=["warn", "critical"], help="Only match this level")
    ap.add_argument("--since", help="Only match entries with timestamp >= this ISO ts")
    ap.add_argument("--until", help="Only match entries with timestamp <= this ISO ts")
    ap.add_argument("--ts", help="Exact timestamp match (ISO)")
    ap.add_argument("--note", required=True, help="Resolution note (commit sha / explanation)")
    ap.add_argument("--force", action="store_true", help="Re-mark even if already resolved")
    ap.add_argument("--dry-run", action="store_true", help="Preview matches without writing")
    args = ap.parse_args()

    if not any([args.subject_contains, args.since, args.until, args.ts]):
        print("ERROR: need at least one of --subject-contains / --since / --until / --ts", file=sys.stderr)
        return 2

    if not LOG.exists():
        print(f"ERROR: {LOG} does not exist", file=sys.stderr)
        return 1

    data = json.loads(LOG.read_text())
    if not isinstance(data, list):
        print("ERROR: notification_log.json is not a list", file=sys.stderr)
        return 1

    needle = args.subject_contains.lower() if args.subject_contains else None
    matched = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        if args.level and entry.get("level") != args.level:
            continue
        ts = entry.get("timestamp", "")
        if args.since and ts < args.since:
            continue
        if args.until and ts > args.until:
            continue
        if args.ts and ts != args.ts:
            continue
        if needle:
            subj = (entry.get("subject") or entry.get("title") or "").lower()
            if needle not in subj:
                continue
        if entry.get("resolved_at") and not args.force:
            continue
        matched.append(entry)

    if not matched:
        print(json.dumps({"ok": True, "matched": 0, "note": "no entries matched"}))
        return 0

    now = datetime.now(timezone.utc).isoformat()
    preview = []
    for e in matched:
        preview.append({
            "timestamp": e.get("timestamp"),
            "level": e.get("level"),
            "subject": (e.get("subject") or e.get("title") or "")[:80],
        })

    if args.dry_run:
        print(json.dumps({"ok": True, "dry_run": True, "would_resolve": len(matched), "entries": preview}, ensure_ascii=False, indent=2))
        return 0

    for e in matched:
        e["resolved_at"] = now
        e["resolved_note"] = args.note

    LOG.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    print(json.dumps({"ok": True, "resolved": len(matched), "at": now, "note": args.note, "entries": preview}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
