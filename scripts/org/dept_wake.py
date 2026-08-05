#!/usr/bin/env python3
"""Dept wake: submit a dept_session dispatch request for a department.

P0 scope: validates the department and prints the exact request payload that
will be submitted. Actual submission through the dispatch request channel is
wired in P3 (per migration plan) — this tool never fakes a submission.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _core import (  # noqa: E402
    DEFAULT_ORG_ROOT,
    build_brief,
    dept_dir,
    inbox_items,
    load_registry,
    now_iso,
    read_lease,
)


def build_request(root: Path, dept: str) -> dict:
    registry = load_registry(root)
    meta = registry["departments"].get(dept)
    if not meta or meta.get("status") != "active":
        raise SystemExit(f"department {dept!r} not active — refusing to wake")
    return {
        "task_type": "dept_session",
        "dept": dept,
        "inbox_open": len(inbox_items(root, dept)),
        "requested_at": now_iso(),
        "rehydrate": {
            "charter": str(dept_dir(root, dept) / "charter.md"),
            "memory": str(dept_dir(root, dept) / "memory" / "notes.md"),
            "journal_tail_lines": 20,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dept")
    parser.add_argument("--root", type=Path, default=DEFAULT_ORG_ROOT)
    parser.add_argument("--print-brief", action="store_true",
                        help="print the rehydration brief a session would receive")
    parser.add_argument("--submit", action="store_true", help="actually submit (wired in P3)")
    args = parser.parse_args()

    if args.print_brief:
        print(build_brief(args.root, args.dept))
        return 0

    # A live cockpit pane owns this department right now; a second headless
    # runner would work the same inbox and double-commit.
    lease = read_lease(args.root, args.dept)
    if lease and lease.get("runner") == "herdr":
        print(json.dumps({
            "deferred": True, "reason": "herdr cockpit pane holds this department",
            "lease": lease,
        }, ensure_ascii=False, indent=2))
        print(f"部門 {args.dept} 目前由 Herdr pane {lease.get('pane_id')} 執行；"
              f"headless 喚醒讓位（要收回：org_attach.py detach --depts {args.dept}）", file=sys.stderr)
        return 0

    request = build_request(args.root, args.dept)
    print(json.dumps(request, ensure_ascii=False, indent=2))
    if args.submit:
        print("dispatch submission not wired yet (P3) — request NOT submitted", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
