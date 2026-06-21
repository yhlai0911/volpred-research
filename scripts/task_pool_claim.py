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

ROOT = Path(__file__).resolve().parents[1]
NEXT_TASKS = ROOT / "storage" / "next_tasks.json"

DEFAULT_STALE_HOURS = 6  # Claim older than this with no completion -> auto-release
CODEX_ELIGIBLE_TASK_TYPES = {
    "platform_ops",
    "experiment",
    "governance",
    "code_review",
    "paper_review",
    "daily_article",
}


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
        fh.write("\n")
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
    task_id = str(task.get("id") or "")
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
        if str(t.get("id") or "").upper() == k_id
        and str(t.get("task_type") or "") == "experiment"
    ]
    if len(exact) == 1:
        return exact[0]

    keyed = []
    for t in tasks:
        if str(t.get("id") or "") == review_task_id:
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
    task_id = str(review_task.get("id") or "")
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
    if any(str(t.get("id") or "") == v2_id for t in tasks):
        effect["v2_task"] = "already_exists"
        return effect

    tasks.append({
        "id": v2_id,
        "task_type": "experiment",
        "status": "pending",
        "priority": review_task.get("priority") or "P3",
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
    })
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
        if _is_codex_owner(args.owner) and not _is_codex_eligible_task(task):
            return {
                "ok": False,
                "reason": "not_codex_eligible",
                "task_type": task.get("task_type"),
                "dispatch_lane": task.get("dispatch_lane"),
                "status": existing_status,
            }
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
        return out


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
            if args.codex_eligible and not _is_codex_eligible_task(t):
                continue
            out.append({
                "id": t.get("id"),
                "title": t.get("title"),
                "task_type": t.get("task_type"),
                "priority": t.get("priority"),
                "status": status,
                "claimed_by": t.get("claimed_by"),
                "claimed_at": t.get("claimed_at"),
                "dispatch_lane": t.get("dispatch_lane"),
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

    args = ap.parse_args()
    result = args.fn(args)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
