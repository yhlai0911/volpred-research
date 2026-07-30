"""H4-4 regression: the heuristic pregate has no formal dispatch authority.

The historical evaluator and its append-only log remain available to explain
the retirement decision.  Operations Core must never import or execute it on
the scheduler fire path again.
"""
from __future__ import annotations

import inspect
import json
from pathlib import Path

from scripts.dispatch_supervisor import decision, scheduler

ROOT = Path(__file__).resolve().parents[2]


def test_scheduler_tick_has_no_pregate_execution_edge() -> None:
    source = inspect.getsource(scheduler._tick_once)
    assert "_run_pregate" not in source
    assert "load_pregate_config" not in source
    assert "pregate_skip" not in source


def test_canonical_schedule_has_no_pregate_authority() -> None:
    payload = json.loads(
        (ROOT / "config" / "runtime_schedules.json").read_text(
            encoding="utf-8"
        )
    )
    row = next(
        item
        for item in payload["cron_jobs"]
        if item["id"] == "volpred-hourly-dispatch"
    )
    assert row["status"] == "retired"
    assert "pregate" not in row
    assert "pregate" not in row["description"].lower()


def test_legacy_pregate_receipt_fields_are_observational_only() -> None:
    inp = decision.DecisionInput(
        auth_blocked=False,
        active_slots=0,
        capacity=1,
        quota_derated=False,
        last_fire_known=True,
        due=True,
        prev_fire="2026-07-30T10:07:00",
        fire_request=None,
        pregate_mode="enforce",
        demand={"pregate_skip": True},
    )
    verdict = decision.decide(inp)
    assert (verdict.action, verdict.reason, verdict.fire_reason) == (
        "fire",
        "due",
        "cron",
    )
