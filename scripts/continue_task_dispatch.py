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

MAIN_THREAD_MARKERS = re.compile(
    r"main\s*thread|NOT\s*agent|main-thread|主線程",
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
    for t in tasks:
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
    return {"agentable": agentable, "main_thread": main_thread}


def build_report() -> dict:
    slots = count_active_slots()
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
        f"agentable={report['pending_agentable']} main_thread={report['pending_main_thread']}"
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="只列 candidates，不派工")
    parser.add_argument("--report", action="store_true", help="寫 report 到 dispatch_report_latest.json")
    parser.add_argument("--execute", action="store_true", help="reserved (尚未實作 actual spawn)")
    args = parser.parse_args()

    report = build_report()
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
