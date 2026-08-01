"""Slot budget must be mechanical — regression guard for Telegram msg 596/600."""

import json

import pytest

from scripts import dispatch_slot_budget as slot_budget
from scripts.dispatch_slot_budget import BASE_CAP, DERATE_CAP, SURGE_CAP, budget


@pytest.fixture(autouse=True)
def isolate_live_occupancy(tmp_path, monkeypatch):
    """Cap tests must not inspect developer-only worktrees or agent receipts."""
    monkeypatch.setattr(
        slot_budget, "WORKTREES_DIR", tmp_path / "no-live-worktrees",
    )
    monkeypatch.setattr(
        slot_budget, "AGENTS_DIR", tmp_path / "no-live-agents",
    )
    monkeypatch.setattr(
        slot_budget, "AGENT_JOBS_DIR", tmp_path / "no-agent-jobs",
    )


def _write(tmp_path, tasks, state):
    tasks_path = tmp_path / "next_tasks.json"
    state_path = tmp_path / "dispatch_state.json"
    tasks_path.write_text(json.dumps(tasks))
    state_path.write_text(json.dumps(state))
    return tasks_path, state_path


def test_baseline_when_no_p1_backlog(tmp_path):
    tasks = [{"status": "pending", "priority": 2} for _ in range(9)]
    t, s = _write(tmp_path, tasks, {"auth_blocked": False})
    assert budget(t, s)["cap"] == BASE_CAP


def test_surge_when_p1_backlog(tmp_path):
    tasks = [{"status": "pending", "priority": 1} for _ in range(3)]
    t, s = _write(tmp_path, tasks, {"auth_blocked": False})
    result = budget(t, s)
    assert result["cap"] == SURGE_CAP
    assert result["p1_only_slots"] == SURGE_CAP - BASE_CAP


def test_completed_p1_does_not_count(tmp_path):
    tasks = [{"status": "succeeded", "priority": 1} for _ in range(5)]
    t, s = _write(tmp_path, tasks, {"auth_blocked": False})
    assert budget(t, s)["cap"] == BASE_CAP


def test_auth_block_derates_even_with_p1_backlog(tmp_path):
    tasks = [{"status": "pending", "priority": 1} for _ in range(6)]
    t, s = _write(tmp_path, tasks, {"auth_blocked": True})
    assert budget(t, s)["cap"] == DERATE_CAP


def test_missing_files_fall_back_to_baseline(tmp_path):
    assert budget(tmp_path / "nope.json", tmp_path / "nope2.json")["cap"] == BASE_CAP
