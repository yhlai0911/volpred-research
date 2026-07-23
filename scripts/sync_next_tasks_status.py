#!/usr/bin/env python3
"""Sync next_tasks.json pending → succeeded for K-experiments already done.

問題：K1125 已 FAIL 2026-04-13 (有 experiments/k1125/{README.md, k1125.py, k1125_results.json})
但 storage/next_tasks.json 仍標 pending → dispatcher 會誤再派。

本 script：
1. 讀 next_tasks.json pending tasks
2. 對 K-id 形式（K\\d+ 或 K\\d+[a-z]+）的 task，檢查 experiments/<lowercase>/ 是否：
   (a) 目錄存在
   (b) 有 README.md
   (c) README.md 第一段 / k<id>_results.json 顯示完成 status (PASS/FAIL/NULL_RESULT/COMPLETE)
3. 若是，把 next_tasks 該 entry status 改 succeeded + 加 completed_at + result_summary

非 K-id 形式（Paper3_reframe / vix_sufficiency_expansion / Data_summary_script_*）跳過 —
那些是 paper writing / scaffolding 任務，不靠 experiments dir 判斷完成。

Usage::
    uv run python scripts/sync_next_tasks_status.py --dry-run
    uv run python scripts/sync_next_tasks_status.py --apply
"""
from __future__ import annotations

import argparse
import fcntl
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
NEXT_TASKS = ROOT / "storage" / "next_tasks.json"
EXPERIMENTS = ROOT / "experiments"

from volpred.canonical_write import guard_canonical_write  # noqa: E402
from volpred.ops.next_tasks import (  # noqa: E402
    enforce_blocked_until,
    normalize_priority,
    validate_blocked_reason,
    write_tasks_to_handle,
)

K_ID_RE = re.compile(r"^K\d+[a-z_]*$")
REVIEW_GATE_K_ID_RE = re.compile(r"^K\d{2,5}[A-Z]?$", re.IGNORECASE)
STATUS_LINE_RE = re.compile(
    # Match three forms:
    #   Status: PASS                       (plain)
    #   **Status**: PASS                   (bold)
    #   | Status | PASS ... |              (markdown table cell — K1108d, K1108e patterns)
    r"(?:^\*?\*?Status\*?\*?\s*:\s*|\|\s*Status\s*\|\s*)"
    r"(?P<status>PASS|FAIL|NULL_RESULT|NULL|COMPLETE|COMPLETED|DONE|SUCCEEDED|REPLICATED|VERIFIED|"
    r"LOW_COVERAGE_PRELIMINARY|LOW_COVERAGE|PRELIMINARY)\b",
    re.IGNORECASE | re.MULTILINE,
)


def _warn(message: str) -> None:
    print(f"[sync_next_tasks] WARN {message}", file=sys.stderr)


def find_experiment_dir(task_id: str) -> Path | None:
    """Map K1125 -> experiments/k1125/, K1100g_d9 -> experiments/k1100g_d9/."""
    for name in (task_id, task_id.lower(), task_id.upper()):
        candidate = EXPERIMENTS / name
        if candidate.is_dir():
            return candidate
    if EXPERIMENTS.is_dir():
        wanted = task_id.lower()
        for candidate in EXPERIMENTS.iterdir():
            if candidate.is_dir() and candidate.name.lower() == wanted:
                return candidate
    return None


def has_codex_review(exp_dir: Path) -> bool:
    """Return True if an experiment folder carries a Codex review artifact."""
    candidates = [
        exp_dir / "codex_review.md",
        *exp_dir.glob("*codex*review*.md"),
        *exp_dir.glob("reviews/*codex*review*.md"),
    ]
    return any(path.is_file() and path.stat().st_size > 0 for path in candidates)


def detect_completion(exp_dir: Path) -> dict | None:
    """Return {status, completed_at, summary} if experiment looks complete; else None."""
    readme = exp_dir / "README.md"
    if not readme.exists():
        return None

    body = readme.read_text(errors="replace")
    m = STATUS_LINE_RE.search(body)
    if not m:
        return None

    status_token = m.group("status").upper()
    # Map token to canonical status
    if status_token in {"PASS", "REPLICATED", "VERIFIED", "COMPLETE", "COMPLETED", "DONE", "SUCCEEDED"}:
        canonical = "succeeded"
    elif status_token in {"FAIL", "NULL_RESULT", "NULL", "LOW_COVERAGE_PRELIMINARY", "LOW_COVERAGE", "PRELIMINARY"}:
        canonical = "succeeded_null_result"
    else:
        canonical = "succeeded"

    # Extract completion date — try README first line "**Date**: YYYY-MM-DD"
    date_match = re.search(r"\*?\*?Date\*?\*?\s*:\s*(\d{4}-\d{2}-\d{2})", body)
    completed_at = date_match.group(1) if date_match else None

    # Try results.json mtime as fallback
    if not completed_at:
        results_files = list(exp_dir.glob("*_results.json"))
        if results_files:
            mtime = datetime.fromtimestamp(
                results_files[0].stat().st_mtime, tz=timezone.utc
            )
            completed_at = mtime.date().isoformat()

    # First non-empty paragraph as summary
    paragraphs = [p.strip() for p in body.split("\n\n") if p.strip() and not p.strip().startswith("#")]
    summary = paragraphs[0][:200] if paragraphs else None

    return {
        "status_token": status_token,
        "canonical_status": canonical,
        "completed_at": completed_at,
        "summary": summary,
    }


def load_tasks() -> list[dict]:
    if not NEXT_TASKS.exists():
        return []
    data = json.loads(NEXT_TASKS.read_text())
    if isinstance(data, dict):
        tasks = data.get("tasks")
        if tasks is None:
            _warn("next_tasks.json dict missing tasks list; treating as empty")
            return []
        if not isinstance(tasks, list):
            _warn(
                "next_tasks.json tasks field is not a list; treating as empty "
                f"type={type(tasks).__name__}"
            )
            return []
        return tasks
    if not isinstance(data, list):
        _warn(
            "next_tasks.json top-level schema is not a list or dict; treating as empty "
            f"type={type(data).__name__}"
        )
        return []
    return data


def is_review_gate_gap(task: dict, exp_dir: Path | None) -> bool:
    """Detect Codex daemon K experiments that reached terminal state without review."""
    if exp_dir is None:
        return False
    if str(task.get("task_type") or "") != "experiment":
        return False
    if str(task.get("claimed_by") or "") != "codex-desktop":
        return False
    if (task.get("status") or "").lower() not in {"succeeded", "succeeded_null_result"}:
        return False
    task_id = str(task.get("id") or "")
    if not REVIEW_GATE_K_ID_RE.match(task_id):
        return False
    return not has_codex_review(exp_dir)


def is_resolved_review_block(task: dict, exp_dir: Path | None) -> bool:
    """Detect a task stuck in `blocked` on a review gate whose Codex review
    artifact now EXISTS — i.e. the block condition is satisfied but nothing
    re-scanned the blocked lane to release it.

    2026-07-04 structural fix (audit finding): the prior scan only walked
    `pending` tasks, so a K marked `blocked / awaiting_codex_review` whose
    review landed later (e.g. K1330 reviewed 2026-06-23) stayed blocked
    forever — the blocked lane was a permanent sync blind spot. This releases
    it back to a completion status through the normal FLOW instead of a manual
    JSON edit.
    """
    if exp_dir is None:
        return False
    if (task.get("status") or "").lower() != "blocked":
        return False
    reason = str(task.get("blocked_reason") or "").lower()
    gate = str(task.get("review_gate_status") or "").lower()
    is_review_block = "codex_review" in reason or "review" in gate or reason == "awaiting_codex_review"
    if not is_review_block:
        return False
    return has_codex_review(exp_dir)


def _followup_task_id(task_id: str) -> str:
    return f"{task_id}_codex_review_followup"


def _has_task_id(tasks: list[dict], task_id: str) -> bool:
    return any(str(t.get("id") or "") == task_id for t in tasks)


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    if not (args.dry_run or args.apply):
        print("error: must specify --dry-run or --apply", file=sys.stderr)
        return 2

    tasks = load_tasks()
    candidates = []  # (idx, task, completion_info)
    review_gaps = []  # (idx, task, exp_dir)
    resolved_blocks = []  # (idx, task, exp_dir, completion_info) — blocked review-gate now reviewed
    skipped_non_kid = 0

    for idx, task in enumerate(tasks):
        tid = task.get("id") or ""
        exp_dir = find_experiment_dir(tid) if tid else None
        if is_review_gate_gap(task, exp_dir):
            review_gaps.append((idx, task, exp_dir))
        if is_resolved_review_block(task, exp_dir):
            info = detect_completion(exp_dir) or {
                "canonical_status": "succeeded",
                "completed_at": None,
                "summary": None,
                "status_token": "REVIEWED",
            }
            resolved_blocks.append((idx, task, exp_dir, info))

        if (task.get("status") or "").lower() != "pending":
            continue
        if not K_ID_RE.match(tid):
            skipped_non_kid += 1
            continue

        if exp_dir is None:
            continue

        info = detect_completion(exp_dir)
        if info is None:
            continue

        candidates.append((idx, task, info, exp_dir))

    print(f"[sync_next_tasks] pending K-id tasks evaluated: {sum(1 for t in tasks if (t.get('status') or '').lower() == 'pending' and K_ID_RE.match(t.get('id') or ''))}")
    print(f"[sync_next_tasks] non-K-id pending skipped: {skipped_non_kid}")
    print(f"[sync_next_tasks] mark-succeeded candidates: {len(candidates)}")
    for _, task, info, exp_dir in candidates:
        print(
            f"  - {task.get('id')} P{task.get('priority')} -> {info['canonical_status']} "
            f"({info['status_token']} on {info['completed_at']}) "
            f"[exp_dir={_display_path(exp_dir)}]"
        )
    print(f"[sync_next_tasks] codex review-gate gaps: {len(review_gaps)}")
    for _, task, exp_dir in review_gaps:
        print(
            f"  - {task.get('id')} P{task.get('priority')} missing Codex review "
            f"[exp_dir={_display_path(exp_dir)}]"
        )
    print(f"[sync_next_tasks] resolved review-blocks (blocked→{{status}}): {len(resolved_blocks)}")
    for _, task, exp_dir, info in resolved_blocks:
        print(
            f"  - {task.get('id')} P{task.get('priority')} blocked/{task.get('blocked_reason')} "
            f"-> {info['canonical_status']} (review artifact present) [exp_dir={_display_path(exp_dir)}]"
        )

    if args.apply and (candidates or review_gaps or resolved_blocks):
        # Apply changes: mutate tasks list in-place
        now_iso = datetime.now(timezone.utc).isoformat()
        for idx, task, info, _ in candidates:
            tasks[idx]["status"] = info["canonical_status"]
            tasks[idx]["completed_at"] = info["completed_at"]
            tasks[idx]["synced_from_experiments_at"] = now_iso
            if info["summary"]:
                tasks[idx]["result_summary"] = info["summary"]
        for idx, task, exp_dir, info in resolved_blocks:
            tasks[idx]["status"] = info["canonical_status"]
            tasks[idx]["completed_at"] = info.get("completed_at")
            tasks[idx]["synced_from_experiments_at"] = now_iso
            tasks[idx]["review_gate_status"] = "reviewed"
            tasks[idx]["blocked_review_released_at"] = now_iso
            tasks[idx]["blocked_review_released_from"] = task.get("blocked_reason")
            # keep blocked_reason/blocked_note as audit trail; status now terminal
            if info.get("summary"):
                tasks[idx]["result_summary"] = info["summary"]
        review_followups_created = 0
        for idx, task, exp_dir in review_gaps:
            task_id = str(task.get("id") or "")
            followup_id = _followup_task_id(task_id)
            previous_status = tasks[idx].get("status")
            tasks[idx]["status"] = "blocked"
            # Strict vocab path (WS-A3): raises loudly if the reason ever
            # drifts out of blocked_reasons.py again.
            tasks[idx]["blocked_reason"] = validate_blocked_reason("awaiting_codex_review")
            tasks[idx]["review_gate_status"] = "awaiting_review"
            tasks[idx]["review_gate_detected_at"] = now_iso
            tasks[idx]["review_gate_previous_status"] = previous_status
            tasks[idx]["review_gate_experiment_dir"] = _display_path(exp_dir)
            # Every new block needs an exit: the sweeper only re-pends EXPIRED
            # blocks, so a review gate with no blocked_until parks forever.
            enforce_blocked_until(tasks[idx])
            if _has_task_id(tasks, followup_id):
                tasks[idx]["review_gate_followup_task_id"] = followup_id
                continue
            tasks.append({
                "id": followup_id,
                "task_type": "experiment",
                "status": "pending",
                "priority": normalize_priority(task.get("priority"), default=3),
                "title": f"{task_id} Codex review follow-up (missing review gate)",
                "description": (
                    f"{task_id} was marked {previous_status} by codex-desktop, "
                    f"but {_display_path(exp_dir)}/ has no Codex review artifact. "
                    "Run source-level Codex review before any knowledge.json promotion. "
                    "If verdict is FAIL, complete this follow-up with verdict=FAIL so "
                    "task_pool_claim.py can open the v2 methodology fix."
                ),
                "source": "sync_next_tasks_status_review_gate",
                "created_at": now_iso,
                "related_k_id": task_id,
                "predecessor": task_id,
                "dispatch_lane": "agent",
            })
            tasks[idx]["review_gate_followup_task_id"] = followup_id
            review_followups_created += 1

        # Write back under the SAME fcntl.LOCK_EX-on-file protocol
        # task_pool_claim.py uses, so an apply can never interleave with a live
        # dispatcher/agent's read-modify-write. WS-A1b: the serialize-first
        # invariant used to be a hand-copied clone of write_tasks_to_handle —
        # the exact "drifts when the helper evolves" shape — now it IS the
        # helper. The legacy dict-root wrapper is read tolerance only (the
        # canonical queue root has been a list since the 2026-07-16
        # single-gateway refactor; both live queues verified list-root
        # 2026-07-20), so writing it back is refused loudly.
        guard_canonical_write(NEXT_TASKS)
        with NEXT_TASKS.open("r+", encoding="utf-8") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                original = json.load(fh)
                if isinstance(original, dict):
                    raise SystemExit(
                        "next_tasks.json root must be a list (single-gateway "
                        "2026-07-16); refusing to rewrite a dict-root queue"
                    )
                write_tasks_to_handle(fh, tasks)
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        print(
            f"[sync_next_tasks] APPLIED {len(candidates)} completion updates, "
            f"{len(review_gaps)} review-gate updates "
            f"({review_followups_created} follow-ups created), and "
            f"{len(resolved_blocks)} blocked-review releases to {NEXT_TASKS.relative_to(ROOT)}"
        )
    elif args.dry_run:
        print("[sync_next_tasks] dry-run only; rerun with --apply to write")

    return 0


if __name__ == "__main__":
    sys.exit(main())
