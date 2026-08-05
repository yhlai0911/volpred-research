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
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _core import (  # noqa: E402
    DEFAULT_ORG_ROOT,
    atomic_write_json,
    dept_dir,
    load_registry,
    now_iso,
    read_lease,
)

PRIORITIES = ("P1", "P2", "P3")

# `decision` is a department asking the coordinator to rule. It is tracked like
# a request: the asker is blocked until answered, so an unanswered ruling is a
# defect, not a backlog item.
# Tasking flows through the manager; peers may only ASK. A department that could
# assign work to another department would recreate the tangle the org exists to
# remove — eight peers issuing orders is not an organization, it is the "所有
# 東西擠在一起" state with extra steps. A request is declinable; an assignment
# is not, and only the coordinator may issue one.
KINDS = ("assignment", "request", "decision", "reply", "report")
HERDR = "/opt/homebrew/bin/herdr"

# Statuses in which a pane must not be interrupted. The boss may be mid-
# conversation with that department; barging in with a dispatch would splice a
# second instruction into their exchange. The item stays in the inbox either
# way, so nothing is lost by waiting.
BUSY_STATES = {"working", "blocked"}


def deliver_to_pane(root: Path, dept: str, item: dict) -> dict:
    """Push a work item into the department's live pane, if that is safe.

    Returns {"delivered": bool, "reason": str} — never raises: a delivery
    problem must not lose the inbox item that is already on disk.
    """
    lease = read_lease(root, dept)
    if not lease or lease.get("runner") != "herdr":
        return {"delivered": False, "reason": "no live cockpit pane (item queued in inbox)"}

    try:
        got = subprocess.run([HERDR, "agent", "get", dept], capture_output=True, text=True, timeout=20)
        if got.returncode != 0:
            return {"delivered": False, "reason": f"agent not resolvable: {got.stderr.strip()[:80]}"}
        status = json.loads(got.stdout)["result"]["agent"]["agent_status"]
    except (OSError, subprocess.SubprocessError, ValueError, KeyError) as exc:
        return {"delivered": False, "reason": f"status unreadable ({type(exc).__name__})"}

    if status in BUSY_STATES:
        return {"delivered": False, "reason": f"pane is {status} — 不打斷（可能是老闆正在協作）"}

    text = (
        f"【運營經理派工 · {item['priority']}】{item['task']}\n"
        f"（工作項 {item['id']}；完整收件匣與章程見 "
        f"{dept_dir(root, dept)}；結束前務必執行 Session 收尾契約）"
    )
    try:
        sent = subprocess.run([HERDR, "agent", "prompt", dept, text],
                              capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"delivered": False, "reason": f"prompt failed ({type(exc).__name__})"}
    if sent.returncode != 0:
        return {"delivered": False, "reason": f"prompt rejected: {sent.stderr.strip()[:80]}"}
    return {"delivered": True, "reason": f"pane {lease.get('pane_id')}"}


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
    parser.add_argument("--kind", choices=KINDS, default=None,
                        help="assignment (manager only) | request | reply | report; "
                             "defaults from --from")
    parser.add_argument("--reply-to", default=None, help="work-item id this answers")
    parser.add_argument("--canonical-task-id", default=None,
                        help="id in storage/next_tasks.json this item points at "
                             "(the canonical task stays the single source of truth)")
    parser.add_argument("--no-wake", action="store_true",
                        help="write the inbox item only; do not push it into a live pane")
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

    kind = args.kind or ("assignment" if args.sender == "manager"
                         else "report" if args.to_manager
                         else "reply" if args.reply_to else "request")
    if kind == "assignment" and args.sender != "manager":
        print(f"只有運營經理能指派工作。部門之間請用 --kind request（可被婉拒），"
              f"或把需求送給經理排序：--to-manager --from {args.sender}", file=sys.stderr)
        return 2

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
        "kind": kind,
        "reply_to": args.reply_to,
        "canonical_task_id": args.canonical_task_id,
        "created_at": now_iso(),
    }
    path = inbox / f"{item['id']}.json"
    atomic_write_json(path, item)
    print(path)

    # Peer traffic is CC'd to the coordinator so it keeps oversight without
    # sitting in the critical path. Replies are not CC'd: the request already
    # told the manager this exchange exists, and echoing both halves would turn
    # its inbox back into the noise the digest was built to end.
    if kind == "request":
        notice = {
            "id": f"cc_{item['id']}", "from": args.sender, "to": "manager",
            "priority": "P3", "kind": "cc",
            "task": f"（知會）{args.sender} → {args.dept}：{args.task[:120]}",
            "refs": [str(path)], "created_at": now_iso(),
        }
        atomic_write_json(args.root / "manager" / "inbox" / f"{notice['id']}.json", notice)

    if args.to_manager or args.no_wake:
        return 0

    result = deliver_to_pane(args.root, args.dept, item)
    if result["delivered"]:
        print(f"→ 已送進 {args.dept} 的視窗（{result['reason']}）")
    else:
        print(f"→ 未即時送達：{result['reason']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
