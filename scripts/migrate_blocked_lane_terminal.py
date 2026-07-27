#!/usr/bin/env python3
"""Migrate deprecated blocked tasks out of the active blocked lane.

This is a one-time-but-idempotent control-plane hygiene script for C2 in
docs/platform_optimization_plan_20260704.md. It keeps the original
blocked_reason/blocked_note as audit trail, moves blocked+deprecated rows to a
terminal status, and clears stale claim metadata on blocked rows so inactive
work does not look owned by a dead session.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
NEXT_TASKS = ROOT / "storage" / "next_tasks.json"

from volpred.ops.next_tasks import (  # noqa: E402
    validate_task_status,
    write_tasks_to_handle,
)

CLAIM_FIELDS = (
    "claimed_by",
    "claimed_at",
    "claim_expires_at",
    "claim_session_id",
)

SUPERSEDED_HINTS = (
    "already covered",
    "already published",
    "already in feed",
    "arc-covered",
    "arc duplicate",
    "arc dup",
    "arc-dedup",
    "canonical",
    "covered by",
    "dedup",
    "draft",
    "dup",
    "duplicate",
    "feed already",
    "merged into",
    "mile_",
    "published",
    "refill 重複",
    "same-family",
    "same-k",
    "subsumed",
    "已 cover",
    "已 published",
    "已覆蓋",
    "撞題",
    "覆蓋",
    "重複",
)


@dataclass
class MigrationStats:
    deprecated_terminalized: int = 0
    to_superseded: int = 0
    to_closed_no_action: int = 0
    stale_claims_cleared: int = 0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _task_text(task: dict[str, Any]) -> str:
    parts = [
        str(task.get("id") or ""),
        str(task.get("title") or ""),
        str(task.get("description") or ""),
        str(task.get("blocked_note") or ""),
    ]
    return "\n".join(parts).lower()


def terminal_status_for_deprecated(task: dict[str, Any]) -> str:
    text = _task_text(task)
    if any(hint in text for hint in SUPERSEDED_HINTS):
        return "superseded"
    return "closed_no_action"


def migrate_tasks(tasks: list[Any], *, now_iso: str | None = None) -> MigrationStats:
    now_iso = now_iso or _now_iso()
    stats = MigrationStats()

    for task in tasks:
        if not isinstance(task, dict):
            continue

        original_status = str(task.get("status") or "").strip().lower()
        reason = str(task.get("blocked_reason") or "").strip().lower()

        if original_status == "blocked" and reason == "deprecated":
            target = terminal_status_for_deprecated(task)
            # This is the one Python writer that derives a status dynamically; a
            # bad derivation must not slip an out-of-vocab status into the queue.
            validate_task_status(target)
            task["status"] = target
            task["terminal_migration_at"] = now_iso
            task["terminal_migration_from_status"] = "blocked"
            task["terminal_migration_from_reason"] = "deprecated"
            task["terminal_migration_target_status"] = target
            task.pop("blocked_until", None)
            stats.deprecated_terminalized += 1
            if target == "superseded":
                stats.to_superseded += 1
            else:
                stats.to_closed_no_action += 1

        if original_status == "blocked" and any(task.get(field) for field in CLAIM_FIELDS):
            task["stale_claim_cleared_at"] = now_iso
            for field in CLAIM_FIELDS:
                previous = task.pop(field, None)
                if previous is not None:
                    task[f"stale_claim_previous_{field}"] = previous
            stats.stale_claims_cleared += 1

    return stats


def _load_tasks(handle) -> list[Any]:
    handle.seek(0)
    data = json.load(handle)
    if not isinstance(data, list):
        raise SystemExit("next_tasks.json must be a list")
    return data


def _write_tasks(handle, tasks: list[Any]) -> None:
    # Shared hardened writer: normalize priorities + status audit +
    # serialize-first-then-truncate + surrogate scrub.
    write_tasks_to_handle(handle, tasks)


def run(*, apply: bool, path: Path = NEXT_TASKS) -> MigrationStats:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("r+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            tasks = _load_tasks(handle)
            stats = migrate_tasks(tasks)
            if apply:
                _write_tasks(handle, tasks)
            return stats
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write changes; default is dry-run")
    parser.add_argument("--path", default=str(NEXT_TASKS), help="next_tasks path for tests or dry runs")
    args = parser.parse_args()

    stats = run(apply=args.apply, path=Path(args.path))
    mode = "apply" if args.apply else "dry-run"
    print(
        "[migrate_blocked_lane_terminal] "
        f"mode={mode} deprecated_terminalized={stats.deprecated_terminalized} "
        f"to_superseded={stats.to_superseded} "
        f"to_closed_no_action={stats.to_closed_no_action} "
        f"stale_claims_cleared={stats.stale_claims_cleared}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
