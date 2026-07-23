#!/usr/bin/env python3
"""Reconcile docs/boss_direction_recommendations.md against the real task pool.

Why this exists
---------------
The direction doc is prose I hand-write, and boss_report.py pastes it verbatim
into every 4-hourly report. Prose cannot be wrong, so nothing ever caught that
the 2026-06-22 roadmap ("1-2 weeks to P1 MVP") was still being mailed out on
2026-07-18 with zero backing tasks in the pool -- the boss had to ask.

So every roadmap item now carries a binding marker:

    - **P1**: Reader analytics ... <!-- rid:reader-analytics task:assign_1234 -->
    - **P3**: paid tier ...        <!-- rid:paid-tier task:none -->

and this script resolves each `task:` against storage/next_tasks.json. An item
claiming progress with no open task shows up as a finding instead of as prose.

Exit 1 when the doc is stale or a P1/P2 item has no live backing task, so it can
run as a gate. `--json` for machine consumption (boss_report.py section 6).
"""

from __future__ import annotations

import argparse
import fcntl
import json
import re
import sys
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path

from volpred.ops.task_pool_mode import (
    TaskPoolMode,
    load_task_pool_mode_evidence,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOC = PROJECT_ROOT / "docs" / "boss_direction_recommendations.md"
NEXT_TASKS = PROJECT_ROOT / "storage" / "next_tasks.json"
TASK_POOL_MODE = PROJECT_ROOT / "storage" / "ops" / "task_pool_mode.json"

# An item is "live" if a human/agent could still pick it up.
OPEN_STATUSES = {"pending", "claimed", "in_progress"}
# blocked is tracked separately: it is legitimately parked, not silently dropped.
PARKED_STATUSES = {"blocked"}

STALE_AFTER_DAYS = 14
GATED_PRIORITIES = {"P1", "P2"}

MARKER_RE = re.compile(r"<!--\s*rid:(?P<rid>[a-z0-9-]+)\s+task:(?P<task>[A-Za-z0-9_-]+)\s*-->")
PRIORITY_RE = re.compile(r"\*\*(P[1-4])\*\*")
UPDATED_RE = re.compile(r"\*\*Updated\*\*:\s*(\d{4}-\d{2}-\d{2})")


def _load_pool() -> dict[str, dict]:
    """Read the task pool under a shared lock; return id -> task."""
    if not NEXT_TASKS.exists():
        return {}
    with NEXT_TASKS.open("r", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_SH)
        try:
            data = json.load(fh)
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    tasks = data.get("tasks", []) if isinstance(data, dict) else data
    return {t["id"]: t for t in tasks if isinstance(t, dict) and t.get("id")}


def _strip_markup(line: str) -> str:
    text = MARKER_RE.sub("", line)
    text = re.sub(r"^[\s*\-]+", "", text)
    text = re.sub(r"[*`]", "", text)
    return text.strip()


def parse_doc(text: str) -> tuple[date | None, list[dict]]:
    """Pull the Updated date and every marker-bearing roadmap item."""
    updated = None
    m = UPDATED_RE.search(text)
    if m:
        updated = datetime.strptime(m.group(1), "%Y-%m-%d").date()

    items = []
    section = ""
    for line in text.splitlines():
        if line.startswith("## "):
            section = line[3:].strip()
            continue
        marker = MARKER_RE.search(line)
        if not marker:
            continue
        prio = PRIORITY_RE.search(line)
        items.append(
            {
                "rid": marker.group("rid"),
                "task_id": None if marker.group("task") == "none" else marker.group("task"),
                "priority": prio.group(1) if prio else "P3",
                "section": section,
                "text": _strip_markup(line)[:160],
            }
        )
    return updated, items


def resolve(
    items: list[dict],
    pool: dict[str, dict],
    today: date,
    *,
    direct_execution: bool = False,
) -> list[dict]:
    """Attach the real pool status to each item and classify the coverage."""
    resolved = []
    for item in items:
        task = pool.get(item["task_id"]) if item["task_id"] else None
        status = task.get("status") if task else None

        if item["task_id"] is None:
            coverage = "no_task"
        elif task is None:
            # Direct execution intentionally removes legacy queue rows after an
            # exact-byte backup. A marker-bound item is therefore suspended from
            # the queue, not silently lost. `task:none` remains a real gap.
            coverage = "pool_suspended" if direct_execution else "dangling"
        elif status in OPEN_STATUSES:
            coverage = "live"
        elif status in PARKED_STATUSES:
            coverage = "parked"
        else:
            coverage = "closed"  # succeeded/failed -- doc should be updated

        resolved.append({**item, "status": status, "coverage": coverage})
    return resolved


def _execution_context() -> dict:
    """Read and validate the receipt that changes roadmap coverage semantics."""
    if not TASK_POOL_MODE.exists():
        return {
            "enabled": False,
            "mode": "queued_execution",
            "state_sha256": None,
        }

    evidence = load_task_pool_mode_evidence(TASK_POOL_MODE)
    mode: TaskPoolMode = evidence.mode
    context = {
        **asdict(mode),
        "state_sha256": evidence.sha256,
    }
    if mode.enabled and mode.mode == "direct_execution":
        complete_backup_receipt = (
            isinstance(mode.backup_path, str)
            and bool(mode.backup_path)
            and isinstance(mode.backup_sha256, str)
            and re.fullmatch(r"[0-9a-f]{64}", mode.backup_sha256) is not None
            and isinstance(mode.backup_bytes, int)
            and mode.backup_bytes > 0
            and isinstance(mode.backup_task_count, int)
            and mode.backup_task_count > 0
        )
        if not complete_backup_receipt:
            raise ValueError(
                "direct-execution mode lacks a complete backup receipt; "
                "roadmap coverage cannot be suspended safely"
            )
    return context


def audit(today: date | None = None) -> dict:
    today = today or date.today()
    if not DOC.exists():
        return {"ok": False, "error": f"missing {DOC.relative_to(PROJECT_ROOT)}", "items": [], "findings": []}

    execution = _execution_context()
    direct_execution = (
        execution["enabled"] is True
        and execution["mode"] == "direct_execution"
    )
    updated, items = parse_doc(DOC.read_text(encoding="utf-8"))
    resolved = resolve(
        items,
        _load_pool(),
        today,
        direct_execution=direct_execution,
    )

    findings = []
    age_days = (today - updated).days if updated else None
    if updated is None:
        findings.append({"kind": "no_updated_date", "detail": "doc has no **Updated**: YYYY-MM-DD line"})
    elif age_days > STALE_AFTER_DAYS:
        findings.append(
            {
                "kind": "stale_doc",
                "detail": f"last updated {updated} ({age_days}d ago) but mailed to the boss every cycle",
            }
        )

    if not items:
        findings.append(
            {"kind": "unbound_doc", "detail": "no roadmap item carries a <!-- rid:... task:... --> marker"}
        )

    for item in resolved:
        if item["priority"] in GATED_PRIORITIES and item["coverage"] in {"no_task", "dangling"}:
            findings.append(
                {
                    "kind": f"{item['priority'].lower()}_{item['coverage']}",
                    "rid": item["rid"],
                    "detail": f"{item['priority']} '{item['text'][:70]}' has no live task",
                }
            )
        elif item["coverage"] == "closed":
            findings.append(
                {
                    "kind": "closed_but_listed",
                    "rid": item["rid"],
                    "detail": f"'{item['rid']}' backing task is {item['status']} -- update the doc",
                }
            )

    counts: dict[str, int] = {}
    for item in resolved:
        counts[item["coverage"]] = counts.get(item["coverage"], 0) + 1

    return {
        "ok": not findings,
        "doc_updated": updated.isoformat() if updated else None,
        "doc_age_days": age_days,
        "execution": execution,
        "items": resolved,
        "coverage_counts": counts,
        "findings": findings,
    }


def _render(report: dict) -> str:
    if report.get("error"):
        return f"ERROR: {report['error']}"

    icon = {
        "live": "OK  ",
        "parked": "PARK",
        "pool_suspended": "HOLD",
        "no_task": "MISS",
        "dangling": "DANG",
        "closed": "DONE",
    }
    lines = [
        f"Roadmap coverage -- doc updated {report['doc_updated']} ({report['doc_age_days']}d ago)",
        f"  execution mode: {report['execution']['mode']}",
        f"  {report['coverage_counts']}",
        "",
    ]
    section = None
    for item in report["items"]:
        if item["section"] != section:
            section = item["section"]
            lines.append(f"[{section}]")
        status = item["status"] or "-"
        lines.append(f"  {icon.get(item['coverage'], '?')}  {item['priority']}  {item['rid']:<24} {status:<12} {item['text'][:60]}")

    if report["findings"]:
        lines.append("")
        lines.append(f"FINDINGS ({len(report['findings'])}):")
        for f in report["findings"]:
            lines.append(f"  - [{f['kind']}] {f['detail']}")
    else:
        lines.append("\nNo findings -- every gated item has a live backing task.")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true", help="emit JSON")
    ap.add_argument("--strict", action="store_true", help="exit 1 on any finding (gate mode)")
    args = ap.parse_args()

    report = audit()
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else _render(report))

    if report.get("error"):
        return 1
    return 1 if (args.strict and report["findings"]) else 0


if __name__ == "__main__":
    sys.exit(main())
