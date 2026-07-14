#!/usr/bin/env python3
"""Backfill deterministic ids for next_tasks.json rows with id=null.

Root problem: some receipt/dispatch writers appended rows without an `id`,
so `jq 'select(.id | test(...))'` throws and the rows are untrackable.

Fix (idempotent, flock-guarded, pre-serialized):
  1. For every row with id is None, synthesize a stable id:
       {task_type}_receipt_{sha1(task_type + title/description)[:12]}
     Collision-checked against all existing ids; on the (unlikely) clash a
     numeric suffix is appended.
  2. These null-id rows are all terminal receipts (succeeded/failed/deprecated).
     Per control-plane rule "claim metadata is active ownership only", strip any
     stale claimed_by / claimed_at / claim_session_id left on THESE rows only
     (scope limited to the backfilled rows — no full-pool sweep here).

Run:
  uv run python scripts/backfill_null_task_ids.py --dry-run
  uv run python scripts/backfill_null_task_ids.py --apply
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
NEXT_TASKS = ROOT / "storage" / "next_tasks.json"

from volpred.canonical_write import guard_canonical_write  # noqa: E402
from volpred.ops.diagnostics import warn  # noqa: E402

TERMINAL = {"succeeded", "failed", "deprecated"}
STALE_CLAIM_FIELDS = ("claimed_by", "claimed_at", "claim_session_id")


def synth_id(task: dict, existing: set[str]) -> str:
    ttype = task.get("task_type") or "task"
    text = task.get("title") or task.get("description") or ""
    digest = hashlib.sha1(f"{ttype}\x00{text}".encode("utf-8")).hexdigest()[:12]
    base = f"{ttype}_receipt_{digest}"
    candidate = base
    n = 1
    while candidate in existing:
        candidate = f"{base}_{n}"
        n += 1
    return candidate


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    if args.apply:
        guard_canonical_write(NEXT_TASKS)
    mode = "r+" if args.apply else "r"
    with NEXT_TASKS.open(mode, encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX if args.apply else fcntl.LOCK_SH)
        try:
            tasks = json.load(fh)
            if not isinstance(tasks, list):
                raise SystemExit("next_tasks.json not a list")

            existing = {t.get("id") for t in tasks if isinstance(t, dict) and t.get("id")}
            changes: list[dict] = []

            for t in tasks:
                if not isinstance(t, dict) or t.get("id") is not None:
                    continue
                new_id = synth_id(t, existing)
                existing.add(new_id)
                status = t.get("status")
                stale = [f for f in STALE_CLAIM_FIELDS if t.get(f) is not None]
                clear_claim = bool(stale) and status in TERMINAL
                changes.append({
                    "new_id": new_id,
                    "task_type": t.get("task_type"),
                    "status": status,
                    "title": (t.get("title") or t.get("description") or "")[:70],
                    "cleared_claim_fields": stale if clear_claim else [],
                })
                if args.apply:
                    t["id"] = new_id
                    t.setdefault("hygiene_log", []).append({
                        "action": "backfill_null_id",
                        "new_id": new_id,
                        "at": "2026-07-07",
                    })
                    if clear_claim:
                        for f in STALE_CLAIM_FIELDS:
                            t.pop(f, None)
                        t["hygiene_log"].append({
                            "action": "strip_stale_claim_terminal_row",
                            "fields": stale,
                            "at": "2026-07-07",
                        })

            if args.apply:
                # Pre-serialize to a string first so a serialization failure
                # cannot leave partial JSON on disk (control-plane invariant).
                try:
                    payload = json.dumps(tasks, indent=2, ensure_ascii=False)
                except (TypeError, ValueError) as e:
                    warn("backfill_null_ids", "serialize failed, aborting write", err=str(e))
                    return 2
                fh.seek(0)
                fh.truncate()
                fh.write(payload)
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"=== Backfill null task ids ({mode}) ===")
    print(f"rows touched: {len(changes)}")
    for c in changes:
        claim = f" | cleared_claim={c['cleared_claim_fields']}" if c["cleared_claim_fields"] else ""
        print(f"  {c['new_id']} [{c['task_type']}/{c['status']}] {c['title']}{claim}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
