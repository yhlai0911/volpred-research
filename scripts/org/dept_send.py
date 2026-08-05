#!/usr/bin/env python3
"""Write a work item into a department inbox (or a report into manager/inbox).

Schema: {id, from, to, priority(P1|P2|P3), task, due?, refs[], issue?, created_at}

Examples:
  uv run python scripts/org/dept_send.py content --from manager --priority P2 \
      --task "本週 digest 選題與撰寫" --due 2026-08-07T12:00:00Z
  uv run python scripts/org/dept_send.py --to-manager --from content \
      --priority P3 --task "報告：digest 已發佈 <slug>"
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _core import DEFAULT_ORG_ROOT, atomic_write_json, dept_dir, load_registry, now_iso  # noqa: E402

PRIORITIES = ("P1", "P2", "P3")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("dept", nargs="?", default=None, help="target department")
    parser.add_argument("--to-manager", action="store_true", help="write to manager/inbox instead")
    parser.add_argument("--root", type=Path, default=DEFAULT_ORG_ROOT)
    parser.add_argument("--from", dest="sender", required=True)
    parser.add_argument("--priority", choices=PRIORITIES, default="P3")
    parser.add_argument("--task", required=True)
    parser.add_argument("--due", default=None, help="ISO-8601 UTC deadline")
    parser.add_argument("--refs", default=None, help="comma-separated file/URL refs")
    parser.add_argument("--issue", type=int, default=None, help="linked GitHub issue number")
    args = parser.parse_args()

    if args.to_manager:
        inbox = args.root / "manager" / "inbox"
    else:
        if not args.dept:
            parser.error("dept is required unless --to-manager")
        registry = load_registry(args.root)
        meta = registry["departments"].get(args.dept)
        if not meta or meta.get("status") != "active":
            print(f"department {args.dept!r} not active — refusing")
            return 1
        inbox = dept_dir(args.root, args.dept) / "inbox"
    if args.due:
        try:
            datetime.fromisoformat(args.due.replace("Z", "+00:00"))
        except ValueError:
            parser.error(f"--due is not ISO-8601: {args.due!r}")

    slug = re.sub(r"[^a-z0-9]+", "-", args.task.lower())[:32].strip("-") or "item"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    item = {
        "id": f"item_{stamp}_{slug}",
        "from": args.sender,
        "to": "manager" if args.to_manager else args.dept,
        "priority": args.priority,
        "task": args.task,
        "due": args.due,
        "refs": [r.strip() for r in (args.refs or "").split(",") if r.strip()],
        "issue": args.issue,
        "created_at": now_iso(),
    }
    path = inbox / f"{item['id']}.json"
    atomic_write_json(path, item)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
