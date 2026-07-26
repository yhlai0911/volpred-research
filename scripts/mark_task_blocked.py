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

sys.path.insert(0, str(ROOT / "src"))
from volpred.ops.next_tasks import write_tasks_locked  # noqa: E402
from volpred.ops.blocked_reasons import BLOCKED_REASONS as VALID_REASONS  # noqa: E402
from volpred.ops.blocked_reasons import is_valid as _valid_blocked_reason  # noqa: E402
from volpred.ops.diagnostics import warn as _diag_warn  # noqa: E402
# 2026-07-18: the 14-day default window used to be this module's own constant.
# It is now owned by volpred.ops.next_tasks (which enforces the same invariant on
# every writer, not just this CLI) so the number cannot drift into two.
from volpred.ops.next_tasks import default_blocked_until as _default_blocked_until  # noqa: E402
# 2026-07-10: this module used to define its OWN `shared_state_lock` — same name, same
# semantics, its own hardcoded LOCK_DIR — shadowing the real one. It therefore never
# picked up the sandboxing that keeps tests off the production lock, and
# test_mark_task_blocked_sets_awaiting_interactive_session took a blocking LOCK_EX on
# the very `control_plane` lock the cron writers use. One implementation, not two.
from volpred.ops.shared_lock import shared_state_lock  # noqa: E402


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


def _load() -> tuple[dict | list, list]:
    try:
        data = json.loads(NEXT_TASKS.read_text(encoding="utf-8"))
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


def _save(payload: dict | list, tasks: list) -> None:
    """Persist the full task list via the canonical one-shot writer (WS-A1b).

    The old tmp+replace held no LOCK_EX — the host-UI daemon's only repo
    mutation could clobber a concurrent claim/dispatch write wholesale.
    write_tasks_locked owns flock + serialize-first + priority normalization.
    The legacy dict-root wrapper is read tolerance only; the canonical queue
    root has been a list since the 2026-07-16 single-gateway refactor
    (append_next_task refuses non-list roots), so writing it back is refused
    loudly instead of silently re-materializing a retired schema.
    """
    if isinstance(payload, dict):
        _warn_block_cli(
            "next_tasks dict-root shape is no longer writable; canonical root is a list"
        )
        raise ValueError("next_tasks.json root must be a list (single-gateway 2026-07-16)")
    write_tasks_locked(NEXT_TASKS, tasks)


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

    with shared_state_lock("control_plane"):
        payload, tasks = _load()
        matched = None
        for idx, t in enumerate(tasks):
            if not isinstance(t, dict):
                _warn_block_cli(
                    "next_tasks entry schema invalid; skipping "
                    f"path={NEXT_TASKS} index={idx} type={type(t).__name__}"
                )
                continue
            if t.get("id") == args.id:
                matched = t
                break

        if matched is None:
            print(f"error: no task with id={args.id}", file=sys.stderr)
            return 1

        if args.unblock:
            status_before = (matched.get("status") or "").lower()
            if status_before in {"blocked", "closed_no_action", "superseded"}:
                matched["status"] = "pending"
            for k in (
                "blocked_reason",
                "blocked_at",
                "blocked_until",
                "blocked_note",
                "terminalized_at",
                "terminalized_reason",
            ):
                matched.pop(k, None)
            _validate_task_schema(matched)
            print(f"[mark_task_blocked] unblocked id={args.id}")
        else:
            reason = str(args.reason or "").strip().lower()
            incompatible = {
                field: matched[field]
                for field in (
                    "claimed_by",
                    "claimed_at",
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
                matched["terminalized_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
                matched["terminalized_reason"] = reason
                matched.pop("blocked_until", None)
            else:
                matched["status"] = "blocked"
                matched["blocked_until"] = args.until or _default_blocked_until()
            matched["blocked_reason"] = args.reason
            matched["blocked_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            if args.note:
                matched["blocked_note"] = args.note
            _validate_task_schema(matched)
            print(
                f"[mark_task_blocked] id={args.id} status={matched['status']} reason={args.reason}"
                + (f" until={matched.get('blocked_until')}" if matched.get("blocked_until") else "")
            )

        _save(payload, tasks)
    return 0


if __name__ == "__main__":
    sys.exit(main())
