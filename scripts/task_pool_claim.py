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
  complete --id <task_id> [--result <text>] [--status succeeded|failed]
           [--issue-disposition contained|close]
           [--gate-decision retain|recalibrate|downgrade_to_warn|retire
            --gate-live-readback <evidence>]
  list     [--status pending|claimed|in_progress|stale] [--owner <name>] [--limit N] [--codex-eligible]
  cleanup  --stale-hours <N>   (auto-release claims older than N hours with no completion)

File lock: fcntl.LOCK_EX on next_tasks.json across read-modify-write.

Run:
  uv run python scripts/task_pool_claim.py claim --id <id> --owner hourly-dispatch
  uv run python scripts/task_pool_claim.py complete --id <id> --result "summary" --status succeeded
  # Only after the linked GitHub issue itself passes every acceptance gate:
  uv run python scripts/task_pool_claim.py complete --id <id> --status succeeded --issue-disposition close
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import subprocess
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

# Ensure repo root in sys.path so `volpred.ops` imports work when invoked as
# `python scripts/task_pool_claim.py` from anywhere.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

from volpred.canonical_write import guard_canonical_write  # noqa: E402
from volpred.ops.next_tasks import (  # noqa: E402
    enforce_blocked_until,
    normalize_priority,
    normalize_task_priority,
    normalize_task_priorities,
    validate_blocked_reason,
    write_tasks_to_handle,
)
from volpred.ops.issue_tracker_sync import (  # noqa: E402
    assign_issue,
    issue_number,
    normalize_issue_ref,
)
from volpred.ops.timestamps import parse_iso_warn  # noqa: E402
from volpred.ops import dreaming_revalidate  # noqa: E402
from volpred.ops.task_pool_selection import (  # noqa: E402
    CODEX_ELIGIBLE_TASK_TYPES,  # noqa: F401 - compatibility re-export
    evaluate_task_claim,
    is_codex_eligible_task as _is_codex_eligible_task,
    is_pending_list_candidate,
    normalized_task_type as _normalized_task_type,
    requires_supervisor_preassignment,
    resolve_task_identity,
    single_flight_blocker_task_id,
    task_identity,
    task_rank_key,
)

ROOT = Path(__file__).resolve().parents[1]
NEXT_TASKS = ROOT / "storage" / "next_tasks.json"
FB_DRAFTS_DIR = ROOT / "storage" / "drafts"
CONTROL_GATE_REGISTRY = ROOT / "config" / "control_gate_registry.json"

DEFAULT_STALE_HOURS = 2  # Canonical handoff stale sweep contract
TERMINAL_STATUSES = {"succeeded", "failed", "blocked"}
FB_DUAL_PUBLISH_TASK_TYPES = {"trending_repost", "event_article"}
_MILE_ID_RE = re.compile(r"\bmile_[A-Za-z0-9_-]+\b")
_PUBLISH_EVIDENCE_RE = re.compile(
    r"(?:發佈|發布|已發|publish(?:ed)?|feed\s+live|volpred\s+feed)",
    re.IGNORECASE,
)
_GATE_REVIEW_ACTIONS = {
    "retain",
    "recalibrate",
    "downgrade_to_warn",
    "retire",
}
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_claim_window(task: dict[str, Any], claimed_at: str) -> None:
    """Persist the deterministic lease boundary used by stale cleanup."""
    task["claimed_at"] = claimed_at
    _renew_claim_expiry(task, renewed_at=claimed_at)


def _renew_claim_expiry(
    task: dict[str, Any], *, renewed_at: str
) -> None:
    """Extend a claim from verified live-execution evidence."""
    task["claim_expires_at"] = (
        datetime.fromisoformat(renewed_at)
        + timedelta(hours=DEFAULT_STALE_HOURS)
    ).isoformat()


def _dispatch_supervisor_authorized() -> bool:
    """Production-only parent proof for supervisor control-plane mutations."""
    if NEXT_TASKS.resolve() != (ROOT / "storage" / "next_tasks.json").resolve():
        return True
    state_path = ROOT / "storage" / "ops" / "dispatch_state.json"
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        supervisor_pid = int(payload.get("supervisor_pid"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        from volpred.ops.diagnostics import warn
        warn(
            "task_pool_claim",
            "supervisor capability proof unavailable; denying mutation",
            err=str(exc),
        )
        return False
    return supervisor_pid > 1 and os.getppid() == supervisor_pid


def _dispatch_job_alive(job_id: Any) -> bool:
    if not job_id:
        return False
    try:
        payload = json.loads(
            (ROOT / "storage" / "ops" / "dispatch_state.json").read_text(
                encoding="utf-8"
            )
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        from volpred.ops.diagnostics import warn
        warn(
            "task_pool_claim",
            "dispatch job liveness unavailable; treating as not live",
            job_id=str(job_id),
            err=str(exc),
        )
        return False
    from scripts.dispatch_supervisor import procutil

    for job in payload.get("current_jobs") or []:
        if (
            not isinstance(job, dict)
            or str(job.get("job_id") or "") != str(job_id)
        ):
            continue
        try:
            pid = int(job.get("pid"))
        except (TypeError, ValueError) as exc:
            from volpred.ops.diagnostics import warn
            warn(
                "task_pool_claim",
                "dispatch job pid invalid; refusing liveness proof",
                job_id=str(job_id),
                err=str(exc),
            )
            return False
        return (
            procutil.check_identity(pid, job.get("started_wall"))
            == procutil.IDENTITY_MATCH
        )
    return False


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
    return task_identity(task)


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


def _find(tasks: list[dict[str, Any]], task_id: str) -> dict[str, Any]:
    resolution = resolve_task_identity(tasks, task_id)
    if resolution.reason_code == "missing_task_id":
        raise SystemExit("task id is missing")
    if resolution.reason_code == "task_not_found":
        raise SystemExit(f"task id not found: {task_id}")
    if resolution.reason_code == "duplicate_task_id":
        statuses = [
            str(tasks[index].get("status") or "")
            for index in resolution.matching_indexes
        ]
        raise SystemExit(
            f"duplicate task id detected: {task_id} "
            f"count={len(resolution.matching_indexes)} statuses={statuses}. "
            "Run scripts/dedupe_next_tasks.py first."
        )
    return tasks[resolution.matching_indexes[0]]


def _published_mile_ids(task: dict[str, Any], result: str) -> set[str]:
    """Extract dual-publish article ids only when completion claims publication.

    A result can mention older ``mile_*`` articles during dedup/research, so an
    id alone is not publication evidence. Limit inference to a local window
    carrying an explicit publish/feed-live marker. Callers may also set
    ``published_mile_id`` on the task as a machine-readable receipt.
    """
    published: set[str] = set()
    explicit = task.get("published_mile_id")
    if isinstance(explicit, str) and _MILE_ID_RE.fullmatch(explicit.strip()):
        published.add(explicit.strip())
    elif isinstance(explicit, list):
        published.update(
            value.strip()
            for value in explicit
            if isinstance(value, str) and _MILE_ID_RE.fullmatch(value.strip())
        )

    for match in _MILE_ID_RE.finditer(result or ""):
        start = max(0, match.start() - 80)
        end = min(len(result), match.end() + 80)
        if _PUBLISH_EVIDENCE_RE.search(result[start:end]):
            published.add(match.group(0))
    return published


def _require_fb_drafts_for_dual_publish(task: dict[str, Any], result: str) -> None:
    """Refuse fake completion when a feed-published article has no FB copy.

    Root cause (2026-07-20): a trending/event article could publish its feed
    entry, file an ``fb_repost_*`` follow-up, and still be marked succeeded
    without writing the copy the FB worker needs. Feed publication remains
    independent of FB delivery, but preparing the canonical draft is part of
    the same task's completion contract.
    """
    if _normalized_task_type(task) not in FB_DUAL_PUBLISH_TASK_TYPES:
        return
    published = _published_mile_ids(task, result)
    if not published:
        return
    missing = sorted(
        mile_id
        for mile_id in published
        if not (FB_DRAFTS_DIR / f"fb_{mile_id}.md").is_file()
    )
    if missing:
        expected = ", ".join(
            f"storage/drafts/fb_{mile_id}.md" for mile_id in missing
        )
        raise SystemExit(
            "dual-publish completion refused: feed publication was reported "
            f"for {', '.join(missing)}, but canonical FB draft(s) are missing: "
            f"{expected}. Write the FB-native copy now; an fb_repost follow-up "
            "is not a substitute for the publish task's completion contract."
        )


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
    task: dict[str, Any],
    *,
    owner: str,
    decision: Any,
    observed_at: datetime,
) -> dict[str, Any] | None:
    """Apply the terminal mutation selected by the pure claim policy."""

    if decision.primary_reason not in {
        "missing_deadline",
        "invalid_deadline",
        "deadline_expired",
    }:
        return None

    task_id = _task_key(task)
    now_text = observed_at.astimezone(timezone.utc).isoformat()
    if decision.primary_reason in {"missing_deadline", "invalid_deadline"}:
        schema_error = decision.primary_reason
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
        "deadline": decision.deadline_at,
    }


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
    from volpred.ops.task_pool_mode import load_task_pool_mode, task_pool_mode_path

    try:
        mode = load_task_pool_mode(task_pool_mode_path(NEXT_TASKS))
    except ValueError as exc:
        return {
            "ok": False,
            "reason": "task_pool_mode_unreadable",
            "error": str(exc),
        }
    if mode.enabled:
        return {
            "ok": False,
            "reason": "direct_execution_mode",
            "mode": mode.mode,
            "hint": "execute owner-directed work directly; task-pool claims are suspended",
        }
    session = args.session or os.environ.get("CLAUDE_SESSION_ID") or uuid.uuid4().hex[:12]
    with _locked_load() as (_fh, tasks):
        task = _find(tasks, args.id)
        if task.get("unblock_gate") is not None:
            return {
                "ok": False,
                "reason": "unblock_gate_not_satisfied",
                "status": task.get("status"),
                "unblock_gate": task.get("unblock_gate"),
            }
        normalized_type = _normalized_task_type(task)
        normalized_owner = str(args.owner or "").strip().lower()
        if (
            requires_supervisor_preassignment(task)
            and (
                normalized_owner.startswith("hourly-")
                or normalized_owner.startswith("codex-failover-")
            )
        ):
            return {
                "ok": False,
                "reason": "supervisor_preassignment_required",
                "task_id": args.id,
                "task_type": normalized_type,
                "hint": (
                    "mutating dispatch work must be claimed and bound by the "
                    "supervisor before worker spawn"
                ),
            }
        existing_status = (task.get("status") or "").lower()
        observed_at = datetime.now(timezone.utc)
        decision = evaluate_task_claim(
            task,
            owner=args.owner,
            main_thread=bool(getattr(args, "main_thread", False)),
            observed_at=observed_at,
        )
        if decision.primary_reason == "already_claimed":
            return {
                "ok": False,
                "reason": "already_claimed",
                "claimed_by": decision.claimed_by,
                "claimed_at": task.get("claimed_at"),
            }
        if decision.primary_reason == "wrong_status":
            return {"ok": False, "reason": "wrong_status", "status": existing_status}
        if existing_status != "claimed":
            deadline_result = _expire_managed_event_before_claim(
                task,
                owner=args.owner,
                decision=decision,
                observed_at=observed_at,
            )
            if deadline_result is not None:
                return deadline_result
            dreaming_result = _revalidate_dreaming_before_claim(task, owner=args.owner)
            if dreaming_result is not None:
                return dreaming_result
            if decision.primary_reason == "live_revalidation_required":
                decision = evaluate_task_claim(
                    task,
                    owner=args.owner,
                    main_thread=bool(
                        getattr(args, "main_thread", False)
                    ),
                    observed_at=observed_at,
                    revalidation_checked=True,
                )
        # 2026-07-20：原本只比對字面 "main_thread"，但 ctd 的候選過濾認得 4 種拼法
        # （main / main_thread / manual / interactive）。詞彙不一致 ⇒ lane="manual"
        # 的任務進不了 PHASE B 候選、卻擋不住 burst 點名 claim。
        # 2026-07-21 incident-lifecycle P4：判定收編進唯一 owner
        # is_main_thread_reserved（status=pending_main_thread 亦算），與
        # task_urgency 的 fire 判定共用同一套詞彙 —— 這裡與 request_fire 讀不同
        # 欄位正是「無合法執行者卻被 hourly fire」矛盾的根因（plan 附註）。
        if decision.primary_reason == "main_thread_lane":
            # 2026-07-20 owner 糾正（refactor_plan_ops_master_2026_07 §5 獨立軌）：
            # lane 只擋候選排序不夠 —— burst/urgent fire 會點名 claim，隔離必須
            # enforce 在 claim 這個唯一入口。互動主線程用 --main-thread 明示越過。
            return {
                "ok": False,
                "reason": "main_thread_lane",
                "dispatch_lane": decision.dispatch_lane or None,
                "status": existing_status,
                "hint": "reserved for main thread; pass --main-thread from an interactive session",
            }
        if decision.primary_reason == "not_codex_eligible":
            return {
                "ok": False,
                "reason": "not_codex_eligible",
                "task_type": task.get("task_type"),
                "dispatch_lane": task.get("dispatch_lane"),
                "status": existing_status,
            }
        active_task_id = single_flight_blocker_task_id(tasks, task)
        if active_task_id is not None:
            return {
                "ok": False,
                "reason": "task_type_single_flight",
                "task_type": normalized_type,
                "active_task_id": active_task_id,
                "status": existing_status,
            }
        prev = existing_status or "pending"
        task["status"] = "claimed"
        task["claimed_by"] = args.owner
        _write_claim_window(task, _now())
        task["claim_session_id"] = session
        _record_status_history(task, frm=prev, to="claimed", by=args.owner)
        result = {
            "ok": True,
            "task_id": args.id,
            "owner": args.owner,
            "session": session,
            "status": "claimed",
            "claim_expires_at": task["claim_expires_at"],
        }
        issue_ref = task.get("issue_ref")
    if issue_ref is not None:
        try:
            result["issue_tracker_sync"] = assign_issue(issue_ref, repo_root=ROOT)
        except Exception as exc:  # noqa: BLE001 — GitHub is not the claim authority
            result["issue_tracker_sync"] = {
                "ok": False,
                "action": "assign",
                "reason": "unexpected_sync_error",
                "detail": f"{type(exc).__name__}: {exc}",
            }
    return result


def _dispatch_execution_contract(
    task: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    """Validate the fail-closed contract required before mutating dispatch."""
    if not requires_supervisor_preassignment(task):
        return None, "not_mutating_dispatch_type"
    write_intent = str(task.get("write_intent") or "")
    if write_intent not in {"repo_patch", "observe_only"}:
        return None, "write_intent_missing_or_unsupported"
    raw_paths = task.get("declared_output_paths")
    if write_intent == "observe_only":
        if not isinstance(raw_paths, list) or raw_paths:
            return None, "observe_only_requires_explicit_empty_outputs"
        declared: list[str] = []
    elif not isinstance(raw_paths, list) or not raw_paths:
        return None, "declared_output_paths_missing"
    else:
        declared = [
            str(path).strip() for path in raw_paths if str(path).strip()
        ]
    invalid = [
        path
        for path in declared
        if path.startswith("/")
        or path.startswith("../")
        or "/../" in path
        or path == "storage"
        or path.startswith("storage/")
        or any(char in path for char in "*?[")
    ]
    if invalid or (write_intent == "repo_patch" and not declared):
        return None, "declared_output_paths_invalid"
    post_actions = task.get("post_merge_actions") or []
    if not isinstance(post_actions, list):
        return None, "post_merge_actions_invalid"
    if post_actions:
        return None, "post_merge_actions_require_separate_task"
    return {
        "task_id": _task_key(task),
        "write_intent": write_intent,
        "declared_output_paths": declared,
        "post_merge_actions": post_actions,
        "title": str(task.get("title") or ""),
        "description": str(task.get("description") or ""),
        "issue_ref": task.get("issue_ref"),
    }, None


def cmd_dispatch_preassign(args: argparse.Namespace) -> dict[str, Any]:
    """Atomically claim+start the highest-ranked contract-complete mutating task."""
    from volpred.ops.task_pool_mode import load_task_pool_mode, task_pool_mode_path

    if not _dispatch_supervisor_authorized():
        return {"ok": False, "reason": "supervisor_capability_required"}
    try:
        mode = load_task_pool_mode(task_pool_mode_path(NEXT_TASKS))
    except ValueError as exc:
        return {"ok": False, "reason": "task_pool_mode_unreadable", "error": str(exc)}
    if mode.enabled:
        return {
            "ok": False,
            "reason": "direct_execution_mode",
            "mode": mode.mode,
        }
    session = args.session or uuid.uuid4().hex[:12]
    blockers: list[dict[str, str]] = []
    with _locked_load() as (_fh, tasks):
        for task in sorted(tasks, key=task_rank_key):
            if (task.get("status") or "").lower() != "pending":
                continue
            if not requires_supervisor_preassignment(task):
                continue
            if task.get("unblock_gate") is not None:
                blockers.append(
                    {
                        "task_id": _task_key(task),
                        "reason": "unblock_gate_not_satisfied",
                    }
                )
                continue
            observed_at = datetime.now(timezone.utc)
            decision = evaluate_task_claim(
                task,
                owner=args.owner,
                main_thread=False,
                observed_at=observed_at,
            )
            if decision.primary_reason == "live_revalidation_required":
                cleared = _revalidate_dreaming_before_claim(task, owner=args.owner)
                if cleared is not None:
                    continue
                decision = evaluate_task_claim(
                    task,
                    owner=args.owner,
                    main_thread=False,
                    observed_at=observed_at,
                    revalidation_checked=True,
                )
            if not decision.eligible:
                continue
            contract, error = _dispatch_execution_contract(task)
            if contract is None:
                blockers.append({"task_id": _task_key(task), "reason": str(error)})
                continue
            now = _now()
            task["status"] = "in_progress"
            task["claimed_by"] = args.owner
            _write_claim_window(task, now)
            task["claim_session_id"] = session
            task["started_at"] = now
            task["dispatch_managed"] = True
            task["dispatch_managed_owner"] = args.owner
            task["dispatch_job_id"] = str(getattr(args, "job_id", "") or "")
            task["dispatch_settlement_pending"] = {
                "job_id": str(getattr(args, "job_id", "") or ""),
                "task_id": _task_key(task),
                "claim_session_id": session,
                "phase": "admission",
                "default_disposition": "retry",
                "created_at": now,
            }
            _record_status_history(
                task,
                frm="pending",
                to="claimed",
                by=args.owner,
                note="supervisor_preassignment",
            )
            _record_status_history(
                task,
                frm="claimed",
                to="in_progress",
                by=args.owner,
                note="workspace_admission",
            )
            return {
                "ok": True,
                "assigned": True,
                "owner": args.owner,
                "session": session,
                "contract": {
                    **contract,
                    "claim_session_id": session,
                    "dispatch_job_id": str(getattr(args, "job_id", "") or ""),
                },
                "blocked_contracts": blockers[:20],
            }
    return {
        "ok": True,
        "assigned": False,
        "reason": "no_contract_complete_mutating_task",
        "blocked_contracts": blockers[:20],
    }


def cmd_dispatch_settle(args: argparse.Namespace) -> dict[str, Any]:
    """CAS-settle a supervisor-owned task after landing/adjudication."""
    if not _dispatch_supervisor_authorized():
        return {"ok": False, "reason": "supervisor_capability_required"}
    with _locked_load() as (_fh, tasks):
        task = _find(tasks, args.id)
        supplied_job_id = str(getattr(args, "job_id", "") or "")
        settled_job_id = str(task.get("dispatch_settled_job_id") or "")
        if (
            str(task.get("dispatch_settled_session_id") or "") == str(args.session)
            and (
                (task.get("status") or "").lower() in TERMINAL_STATUSES
                or (
                    (task.get("status") or "").lower() == "pending"
                    and args.disposition in {"retry", "empty", "failure"}
                )
            )
        ):
            if settled_job_id and supplied_job_id != settled_job_id:
                return {
                    "ok": False,
                    "reason": "dispatch_job_mismatch",
                    "task_id": args.id,
                    "expected_job_id": settled_job_id,
                }
            return {
                "ok": True,
                "task_id": args.id,
                "status": task.get("status"),
                "already_settled": True,
            }
        if str(task.get("claim_session_id") or "") != str(args.session):
            return {
                "ok": False,
                "reason": "claim_session_mismatch",
                "task_id": args.id,
            }
        expected_job_id = str(task.get("dispatch_job_id") or "")
        if task.get("dispatch_managed") is True and not expected_job_id:
            return {
                "ok": False,
                "reason": "dispatch_job_identity_missing",
                "task_id": args.id,
            }
        if expected_job_id and supplied_job_id != expected_job_id:
            return {
                "ok": False,
                "reason": "dispatch_job_mismatch",
                "task_id": args.id,
                "expected_job_id": expected_job_id,
            }
        current = (task.get("status") or "").lower()
        if current not in {"claimed", "in_progress"}:
            return {
                "ok": False,
                "reason": "wrong_status",
                "status": current,
            }
        owner = str(task.get("claimed_by") or "dispatch-supervisor")
        write_intent = str(task.get("write_intent") or "")
        if (
            args.disposition == "observed"
            and write_intent != "observe_only"
        ) or (
            args.disposition == "merged"
            and write_intent != "repo_patch"
        ):
            return {
                "ok": False,
                "reason": "disposition_write_intent_mismatch",
                "task_id": args.id,
                "disposition": args.disposition,
                "write_intent": write_intent,
            }
        if args.disposition in {"merged", "observed"}:
            task["status"] = "succeeded"
            task["completed_at"] = _now()
            task["result"] = args.result or (
                "read-only observation completed"
                if args.disposition == "observed"
                else "workspace merged and read back"
            )
            _record_status_history(
                task, frm=current, to="succeeded", by=owner,
                note=(
                    "supervisor_observation_settlement"
                    if args.disposition == "observed"
                    else "supervisor_post_merge_settlement"
                ),
            )
        elif args.disposition == "remediation":
            diagnostic = args.result or "workspace remediation opened"
            blocked_at = _now()
            task["status"] = "blocked"
            task["completed_at"] = blocked_at
            task["blocked_at"] = blocked_at
            task["blocked_reason"] = validate_blocked_reason(
                "awaiting_prerequisite_fix"
            )
            task["blocked_note"] = diagnostic
            task["result"] = diagnostic
            enforce_blocked_until(
                task, now=datetime.fromisoformat(blocked_at)
            )
            _record_status_history(
                task, frm=current, to="blocked", by=owner,
                note="workspace_adjudication",
            )
        else:
            task["dispatch_settled_session_id"] = str(args.session)
            task["dispatch_settled_job_id"] = (
                expected_job_id or supplied_job_id
            )
            previous_owner = _repend_task(
                task,
                note=f"supervisor_settle_{args.disposition}",
                reason=f"workspace_{args.disposition}",
            )
            return {
                "ok": True,
                "task_id": args.id,
                "status": "pending",
                "released_from": previous_owner,
            }
        task["dispatch_settled_session_id"] = str(args.session)
        task["dispatch_settled_job_id"] = expected_job_id or supplied_job_id
        task.pop("dispatch_managed", None)
        task.pop("dispatch_managed_owner", None)
        task.pop("dispatch_job_id", None)
        task.pop("dispatch_settlement_pending", None)
        task.pop("claimed_by", None)
        task.pop("claimed_at", None)
        task.pop("claim_expires_at", None)
        task.pop("claim_session_id", None)
        return {"ok": True, "task_id": args.id, "status": task["status"]}


def cmd_dispatch_pending(args: argparse.Namespace) -> dict[str, Any]:
    """List supervisor-owned admission outbox rows for crash reconciliation."""
    if not _dispatch_supervisor_authorized():
        return {"ok": False, "reason": "supervisor_capability_required"}
    rows: list[dict[str, Any]] = []
    with _locked_readonly() as tasks:
        for task in tasks:
            intent = task.get("dispatch_settlement_pending")
            if (
                task.get("dispatch_managed") is not True
                or not isinstance(intent, dict)
                or (task.get("status") or "").lower()
                not in {"claimed", "in_progress"}
            ):
                continue
            rows.append({
                "task_id": _task_key(task),
                "claim_session_id": str(task.get("claim_session_id") or ""),
                "dispatch_job_id": str(task.get("dispatch_job_id") or ""),
                "intent": dict(intent),
            })
            if len(rows) >= max(0, int(args.limit)):
                break
    return {"ok": True, "pending": rows, "count": len(rows)}


def cmd_start(args: argparse.Namespace) -> dict[str, Any]:
    with _locked_load() as (_fh, tasks):
        task = _find(tasks, args.id)
        if task.get("unblock_gate") is not None:
            return {
                "ok": False,
                "reason": "unblock_gate_not_satisfied",
                "status": task.get("status"),
            }
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
    """Return one task to a clean `pending` lifecycle state (single mutation site).

    Every re-pend in this module goes through here so the claim fields, the
    release timestamp and the status_history trace can never drift apart
    between the manual, kill-triggered, stale-sweep and residue-normalization
    paths.  A pending→pending transition is intentional audit evidence when an
    old backup contains claim metadata that contradicts its pending status.
    """
    if task.get("unblock_gate") is not None:
        raise ValueError(
            "cannot re-pend a task with an unresolved unblock_gate"
        )
    prev_owner = task.get("claimed_by")
    prev_status = (task.get("status") or "").lower() or "claimed"
    task["status"] = "pending"
    task.pop("claimed_by", None)
    task.pop("claimed_at", None)
    task.pop("claim_expires_at", None)
    task.pop("claim_session_id", None)
    task.pop("started_at", None)
    task.pop("dispatch_managed", None)
    task.pop("dispatch_managed_owner", None)
    task.pop("dispatch_job_id", None)
    task.pop("dispatch_settlement_pending", None)
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


def renew_verified_dispatch_claims(
    job_ids: Any, *, renewed_at: str | None = None
) -> dict[str, Any]:
    """Renew active dispatch claims after the health loop verifies processes.

    The caller must supply only job ids whose PID/start-wall identity matched
    the current worker process.  This runs every health heartbeat, well before
    the two-hour expiry; hourly cleanup only remains a safety net.
    """
    verified = {
        str(job_id) for job_id in job_ids if str(job_id or "").strip()
    }
    if not verified:
        return {"ok": True, "renewed": [], "count": 0}
    timestamp = renewed_at or _now()
    renewed: list[dict[str, str]] = []
    with _locked_load() as (_fh, tasks):
        for task in tasks:
            if (
                (task.get("status") or "").lower()
                not in {"claimed", "in_progress"}
                or task.get("dispatch_managed") is not True
                or str(task.get("dispatch_job_id") or "") not in verified
            ):
                continue
            _renew_claim_expiry(task, renewed_at=timestamp)
            renewed.append({
                "id": _task_key(task),
                "dispatch_job_id": str(task["dispatch_job_id"]),
                "claim_expires_at": str(task["claim_expires_at"]),
            })
    return {"ok": True, "renewed": renewed, "count": len(renewed)}


def cmd_release(args: argparse.Namespace) -> dict[str, Any]:
    with _locked_load() as (_fh, tasks):
        task = _find(tasks, args.id)
        status = (task.get("status") or "").lower()
        if status not in {"claimed", "in_progress"}:
            return {
                "ok": False,
                "reason": "wrong_status",
                "status": task.get("status"),
            }
        if task.get("unblock_gate") is not None:
            return {
                "ok": False,
                "reason": "unblock_gate_not_satisfied",
                "status": task.get("status"),
            }
        prev_owner = _repend_task(task, note="manual_release")
        return {"ok": True, "task_id": args.id, "released_from": prev_owner}


def cmd_handoff_main_thread(args: argparse.Namespace) -> dict[str, Any]:
    with _locked_load() as (_fh, tasks):
        task = _find(tasks, args.id)
        prev_status = (task.get("status") or "").lower()
        if task.get("unblock_gate") is not None:
            return {
                "ok": False,
                "reason": "unblock_gate_not_satisfied",
                "status": task.get("status"),
            }
        if prev_status not in {"claimed", "in_progress", "pending", "pending_main_thread"}:
            return {"ok": False, "reason": "wrong_status", "status": task.get("status")}
        prev_owner = task.get("claimed_by") or "handoff"
        task["status"] = "pending_main_thread"
        task["handoff_note"] = args.note
        task["handoff_at"] = _now()
        task.pop("claimed_by", None)
        task.pop("claimed_at", None)
        task.pop("claim_expires_at", None)
        task.pop("claim_session_id", None)
        _record_status_history(
            task,
            frm=prev_status or "claimed",
            to="pending_main_thread",
            by=prev_owner,
            note=args.note,
        )
        return {"ok": True, "task_id": args.id, "status": "pending_main_thread"}


def _burst_continuation_actions(
    tasks: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """What a burst window wants doing for this completion, or None.

    Returns None when no window is open (the normal state — completions are
    silent and dispatch keeps its hourly cadence), or when the burst module is
    unavailable: a continuation probe problem must never fail the completion
    it is only accelerating.

    Completion reporting is deliberately absent here.  Burst mode only
    accelerates scheduling; structured progress is owned by
    ``progress_report.py``.  Counting pending here, under the lock, avoids
    waking the supervisor for an empty queue.
    """
    try:
        from volpred.ops import dispatch_burst
        if not dispatch_burst.active():
            return None
        pending = sum(1 for t in tasks
                      if isinstance(t, dict) and (t.get("status") or "").lower() == "pending")
        return {"pending_left": pending}
    except Exception as exc:
        # Fail-open: the claim/complete write already landed under the lock, so a
        # broken burst window must never fail the caller. Observable, not silent.
        from volpred.ops.diagnostics import warn
        warn(
            "task_pool_claim",
            "burst continuation probe failed",
            err=f"{type(exc).__name__}: {exc}",
        )
        return None


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


def _current_repo_head(repo_root: Path = ROOT) -> str | None:
    """Return the immutable completion fence used by post-commit settlement."""
    try:
        observed = subprocess.run(
            ["git", "rev-parse", "--verify", "HEAD^{commit}"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        from volpred.ops.diagnostics import warn

        warn(
            "task-pool-issue-sync",
            "cannot resolve completion base commit",
            repo_root=str(repo_root),
            err=str(exc),
        )
        return None
    sha = str(observed.stdout or "").strip().lower()
    return sha if observed.returncode == 0 and re.fullmatch(r"[0-9a-f]{40}", sha) else None


def _gate_review_completion_contract(
    task: dict[str, Any],
    args: argparse.Namespace,
) -> tuple[dict[str, str] | None, dict[str, Any] | None]:
    """Require a review to finish the PDCA Act step, not merely say "done"."""

    gate_id = str(task.get("gate_review_id") or "").strip()
    if not gate_id or args.status != "succeeded":
        return None, None
    decision = str(getattr(args, "gate_decision", None) or "").strip()
    live_readback = str(
        getattr(args, "gate_live_readback", None) or ""
    ).strip()
    if decision not in _GATE_REVIEW_ACTIONS or not live_readback:
        return None, {
            "ok": False,
            "reason": "gate_adjudication_required",
            "task_id": args.id,
            "required_decisions": sorted(_GATE_REVIEW_ACTIONS),
            "required_evidence": "gate_live_readback",
        }
    try:
        registry = json.loads(
            CONTROL_GATE_REGISTRY.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        return None, {
            "ok": False,
            "reason": "gate_registry_unavailable",
            "task_id": args.id,
            "error": f"{type(exc).__name__}: {exc}",
        }
    gate = next(
        (
            row
            for row in registry.get("gates", [])
            if isinstance(row, dict) and row.get("gate_id") == gate_id
        ),
        None,
    )
    lifecycle = gate.get("lifecycle") if isinstance(gate, dict) else None
    if not isinstance(lifecycle, dict):
        return None, {
            "ok": False,
            "reason": "gate_registry_act_missing",
            "task_id": args.id,
            "gate_id": gate_id,
        }
    reviewed_at = str(lifecycle.get("last_reviewed_at") or "").strip()
    try:
        parsed_reviewed_at = datetime.fromisoformat(
            reviewed_at.replace("Z", "+00:00")
        )
    except ValueError:
        parsed_reviewed_at = None
    watermark_raw = str(
        task.get("gate_review_watermark")
        or task.get("created_at")
        or ""
    ).strip()
    try:
        parsed_watermark = datetime.fromisoformat(
            watermark_raw.replace("Z", "+00:00")
        )
    except ValueError:
        parsed_watermark = None
    has_review_timezone = (
        parsed_reviewed_at is not None
        and parsed_reviewed_at.tzinfo is not None
        and parsed_reviewed_at.utcoffset() is not None
    )
    has_watermark_timezone = (
        parsed_watermark is not None
        and parsed_watermark.tzinfo is not None
        and parsed_watermark.utcoffset() is not None
    )
    current = datetime.now(timezone.utc)
    reviewed_utc = (
        parsed_reviewed_at.astimezone(timezone.utc)
        if has_review_timezone
        else None
    )
    watermark_utc = (
        parsed_watermark.astimezone(timezone.utc)
        if has_watermark_timezone
        else None
    )
    if (
        lifecycle.get("last_action") != decision
        or lifecycle.get("review_task_id") != args.id
        or reviewed_utc is None
        or watermark_utc is None
        or reviewed_utc < watermark_utc
        or reviewed_utc > current
    ):
        return None, {
            "ok": False,
            "reason": "gate_registry_act_missing",
            "task_id": args.id,
            "gate_id": gate_id,
            "expected_action": decision,
        }
    return {
        "gate_decision": decision,
        "gate_live_readback": live_readback,
        "gate_registry_reviewed_at": reviewed_at,
    }, None


def cmd_complete(args: argparse.Namespace) -> dict[str, Any]:
    out, burst = _complete_locked(
        args,
        completion_base_commit=_current_repo_head(),
    )
    if burst:
        # The supervisor owns a separate lock; never hold queue LOCK_EX while
        # requesting the next fire.
        if burst.get("pending_left"):
            out["burst_next_fire"] = _request_burst_fire(args.id, burst["pending_left"])
    return out


def _complete_locked(
    args: argparse.Namespace,
    *,
    completion_base_commit: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    if args.status == "blocked":
        return {
            "ok": False,
            "reason": "use_mark_task_blocked",
            "task_id": args.id,
        }, None
    with _locked_load() as (_fh, tasks):
        task = _find(tasks, args.id)
        prev_status = (task.get("status") or "").lower() or "in_progress"
        completion_owner = task.get("claimed_by") or "complete"
        issue_ref = task.get("issue_ref")
        issue_disposition = getattr(
            args, "issue_disposition", "contained"
        )
        if issue_disposition not in {"contained", "close"}:
            raise ValueError(
                "issue_disposition must be contained or close"
            )
        if prev_status in TERMINAL_STATUSES and prev_status == args.status:
            # Idempotent repair path: terminal rows are historical receipts,
            # never active ownership. Older complete() versions left these
            # fields behind, so a safe re-run must clean them too.
            task.pop("claimed_by", None)
            task.pop("claimed_at", None)
            task.pop("claim_expires_at", None)
            task.pop("claim_session_id", None)
            return {
                "ok": True,
                "task_id": args.id,
                "status": prev_status,
                "already_completed": True,
            }, None
        if (
            args.status == "succeeded"
            and issue_ref is not None
            and issue_disposition == "close"
        ):
            number = issue_number(issue_ref)
            if number is None:
                return {
                    "ok": False,
                    "reason": "invalid_issue_ref",
                    "task_id": args.id,
                }, None
            if not completion_base_commit:
                return {
                    "ok": False,
                    "reason": "git_head_unavailable",
                    "task_id": args.id,
                    "issue_ref": normalize_issue_ref(issue_ref),
                    "issue_number": number,
                }, None
        existing_result = str(task.get("result") or "")
        result_text = (
            (existing_result + "\n\n" + args.result).strip()
            if existing_result and args.result
            else (args.result or existing_result)
        )
        if args.status == "succeeded":
            _require_fb_drafts_for_dual_publish(task, result_text)
        gate_receipt, gate_error = _gate_review_completion_contract(task, args)
        if gate_error is not None:
            return gate_error, None
        if gate_receipt is not None:
            task.update(gate_receipt)
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
        task.pop("claim_expires_at", None)
        task.pop("claim_session_id", None)
        if args.result:
            task["result"] = result_text
            result_text = task["result"]
        effect = None
        if args.status == "succeeded":
            effect = _apply_codex_review_followup_fail(tasks, task, result_text)
        out = {"ok": True, "task_id": args.id, "status": args.status}
        if args.status == "succeeded" and issue_ref is not None:
            number = issue_number(issue_ref)
            if number is None:
                out["issue_tracker_sync"] = {
                    "ok": False,
                    "action": (
                        "defer_close_until_commit"
                        if issue_disposition == "close"
                        else "keep_open"
                    ),
                    "reason": "invalid_issue_ref",
                }
            else:
                canonical_ref = normalize_issue_ref(issue_ref)
                task["issue_ref"] = canonical_ref
                task["issue_disposition"] = issue_disposition
            if number is not None and issue_disposition == "contained":
                task.pop("issue_close_pending", None)
                out["issue_tracker_sync"] = {
                    "ok": True,
                    "action": "keep_open",
                    "issue_ref": canonical_ref,
                    "issue_number": number,
                    "disposition": "contained",
                }
            elif number is not None and not completion_base_commit:
                out["issue_tracker_sync"] = {
                    "ok": False,
                    "action": "defer_close_until_commit",
                    "issue_ref": canonical_ref,
                    "issue_number": number,
                    "reason": "git_head_unavailable",
                }
            elif number is not None:
                task["issue_close_pending"] = {
                    "issue_disposition": "close",
                    "issue_ref": canonical_ref,
                    "task_id": args.id,
                    "completion_owner": completion_owner,
                    "completed_at": task["completed_at"],
                    "completion_base_commit": completion_base_commit,
                }
                out["issue_tracker_sync"] = {
                    "ok": True,
                    "action": "defer_close_until_commit",
                    "issue_ref": canonical_ref,
                    "issue_number": number,
                }
        if effect:
            out["review_followup_effect"] = effect
        burst = _burst_continuation_actions(tasks)
        return out, burst


#: annotate 只准動 free-form metadata；生命週期/身分欄位各有專屬入口
#: （claim/start/complete/release/mark_task_blocked），繞過那些入口 = 繞過
#: 它們的 guard 與 status vocab 檢查。
ANNOTATE_PROTECTED_FIELDS = frozenset({
    "id", "status", "priority", "task_type", "created_at", "completed_at",
    "claimed_by", "claimed_at", "claim_expires_at", "claim_session_id",
    "blocked_reason", "blocked_at", "blocked_until",
    "unblock_gate",
    "issue_ref", "issue_close_pending", "issue_disposition",
    "issue_closed_commit", "issue_closed_at",
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
                now = datetime.now(timezone.utc)
                claim_expires_at = t.get("claim_expires_at")
                if claim_expires_at:
                    expiry = parse_iso_warn(
                        claim_expires_at,
                        tag="claim",
                        field_name="claim_expires_at",
                        fallback=None,
                        site="list_stale",
                        task_id=_task_key(t),
                    )
                    if expiry is None or now < expiry:
                        continue
                else:
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
                    age_h = (now - claimed_dt).total_seconds() / 3600
                    if age_h < args.stale_hours:
                        continue
            elif args.status == "pending":
                if not is_pending_list_candidate(
                    t,
                    codex_eligible=bool(args.codex_eligible),
                ):
                    continue
            elif args.status and status != args.status:
                continue
            if args.owner and t.get("claimed_by") != args.owner:
                continue
            if (
                args.codex_eligible
                and args.status != "pending"
                and not _is_codex_eligible_task(t)
            ):
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
        out.sort(key=task_rank_key)
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


def _read_compute_job(job_id: str | None) -> dict[str, Any] | None:
    """Read the durable compute owner receipt, or return ``None`` if absent."""
    if not job_id:
        return None
    path = _COMPUTE_QUEUE_DIR / f"{job_id}.json"
    try:
        with path.open(encoding="utf-8") as fh:
            payload = json.load(fh)
    except (OSError, ValueError):  # silent-ok: cleanup emits gone release receipt
        return None
    return payload if isinstance(payload, dict) else None


def _compute_job_alive(job_id: str | None) -> bool:
    """True 若 task 掛著的 compute-queue job 仍在飛。

    stale reaper 只看 claimed_at 的年齡，看不見「工作其實在 compute worker 上跑」。
    長研究 job timeout 動輒 5400s，遠超 --stale-hours 2 —— 於是 dispatch 到 compute
    queue 的 task 會在 2h 後被放回 pending，重新進 starvation lockout 被第二次派工，
    產生重複 agent job 與重複 worktree（實例：assign_5aa9d5f5 於 2026-07-19/07-20
    連兩次 auto_release_stale_2h，工作全程在 queue 上正常執行）。

    job 已進終態（completed / failed / timeout）則不擋 —— task 本來就該回池等收件。
    """
    job = _read_compute_job(job_id)
    if job is None:
        return False
    status = str(job.get("status") or "").lower()
    return status in _COMPUTE_JOB_LIVE


def cmd_cleanup(args: argparse.Namespace) -> dict[str, Any]:
    released = []
    normalized_pending = []
    skipped_compute = []
    renewed_live_claims = []
    invalid_claim_expiries = []
    reconciled_awaiting_agent_jobs = []
    awaiting_receipt_collection = []
    invalid_compute_bindings = []
    with _locked_load() as (_fh, tasks):
        now = datetime.now(timezone.utc)
        for t in tasks:
            status = (t.get("status") or "").lower()
            if status == "awaiting_agent_job":
                job_id = str(t.get("compute_job_id") or "")
                blocked_reason = str(t.get("blocked_reason") or "")
                if (
                    blocked_reason
                    == "external_compute_receipt_pending_collection"
                ):
                    awaiting_receipt_collection.append(
                        {"id": _task_key(t), "compute_job_id": job_id}
                    )
                    continue
                if blocked_reason not in {
                    "external_compute_job_active",
                    "external_compute_job_running",
                }:
                    continue
                job = _read_compute_job(job_id)
                job_status = (
                    str(job.get("status") or "").lower()
                    if job is not None
                    else "gone"
                )
                binding_matches = (
                    job is not None
                    and str(job.get("id") or job_id) == job_id
                    and str(job.get("source_task_id") or "") == _task_key(t)
                )
                if job is not None and not binding_matches:
                    invalid_compute_bindings.append(
                        {
                            "id": _task_key(t),
                            "compute_job_id": job_id,
                            "job_source_task_id": str(
                                job.get("source_task_id") or ""
                            ),
                        }
                    )
                    continue
                if binding_matches and job_status in _COMPUTE_JOB_LIVE:
                    skipped_compute.append(
                        {"id": _task_key(t), "compute_job_id": job_id}
                    )
                    continue
                if binding_matches and job_status == "completed":
                    t["blocked_reason"] = (
                        "external_compute_receipt_pending_collection"
                    )
                    t["compute_finished_at"] = (
                        job.get("completed_at") or now.isoformat()
                    )
                    reconciled_awaiting_agent_jobs.append(
                        {
                            "id": _task_key(t),
                            "compute_job_id": job_id,
                            "job_status": job_status,
                            "action": "await_receipt_collection",
                        }
                    )
                    continue
                release_status = job_status
                release_reason = f"external_compute_job_{release_status}"
                _repend_task(
                    t,
                    note=release_reason,
                    reason=release_reason,
                )
                t["compute_released_at"] = now.isoformat()
                t["compute_release_reason"] = release_reason
                for field in (
                    "blocked_reason",
                    "compute_job_id",
                    "compute_started_at",
                    "compute_finished_at",
                    "external_execution_ref",
                ):
                    t.pop(field, None)
                reconciled_awaiting_agent_jobs.append(
                    {
                        "id": _task_key(t),
                        "compute_job_id": job_id,
                        "job_status": release_status,
                        "action": "repend",
                    }
                )
                continue
            if status == "pending" and any(
                t.get(field) not in (None, "")
                for field in (
                    "claimed_by",
                    "claimed_at",
                    "claim_expires_at",
                    "claim_session_id",
                    "started_at",
                )
            ):
                job_id = t.get("compute_job_id")
                if _compute_job_alive(job_id):
                    skipped_compute.append(
                        {"id": _task_key(t), "compute_job_id": job_id}
                    )
                    continue
                reason = "normalize_pending_claim_residue"
                prev_owner = _repend_task(t, note=reason, reason=reason)
                normalized_pending.append(
                    {"id": _task_key(t), "owner": prev_owner}
                )
                continue
            if status not in {"claimed", "in_progress"}:
                continue
            if t.get("dispatch_managed") is True:
                dispatch_job_id = t.get("dispatch_job_id")
                if _dispatch_job_alive(dispatch_job_id):
                    _renew_claim_expiry(t, renewed_at=now.isoformat())
                    renewed_live_claims.append({
                        "id": _task_key(t),
                        "evidence": "dispatch_job_alive",
                        "claim_expires_at": t["claim_expires_at"],
                    })
                    skipped_compute.append({
                        "id": _task_key(t),
                        "dispatch_managed": True,
                        "dispatch_job_id": dispatch_job_id,
                    })
                    continue
            job_id = t.get("compute_job_id")
            if _compute_job_alive(job_id):
                _renew_claim_expiry(t, renewed_at=now.isoformat())
                renewed_live_claims.append({
                    "id": _task_key(t),
                    "evidence": "compute_job_alive",
                    "claim_expires_at": t["claim_expires_at"],
                })
                skipped_compute.append({"id": _task_key(t), "compute_job_id": job_id})
                continue
            claim_expires_at = t.get("claim_expires_at")
            claimed_dt = None
            age_source = "claim_expires_at"
            expiry_authoritative = bool(claim_expires_at)
            if claim_expires_at:
                claimed_dt = parse_iso_warn(
                    claim_expires_at,
                    tag="claim",
                    field_name="claim_expires_at",
                    fallback=None,
                    site="cleanup_stale",
                    task_id=_task_key(t),
                )
                if claimed_dt is None:
                    invalid_claim_expiries.append({
                        "id": _task_key(t),
                        "claim_expires_at": claim_expires_at,
                    })
                    continue
                if claimed_dt is not None and now < claimed_dt:
                    continue
            if not expiry_authoritative:
                claimed_at = t.get("claimed_at")
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
            if claimed_dt is None and not expiry_authoritative:
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
            if expiry_authoritative or age_h >= args.stale_hours:
                release_reason = (
                    "auto_release_claim_expired"
                    if expiry_authoritative
                    else f"auto_release_stale_{args.stale_hours}h"
                )
                prev_owner = _repend_task(
                    t,
                    note=release_reason,
                    reason=release_reason,
                )
                released.append(
                    {
                        "id": _task_key(t),
                        "owner": prev_owner,
                        "age_h": round(age_h, 1) if claimed_dt is not None else None,
                        "age_source": age_source,
                    }
                )
    return {
        "ok": True,
        "released": released,
        "count": len(released),
        "normalized_pending_claim_residue": normalized_pending,
        "normalized_count": len(normalized_pending),
        "skipped_compute_in_flight": skipped_compute,
        "renewed_live_claims": renewed_live_claims,
        "invalid_claim_expiries": invalid_claim_expiries,
        "reconciled_awaiting_agent_jobs": reconciled_awaiting_agent_jobs,
        "awaiting_receipt_collection": awaiting_receipt_collection,
        "invalid_compute_bindings": invalid_compute_bindings,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("claim"); p.add_argument("--id", required=True); p.add_argument("--owner", required=True); p.add_argument("--session"); p.add_argument("--main-thread", action="store_true", dest="main_thread", help="claim a main_thread-lane task (interactive session only)"); p.set_defaults(fn=cmd_claim)
    p = sub.add_parser(
        "dispatch-preassign",
        help="supervisor-only atomic claim+start for contract-complete mutating work",
    )
    p.add_argument("--owner", required=True)
    p.add_argument("--session", required=True)
    p.add_argument("--job-id")
    p.set_defaults(fn=cmd_dispatch_preassign)
    p = sub.add_parser(
        "dispatch-pending",
        help="supervisor-only admission settlement outbox readback",
    )
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(fn=cmd_dispatch_pending)
    p = sub.add_parser(
        "dispatch-settle",
        help="supervisor-only claim-session CAS after workspace finalization",
    )
    p.add_argument("--id", required=True)
    p.add_argument("--session", required=True)
    p.add_argument("--job-id", required=True)
    p.add_argument(
        "--disposition",
        required=True,
        choices=[
            "merged", "observed", "remediation", "retry", "empty", "failure"
        ],
    )
    p.add_argument("--result")
    p.set_defaults(fn=cmd_dispatch_settle)
    p = sub.add_parser("start"); p.add_argument("--id", required=True); p.set_defaults(fn=cmd_start)
    p = sub.add_parser("release"); p.add_argument("--id", required=True); p.set_defaults(fn=cmd_release)
    p = sub.add_parser("handoff-main-thread"); p.add_argument("--id", required=True); p.add_argument("--note", required=True); p.set_defaults(fn=cmd_handoff_main_thread)
    p = sub.add_parser("complete"); p.add_argument("--id", required=True); p.add_argument("--status", choices=["succeeded", "failed"], default="succeeded"); p.add_argument("--result"); p.add_argument("--issue-disposition", choices=["contained", "close"], default="contained", help="GitHub issue lifecycle: keep open by default; close only after all issue acceptance gates pass"); p.add_argument("--gate-decision", choices=sorted(_GATE_REVIEW_ACTIONS), help="Required for succeeded control-gate reviews; must match registry lifecycle.last_action"); p.add_argument("--gate-live-readback", help="Required downstream read-back for succeeded control-gate reviews"); p.set_defaults(fn=cmd_complete)
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
