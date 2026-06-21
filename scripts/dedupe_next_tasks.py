#!/usr/bin/env python3
"""Deduplicate storage/next_tasks.json by task id, preserving the best receipt.

Why this exists:
- `task_pool_claim.py` assumes task ids are unique.
- A duplicate pending row after a terminal row creates a zombie task:
  dispatcher sees pending, but claim/start resolves to the earlier terminal row.

Policy:
- Group by exact `id`.
- Keep the "best" row per id by lifecycle depth:
  terminal (succeeded/failed/blocked) > in_progress > claimed > pending_main_thread > pending > blank
- Break ties by richer receipts (`completed_at`, `started_at`, `claimed_at`, `result` length),
  then preserve the earlier row.
"""
from __future__ import annotations

import argparse
import fcntl
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
NEXT_TASKS = ROOT / "storage" / "next_tasks.json"

STATUS_RANK = {
    "succeeded": 60,
    "failed": 60,
    "blocked": 60,
    "succeeded_null_result": 60,
    "closed": 60,
    "superseded": 60,
    "in_progress": 40,
    "claimed": 30,
    "pending_main_thread": 20,
    "pending": 10,
    "": 0,
}


def _utc_iso_z() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_tasks(fh) -> list[dict[str, Any]]:
    fh.seek(0)
    data = json.load(fh)
    if not isinstance(data, list):
        raise SystemExit("next_tasks.json is not a list")
    return data


def _score(task: dict[str, Any], index: int) -> tuple[int, int, int, int, int]:
    status = str(task.get("status") or "").lower()
    return (
        STATUS_RANK.get(status, 0),
        1 if task.get("completed_at") else 0,
        1 if task.get("started_at") else 0,
        1 if task.get("claimed_at") else 0,
        len(str(task.get("result") or "")) * 100000 - index,
    )


def dedupe(tasks: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    grouped: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    ordered: list[str] = []
    passthrough: list[dict[str, Any]] = []

    for idx, task in enumerate(tasks):
        task_id = str(task.get("id") or "")
        if not task_id:
            passthrough.append(task)
            continue
        if task_id not in grouped:
            grouped[task_id] = []
            ordered.append(task_id)
        grouped[task_id].append((idx, task))

    deduped: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for task_id in ordered:
        entries = grouped[task_id]
        if len(entries) == 1:
            deduped.append(entries[0][1])
            continue
        best_idx, best_task = max(entries, key=lambda pair: _score(pair[1], pair[0]))
        kept = dict(best_task)
        kept["dedup_kept_at"] = kept.get("dedup_kept_at") or _utc_iso_z()
        kept["dedup_kept_reason"] = (
            f"kept among {len(entries)} duplicates by status/receipt precedence; "
            f"statuses={[str(t.get('status') or '') for _, t in entries]}"
        )
        deduped.append(kept)
        for idx, task in entries:
            if idx == best_idx:
                continue
            dropped.append({
                "id": task_id,
                "dropped_status": task.get("status"),
                "kept_status": best_task.get("status"),
                "created_at": task.get("created_at"),
            })

    deduped.extend(passthrough)
    return deduped, dropped


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="rewrite storage/next_tasks.json in-place")
    ap.add_argument("--json", action="store_true", help="print full JSON summary")
    args = ap.parse_args()

    with NEXT_TASKS.open("r+", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            tasks = _load_tasks(fh)
            deduped, dropped = dedupe(tasks)
            summary = {
                "ok": True,
                "before": len(tasks),
                "after": len(deduped),
                "dropped_count": len(dropped),
                "dropped": dropped,
                "apply": args.apply,
            }
            if args.apply and dropped:
                fh.seek(0)
                fh.truncate()
                json.dump(deduped, fh, ensure_ascii=False, indent=2)
                fh.write("\n")
            if args.json:
                print(json.dumps(summary, ensure_ascii=False, indent=2))
            else:
                print(
                    json.dumps(
                        {
                            "ok": True,
                            "before": len(tasks),
                            "after": len(deduped),
                            "dropped_count": len(dropped),
                            "apply": args.apply,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
