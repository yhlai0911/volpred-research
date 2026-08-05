#!/usr/bin/env python3
"""Route the canonical pending queue to the departments that own each task_type.

ONE queue, ONE dispatcher. The canonical queue stays `storage/next_tasks.json`;
this does not copy work into a second pool. A department inbox item is a
*pointer* to a canonical task — the department claims and settles it through the
normal task-pool CLI, so completion is recorded in one place, not two.

Running new and old dispatch in parallel is what makes failures unattributable:
two engines claiming from the same pool cannot tell you which one wedged a task.
This is the piece that lets the old engine be switched off.

  uv run python scripts/org/queue_dispatch.py --dry-run
  uv run python scripts/org/queue_dispatch.py --apply [--limit 20]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _core import (  # noqa: E402
    DEFAULT_ORG_ROOT,
    REPO_ROOT,
    dept_dir,
    inbox_items,
    load_registry,
)

NEXT_TASKS = REPO_ROOT / "storage" / "next_tasks.json"
PENDING = {"pending", "pending_main_thread"}


def owner_map(registry: dict) -> dict[str, str]:
    """task_type → department. Ownership is declared once, in the registry."""
    out: dict[str, str] = {}
    for name, meta in registry.get("departments", {}).items():
        if meta.get("status") != "active":
            continue
        for tt in meta.get("owned_task_types", []):
            out[tt] = name
    return out


def already_dispatched(root: Path, registry: dict) -> set[str]:
    """Canonical task ids already pointed at by some department inbox item.

    Includes archived items: re-dispatching a finished task would make the org
    chase its own tail.
    """
    seen: set[str] = set()
    for dept in registry.get("departments", {}):
        base = dept_dir(root, dept) / "inbox"
        for folder in (base, base / "_archive"):
            if not folder.is_dir():
                continue
            for path in folder.glob("*.json"):
                try:
                    item = json.loads(path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):  # silent-ok: unreadable items surface in the inbox reader
                    continue
                if item.get("canonical_task_id"):
                    seen.add(str(item["canonical_task_id"]))
    return seen


def plan(root: Path) -> dict:
    registry = load_registry(root)
    owners = owner_map(registry)
    try:
        tasks = json.loads(NEXT_TASKS.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise SystemExit(f"無法讀取 canonical 任務池 {NEXT_TASKS}：{type(exc).__name__}: {exc}")
    if isinstance(tasks, dict):
        tasks = tasks.get("tasks", [])

    dispatched = already_dispatched(root, registry)
    by_dept: dict[str, list[dict]] = defaultdict(list)
    unmapped: dict[str, int] = defaultdict(int)
    skipped = 0

    for t in tasks:
        if not isinstance(t, dict) or str(t.get("status", "")).lower() not in PENDING:
            continue
        if t.get("tombstone"):
            continue
        tid = str(t.get("id"))
        if tid in dispatched:
            skipped += 1
            continue
        dept = owners.get(str(t.get("task_type")))
        if not dept:
            unmapped[str(t.get("task_type"))] += 1
            continue
        by_dept[dept].append(t)

    for items in by_dept.values():
        items.sort(key=lambda t: (t.get("priority") or 9, str(t.get("id"))))
    return {
        "by_dept": dict(by_dept),
        "unmapped": dict(unmapped),
        "already_dispatched": skipped,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=DEFAULT_ORG_ROOT)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--limit", type=int, default=5,
                        help="max new items per department per round (default 5)")
    args = parser.parse_args()
    if not args.dry_run and not args.apply:
        parser.error("需要 --dry-run 或 --apply")

    result = plan(args.root)
    total = sum(len(v) for v in result["by_dept"].values())
    print(f"canonical 池可派 {total} 件；已派過 {result['already_dispatched']} 件")
    for dept, items in sorted(result["by_dept"].items()):
        head = ", ".join(f"P{t.get('priority')}·{t.get('id')}" for t in items[:args.limit])
        print(f"  {dept:<18} {len(items):>3} 件（本輪派 {min(len(items), args.limit)}）：{head}")
    if result["unmapped"]:
        print("\n⚠️ 無部門認領的 task_type（經理要處置：指派歸屬、或該類型已退役）：")
        for tt, n in sorted(result["unmapped"].items(), key=lambda kv: -kv[1]):
            print(f"  {tt or '(空)':<24} {n} 件")

    if args.dry_run:
        return 0

    import subprocess
    sent = 0
    for dept, items in sorted(result["by_dept"].items()):
        for t in items[:args.limit]:
            proc = subprocess.run(
                ["uv", "run", "python", str(Path(__file__).parent / "dept_send.py"),
                 dept, "--root", str(args.root), "--from", "manager",
                 "--priority", f"P{min(int(t.get('priority') or 3), 3)}",
                 "--task", f"【canonical 任務】{str(t.get('title') or t.get('id'))[:200]}",
                 "--refs", f"storage/next_tasks.json#{t.get('id')}",
                 "--canonical-task-id", str(t.get("id"))],
                cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=120,
            )
            if proc.returncode == 0:
                sent += 1
            else:
                print(f"  ✗ {dept} {t.get('id')}: {(proc.stderr or proc.stdout).strip()[:120]}",
                      file=sys.stderr)
    print(f"\n已派出 {sent} 件到部門收件匣（canonical 任務仍是唯一真相，部門透過 task_pool_claim 結案）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
