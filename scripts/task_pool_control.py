#!/usr/bin/env python3
"""Control the recoverable direct-execution mode for the legacy task pool."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from volpred.ops.task_pool_mode import (  # noqa: E402
    enter_direct_execution_mode,
    load_task_pool_mode,
    reconcile_direct_execution_pool,
    restore_task_pool_backup,
)


DEFAULT_QUEUE = ROOT / "storage" / "next_tasks.json"
DEFAULT_STATE = ROOT / "storage" / "ops" / "task_pool_mode.json"
DEFAULT_BACKUP_DIR = ROOT / "storage" / "backups" / "task_pool"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _paths(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    enter = commands.add_parser(
        "enter-direct",
        help="verify an exact backup, close admission, and clear the queue",
    )
    _paths(enter)
    enter.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP_DIR)
    enter.add_argument("--actor", required=True)
    enter.add_argument("--reason", required=True)
    enter.add_argument("--preserve-task-id", action="append", default=[])
    enter.add_argument("--now", default=None, help=argparse.SUPPRESS)

    status = commands.add_parser("status", help="read back mode and queue counts")
    _paths(status)

    reconcile = commands.add_parser(
        "reconcile-direct",
        help="remove rows outside the active direct-mode preserve receipt",
    )
    _paths(reconcile)
    reconcile.add_argument("--actor", required=True)
    reconcile.add_argument("--reason", required=True)
    reconcile.add_argument("--now", default=None, help=argparse.SUPPRESS)

    restore = commands.add_parser(
        "restore",
        help="restore the active verified backup when the live queue is empty",
    )
    _paths(restore)
    restore.add_argument("--backup", type=Path, required=True)
    restore.add_argument("--actor", required=True)
    restore.add_argument("--reason", required=True)
    restore.add_argument("--now", default=None, help=argparse.SUPPRESS)
    return parser


def _queue_snapshot(path: Path) -> dict[str, object]:
    if not path.exists():
        rows: list[object] = []
    else:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError("task queue root must be a list")
        rows = payload
    pending = 0
    claimed_pending = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("status") == "pending":
            pending += 1
            if row.get("claimed_by"):
                claimed_pending += 1
    return {
        "pool_count": len(rows),
        "pending_count": pending,
        "claimed_pending_count": claimed_pending,
    }


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "enter-direct":
        receipt = enter_direct_execution_mode(
            queue_path=args.queue,
            state_path=args.state,
            backup_dir=args.backup_dir,
            activated_by=args.actor,
            reason=args.reason,
            preserve_task_ids=args.preserve_task_id,
            now=args.now or _now(),
        )
        print(json.dumps({"ok": True, **asdict(receipt)}, ensure_ascii=False, indent=2))
        return 0
    if args.command == "reconcile-direct":
        receipt = reconcile_direct_execution_pool(
            queue_path=args.queue,
            state_path=args.state,
            reconciled_by=args.actor,
            reason=args.reason,
            now=args.now or _now(),
        )
        print(json.dumps({"ok": True, **asdict(receipt)}, ensure_ascii=False, indent=2))
        return 0
    if args.command == "restore":
        receipt = restore_task_pool_backup(
            queue_path=args.queue,
            state_path=args.state,
            backup_path=args.backup,
            restored_by=args.actor,
            reason=args.reason,
            now=args.now or _now(),
        )
        print(json.dumps({"ok": True, **asdict(receipt)}, ensure_ascii=False, indent=2))
        return 0

    mode = load_task_pool_mode(args.state)
    snapshot = _queue_snapshot(args.queue)
    print(
        json.dumps(
            {"ok": True, **snapshot, "mode": asdict(mode)},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
