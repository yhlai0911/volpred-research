"""Starvation guard for the dispatch candidate menu.

2026-07-13 incident: a P1 `member_qa` task sat pending for 17 hours across ~17
hourly fires while the `member_qa_stale` alert emailed the owner an hourly to-do
list. Nothing was broken — the dispatcher listed the task, correctly, as the
top-priority agentable candidate every single hour. But the candidate list was
only ever *advisory*: which task a fire took was the LLM's discretion, and the
diversity rule (rotate away from recently-used task_types) actively pushed
against work that had already been skipped. Priority alone cannot escape that;
a task that loses the rotation once loses it the same way every hour.

The fix makes age — not prose — the thing that forces the issue: past a
per-priority threshold, the candidate menu collapses to the starved tasks only.
These tests pin the behaviour that made the incident possible.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from continue_task_dispatch import (  # noqa: E402
    STARVATION_HOURS,
    find_starved,
    starvation_threshold_hours,
    task_age_hours,
)

NOW = datetime(2026, 7, 13, 0, 0, tzinfo=timezone.utc)


def _task(task_id: str, priority, age_hours: float | None, **extra) -> dict:
    task: dict = {"id": task_id, "priority": priority, "task_type": "member_qa", **extra}
    if age_hours is not None:
        task["created_at"] = (NOW - timedelta(hours=age_hours)).isoformat()
    return task


def test_p1_starves_at_threshold_the_incident_condition() -> None:
    """The exact 2026-07-13 shape: a P1 pending 17h must be flagged starved."""
    starved = find_starved([_task("member_qa_e79a7097_evaluate", 1, 17.1)], now=NOW)

    assert [s["task"]["id"] for s in starved] == ["member_qa_e79a7097_evaluate"]
    assert starved[0]["age_hours"] == pytest.approx(17.1, abs=0.05)
    assert starved[0]["over_by_hours"] > 0


def test_fresh_task_is_not_starved() -> None:
    assert find_starved([_task("fresh", 1, STARVATION_HOURS[1] - 0.5)], now=NOW) == []


def test_priority_leads_lateness_inside_the_starved_set() -> None:
    """A P1 that just crossed its line outranks a P3 that is 47h overdue.

    Sorting the starved set purely by lateness would relocate the starvation
    rather than end it: the long-overdue P3 would take the slot every hour and
    the P1 would keep losing, exactly as before.
    """
    starved = find_starved(
        [
            _task("old_p3", 3, STARVATION_HOURS[3] + 47),
            _task("just_starved_p1", 1, STARVATION_HOURS[1] + 0.2),
        ],
        now=NOW,
    )

    assert [s["task"]["id"] for s in starved] == ["just_starved_p1", "old_p3"]


def test_string_priority_is_coerced() -> None:
    """Agents write "P1" as often as 1; a starving P1 must not hide behind its type."""
    starved = find_starved([_task("string_p1", "P1", STARVATION_HOURS[1] + 1)], now=NOW)

    assert [s["task"]["id"] for s in starved] == ["string_p1"]
    assert starvation_threshold_hours({"priority": "P1"}) == STARVATION_HOURS[1]


def test_unparseable_created_at_is_never_starved_and_never_crashes() -> None:
    """No timestamp means no verdict — the task stays in the normal queue.

    Silently promoting an undated task would let a bad `created_at` monopolise
    every fire; silently dropping it would hide it. It just isn't judged.
    """
    assert find_starved([_task("undated", 1, None)], now=NOW) == []
    assert find_starved([_task("garbage", 1, None, created_at="not-a-date")], now=NOW) == []
    assert task_age_hours({"id": "x", "created_at": "not-a-date"}) is None


def test_lockout_collapses_the_candidate_menu(monkeypatch: pytest.MonkeyPatch) -> None:
    """Starved work is the *only* thing on the menu — diversity cannot route around it.

    This is the mechanical half of the fix. An advisory "please take the oldest
    P1" is what the dispatcher already had, and it is what let the P1 sit for 17h.
    """
    import continue_task_dispatch as ctd

    starving = _task("starving_p1", 1, 17.0)
    fresh = _task("fresh_p2", 2, 0.5, task_type="experiment")

    monkeypatch.setattr(ctd, "count_active_slots", lambda: {"occupied": 0, "worktrees": 0, "active_agents": 0})
    monkeypatch.setattr(ctd, "_maybe_retire_covered_article_tasks", lambda **_kw: None)
    monkeypatch.setattr(ctd, "load_pending_tasks", lambda: [starving, fresh])
    monkeypatch.setattr(ctd, "load_recent_task_type_counts", lambda: None)
    monkeypatch.setattr(ctd, "_maybe_refill", lambda *_a, **_kw: {})
    monkeypatch.setattr(ctd, "_maybe_refill_draft_pool", lambda **_kw: {})

    report = ctd.build_report(auto_refill=False)

    assert report["starvation"]["locked"] is True
    assert [c["id"] for c in report["dispatch_candidates"]] == ["starving_p1"]
    assert report["dispatch_candidates"][0]["starved"] is True
