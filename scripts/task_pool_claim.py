#!/usr/bin/env python3
"""Unified task-pool claim/complete CLI with cross-session file lock.

Schema additions to storage/next_tasks.json task entries:
  - claimed_by        : str  (session/owner id)
  - claimed_at        : ISO timestamp
  - claim_session_id  : str  (unique per spawn; lets us detect orphans)
  - completed_at      : ISO timestamp  (already exists)
  - result            : str  (already exists)
  - dispatch_lane     : agent | main_thread | blocked  (dispatcher ownership)

Status machine:
  pending  --claim-->  claimed  --start-->  in_progress  --complete-->  succeeded / failed / blocked
                          |
                          +--release-->  pending

Commands:
  claim    --id <task_id> --owner <name> [--session <sid>]
  release  --id <task_id>
  start    --id <task_id>
  handoff-main-thread --id <task_id> --note <text>
  complete --id <task_id> [--result <text>] [--status succeeded|failed|blocked]
  list     [--status pending|claimed|in_progress|stale] [--owner <name>] [--limit N]
  cleanup  --stale-hours <N>   (auto-release claims older than N hours with no completion)

File lock: fcntl.LOCK_EX on next_tasks.json across read-modify-write.

Run:
  uv run python scripts/task_pool_claim.py claim --id <id> --owner hourly-dispatch
  uv run python scripts/task_pool_claim.py complete --id <id> --result "summary" --status succeeded
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parents[1]
NEXT_TASKS = ROOT / "storage" / "next_tasks.json"

DEFAULT_STALE_HOURS = 6  # Claim older than this with no completion -> auto-release


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def _locked_load() -> Iterator[tuple[Any, list[dict[str, Any]]]]:
    NEXT_TASKS.parent.mkdir(parents=True, exist_ok=True)
    if not NEXT_TASKS.exists():
        NEXT_TASKS.write_text("[]", encoding="utf-8")
    fh = NEXT_TASKS.open("r+", encoding="utf-8")
    fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
    try:
        data = json.load(fh)
        if not isinstance(data, list):
            raise SystemExit("next_tasks.json is not a list")
        yield fh, data
        fh.seek(0)
        fh.truncate()
        json.dump(data, fh, indent=2, ensure_ascii=False)
    finally:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        fh.close()


def _matches(tasks: list[dict[str, Any]], task_id: str) -> list[dict[str, Any]]:
    return [t for t in tasks if t.get("id") == task_id]


def _find(tasks: list[dict[str, Any]], task_id: str) -> dict[str, Any]:
    matches = _matches(tasks, task_id)
    if not matches:
        raise SystemExit(f"task id not found: {task_id}")
    if len(matches) > 1:
        statuses = [str(t.get("status") or "") for t in matches]
        raise SystemExit(
            f"duplicate task id detected: {task_id} count={len(matches)} statuses={statuses}. "
            "Run scripts/dedupe_next_tasks.py first."
        )
    return matches[0]


def cmd_claim(args: argparse.Namespace) -> dict[str, Any]:
    session = args.session or os.environ.get("CLAUDE_SESSION_ID") or uuid.uuid4().hex[:12]
    with _locked_load() as (_fh, tasks):
        task = _find(tasks, args.id)
        existing_owner = task.get("claimed_by")
        existing_status = (task.get("status") or "").lower()
        # Idempotent: same owner re-claiming is OK
        if existing_owner and existing_owner != args.owner and existing_status in {"claimed", "in_progress"}:
            return {
                "ok": False,
                "reason": "already_claimed",
                "claimed_by": existing_owner,
                "claimed_at": task.get("claimed_at"),
            }
        if existing_status not in {"pending", "pending_main_thread", "claimed", "blocked", ""}:
            return {"ok": False, "reason": "wrong_status", "status": existing_status}
        task["status"] = "claimed"
        task["claimed_by"] = args.owner
        task["claimed_at"] = _now()
        task["claim_session_id"] = session
        return {"ok": True, "task_id": args.id, "owner": args.owner, "session": session, "status": "claimed"}


def cmd_start(args: argparse.Namespace) -> dict[str, Any]:
    with _locked_load() as (_fh, tasks):
        task = _find(tasks, args.id)
        if task.get("status") not in {"claimed", "in_progress"}:
            return {"ok": False, "reason": "not_claimed", "status": task.get("status")}
        task["status"] = "in_progress"
        task["started_at"] = _now()
        return {"ok": True, "task_id": args.id, "status": "in_progress"}


def cmd_release(args: argparse.Namespace) -> dict[str, Any]:
    with _locked_load() as (_fh, tasks):
        task = _find(tasks, args.id)
        prev_owner = task.get("claimed_by")
        task["status"] = "pending"
        task.pop("claimed_by", None)
        task.pop("claimed_at", None)
        task.pop("claim_session_id", None)
        task["last_released_at"] = _now()
        return {"ok": True, "task_id": args.id, "released_from": prev_owner}


def cmd_handoff_main_thread(args: argparse.Namespace) -> dict[str, Any]:
    with _locked_load() as (_fh, tasks):
        task = _find(tasks, args.id)
        prev_status = (task.get("status") or "").lower()
        if prev_status not in {"claimed", "in_progress", "pending", "pending_main_thread"}:
            return {"ok": False, "reason": "wrong_status", "status": task.get("status")}
        task["status"] = "pending_main_thread"
        task["handoff_note"] = args.note
        task["handoff_at"] = _now()
        task.pop("claimed_by", None)
        task.pop("claimed_at", None)
        task.pop("claim_session_id", None)
        return {"ok": True, "task_id": args.id, "status": "pending_main_thread"}


def cmd_complete(args: argparse.Namespace) -> dict[str, Any]:
    with _locked_load() as (_fh, tasks):
        task = _find(tasks, args.id)
        task["status"] = args.status
        task["completed_at"] = _now()
        if args.result:
            existing = task.get("result") or ""
            task["result"] = (existing + "\n\n" + args.result).strip() if existing else args.result
        return {"ok": True, "task_id": args.id, "status": args.status}


def cmd_list(args: argparse.Namespace) -> dict[str, Any]:
    with _locked_load() as (_fh, tasks):
        out: list[dict[str, Any]] = []
        for t in tasks:
            status = (t.get("status") or "").lower()
            if args.status == "stale":
                if status not in {"claimed", "in_progress"}:
                    continue
                claimed_at = t.get("claimed_at")
                if not claimed_at:
                    continue
                try:
                    age_h = (datetime.now(timezone.utc) - datetime.fromisoformat(claimed_at)).total_seconds() / 3600
                except Exception:
                    continue
                if age_h < args.stale_hours:
                    continue
            elif args.status and status != args.status:
                continue
            if args.owner and t.get("claimed_by") != args.owner:
                continue
            out.append({
                "id": t.get("id"),
                "title": t.get("title"),
                "task_type": t.get("task_type"),
                "priority": t.get("priority"),
                "status": status,
                "claimed_by": t.get("claimed_by"),
                "claimed_at": t.get("claimed_at"),
            })
        def _prio_key(x: dict[str, Any]) -> tuple[int, str]:
            p = x.get("priority")
            try:
                return (int(p), x.get("id") or "")
            except (TypeError, ValueError):
                return (9, x.get("id") or "")
        out.sort(key=_prio_key)
        if args.limit:
            out = out[: args.limit]
        return {"ok": True, "count": len(out), "tasks": out}


def cmd_cleanup(args: argparse.Namespace) -> dict[str, Any]:
    released = []
    with _locked_load() as (_fh, tasks):
        now = datetime.now(timezone.utc)
        for t in tasks:
            status = (t.get("status") or "").lower()
            if status not in {"claimed", "in_progress"}:
                continue
            claimed_at = t.get("claimed_at")
            if not claimed_at:
                continue
            try:
                age_h = (now - datetime.fromisoformat(claimed_at)).total_seconds() / 3600
            except Exception:
                continue
            if age_h >= args.stale_hours:
                released.append({"id": t.get("id"), "owner": t.get("claimed_by"), "age_h": round(age_h, 1)})
                t["status"] = "pending"
                t.pop("claimed_by", None)
                t.pop("claimed_at", None)
                t.pop("claim_session_id", None)
                t["last_released_at"] = _now()
                t["last_release_reason"] = f"auto_release_stale_{args.stale_hours}h"
    return {"ok": True, "released": released, "count": len(released)}


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("claim"); p.add_argument("--id", required=True); p.add_argument("--owner", required=True); p.add_argument("--session"); p.set_defaults(fn=cmd_claim)
    p = sub.add_parser("start"); p.add_argument("--id", required=True); p.set_defaults(fn=cmd_start)
    p = sub.add_parser("release"); p.add_argument("--id", required=True); p.set_defaults(fn=cmd_release)
    p = sub.add_parser("handoff-main-thread"); p.add_argument("--id", required=True); p.add_argument("--note", required=True); p.set_defaults(fn=cmd_handoff_main_thread)
    p = sub.add_parser("complete"); p.add_argument("--id", required=True); p.add_argument("--status", choices=["succeeded", "failed", "blocked"], default="succeeded"); p.add_argument("--result"); p.set_defaults(fn=cmd_complete)
    p = sub.add_parser("list"); p.add_argument("--status"); p.add_argument("--owner"); p.add_argument("--limit", type=int); p.add_argument("--stale-hours", type=int, default=DEFAULT_STALE_HOURS); p.set_defaults(fn=cmd_list)
    p = sub.add_parser("cleanup"); p.add_argument("--stale-hours", type=int, default=DEFAULT_STALE_HOURS); p.set_defaults(fn=cmd_cleanup)

    args = ap.parse_args()
    result = args.fn(args)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
