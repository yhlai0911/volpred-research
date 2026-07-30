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


def test_retired_pregate_has_no_active_executable_surface() -> None:
    assert not (ROOT / "scripts" / "hourly_dispatch_pregate.py").exists()
    assert (ROOT / "scripts" / "_legacy" / "hourly_dispatch_pregate.py").is_file()


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


def test_observation_ledger_closes_shadow_and_tracks_retirement_window() -> None:
    payload = json.loads(
        (ROOT / "storage" / "ops" / "observation_ledger.json").read_text(
            encoding="utf-8"
        )
    )
    items = {item["id"]: item for item in payload["items"]}
    assert items["pregate_shadow"]["status"] == "decided"
    monitor = items["hourly_pregate_retirement_monitor"]
    assert monitor["status"] == "observing"
    assert monitor["deadline"] == "2026-08-06T19:30:00+08:00"


def test_decision_input_has_no_retired_pregate_fields() -> None:
    parameters = inspect.signature(decision.DecisionInput).parameters
    assert {"pregate_mode", "demand"}.isdisjoint(parameters)
