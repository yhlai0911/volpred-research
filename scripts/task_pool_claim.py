#!/usr/bin/env python3
"""Unified task-pool claim/complete CLI with cross-session file lock.

Schema additions to storage/next_tasks.json task entries:
  - claimed_by        : str  (session/owner id)
  - claimed_at        : ISO timestamp
  - claim_session_id  : str  (unique per spawn; lets us detect orphans)
  - completed_at      : ISO timestamp  (already exists)
  - result            : str  (already exists)
  - dispatch_lane     : agent | main_thread | blocked  (dispatcher ownership)
  - compute_job_id    : str  (掛在 compute queue 上的 job id；job 仍活著時
                              cleanup 的 stale reaper 不回收此 task)

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
  list     [--status pending|claimed|in_progress|stale] [--owner <name>] [--limit N] [--codex-eligible]
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
import re
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

# Ensure repo root in sys.path so `volpred.ops` imports work when invoked as
# `python scripts/task_pool_claim.py` from anywhere.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

from volpred.canonical_write import guard_canonical_write  # noqa: E402
from volpred.ops.next_tasks import (  # noqa: E402
    normalize_priority,
    normalize_task_priority,
    normalize_task_priorities,
    priority_sort_key,
    write_tasks_to_handle,
)
from volpred.ops.timestamps import parse_iso_warn  # noqa: E402
from volpred.ops import dreaming_revalidate  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
NEXT_TASKS = ROOT / "storage" / "next_tasks.json"

DEFAULT_STALE_HOURS = 6  # Claim older than this with no completion -> auto-release
TERMINAL_STATUSES = {"succeeded", "failed", "blocked"}
CODEX_ELIGIBLE_TASK_TYPES = {
    "platform_ops",
    "experiment",
    "governance",
    "code_review",
    "paper_review",
    "daily_article",
    "daily_digest",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def _locked_load() -> Iterator[tuple[Any, list[dict[str, Any]]]]:
    guard_canonical_write(NEXT_TASKS)
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
        # Shared hardened writer: serialize-first-then-truncate + surrogate scrub
        # + status audit. The serialize-first invariant (originally grown inline
        # here after incident 2026-07-05) now lives in
        # volpred.ops.next_tasks.write_tasks_to_handle so every writer shares it.
        write_tasks_to_handle(fh, data)
    finally:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        fh.close()


@contextmanager
def _locked_readonly() -> Iterator[list[dict[str, Any]]]:
    if not NEXT_TASKS.exists():
        yield []
        return
    fh = NEXT_TASKS.open("r", encoding="utf-8")
    fcntl.flock(fh.fileno(), fcntl.LOCK_SH)
    try:
        data = json.load(fh)
        if not isinstance(data, list):
            raise SystemExit("next_tasks.json is not a list")
        yield data
    finally:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        fh.close()


def _task_key(task: dict[str, Any]) -> str:
    return str(task.get("id") or task.get("task_id") or "")


def _record_status_history(
    task: dict[str, Any],
    *,
    frm: str,
    to: str,
    by: str,
    note: str | None = None,
) -> None:
    """Append a status-transition trace so loop_health can judge first-pass rate.

    Why: `loop_health.compute_first_pass_success` infers retry vs first-pass from
    `status_history`. Without it, only the small subset of tasks that also appear
    in work_log by their tid/kid is traceable (~23% coverage as of 2026-06-30),
    forcing the metric into perpetual `low_coverage`. Logging on every transition
    here closes that gap for hourly-dispatched tasks.
    """
    if not isinstance(task.get("status_history"), list):
        task["status_history"] = []
    entry: dict[str, Any] = {"ts": _now(), "from": frm, "to": to, "by": by}
    if note:
        entry["note"] = note
    task["status_history"].append(entry)


def _matches(tasks: list[dict[str, Any]], task_id: str) -> list[dict[str, Any]]:
    return [t for t in tasks if _task_key(t) == task_id]


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


def _normalized_task_type(task: dict[str, Any]) -> str:
    return (
        str(task.get("task_type") or "")
        .strip()
        .lower()
        .replace("-", "_")
        .replace(" ", "_")
    )


def _is_codex_eligible_task(task: dict[str, Any]) -> bool:
    status = str(task.get("status") or "").strip().lower()
    if status == "pending_main_thread":
        return False
    lane = str(task.get("dispatch_lane") or "").strip().lower()
    if lane in {"main_thread", "blocked"}:
        return False
    task_type = _normalized_task_type(task)
    if task_type in CODEX_ELIGIBLE_TASK_TYPES:
        return True
    preferred_agent = (
        str(task.get("preferred_agent") or task.get("target_agent") or "")
        .strip()
        .lower()
    )
    return preferred_agent == "codex"


def _revalidate_dreaming_before_claim(
    task: dict[str, Any], *, owner: str
) -> dict[str, Any] | None:
    """Refuse a dreaming claim whose condition dissolved since the night it was seen.

    A dreaming task is a snapshot. On 2026-07-17 four `orphaned_experiment` tasks
    were dispatched three days after `kb_backfill_unrecorded_experiments` had already
    written the knowledge entries they existed to demand — an agent following the
    description literally writes DUPLICATES. Re-running the finding's own detector
    here closes it as a fresh no-op instead, the same guard alerts already have.

    Returns None for every task with no verdict (non-dreaming, unregistered pattern,
    check failed, condition still true) — silence means dispatch as before.
    """
    verdict = dreaming_revalidate.revalidate(task)
    if verdict is None or not verdict.cleared:
        return None
    dreaming_revalidate.close_as_cleared(task, verdict, by=owner, now=_now())
    return {
        "ok": False,
        "reason": dreaming_revalidate.CLEARED_REASON,
        "task_id": _task_key(task),
        "pattern_type": verdict.pattern_type,
        "detail": verdict.detail,
        "status": "succeeded",
    }


def _expire_managed_event_before_claim(
    task: dict[str, Any], *, owner: str
) -> dict[str, Any] | None:
    """Reject a canonical event claim that lost the race with its deadline."""

    managed = _normalized_task_type(task) == "event_article" and (
        str(task.get("source") or "").strip().lower() == "event_expander"
        or bool(task.get("ref_event_job_id"))
    )
    if not managed:
        return None

    task_id = _task_key(task)
    raw_deadline = task.get("deadline")
    if not raw_deadline:
        schema_error = "missing_deadline"
        deadline = None
    else:
        deadline = parse_iso_warn(
            raw_deadline,
            tag="claim",
            field_name="deadline",
            fallback=None,
            site="event_deadline_guard",
            task_id=task_id,
        )
        schema_error = "invalid_deadline" if deadline is None else None
    if schema_error:
        now_text = _now()
        previous = str(task.get("status") or "").strip().lower() or "pending"
        task["status"] = "failed"
        task["completed_at"] = now_text
        task["failed_at"] = now_text
        task["result"] = "managed event task has no valid deadline"
        task["last_error"] = schema_error
        _record_status_history(
            task,
            frm=previous,
            to="failed",
            by=owner,
            note=f"claim_rejected_{schema_error}",
        )
        return {
            "ok": False,
            "reason": schema_error,
            "task_id": task_id,
            "status": "failed",
        }

    now_text = _now()
    now = parse_iso_warn(
        now_text,
        tag="claim",
        field_name="claim_now",
        fallback=None,
        site="event_deadline_guard",
        task_id=task_id,
    )
    if now is None or now <= deadline:
        return None

    previous = str(task.get("status") or "").strip().lower() or "pending"
    task["status"] = "expired"
    task["expired_at"] = now_text
    task["completed_at"] = now_text
    task["result"] = "event_deadline_expired_before_dispatch"
    task["last_error"] = "deadline_expired_never_dispatched"
    _record_status_history(
        task,
        frm=previous,
        to="expired",
        by=owner,
        note="claim_rejected_after_event_deadline",
    )
    return {
        "ok": False,
        "reason": "deadline_expired",
        "task_id": task_id,
        "status": "expired",
        "deadline": deadline.isoformat(),
    }


def _is_codex_owner(owner: str) -> bool:
    normalized = str(owner or "").strip().lower()
    return normalized == "codex" or normalized.startswith("codex-") or normalized.startswith("codex_")


_K_ID_RE = re.compile(r"^K\d{2,5}[A-Z]?$", re.IGNORECASE)


def _extract_review_verdict(result: str) -> str | None:
    """Extract an explicit Codex review verdict from a compact completion note."""
    if not result:
        return None
    upper = result.upper()
    explicit = [
        m.group(1)
        for m in re.finditer(
            (
                r"(?:^|[^A-Z0-9_])(?:FINAL\s+|FORMAL\s+)?"
                r"VERDICT\s*[:=：]?\s*(CONDITIONAL_PASS|FAIL|PASS)(?![A-Z_])"
            ),
            upper,
        )
    ]
    if explicit:
        return explicit[-1]
    if re.search(r"\bCODEX\s+REVIEW\s+FAIL\b", upper):
        return "FAIL"
    # Fallback for short review-task summaries such as "review FAIL: ...".
    # Avoid treating repair summaries like "FAIL -> CONDITIONAL_PASS" as FAIL.
    if (
        re.search(r"\bREVIEW\s+FAIL\b", upper)
        and "CONDITIONAL_PASS" not in upper
        and not re.search(r"\bPASS\b", upper)
    ):
        return "FAIL"
    return None


def _codex_review_followup_k_id(task: dict[str, Any]) -> str | None:
    task_id = _task_key(task)
    for key in ("related_k_id", "source_k_id", "predecessor", "k_id", "experiment_id"):
        value = str(task.get(key) or "").upper()
        if _K_ID_RE.fullmatch(value):
            return value
    match = re.match(
        r"^(K\d{2,5}[A-Z]?)_CODEX_REVIEW_FOLLOWUP$",
        task_id,
        flags=re.IGNORECASE,
    )
    if match:
        return match.group(1).upper()
    return None


def _find_source_experiment_task(
    tasks: list[dict[str, Any]],
    k_id: str,
    review_task_id: str,
) -> dict[str, Any] | None:
    exact = [
        t for t in tasks
        if _task_key(t).upper() == k_id
        and str(t.get("task_type") or "") == "experiment"
    ]
    if len(exact) == 1:
        return exact[0]

    keyed = []
    for t in tasks:
        if _task_key(t) == review_task_id:
            continue
        if str(t.get("task_type") or "") != "experiment":
            continue
        values = {str(t.get(key) or "").upper() for key in ("k_id", "experiment_id")}
        if k_id in values:
            keyed.append(t)
    return keyed[0] if len(keyed) == 1 else None


def _append_note(existing: Any, note: str) -> str:
    current = str(existing or "").strip()
    if note in current:
        return current
    return f"{current}\n\n{note}".strip() if current else note


def _compact_note(text: str, limit: int = 360) -> str:
    cleaned = " ".join(str(text or "").split())
    return cleaned if len(cleaned) <= limit else cleaned[: limit - 3].rstrip() + "..."


def _apply_codex_review_followup_fail(
    tasks: list[dict[str, Any]],
    review_task: dict[str, Any],
    result: str,
) -> dict[str, Any] | None:
    """Propagate `<K>_codex_review_followup` verdict=FAIL to source K task.

    The review task itself can succeed because the review was completed. The
    source experiment must still be downgraded when the completed review says
    the methodology or claims failed.
    """
    task_id = _task_key(review_task)
    if not re.search(r"_codex_review_followup$", task_id, flags=re.IGNORECASE):
        return None
    verdict = _extract_review_verdict(result)
    if verdict != "FAIL":
        return None

    k_id = _codex_review_followup_k_id(review_task)
    if not k_id:
        return {
            "applied": False,
            "reason": "source_k_id_not_found",
            "review_task_id": task_id,
            "verdict": verdict,
        }

    now = _now()
    source_task = _find_source_experiment_task(tasks, k_id, task_id)
    reason = f"Codex review follow-up {task_id} verdict=FAIL: {_compact_note(result)}"
    effect: dict[str, Any] = {
        "applied": True,
        "review_task_id": task_id,
        "source_k_id": k_id,
        "verdict": verdict,
    }
    if source_task is None:
        effect["source_status"] = "not_found"
    else:
        source_task["status"] = "failed"
        source_task["failed_at"] = now
        source_task["failed_by"] = "task_pool_claim:codex_review_followup"
        source_task["failure_reason"] = _append_note(source_task.get("failure_reason"), reason)
        effect["source_status"] = "failed"

    v2_id = f"{k_id}_v2_fix_methodology"
    if any(_task_key(t) == v2_id for t in tasks):
        effect["v2_task"] = "already_exists"
        return effect

    new_task = {
        "id": v2_id,
        "task_type": "experiment",
        "status": "pending",
        "priority": normalize_priority(review_task.get("priority"), default=3),
        "title": f"{k_id}-v2: fix methodology after Codex review FAIL",
        "description": (
            f"{k_id} Codex review follow-up task {task_id} returned verdict=FAIL. "
            "Fix the methodology / claim issues identified by the review, rerun the "
            "experiment, and rerun Codex review before any knowledge.json promotion. "
            f"Review summary: {_compact_note(result)}"
        ),
        "source": "codex_review_followup",
        "created_at": now,
        "predecessor": k_id,
        "predecessor_codex_review_task": task_id,
        "dispatch_lane": "agent",
    }
    normalize_task_priority(new_task)
    tasks.append(new_task)
    effect["v2_task"] = "created"
    effect["v2_task_id"] = v2_id
    return effect


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
        if existing_status != "claimed":
            deadline_result = _expire_managed_event_before_claim(task, owner=args.owner)
            if deadline_result is not None:
                return deadline_result
            dreaming_result = _revalidate_dreaming_before_claim(task, owner=args.owner)
            if dreaming_result is not None:
                return dreaming_result
        from volpred.ops.next_tasks import (
            MAIN_THREAD_DISPATCH_LANES,
            normalize_dispatch_lane,
        )

        lane = normalize_dispatch_lane(task)
        # 2026-07-20：原本只比對字面 "main_thread"，但 ctd 的候選過濾認得 4 種拼法
        # （main / main_thread / manual / interactive）。詞彙不一致 ⇒ lane="manual"
        # 的任務進不了 PHASE B 候選、卻擋不住 burst 點名 claim。改用 canonical set。
        if (
            lane in MAIN_THREAD_DISPATCH_LANES or existing_status == "pending_main_thread"
        ) and not getattr(args, "main_thread", False):
            # 2026-07-20 owner 糾正（refactor_plan_ops_master_2026_07 §5 獨立軌）：
            # lane 只擋候選排序不夠 —— burst/urgent fire 會點名 claim，隔離必須
            # enforce 在 claim 這個唯一入口。互動主線程用 --main-thread 明示越過。
            return {
                "ok": False,
                "reason": "main_thread_lane",
                "dispatch_lane": lane or None,
                "status": existing_status,
                "hint": "reserved for main thread; pass --main-thread from an interactive session",
            }
        if _is_codex_owner(args.owner) and not _is_codex_eligible_task(task):
            return {
                "ok": False,
                "reason": "not_codex_eligible",
                "task_type": task.get("task_type"),
                "dispatch_lane": task.get("dispatch_lane"),
                "status": existing_status,
            }
        prev = existing_status or "pending"
        task["status"] = "claimed"
        task["claimed_by"] = args.owner
        task["claimed_at"] = _now()
        task["claim_session_id"] = session
        _record_status_history(task, frm=prev, to="claimed", by=args.owner)
        return {"ok": True, "task_id": args.id, "owner": args.owner, "session": session, "status": "claimed"}


def cmd_start(args: argparse.Namespace) -> dict[str, Any]:
    with _locked_load() as (_fh, tasks):
        task = _find(tasks, args.id)
        prev = (task.get("status") or "").lower()
        if prev not in {"claimed", "in_progress"}:
            return {"ok": False, "reason": "not_claimed", "status": task.get("status")}
        task["status"] = "in_progress"
        task["started_at"] = _now()
        if prev != "in_progress":
            _record_status_history(
                task, frm=prev, to="in_progress", by=task.get("claimed_by") or "unknown"
            )
        return {"ok": True, "task_id": args.id, "status": "in_progress"}


def _repend_task(
    task: dict[str, Any], *, note: str, reason: str | None = None
) -> str | None:
    """Return one claimed/in_progress task to `pending` (single mutation site).

    Every re-pend in this module goes through here so the claim fields, the
    release timestamp and the status_history trace can never drift apart
    between the manual, kill-triggered and stale-sweep paths.
    """
    prev_owner = task.get("claimed_by")
    prev_status = (task.get("status") or "").lower() or "claimed"
    task["status"] = "pending"
    task.pop("claimed_by", None)
    task.pop("claimed_at", None)
    task.pop("claim_session_id", None)
    task["last_released_at"] = _now()
    if reason:
        task["last_release_reason"] = reason
    _record_status_history(
        task,
        frm=prev_status,
        to="pending",
        by=prev_owner or "release",
        note=note,
    )
    return prev_owner


def release_owner_claims(
    owners: Any, *, reason: str, note: str | None = None
) -> dict[str, Any]:
    """Re-pend every live claim held by any of `owners`.

    The dispatch supervisor's kill path uses this: when `health.py` force-kills
    a hung worker it frees the dispatch_state slot, and the task that dead fire
    was holding must go back to the pool in the same breath.  Before this
    existed the claim stayed `claimed`/`in_progress` until the stale sweep
    noticed hours later, so a P1 task could sit dead with nothing running behind
    it (refactor_plan_ops_master_2026_07 §1.2 P1 / WS-A2b).

    Owner-scoped rather than id-scoped because the supervisor knows which fire
    it killed (slot+job → ownership token), not which task that fire claimed.
    """
    wanted = {str(owner) for owner in owners if str(owner or "").strip()}
    if not wanted:
        return {"ok": True, "released": [], "count": 0}
    released: list[dict[str, Any]] = []
    with _locked_load() as (_fh, tasks):
        for task in tasks:
            if not isinstance(task, dict):
                continue
            if (task.get("status") or "").lower() not in {"claimed", "in_progress"}:
                continue
            if str(task.get("claimed_by") or "") not in wanted:
                continue
            prev_owner = _repend_task(task, note=note or reason, reason=reason)
            released.append({"id": _task_key(task), "owner": prev_owner})
    return {"ok": True, "released": released, "count": len(released)}


def cmd_release(args: argparse.Namespace) -> dict[str, Any]:
    with _locked_load() as (_fh, tasks):
        task = _find(tasks, args.id)
        prev_owner = _repend_task(task, note="manual_release")
        return {"ok": True, "task_id": args.id, "released_from": prev_owner}


def cmd_handoff_main_thread(args: argparse.Namespace) -> dict[str, Any]:
    with _locked_load() as (_fh, tasks):
        task = _find(tasks, args.id)
        prev_status = (task.get("status") or "").lower()
        if prev_status not in {"claimed", "in_progress", "pending", "pending_main_thread"}:
            return {"ok": False, "reason": "wrong_status", "status": task.get("status")}
        prev_owner = task.get("claimed_by") or "handoff"
        task["status"] = "pending_main_thread"
        task["handoff_note"] = args.note
        task["handoff_at"] = _now()
        task.pop("claimed_by", None)
        task.pop("claimed_at", None)
        task.pop("claim_session_id", None)
        _record_status_history(
            task,
            frm=prev_status or "claimed",
            to="pending_main_thread",
            by=prev_owner,
            note=args.note,
        )
        return {"ok": True, "task_id": args.id, "status": "pending_main_thread"}


def _burst_actions(task: dict[str, Any], status_value: str,
                   tasks: list[dict[str, Any]]) -> dict[str, Any] | None:
    """What a burst window wants doing for this completion, or None.

    Returns None when no window is open (the normal state — completions are
    silent and dispatch keeps its hourly cadence), or when the burst module is
    unavailable: a notification problem must never fail the completion it is
    only describing.

    `text` is omitted if the row already carries `burst_reported_at`, so a
    re-run of `complete` never double-notifies while still keeping the loop
    going. Counting pending here, under the lock, avoids waking the supervisor
    for an empty queue.
    """
    try:
        from volpred.ops import dispatch_burst
        if not dispatch_burst.active():
            return None
        pending = sum(1 for t in tasks
                      if isinstance(t, dict) and (t.get("status") or "").lower() == "pending")
        out: dict[str, Any] = {"pending_left": pending}
        if not task.get("burst_reported_at"):
            out["text"] = dispatch_burst.format_completion(task, status_value)
        return out
    except Exception as exc:
        # Fail-open: the claim/complete write already landed under the lock, so a
        # broken burst window must never fail the caller. Observable, not silent.
        from volpred.ops.diagnostics import warn
        warn("task_pool_claim", "burst report probe failed",
             err=f"{type(exc).__name__}: {exc}", task_id=str(task.get("id") or ""))
        return None


def _send_burst_report(*, text: str) -> dict[str, Any]:
    """Best-effort Telegram line. Never raises — the work is already done."""
    try:
        from volpred.ops.telegram import send_telegram
        return send_telegram(text)
    except Exception as exc:
        return {"sent": False, "reason": f"{type(exc).__name__}: {exc}"}


def _request_burst_fire(task_id: str, pending_left: int) -> dict[str, Any]:
    """Pull the next fire forward instead of waiting for the cron slot.

    This is the whole continuous-dispatch mechanism: a completion is exactly
    the moment a slot may have freed, so it is the only moment worth checking.
    `request_fire` just sets a flag under the supervisor's own lock — the
    scheduler consumes it on its next ≤60s tick through the normal
    `reserve_fire()` slot path, so a full pool queues rather than
    double-dispatches.
    """
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from scripts.dispatch_supervisor import state as sup_state
        sup_state.request_fire(f"burst:{task_id}")
        return {"requested": True, "pending_left": pending_left}
    except Exception as exc:
        return {"requested": False, "reason": f"{type(exc).__name__}: {exc}"}


def cmd_complete(args: argparse.Namespace) -> dict[str, Any]:
    out, burst = _complete_locked(args)
    if burst:
        # Both run outside the queue lock: network IO and the supervisor's own
        # lock have no business being held under the queue's LOCK_EX.
        if burst.get("text"):
            out["burst_report"] = _send_burst_report(text=burst["text"])
        if burst.get("pending_left"):
            out["burst_next_fire"] = _request_burst_fire(args.id, burst["pending_left"])
    return out


def _complete_locked(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any] | None]:
    with _locked_load() as (_fh, tasks):
        task = _find(tasks, args.id)
        prev_status = (task.get("status") or "").lower() or "in_progress"
        completion_owner = task.get("claimed_by") or "complete"
        if prev_status in TERMINAL_STATUSES and prev_status == args.status:
            # Idempotent repair path: terminal rows are historical receipts,
            # never active ownership. Older complete() versions left these
            # fields behind, so a safe re-run must clean them too.
            task.pop("claimed_by", None)
            task.pop("claimed_at", None)
            task.pop("claim_session_id", None)
            return {
                "ok": True,
                "task_id": args.id,
                "status": prev_status,
                "already_completed": True,
            }, None
        task["status"] = args.status
        task["completed_at"] = _now()
        _record_status_history(
            task,
            frm=prev_status,
            to=args.status,
            by=completion_owner,
        )
        task.pop("claimed_by", None)
        task.pop("claimed_at", None)
        task.pop("claim_session_id", None)
        result_text = args.result or ""
        if args.result:
            existing = task.get("result") or ""
            task["result"] = (existing + "\n\n" + args.result).strip() if existing else args.result
            result_text = task["result"]
        effect = None
        if args.status == "succeeded":
            effect = _apply_codex_review_followup_fail(tasks, task, result_text)
        out = {"ok": True, "task_id": args.id, "status": args.status}
        if effect:
            out["review_followup_effect"] = effect
        # Stamped inside the same LOCK_EX that wrote the terminal status, so the
        # "already reported" claim can never disagree with the row it describes.
        burst = _burst_actions(task, args.status, tasks)
        if burst and burst.get("text"):
            task["burst_reported_at"] = _now()
        return out, burst


#: annotate 只准動 free-form metadata；生命週期/身分欄位各有專屬入口
#: （claim/start/complete/release/mark_task_blocked），繞過那些入口 = 繞過
#: 它們的 guard 與 status vocab 檢查。
ANNOTATE_PROTECTED_FIELDS = frozenset({
    "id", "status", "priority", "task_type", "created_at", "completed_at",
    "claimed_by", "claimed_at", "claim_session_id",
    "blocked_reason", "blocked_at", "blocked_until",
})


def cmd_annotate(args: argparse.Namespace) -> dict[str, Any]:
    """Set free-form metadata fields (plan / linked_task_ids / ...) on one task.

    WS-A1b: replaces the cron-dispatch-prompt era ``jq ... > /tmp/nt && mv``
    instruction — that pipeline rewrote the whole queue OUTSIDE the flock and
    the status-vocab audit, and it was teaching agents (N-times amplification).
    This lands through _locked_load → write_tasks_to_handle like every other
    queue mutation.
    """
    updates: dict[str, Any] = {}
    for raw in args.set or []:
        key, sep, value = raw.partition("=")
        if not sep or not key:
            raise SystemExit(f"annotate: --set expects FIELD=VALUE, got {raw!r}")
        updates[key] = value
    for raw in args.set_json or []:
        key, sep, value = raw.partition("=")
        if not sep or not key:
            raise SystemExit(f"annotate: --set-json expects FIELD=JSON, got {raw!r}")
        try:
            updates[key] = json.loads(value)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"annotate: --set-json {key}: invalid JSON ({exc}): {value!r}")
    if not updates:
        raise SystemExit("annotate: nothing to set (use --set FIELD=VALUE / --set-json FIELD=JSON)")
    protected = sorted(set(updates) & ANNOTATE_PROTECTED_FIELDS)
    if protected:
        raise SystemExit(
            f"annotate: refusing lifecycle/identity fields {protected}; "
            "use claim/start/complete/release or scripts/mark_task_blocked.py"
        )
    with _locked_load() as (_fh, tasks):
        task = _find(tasks, args.id)
        task.update(updates)
    return {"ok": True, "task_id": args.id, "fields": sorted(updates)}


def cmd_list(args: argparse.Namespace) -> dict[str, Any]:
    with _locked_readonly() as tasks:
        out: list[dict[str, Any]] = []
        for t in tasks:
            status = (t.get("status") or "").lower()
            if args.status == "stale":
                if status not in {"claimed", "in_progress"}:
                    continue
                claimed_at = t.get("claimed_at")
                if not claimed_at:
                    continue
                claimed_dt = parse_iso_warn(
                    claimed_at,
                    tag="claim",
                    field_name="claimed_at",
                    fallback=None,
                    site="list_stale",
                    task_id=_task_key(t),
                )
                if claimed_dt is None:
                    continue
                age_h = (datetime.now(timezone.utc) - claimed_dt).total_seconds() / 3600
                if age_h < args.stale_hours:
                    continue
            elif args.status and status != args.status:
                continue
            if args.owner and t.get("claimed_by") != args.owner:
                continue
            if args.codex_eligible and not _is_codex_eligible_task(t):
                continue
            out.append({
                "id": _task_key(t),
                "title": t.get("title"),
                "task_type": t.get("task_type"),
                "priority": t.get("priority"),
                "status": status,
                "claimed_by": t.get("claimed_by"),
                "claimed_at": t.get("claimed_at"),
                "dispatch_lane": t.get("dispatch_lane"),
            })
        out.sort(key=lambda x: (priority_sort_key(x.get("priority"), default=999), x.get("id") or ""))
        if args.limit:
            out = out[: args.limit]
        return {"ok": True, "count": len(out), "tasks": out}


def cmd_normalize_priorities(args: argparse.Namespace) -> dict[str, Any]:
    if args.dry_run:
        with _locked_readonly() as tasks:
            changed = normalize_task_priorities(tasks, mutate=False)
            return {"ok": True, "dry_run": True, "would_change": changed}
    with _locked_load() as (_fh, tasks):
        changed = normalize_task_priorities(tasks)
        return {"ok": True, "changed": changed}


_COMPUTE_QUEUE_DIR = ROOT / "storage" / "ops" / "compute_queue"
_COMPUTE_JOB_LIVE = {"pending", "queued", "running", "claimed"}


def _compute_job_alive(job_id: str | None) -> bool:
    """True 若 task 掛著的 compute-queue job 仍在飛。

    stale reaper 只看 claimed_at 的年齡，看不見「工作其實在 compute worker 上跑」。
    長研究 job timeout 動輒 5400s，遠超 --stale-hours 2 —— 於是 dispatch 到 compute
    queue 的 task 會在 2h 後被放回 pending，重新進 starvation lockout 被第二次派工，
    產生重複 agent job 與重複 worktree（實例：assign_5aa9d5f5 於 2026-07-19/07-20
    連兩次 auto_release_stale_2h，工作全程在 queue 上正常執行）。

    job 已進終態（completed / failed / timeout）則不擋 —— task 本來就該回池等收件。
    """
    if not job_id:
        return False
    path = _COMPUTE_QUEUE_DIR / f"{job_id}.json"
    try:
        with path.open(encoding="utf-8") as fh:
            status = (json.load(fh).get("status") or "").lower()
    except (OSError, ValueError):  # silent-ok: 缺檔/壞檔 = 無法證明 job 活著，回退到原回收邏輯
        # 讀不到 job 檔 = 無法證明它活著，照原邏輯回收（不要因為 IO 錯誤把 task 永久釘住）
        return False
    return status in _COMPUTE_JOB_LIVE


def cmd_cleanup(args: argparse.Namespace) -> dict[str, Any]:
    released = []
    skipped_compute = []
    with _locked_load() as (_fh, tasks):
        now = datetime.now(timezone.utc)
        for t in tasks:
            status = (t.get("status") or "").lower()
            if status not in {"claimed", "in_progress"}:
                continue
            job_id = t.get("compute_job_id")
            if _compute_job_alive(job_id):
                skipped_compute.append({"id": _task_key(t), "compute_job_id": job_id})
                continue
            claimed_at = t.get("claimed_at")
            claimed_dt = None
            age_source = "claimed_at"
            if claimed_at:
                claimed_dt = parse_iso_warn(
                    claimed_at,
                    tag="claim",
                    field_name="claimed_at",
                    fallback=None,
                    site="cleanup_stale",
                    task_id=_task_key(t),
                )
            if claimed_dt is None:
                # claim 沒留（或留了壞的）claimed_at：退而用其他生命週期欄位推
                # 年齡；全缺 = 無法證明活著，視為無限 stale 立即回收
                # （P4 claimed_at 盲點，refactor_plan_ops_master_2026_07 WS-A2）
                for fallback_field in ("started_at", "updated_at", "created_at"):
                    raw = t.get(fallback_field)
                    if not raw:
                        continue
                    claimed_dt = parse_iso_warn(
                        raw,
                        tag="claim",
                        field_name=fallback_field,
                        fallback=None,
                        site="cleanup_stale_fallback",
                        task_id=_task_key(t),
                    )
                    if claimed_dt is not None:
                        age_source = fallback_field
                        break
            if claimed_dt is None:
                age_h = float("inf")
                age_source = None
            else:
                age_h = (now - claimed_dt).total_seconds() / 3600
            if age_h >= args.stale_hours:
                prev_owner = t.get("claimed_by")
                released.append(
                    {
                        "id": _task_key(t),
                        "owner": prev_owner,
                        "age_h": round(age_h, 1) if claimed_dt is not None else None,
                        "age_source": age_source,
                    }
                )
                t["status"] = "pending"
                t.pop("claimed_by", None)
                t.pop("claimed_at", None)
                t.pop("claim_session_id", None)
                t["last_released_at"] = _now()
                t["last_release_reason"] = f"auto_release_stale_{args.stale_hours}h"
                _record_status_history(
                    t,
                    frm=status or "claimed",
                    to="pending",
                    by=prev_owner or "cleanup",
                    note=f"auto_release_stale_{args.stale_hours}h",
                )
    return {
        "ok": True,
        "released": released,
        "count": len(released),
        "skipped_compute_in_flight": skipped_compute,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("claim"); p.add_argument("--id", required=True); p.add_argument("--owner", required=True); p.add_argument("--session"); p.add_argument("--main-thread", action="store_true", dest="main_thread", help="claim a main_thread-lane task (interactive session only)"); p.set_defaults(fn=cmd_claim)
    p = sub.add_parser("start"); p.add_argument("--id", required=True); p.set_defaults(fn=cmd_start)
    p = sub.add_parser("release"); p.add_argument("--id", required=True); p.set_defaults(fn=cmd_release)
    p = sub.add_parser("handoff-main-thread"); p.add_argument("--id", required=True); p.add_argument("--note", required=True); p.set_defaults(fn=cmd_handoff_main_thread)
    p = sub.add_parser("complete"); p.add_argument("--id", required=True); p.add_argument("--status", choices=["succeeded", "failed", "blocked"], default="succeeded"); p.add_argument("--result"); p.set_defaults(fn=cmd_complete)
    p = sub.add_parser("annotate", help="set free-form metadata fields on a task (locked canonical write; replaces jq-edit)")
    p.add_argument("--id", required=True)
    p.add_argument("--set", action="append", metavar="FIELD=VALUE", help="set FIELD to a string VALUE (repeatable)")
    p.add_argument("--set-json", action="append", dest="set_json", metavar="FIELD=JSON", help="set FIELD to a parsed JSON value (repeatable)")
    p.set_defaults(fn=cmd_annotate)
    p = sub.add_parser("list")
    p.add_argument("--status")
    p.add_argument("--owner")
    p.add_argument("--limit", type=int)
    p.add_argument("--stale-hours", type=int, default=DEFAULT_STALE_HOURS)
    p.add_argument(
        "--codex-eligible",
        action="store_true",
        help="Only show task types Codex is allowed to claim",
    )
    p.set_defaults(fn=cmd_list)
    p = sub.add_parser("cleanup"); p.add_argument("--stale-hours", type=int, default=DEFAULT_STALE_HOURS); p.set_defaults(fn=cmd_cleanup)
    p = sub.add_parser("normalize-priorities")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_normalize_priorities)

    args = ap.parse_args()
    result = args.fn(args)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
