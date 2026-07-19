"""Regression tests for the 2026-07-19 max_slots surge + quota de-rate.

Task `assign_794c4bc2` raised the supervisor pool 2 -> 4 to clear a backlog.
A surge without a brake is how a quota outage gets amplified: each extra slot
spends a ~95K cold-load on a fire that cannot do work. `load_max_slots` is the
single owner of "how many slots exist", so the brake lives there.

Covers:
  * configured value is honoured when nothing is wrong
  * two consecutive quota_blocked completions clamp back to DEFAULT_MAX_SLOTS
  * one success after the streak restores the configured value (self-clearing —
    quota resolves on a clock, unlike latched auth_blocked)
  * a single quota_blocked is not enough to de-rate
  * the de-rate never pushes capacity BELOW a configured value already <= floor
  * unreadable / malformed state is fail-open (never strands the pool)

Run::
    uv run pytest scripts/tests/test_scheduler_max_slots.py -v
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.dispatch_supervisor import scheduler


def _schedules(tmp_path: Path, max_slots) -> Path:
    path = tmp_path / "runtime_schedules.json"
    path.write_text(json.dumps({
        "daemons": [{"id": scheduler.DAEMON_ID, "max_slots": max_slots}]
    }), encoding="utf-8")
    return path


def _state(tmp_path: Path, outcomes) -> Path:
    path = tmp_path / "dispatch_state.json"
    path.write_text(json.dumps({
        "completions": [{"job_id": f"j{i}", "outcome": o} for i, o in enumerate(outcomes)]
    }), encoding="utf-8")
    return path


def _load(tmp_path: Path, *, max_slots, outcomes) -> int:
    return scheduler.load_max_slots(
        schedules_path=_schedules(tmp_path, max_slots),
        state_path=_state(tmp_path, outcomes),
    )


def test_configured_value_honoured_when_healthy(tmp_path):
    assert _load(tmp_path, max_slots=4, outcomes=["success"] * 5) == 4


def test_quota_streak_derates_to_floor(tmp_path):
    got = _load(tmp_path, max_slots=4,
                outcomes=["success", "quota_blocked", "quota_blocked"])
    assert got == scheduler.DEFAULT_MAX_SLOTS


def test_one_success_clears_the_streak(tmp_path):
    # The whole point of the quota class: it resolves on a clock, so recovery
    # must need no human. A single completed fire is proof the window reopened.
    got = _load(tmp_path, max_slots=4,
                outcomes=["quota_blocked", "quota_blocked", "success"])
    assert got == 4


def test_single_quota_block_does_not_derate(tmp_path):
    assert _load(tmp_path, max_slots=4, outcomes=["success", "quota_blocked"]) == 4


def test_derate_never_raises_a_low_configured_value(tmp_path):
    # The clamp is a ceiling reduction, not an assignment: a deliberately small
    # pool must stay small during an outage too.
    got = _load(tmp_path, max_slots=1, outcomes=["quota_blocked", "quota_blocked"])
    assert got == 1


@pytest.mark.parametrize("payload", ["{ not json", json.dumps({"completions": "nope"})])
def test_unreadable_state_is_fail_open(tmp_path, payload):
    state_path = tmp_path / "dispatch_state.json"
    state_path.write_text(payload, encoding="utf-8")
    got = scheduler.load_max_slots(
        schedules_path=_schedules(tmp_path, 4), state_path=state_path,
    )
    assert got == 4


def test_missing_state_file_is_fail_open(tmp_path):
    got = scheduler.load_max_slots(
        schedules_path=_schedules(tmp_path, 4), state_path=tmp_path / "absent.json",
    )
    assert got == 4


def test_canonical_config_parses_and_matches_committed_capacity():
    # Guards the real file: a typo here silently reverts the surge to 2.
    data = json.loads(scheduler.SCHEDULES_PATH.read_text(encoding="utf-8"))
    daemon = next(d for d in data["daemons"] if d["id"] == scheduler.DAEMON_ID)
    assert daemon["max_slots"] == 4
