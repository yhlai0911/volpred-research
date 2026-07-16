"""storage/ops/tasks/ is receipts-only — the single-gateway invariant.

docs/refactor_plan_single_gateway_task_system.md (2026-07-16): `volpred ops
assign` used to write queued TaskRecords into storage/ops/tasks/, a queue no
dispatcher consumes. 16 tasks were silently black-holed over five days before
the 2026-07-16 migration. The only pending queue is storage/next_tasks.json.

This test is the sole enforcement owner of that invariant (anti-stacking: do
not add a second watchdog). It fails if ANY record under storage/ops/tasks/
carries a non-terminal status — i.e. someone re-opened a write path that
enqueues work where no consumer exists.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TASKS_DIR = REPO_ROOT / "storage" / "ops" / "tasks"

# Anything that still expects execution. awaiting_* is non-terminal by the
# passive-terminal rule (memory feedback_audit_no_passive_terminal).
NON_TERMINAL = {
    "queued",
    "claimed",
    "running",
    "awaiting_approval",
    "awaiting_retry",
    "pending",
}


def test_ops_tasks_dir_contains_no_pending_work() -> None:
    if not TASKS_DIR.is_dir():
        return  # nothing to assert on a fresh checkout
    offenders: list[str] = []
    for path in sorted(TASKS_DIR.glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue  # silent-ok: unreadable receipt is not pending work; this gate only asserts queue emptiness
        status = str(record.get("status") or "").strip().lower()
        if status in NON_TERMINAL:
            offenders.append(f"{path.name}: status={status}")
    assert not offenders, (
        "storage/ops/tasks/ is receipts-only (audit trail); found records that "
        "still expect execution — no dispatcher consumes this directory, so "
        "they would be silently black-holed. Route new work through "
        "storage/next_tasks.json (`volpred ops assign` already does). "
        f"Offenders: {offenders}"
    )
