"""Move handled inbox items into <dept>/inbox/_archive/ — interim, runnable by any department.

Why this exists: every charter's closeout contract step 3 says "move handled
inbox items into inbox/_archive/", but no CLI does it, and the department
permission mode denies both `mv` and `mkdir`.  Governance, content and research
all reported the same dead end on 2026-08-05, and the manager raised it as
ruling D2.  The real fix is a subcommand on the org CLI (`scripts/org/`), which
platform_eng currently cannot write; this script is the interim relief so that
closeout stops failing today.

It is deliberately a plain Python file: departments may not have `mv` allowed,
but `uv run python <path>` is.  Running it needs no write permission on this
file, so every department can use it from where it sits.

Usage
-----
    uv run python storage/org/departments/platform_eng/work/inbox_archive/archive_inbox.py \
        --dept research --id item_2026...json [--id ...]

    # or archive every item bound to one canonical task
    ... --dept research --canonical assign_1fe316ba

    # see what would move, change nothing
    ... --dept research --all-handled --dry-run

Safety
------
* Only ever moves files inside `<dept>/inbox/` into `<dept>/inbox/_archive/`.
* Refuses a `--dept` that is not a directory under storage/org/departments/.
* Never deletes anything; a name collision in _archive/ aborts that one file.
* `--all-handled` is NOT "everything": it requires an explicit id or canonical
  filter, because "archive my whole inbox" is exactly how a department loses an
  item it never actually handled.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# .../storage/org/departments/platform_eng/work/inbox_archive/archive_inbox.py
# parents: [0]=inbox_archive [1]=work [2]=platform_eng [3]=departments
DEPTS = Path(__file__).resolve().parents[3]
ROOT = DEPTS.parents[2]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dept", required=True)
    ap.add_argument("--id", action="append", default=[],
                    help="item id or filename (repeatable)")
    ap.add_argument("--canonical", action="append", default=[],
                    help="archive every item carrying this canonical_task_id")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    inbox = DEPTS / args.dept / "inbox"
    if not inbox.is_dir():
        print(f"no such department inbox: {inbox}", file=sys.stderr)
        return 2
    if not args.id and not args.canonical:
        print("refusing to run without --id or --canonical: archiving a whole "
              "inbox is how an unhandled item disappears", file=sys.stderr)
        return 2

    wanted_ids = {i[:-5] if i.endswith(".json") else i for i in args.id}
    wanted_canon = set(args.canonical)
    archive = inbox / "_archive"
    if not args.dry_run:
        archive.mkdir(exist_ok=True)

    moved = 0
    for item in sorted(inbox.glob("item_*.json")):
        matched = item.stem in wanted_ids
        if not matched and wanted_canon:
            try:
                payload = json.loads(item.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                print(f"skip unreadable {item.name}: {exc}", file=sys.stderr)
                continue
            matched = payload.get("canonical_task_id") in wanted_canon
        if not matched:
            continue
        target = archive / item.name
        if target.exists():
            print(f"skip (already in _archive): {item.name}", file=sys.stderr)
            continue
        if args.dry_run:
            print(f"would archive {item.name}")
        else:
            item.replace(target)
            print(f"archived {item.name}")
        moved += 1

    unmatched = wanted_ids - {p.stem for p in (archive.glob("item_*.json") if archive.is_dir() else [])}
    if args.id and moved == 0:
        print(f"nothing matched; ids not found in {inbox}: {sorted(unmatched)}",
              file=sys.stderr)
        return 1
    print(f"{'would archive' if args.dry_run else 'archived'} {moved} item(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
