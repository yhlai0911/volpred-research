#!/usr/bin/env python3
"""Org intake: route boss messages and dept-labeled GitHub issues into the org.

P0 scope:
  --boss-message "text" [--channel telegram|email]  → manager/inbox item (P1)
GitHub mirroring (--github) and immediate request_fire wake are wired in P1/P3;
until then this tool only records intent honestly.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _core import DEFAULT_ORG_ROOT, atomic_write_json, now_iso  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ORG_ROOT)
    parser.add_argument("--boss-message", default=None)
    parser.add_argument("--channel", choices=("telegram", "email"), default="telegram")
    parser.add_argument("--github", action="store_true", help="mirror dept:* labeled issues (wired in P1)")
    args = parser.parse_args()

    if args.github:
        print("github mirroring not wired yet (P1) — no-op", file=sys.stderr)
        return 1
    if not args.boss_message:
        parser.error("nothing to do: pass --boss-message or --github")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    item = {
        "id": f"boss_{stamp}",
        "from": "boss",
        "to": "manager",
        "priority": "P1",
        "channel": args.channel,
        "task": args.boss_message,
        "created_at": now_iso(),
    }
    path = args.root / "manager" / "inbox" / f"{item['id']}.json"
    atomic_write_json(path, item)
    print(path)
    print("note: immediate request_fire wake not wired yet (P1) — next manager_tick will pick this up", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
