"""Regression tests for fail-closed single-slot producer custody.

Shared launchd coalition custody cannot distinguish concurrently-started
producers. Until per-fire kernel isolation exists, `load_max_slots` must return
one regardless of stale surge configuration or state readability.

Covers:
  * stale configured values cannot re-enable unsafe concurrency
  * completion history cannot override the custody ceiling
  * unreadable / missing state remains fail-closed
  * canonical production config declares the same single-slot contract

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


def test_stale_surged_value_fails_closed_when_healthy(tmp_path):
    assert _load(tmp_path, max_slots=4, outcomes=["success"] * 5) == 1


def test_quota_streak_stays_at_custody_floor(tmp_path):
    got = _load(tmp_path, max_slots=4,
                outcomes=["success", "quota_blocked", "quota_blocked"])
    assert got == 1


def test_success_cannot_restore_unsafe_concurrency(tmp_path):
    got = _load(tmp_path, max_slots=4,
                outcomes=["quota_blocked", "quota_blocked", "success"])
    assert got == 1


def test_single_quota_block_remains_single_slot(tmp_path):
    assert _load(tmp_path, max_slots=4, outcomes=["success", "quota_blocked"]) == 1


def test_derate_never_raises_a_low_configured_value(tmp_path):
    # The clamp is a ceiling reduction, not an assignment: a deliberately small
    # pool must stay small during an outage too.
    got = _load(tmp_path, max_slots=1, outcomes=["quota_blocked", "quota_blocked"])
    assert got == 1


@pytest.mark.parametrize("payload", ["{ not json", json.dumps({"completions": "nope"})])
def test_unreadable_state_is_fail_closed(tmp_path, payload):
    state_path = tmp_path / "dispatch_state.json"
    state_path.write_text(payload, encoding="utf-8")
    got = scheduler.load_max_slots(
        schedules_path=_schedules(tmp_path, 4), state_path=state_path,
    )
    assert got == 1


def test_missing_state_file_is_fail_closed(tmp_path):
    got = scheduler.load_max_slots(
        schedules_path=_schedules(tmp_path, 4), state_path=tmp_path / "absent.json",
    )
    assert got == 1


def test_canonical_config_parses_and_matches_committed_capacity():
    # Guards the real file: drift here would contradict kernel custody safety.
    data = json.loads(scheduler.SCHEDULES_PATH.read_text(encoding="utf-8"))
    daemon = next(d for d in data["daemons"] if d["id"] == scheduler.DAEMON_ID)
    assert daemon["max_slots"] == 1
    assert daemon["producer_custody"]["mode"] == scheduler.SHARED_LAUNCHD_COALITION_MODE
    assert daemon["writer_isolation"]["max_active"] == 1
