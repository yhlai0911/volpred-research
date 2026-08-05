#!/usr/bin/env python3
"""Move handled inbox items into `_archive/` — the one supported way.

Every charter ends with "archive what you handled", and until now no tool
existed to do it. Each department improvised a bare `mv`, which the permission
layer denies, so the step failed **quietly**: the next shift opened the same
inbox, saw the same item as unprocessed, and did the work again. Eleven hours
of content's inbox never dropping by one is what that looks like from outside.

The fix is a canonical entry point rather than looser permissions. A bare `mv`
cannot check anything; this can, and the one thing worth checking is the org's
own rule: a `request` or `decision` may not be filed away without answering the
person waiting on it. The wake gate already names anyone who does that — better
to make it impossible than to detect it afterwards.

  uv run python scripts/org/inbox_archive.py content --id item_2026... [--id ...]
  uv run python scripts/org/inbox_archive.py manager --id boss_telegram_1701
  uv run python scripts/org/inbox_archive.py content --id ... --dry-run
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _core import DEFAULT_ORG_ROOT, dept_dir, load_registry  # noqa: E402

MANAGER = "manager"


def inbox_of(root: Path, role: str) -> Path:
    base = (root / MANAGER) if role == MANAGER else dept_dir(root, role)
    return base / "inbox"


def _replied_ids(root: Path) -> set[str]:
    """Every work-item id that some reply anywhere in the org points at."""
    replied: set[str] = set()
    try:
        roles = list(load_registry(root).get("departments", {})) + [MANAGER]
    except FileNotFoundError:
        return replied
    for role in roles:
        base = inbox_of(root, role)
        for folder in (base, base / "_archive"):
            if not folder.is_dir():
                continue
            for path in folder.glob("*.json"):
                try:
                    item = json.loads(path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):  # silent-ok: unreadable items surface in the inbox reader
                    continue
                if item.get("reply_to"):
                    replied.add(str(item["reply_to"]))
    return replied


def archive(root: Path, role: str, item_ids: list[str], *,
            dry_run: bool = False, no_reply_needed: bool = False) -> dict:
    inbox = inbox_of(root, role)
    if not inbox.is_dir():
        raise SystemExit(f"找不到收件匣：{inbox}")
    dest = inbox / "_archive"
    replied = _replied_ids(root)

    moved, missing, blocked = [], [], []
    for item_id in item_ids:
        src = inbox / f"{item_id}.json"
        if not src.is_file():
            missing.append(item_id)
            continue
        try:
            item = json.loads(src.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            item = {"kind": "unreadable", "error": f"{type(exc).__name__}: {exc}"}
        if (item.get("kind") in {"request", "decision"}
                and item_id not in replied and not no_reply_needed):
            blocked.append({
                "id": item_id,
                "from": item.get("from"),
                "fix": (f"uv run python scripts/org/dept_send.py {item.get('from')} "
                        f"--from {role} --reply-to {item_id} --task \"結果：…\""),
            })
            continue
        if not dry_run:
            dest.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dest / src.name))
        moved.append(item_id)
    return {"moved": moved, "missing": missing, "blocked": blocked,
            "dry_run": dry_run, "inbox": str(inbox)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("role", help="department name, or 'manager'")
    parser.add_argument("--root", type=Path, default=DEFAULT_ORG_ROOT)
    parser.add_argument("--id", dest="ids", action="append", required=True,
                        help="work-item id (repeatable). No bulk sweep on purpose: "
                             "an accidental empty selector must not empty an inbox.")
    parser.add_argument("--no-reply-needed", action="store_true",
                        help="this request/decision genuinely needs no answer")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    result = archive(args.root, args.role, args.ids,
                     dry_run=args.dry_run, no_reply_needed=args.no_reply_needed)
    if args.as_json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        verb = "會歸檔" if args.dry_run else "已歸檔"
        print(f"{verb} {len(result['moved'])} 件" + (f"：{', '.join(result['moved'])}" if result["moved"] else ""))
        for m in result["missing"]:
            print(f"  ⚠️ 找不到 {m}（可能已歸檔）", file=sys.stderr)
        for b in result["blocked"]:
            print(f"  ⛔ {b['id']} 是 {b['from']} 的請求／裁決請示，還沒回覆就歸檔＝對方會一直等。\n"
                  f"     先回覆：{b['fix']}\n"
                  f"     （確定不需要回覆才加 --no-reply-needed）", file=sys.stderr)
    return 1 if result["blocked"] or result["missing"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
