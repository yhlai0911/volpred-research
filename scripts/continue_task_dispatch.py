#!/usr/bin/env python3
"""Slot-aware continuation dispatcher (replaces stub-only continue_task host cron).

讀 storage/next_tasks.json 的 pending queue，按 priority asc 排序，
count 當前 slot 占用（.claude/worktrees/ + storage/ops/agents/ active），
若 slot < cap (4) 且有可派 agent 的 task → 列出 / 派出（依 mode）。

執行模式：
  --dry-run    僅列 candidates 不派任何工作（default 安全）
  --report     寫 report 到 storage/ops/dispatch_report_latest.json
  --execute    真的 spawn agent（需 cron-runtime；目前主線程 fallback = print 指令給人類）

main-thread-only 任務（從 title/description 擷取「main thread」/「NOT agent」標記）
不會被列為可派 agent，但會列在 main_thread_queue。

Usage::
    uv run python scripts/continue_task_dispatch.py --dry-run
    uv run python scripts/continue_task_dispatch.py --report
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NEXT_TASKS = ROOT / "storage" / "next_tasks.json"
WORKTREES_DIR = ROOT / ".claude" / "worktrees"
AGENTS_DIR = ROOT / "storage" / "ops" / "agents"
REPORT_PATH = ROOT / "storage" / "ops" / "dispatch_report_latest.json"
SLOT_CAP = 4
# Refill threshold: when agentable count drops below this, dispatcher
# auto-runs refill_task_pool.py to top up. Keeps the rule "任務池永遠要有
# 待辦任務" enforceable by mechanism, not by main-thread discipline.
REFILL_FLOOR = 4

MAIN_THREAD_MARKERS = re.compile(
    r"main\s*thread|NOT\s*agent|main-thread|主線程",
    re.IGNORECASE,
)

# 2026-05-04 finding: dispatcher previously had no concept of "blocked".
# Tasks that can never be dispatched (awaiting external auth, prior compute
# failures, self-tagged optional, K-id collision, etc.) sat in `pending`
# and got recommended every cycle, forcing main thread into a skip-loop.
#
# Hard blocks are persisted on the task itself via `blocked_reason` (set
# by scripts/mark_task_blocked.py or schema-level edits). Soft blocks are
# auto-detected from title/description patterns below; they can be
# upgraded to hard blocks on first encounter so the dispatcher is
# self-correcting.
BLOCKED_REASONS = {
    "awaiting_external_data",       # auth / data not yet available (Dropbox, GCP)
    "compute_runtime_incompatible", # background agent timeout < experiment runtime
    "self_tagged_optional",         # task self-flags itself as optional / skippable
    "kid_collision",                # K-id reuse — needs rename before dispatch
    "prior_attempts_failed",        # repeated failures; needs main-thread debug
    "deprecated",                   # superseded by another task / no longer relevant
}

SELF_OPTIONAL_PATTERN = re.compile(
    r"\(\s*optional\s*\)|（\s*optional\s*）|"
    r"only\s+if\s+truly\s+new|"
    r"否則跳過|skip\s+if\s+already",
    re.IGNORECASE,
)


def count_active_slots() -> dict:
    """Count occupied slots across worktrees + agent records."""
    worktrees = []
    if WORKTREES_DIR.exists():
        for p in WORKTREES_DIR.iterdir():
            if p.is_dir() and not p.name.startswith("."):
                worktrees.append(p.name)

    active_agents = []
    if AGENTS_DIR.exists():
        for f in AGENTS_DIR.glob("*.json"):
            try:
                data = json.loads(f.read_text())
            except json.JSONDecodeError:
                continue
            status = (data.get("status") or "").lower()
            if status in {"running", "active", "in_progress", "claimed"}:
                active_agents.append(f.stem)

    return {
        "worktrees": worktrees,
        "active_agents": active_agents,
        "occupied": len(worktrees) + len(active_agents),
    }


def load_pending_tasks() -> list[dict]:
    if not NEXT_TASKS.exists():
        return []
    data = json.loads(NEXT_TASKS.read_text())
    if isinstance(data, dict):
        data = data.get("tasks", [])
    return [t for t in data if (t.get("status") or "").lower() == "pending"]


def is_main_thread_only(task: dict) -> bool:
    """Detect main-thread-only markers in title or description."""
    blob = " ".join(
        str(task.get(k, "") or "") for k in ("title", "description", "notes")
    )
    return bool(MAIN_THREAD_MARKERS.search(blob))


def detect_block_reason(task: dict) -> str | None:
    """Return blocked reason if task should be filtered from dispatch, else None.

    Priority order:
    1. Explicit task.blocked_reason field (hard block, set via CLI)
    2. blocked_until timestamp still in future
    3. Auto-detected from title/description (soft block — caller may
       optionally promote to hard block)
    """
    explicit = (task.get("blocked_reason") or "").strip().lower()
    if explicit:
        # Honor blocked_until expiry (auto-recheck): if blocked_until is in
        # the past, treat block as expired and let task return to pending.
        unblock_at = task.get("blocked_until")
        if unblock_at:
            try:
                deadline = datetime.fromisoformat(str(unblock_at).replace("Z", "+00:00"))
                if deadline.tzinfo is None:
                    deadline = deadline.replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) >= deadline:
                    return None
            except Exception:
                pass
        return explicit

    blob = " ".join(
        str(task.get(k, "") or "") for k in ("title", "description", "notes")
    )
    if SELF_OPTIONAL_PATTERN.search(blob):
        return "self_tagged_optional"
    return None


def is_paper_task(task: dict) -> bool:
    """Paper writing tasks are main-thread-only per CLAUDE.md."""
    blob = " ".join(
        str(task.get(k, "") or "") for k in ("title", "description", "id", "task_type")
    )
    return bool(
        re.search(
            r"paper\s*\d+|paper_|paper/.*\.tex|narrative\s*rewrite|"
            r"vix.sufficiency|paper.synthesis|integrate.*K\d+/K\d+",
            blob,
            re.IGNORECASE,
        )
    )


def categorize(tasks: list[dict]) -> dict:
    agentable = []
    main_thread = []
    blocked = []
    for t in tasks:
        # Block check first — blocked tasks never enter dispatch or main_thread
        # queue (they're surfaced separately so the user/main thread can
        # periodically review and unblock).
        block_reason = detect_block_reason(t)
        if block_reason:
            blocked.append({"task": t, "reason": block_reason})
            continue

        # P1 conservative default: P1 tasks are critical-tier, main-thread owns.
        # Override only via explicit task_type=experiment (agent-runnable K-experiments).
        priority = t.get("priority", 999)
        is_p1 = priority == 1
        explicit_experiment = (t.get("task_type") or "").lower() == "experiment"

        if is_main_thread_only(t) or is_paper_task(t):
            main_thread.append(t)
        elif is_p1 and not explicit_experiment:
            main_thread.append(t)
        else:
            agentable.append(t)

    agentable.sort(key=lambda t: (t.get("priority", 999), t.get("id", "")))
    main_thread.sort(key=lambda t: (t.get("priority", 999), t.get("id", "")))
    blocked.sort(key=lambda b: (b["task"].get("priority", 999), b["task"].get("id", "")))
    return {"agentable": agentable, "main_thread": main_thread, "blocked": blocked}


def _maybe_refill(agentable_count: int, *, auto_refill: bool) -> dict | None:
    """Auto-trigger refill_task_pool.py when agentable < REFILL_FLOOR.

    Returns the refill result dict if refill ran, else None. Refill is
    quiet-on-no-add to avoid log noise in healthy steady state.
    """
    if not auto_refill:
        return None
    if agentable_count >= REFILL_FLOOR:
        return None
    try:
        # Inline import to keep dispatcher importable even if refill script
        # is missing or has import errors.
        sys.path.insert(0, str(ROOT / "scripts"))
        from refill_task_pool import refill as _refill_fn  # type: ignore
        return _refill_fn(target=REFILL_FLOOR - agentable_count, dry_run=False)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def build_report(*, auto_refill: bool = True) -> dict:
    slots = count_active_slots()
    pending = load_pending_tasks()
    cats = categorize(pending)

    refill_result = _maybe_refill(len(cats["agentable"]), auto_refill=auto_refill)
    if refill_result and refill_result.get("added"):
        # Reload after refill so the report shows the fresh tasks
        pending = load_pending_tasks()
        cats = categorize(pending)

    free_slots = max(0, SLOT_CAP - slots["occupied"])
    candidates_to_dispatch = cats["agentable"][:free_slots]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "slot_cap": SLOT_CAP,
        "slot_state": slots,
        "free_slots": free_slots,
        "pending_total": len(pending),
        "pending_agentable": len(cats["agentable"]),
        "pending_main_thread": len(cats["main_thread"]),
        "pending_blocked": len(cats["blocked"]),
        "dispatch_candidates": [
            {
                "id": t.get("id"),
                "priority": t.get("priority"),
                "title": (t.get("title") or t.get("description") or "")[:120],
            }
            for t in candidates_to_dispatch
        ],
        "main_thread_queue_top5": [
            {
                "id": t.get("id"),
                "priority": t.get("priority"),
                "title": (t.get("title") or t.get("description") or "")[:120],
            }
            for t in cats["main_thread"][:5]
        ],
        "refill": refill_result,
        "blocked_tasks": [
            {
                "id": b["task"].get("id"),
                "priority": b["task"].get("priority"),
                "reason": b["reason"],
                "title": (b["task"].get("title") or b["task"].get("description") or "")[:120],
                "blocked_at": b["task"].get("blocked_at"),
                "blocked_until": b["task"].get("blocked_until"),
            }
            for b in cats["blocked"]
        ],
    }


def print_report(report: dict) -> None:
    print(f"[dispatch] generated_at={report['generated_at']}")
    s = report["slot_state"]
    print(
        f"[dispatch] slots: occupied={s['occupied']}/{report['slot_cap']} "
        f"(worktrees={len(s['worktrees'])}, active_agents={len(s['active_agents'])}) "
        f"free={report['free_slots']}"
    )
    print(
        f"[dispatch] pending: total={report['pending_total']} "
        f"agentable={report['pending_agentable']} main_thread={report['pending_main_thread']} "
        f"blocked={report.get('pending_blocked', 0)}"
    )

    if report["dispatch_candidates"]:
        print(f"[dispatch] candidates to dispatch ({len(report['dispatch_candidates'])}):")
        for c in report["dispatch_candidates"]:
            print(f"  - P{c['priority']} {c['id']} :: {c['title']}")
    else:
        print("[dispatch] NO agent dispatch candidates "
              "(slot full or all pending are main-thread-only)")

    if report["main_thread_queue_top5"]:
        print("[dispatch] main-thread queue (top 5):")
        for c in report["main_thread_queue_top5"]:
            print(f"  - P{c['priority']} {c['id']} :: {c['title']}")

    refill = report.get("refill") or {}
    if refill.get("added"):
        print(f"[dispatch] auto-refill: +{refill['added']} tasks {refill.get('added_ids')}")
    elif refill.get("ok") is False:
        print(f"[dispatch] auto-refill error: {refill.get('error') or refill.get('reason')}")

    blocked = report.get("blocked_tasks") or []
    if blocked:
        print(f"[dispatch] blocked ({len(blocked)}):")
        for b in blocked[:8]:
            until = f" until={b['blocked_until']}" if b.get("blocked_until") else ""
            print(f"  - P{b['priority']} {b['id']} reason={b['reason']}{until}")
        if len(blocked) > 8:
            print(f"  ... and {len(blocked) - 8} more")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="只列 candidates，不派工")
    parser.add_argument("--report", action="store_true", help="寫 report 到 dispatch_report_latest.json")
    parser.add_argument("--execute", action="store_true", help="reserved (尚未實作 actual spawn)")
    parser.add_argument("--no-refill", action="store_true",
                        help="skip auto-refill even if agentable < floor (debug only)")
    args = parser.parse_args()

    report = build_report(auto_refill=not args.no_refill)
    print_report(report)

    if args.report:
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
        print(f"[dispatch] report written: {REPORT_PATH}")

    if args.execute:
        print("[dispatch] --execute not yet implemented; main-thread should pick up candidates and dispatch agents (Task tool / claude general-purpose / codex-rescue) per .claude/rules/agent-delegation.md")
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
