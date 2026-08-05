#!/usr/bin/env python3
"""Org status: one readable snapshot of registry + per-department state.

  uv run python scripts/org/org_status.py [--json] [--herdr]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _core import DEFAULT_ORG_ROOT, dept_dir, load_registry  # noqa: E402
from dept_routing import resolve_dept_routing  # noqa: E402


def _tail(path: Path, n: int) -> list[str]:
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8").splitlines()[-n:]


def collect(root: Path) -> dict:
    registry = load_registry(root)
    routing = resolve_dept_routing(registry)["departments"]
    manager_inbox = len(list((root / "manager" / "inbox").glob("*.json")))
    depts = {}
    for name, meta in registry.get("departments", {}).items():
        if meta.get("status") == "retired":
            depts[name] = {"status": "retired"}
            continue
        ddir = dept_dir(root, name)
        state = {}
        state_path = ddir / "state.json"
        if state_path.exists():
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                state = {"error": "corrupt state.json"}
        depts[name] = {
            "status": meta.get("status"),
            "title": meta.get("title"),
            "inbox_open": len(list((ddir / "inbox").glob("*.json"))),
            "state": state,
            "journal_tail": _tail(ddir / "journal.md", 3),
            "task_routing": routing.get(name, {}).get("task_routing", {}),
        }
    return {
        "registry_updated_at": registry.get("updated_at"),
        "manager_inbox_open": manager_inbox,
        "departments": depts,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ORG_ROOT)
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--herdr", action="store_true", help="print Herdr observation commands (optional live view)")
    args = parser.parse_args()

    snap = collect(args.root)
    if args.as_json:
        print(json.dumps(snap, ensure_ascii=False, indent=2))
    else:
        print(f"org @ {args.root}  (registry updated {snap['registry_updated_at']})")
        print(f"manager inbox open: {snap['manager_inbox_open']}")
        for name, d in sorted(snap["departments"].items()):
            if d.get("status") == "retired":
                continue
            print(f"  [{d['status']:>9}] {name:<18} inbox={d['inbox_open']}  last_run={d['state'].get('last_run')}")
            if d.get("task_routing"):
                pairs = "  ".join(
                    f"{tt}={r['model']}/{r['effort']}" + ("" if r["mapped"] else "[UNMAPPED]")
                    for tt, r in d["task_routing"].items()
                )
                print(f"              routing: {pairs}")

    if args.herdr:
        if os.environ.get("HERDR_ENV") != "1":
            print("\n--herdr: not inside a Herdr session (HERDR_ENV != 1); live view unavailable")
        else:
            print("\nHerdr live-view (optional observation layer, not the org backbone):")
            print("  herdr agent list                      # see live sessions")
            print("  herdr pane split --current --direction right --cwd \"$PWD\" --no-focus")
            print("  herdr agent start <dept> --kind claude --pane <pane-id>")
            print("  herdr agent read <dept> --source recent-unwrapped --lines 40")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
