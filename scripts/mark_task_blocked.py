"""Mark a task in storage/next_tasks.json as blocked.

Hard-blocks (persist on the task record) sit alongside soft auto-detected
blocks in continue_task_dispatch.py. Use this CLI when a candidate has a
persistent dispatch obstacle that cannot be inferred from title/description:

- prior_attempts_failed: the task has been dispatched + failed; needs
  main-thread debug before retry (e.g. K1100g_d9 IS-fits subprocess hang)
- awaiting_external_data: needs auth/credentials/raw data not yet
  configured (e.g. Dropbox tick data, GCP BigQuery)
- awaiting_interactive_session: needs Chrome MCP / FB auth / other
  interactive-only UI access that hourly cron cannot provide
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

  # expiry is only a not-before; named live gate must also pass:
  uv run python scripts/mark_task_blocked.py --id issue9 \
    --reason awaiting_event_window \
    --until 2026-08-03T04:56:16+00:00 \
    --unblock-gate work_shadow_cutover_ready_v1

Inverse:
  uv run python scripts/mark_task_blocked.py --id <id> --unblock
"""
from __future__ import annotations

import argparse
import fcntl
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NEXT_TASKS = ROOT / "storage" / "next_tasks.json"

sys.path.insert(0, str(ROOT / "src"))
from volpred.canonical_write import guard_canonical_write
from volpred.ops.blocked_reasons import BLOCKED_REASONS as VALID_REASONS
from volpred.ops.blocked_reasons import (
    INCIDENT_SUSTAINED_CLEAN_GATE,
    UNBLOCK_GATES as VALID_UNBLOCK_GATES,
)
from volpred.ops.blocked_reasons import is_valid as _valid_blocked_reason
from volpred.ops.diagnostics import warn as _diag_warn

# 2026-07-18: the 14-day default window used to be this module's own constant.
# It is now owned by volpred.ops.next_tasks (which enforces the same invariant on
# every writer, not just this CLI) so the number cannot drift into two.
from volpred.ops.next_tasks import clear_claim_ownership
from volpred.ops.next_tasks import (
    default_blocked_until as _default_blocked_until,
)
from volpred.ops.next_tasks import write_tasks_to_handle

TERMINAL_INTENT_REASONS = {"deprecated"}
CANONICAL_STATUSES = {
    "pending",
    "pending_main_thread",
    "claimed",
    "in_progress",
    "compute_queued",
    "blocked",
    "blocked_on_user",
    "succeeded",
    "succeeded_null_result",
    "failed",
    "cancelled",
    "closed",
    "closed_no_action",
    "superseded",
}


def _warn_block_cli(message: str) -> None:
    _diag_warn("mark_task_blocked", message)


def _decode_tasks(raw: str) -> tuple[dict | list, list]:
    try:
        data = json.loads(raw)
    except Exception as exc:
        _warn_block_cli(
            "next_tasks read failed; refusing to update "
            f"path={NEXT_TASKS} error={type(exc).__name__}: {exc}"
        )
        raise
    if isinstance(data, dict):
        tasks = data.get("tasks", [])
        if not isinstance(tasks, list):
            _warn_block_cli(
                "next_tasks schema invalid; refusing to update "
                f"path={NEXT_TASKS} field=tasks type={type(tasks).__name__}"
            )
            raise ValueError("next_tasks payload field 'tasks' must be a list")
        return data, tasks
    if not isinstance(data, list):
        _warn_block_cli(
            "next_tasks schema invalid; refusing to update "
            f"path={NEXT_TASKS} type={type(data).__name__}"
        )
        raise ValueError("next_tasks payload must be a list or object with tasks list")
    return data, data


def _load() -> tuple[dict | list, list]:
    return _decode_tasks(NEXT_TASKS.read_text(encoding="utf-8"))


def _validate_task_schema(task: dict) -> None:
    status = str(task.get("status") or "").strip().lower()
    if status not in CANONICAL_STATUSES:
        raise ValueError(f"task status is not canonical: {status!r}")
    if status != "blocked":
        return

    reason = str(task.get("blocked_reason") or "").strip().lower()
    if not _valid_blocked_reason(reason):
        raise ValueError("status=blocked requires a valid blocked_reason")
    if reason not in TERMINAL_INTENT_REASONS and not task.get("blocked_until"):
        raise ValueError("non-terminal blocked task requires blocked_until")
    gate = task.get("unblock_gate")
    if gate is not None and (
        gate not in VALID_UNBLOCK_GATES
        or reason != "awaiting_event_window"
    ):
        raise ValueError(
            "unblock_gate requires an allowlisted gate and "
            "blocked_reason=awaiting_event_window"
        )


def _mutate_tasks(args: argparse.Namespace, tasks: list) -> int:
    matched = None
    for idx, task in enumerate(tasks):
        if not isinstance(task, dict):
            _warn_block_cli(
                "next_tasks entry schema invalid; skipping "
                f"path={NEXT_TASKS} index={idx} "
                f"type={type(task).__name__}"
            )
            continue
        if task.get("id") == args.id:
            matched = task
            break
    if matched is None:
        print(f"error: no task with id={args.id}", file=sys.stderr)
        return 1

    if args.unblock:
        if matched.get("unblock_gate") is not None:
            print(
                "error: task has an unresolved unblock_gate; "
                "run the canonical expiry sweeper",
                file=sys.stderr,
            )
            return 2
        status_before = (matched.get("status") or "").lower()
        if status_before in {"blocked", "closed_no_action", "superseded"}:
            matched["status"] = "pending"
            # Same duty as the expiry sweeper and _repend_task: a row returning
            # to pending must not keep the claim trace of its previous holder,
            # or the Work Coordinator reconciler reports invalid_lifecycle.
            clear_claim_ownership(matched)
        for key in (
            "blocked_reason",
            "blocked_at",
            "blocked_until",
            "blocked_note",
            "unblock_gate",
            "unblock_incident_id",
            "terminalized_at",
            "terminalized_reason",
        ):
            matched.pop(key, None)
        _validate_task_schema(matched)
        print(f"[mark_task_blocked] unblocked id={args.id}")
        return 0

    reason = str(args.reason or "").strip().lower()
    existing_gate = matched.get("unblock_gate")
    if existing_gate is not None and (
        reason not in {"awaiting_event_window", *TERMINAL_INTENT_REASONS}
        or (
            args.unblock_gate is not None
            and args.unblock_gate != existing_gate
        )
    ):
        print(
            "error: unresolved unblock_gate cannot be changed by a "
            "non-terminal re-block",
            file=sys.stderr,
        )
        return 2
    incompatible = {
        field: matched[field]
        for field in (
            "claimed_by",
            "claimed_at",
            "claim_expires_at",
            "claim_session_id",
            "started_at",
            "completed_at",
        )
        if field in matched
    }
    if incompatible:
        previous = matched.setdefault("block_transition_previous", {})
        previous.update(incompatible)
        for field in incompatible:
            matched.pop(field, None)
    if reason in TERMINAL_INTENT_REASONS:
        matched["status"] = "closed_no_action"
        matched["terminalized_at"] = datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        )
        matched["terminalized_reason"] = reason
        matched.pop("blocked_until", None)
        matched.pop("unblock_gate", None)
        matched.pop("unblock_incident_id", None)
    else:
        matched["status"] = "blocked"
        matched["blocked_until"] = args.until or _default_blocked_until()
        if existing_gate is None and args.unblock_gate:
            matched["unblock_gate"] = args.unblock_gate
        if args.unblock_gate == INCIDENT_SUSTAINED_CLEAN_GATE:
            matched["unblock_incident_id"] = args.unblock_incident_id
        elif matched.get("unblock_gate") != INCIDENT_SUSTAINED_CLEAN_GATE:
            matched.pop("unblock_incident_id", None)
    matched["blocked_reason"] = args.reason
    matched["blocked_at"] = datetime.now(timezone.utc).isoformat(
        timespec="seconds"
    )
    if args.note:
        matched["blocked_note"] = args.note
    _validate_task_schema(matched)
    print(
        f"[mark_task_blocked] id={args.id} "
        f"status={matched['status']} reason={args.reason}"
        + (
            f" until={matched.get('blocked_until')}"
            if matched.get("blocked_until")
            else ""
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id", required=True, help="task id to mark")
    parser.add_argument(
        "--reason",
        choices=sorted(VALID_REASONS),
        help=f"block reason (one of: {sorted(VALID_REASONS)})",
    )
    parser.add_argument("--note", default=None, help="free-form context")
    parser.add_argument(
        "--until",
        default=None,
        help=(
            "ISO date for auto-recheck; after this dispatcher treats "
            "block as expired"
        ),
    )
    parser.add_argument(
        "--unblock-gate",
        choices=sorted(VALID_UNBLOCK_GATES),
        help="Named live condition that must pass after --until before re-pending",
    )
    parser.add_argument(
        "--unblock-incident-id",
        help=(
            "Canonical incident id required by "
            f"--unblock-gate {INCIDENT_SUSTAINED_CLEAN_GATE}"
        ),
    )
    parser.add_argument(
        "--unblock",
        action="store_true",
        help="remove block fields instead of setting them",
    )
    args = parser.parse_args()

    if not args.unblock and not args.reason:
        print("error: --reason required unless --unblock", file=sys.stderr)
        return 2
    if args.unblock_gate and args.reason != "awaiting_event_window":
        print(
            "error: --unblock-gate requires --reason awaiting_event_window",
            file=sys.stderr,
        )
        return 2
    if (
        args.unblock_gate == INCIDENT_SUSTAINED_CLEAN_GATE
        and not str(args.unblock_incident_id or "").strip()
    ):
        print(
            f"error: --unblock-gate {INCIDENT_SUSTAINED_CLEAN_GATE} "
            "requires --unblock-incident-id",
            file=sys.stderr,
        )
        return 2
    if (
        args.unblock_incident_id
        and args.unblock_gate != INCIDENT_SUSTAINED_CLEAN_GATE
    ):
        print(
            "error: --unblock-incident-id is only valid with "
            f"--unblock-gate {INCIDENT_SUSTAINED_CLEAN_GATE}",
            file=sys.stderr,
        )
        return 2

    guard_canonical_write(NEXT_TASKS)
    with NEXT_TASKS.open("r+", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            fh.seek(0)
            payload, tasks = _decode_tasks(fh.read())
            result = _mutate_tasks(args, tasks)
            if result == 0:
                if isinstance(payload, dict):
                    _warn_block_cli(
                        "next_tasks dict-root shape is no longer writable; "
                        "canonical root is a list"
                    )
                    raise ValueError(
                        "next_tasks.json root must be a list "
                        "(single-gateway 2026-07-16)"
                    )
                write_tasks_to_handle(fh, tasks)
            return result
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


if __name__ == "__main__":
    sys.exit(main())
