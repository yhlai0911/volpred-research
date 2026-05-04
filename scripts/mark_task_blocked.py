"""Mark a task in storage/next_tasks.json as blocked.

Hard-blocks (persist on the task record) sit alongside soft auto-detected
blocks in continue_task_dispatch.py. Use this CLI when a candidate has a
persistent dispatch obstacle that cannot be inferred from title/description:

- prior_attempts_failed: the task has been dispatched + failed; needs
  main-thread debug before retry (e.g. K1100g_d9 IS-fits subprocess hang)
- awaiting_external_data: needs auth/credentials/raw data not yet
  configured (e.g. Dropbox tick data, GCP BigQuery)
- compute_runtime_incompatible: experiment runtime exceeds background
  agent timeout; main-thread or specific worker only
- kid_collision: K-id reused; rename before dispatch
- self_tagged_optional: task self-flags itself optional/skippable
- deprecated: superseded by another task / no longer relevant

Usage:
  uv run python scripts/mark_task_blocked.py \
    --id K1100g_d9_cadence_verify \
    --reason compute_runtime_incompatible \
    --note "Prior agent IS-fits subprocess killed at 17:09; needs main-thread or longer-runtime worker"

  # auto-recheck after a date:
  uv run python scripts/mark_task_blocked.py --id K1100h \
    --reason awaiting_external_data \
    --until 2026-06-01 \
    --note "Awaiting Dropbox tick data 2017-2021 access from user"

Inverse:
  uv run python scripts/mark_task_blocked.py --id <id> --unblock
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NEXT_TASKS = ROOT / "storage" / "next_tasks.json"

VALID_REASONS = {
    "awaiting_external_data",
    "compute_runtime_incompatible",
    "self_tagged_optional",
    "kid_collision",
    "prior_attempts_failed",
    "deprecated",
}


def _load() -> tuple[dict | list, list]:
    data = json.loads(NEXT_TASKS.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return data, data.get("tasks", [])
    return data, data


def _save(payload: dict | list, tasks: list) -> None:
    if isinstance(payload, dict) and "tasks" in payload:
        payload["tasks"] = tasks
        out = payload
    else:
        out = tasks
    NEXT_TASKS.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id", required=True, help="task id to mark")
    parser.add_argument("--reason", choices=sorted(VALID_REASONS),
                        help=f"block reason (one of: {sorted(VALID_REASONS)})")
    parser.add_argument("--note", default=None, help="free-form context")
    parser.add_argument("--until", default=None,
                        help="ISO date for auto-recheck; after this dispatcher treats block as expired")
    parser.add_argument("--unblock", action="store_true",
                        help="remove block fields instead of setting them")
    args = parser.parse_args()

    if not args.unblock and not args.reason:
        print("error: --reason required unless --unblock", file=sys.stderr)
        return 2

    payload, tasks = _load()
    matched = None
    for t in tasks:
        if t.get("id") == args.id:
            matched = t
            break

    if matched is None:
        print(f"error: no task with id={args.id}", file=sys.stderr)
        return 1

    if args.unblock:
        for k in ("blocked_reason", "blocked_at", "blocked_until", "blocked_note"):
            matched.pop(k, None)
        print(f"[mark_task_blocked] unblocked id={args.id}")
    else:
        matched["blocked_reason"] = args.reason
        matched["blocked_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if args.note:
            matched["blocked_note"] = args.note
        if args.until:
            matched["blocked_until"] = args.until
        print(
            f"[mark_task_blocked] id={args.id} reason={args.reason}"
            + (f" until={args.until}" if args.until else "")
        )

    _save(payload, tasks)
    return 0


if __name__ == "__main__":
    sys.exit(main())
