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


def test_lockout_collapses_the_candidate_menu(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Starved work is the *only* thing on the menu — diversity cannot route around it.

    This is the mechanical half of the fix. An advisory "please take the oldest
    P1" is what the dispatcher already had, and it is what let the P1 sit for 17h.
    """
    import continue_task_dispatch as ctd

    starving = _task("starving_p1", 1, 17.0)
    fresh = _task("fresh_p2", 2, 0.5, task_type="experiment")

    monkeypatch.setattr(ctd, "count_active_slots", lambda: {"occupied": 0, "worktrees": 0, "active_agents": 0})
    monkeypatch.setattr(ctd._slot_budget, "budget", lambda: {"cap": 4})
    monkeypatch.setattr(ctd, "NEXT_TASKS", tmp_path / "next_tasks.json")
    monkeypatch.setattr(ctd, "_maybe_retire_covered_article_tasks", lambda **_kw: None)
    monkeypatch.setattr(ctd, "load_pending_tasks", lambda: [starving, fresh])
    monkeypatch.setattr(ctd, "load_recent_task_type_counts", lambda: None)
    monkeypatch.setattr(ctd, "_maybe_refill", lambda *_a, **_kw: {})
    monkeypatch.setattr(ctd, "_maybe_refill_draft_pool", lambda **_kw: {})

    # Pin the clock to the same instant the fixtures are dated against. On the wall
    # clock `fresh_p2` keeps ageing, and once it drifts past its own 24h threshold it
    # joins the starved set — the assertion below then fails for a reason that has
    # nothing to do with the lockout it is pinning.
    report = ctd.build_report(auto_refill=False, now=NOW)

    assert report["starvation"]["locked"] is True
    assert [c["id"] for c in report["dispatch_candidates"]] == ["starving_p1"]
    assert report["dispatch_candidates"][0]["starved"] is True


def test_ci_incident_preempts_starvation_but_ordinary_fresh_work_stays_excluded(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A generic request_fire must actually offer its fresh CI P1 to the worker."""
    import continue_task_dispatch as ctd

    starving = _task("starving_p1", 1, 17.0)
    ci_red = _task(
        "ci-red-123",
        1,
        0.1,
        task_type="platform_ops",
        dispatch_lane="agent",
        dispatch_preempt=True,
    )
    ordinary = _task("fresh_p1", 1, 0.1, task_type="platform_ops", dispatch_lane="agent")

    monkeypatch.setattr(
        ctd,
        "count_active_slots",
        lambda: {"occupied": 0, "worktrees": 0, "active_agents": 0},
    )
    monkeypatch.setattr(ctd._slot_budget, "budget", lambda: {"cap": 2})
    monkeypatch.setattr(ctd, "NEXT_TASKS", tmp_path / "next_tasks.json")
    monkeypatch.setattr(ctd, "_maybe_retire_covered_article_tasks", lambda **_kw: None)
    monkeypatch.setattr(ctd, "load_pending_tasks", lambda: [ordinary, starving, ci_red])
    monkeypatch.setattr(ctd, "load_recent_task_type_counts", lambda: None)
    monkeypatch.setattr(ctd, "_maybe_refill", lambda *_a, **_kw: {})
    monkeypatch.setattr(ctd, "_maybe_refill_draft_pool", lambda **_kw: {})

    report = ctd.build_report(auto_refill=False, now=NOW)

    assert report["starvation"]["locked"] is True
    assert report["starvation"]["incident_preempt_count"] == 1
    assert [item["id"] for item in report["dispatch_candidates"]] == [
        "ci-red-123",
        "starving_p1",
    ]
    assert report["dispatch_candidates"][0]["dispatch_preempt"] is True


def test_ci_incident_preempts_normal_rotation_when_only_one_slot_is_free(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import continue_task_dispatch as ctd

    ordinary = _task(
        "aaa-ordinary-p1",
        1,
        0.1,
        task_type="platform_ops",
        dispatch_lane="agent",
    )
    ci_red = _task(
        "zzz-ci-red",
        1,
        0.1,
        task_type="platform_ops",
        dispatch_lane="agent",
        dispatch_preempt=True,
    )
    monkeypatch.setattr(
        ctd,
        "count_active_slots",
        lambda: {"occupied": 0, "worktrees": 0, "active_agents": 0},
    )
    monkeypatch.setattr(ctd._slot_budget, "budget", lambda: {"cap": 1})
    monkeypatch.setattr(ctd, "NEXT_TASKS", tmp_path / "next_tasks.json")
    monkeypatch.setattr(ctd, "_maybe_retire_covered_article_tasks", lambda **_kw: None)
    monkeypatch.setattr(ctd, "load_pending_tasks", lambda: [ordinary, ci_red])
    monkeypatch.setattr(ctd, "load_recent_task_type_counts", lambda: None)
    monkeypatch.setattr(ctd, "_maybe_refill", lambda *_a, **_kw: {})
    monkeypatch.setattr(ctd, "_maybe_refill_draft_pool", lambda **_kw: {})

    report = ctd.build_report(auto_refill=False, now=NOW)

    assert report["starvation"]["locked"] is False
    assert [item["id"] for item in report["dispatch_candidates"]] == ["zzz-ci-red"]


def _dispatch_env(monkeypatch, tmp_path, tasks, cap: int) -> None:
    import continue_task_dispatch as ctd

    monkeypatch.setattr(
        ctd, "count_active_slots", lambda: {"occupied": 0, "worktrees": 0, "active_agents": 0}
    )
    monkeypatch.setattr(ctd._slot_budget, "budget", lambda: {"cap": cap})
    monkeypatch.setattr(ctd, "NEXT_TASKS", tmp_path / "next_tasks.json")
    monkeypatch.setattr(ctd, "_maybe_retire_covered_article_tasks", lambda **_kw: None)
    monkeypatch.setattr(ctd, "load_pending_tasks", lambda: tasks)
    monkeypatch.setattr(ctd, "load_recent_task_type_counts", lambda: None)
    monkeypatch.setattr(ctd, "_maybe_refill", lambda *_a, **_kw: {})
    monkeypatch.setattr(ctd, "_maybe_refill_draft_pool", lambda **_kw: {})


def test_starved_tail_band_gets_one_reserved_slot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The lowest starved band must reach the menu even when P1s outnumber the slots.

    The 2026-07-21 shape (boss telegram-1224): 20 dreaming-derived P3 rows, the
    oldest 84h past its 72h line, queued behind 37 pending P1. Priority-first
    ordering plus the free_slots truncation meant the P3 band had no arrival rate
    at which it could ever be dispatched: starved in the report, unreachable in
    practice, so the critical findings those rows owned stayed red forever.
    """
    import continue_task_dispatch as ctd

    p1s = [_task(f"p1_{i}", 1, STARVATION_HOURS[1] + 10 - i) for i in range(4)]
    dreaming = _task("dreaming_persistent_alert", 3, STARVATION_HOURS[3] + 12)
    dreaming_fresher = _task("dreaming_other", 3, STARVATION_HOURS[3] + 1)

    _dispatch_env(monkeypatch, tmp_path, [*p1s, dreaming_fresher, dreaming], cap=4)
    report = ctd.build_report(auto_refill=False, now=NOW)

    ids = [c["id"] for c in report["dispatch_candidates"]]
    assert len(ids) == 4
    # One seat only, and it goes to the most-overdue row of the tail band.
    assert ids[-1] == "dreaming_persistent_alert"
    assert ids[:3] == ["p1_0", "p1_1", "p1_2"]
    assert report["starvation"]["tail_floor_task_ids"] == ["dreaming_persistent_alert"]


def test_tail_floor_never_takes_the_only_free_slot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """With one slot the top band keeps it - the floor must not resurrect P1 starvation."""
    import continue_task_dispatch as ctd

    _dispatch_env(
        monkeypatch,
        tmp_path,
        [
            _task("p1_only", 1, STARVATION_HOURS[1] + 5),
            _task("dreaming_p3", 3, STARVATION_HOURS[3] + 40),
        ],
        cap=1,
    )
    report = ctd.build_report(auto_refill=False, now=NOW)

    assert [c["id"] for c in report["dispatch_candidates"]] == ["p1_only"]
    assert report["starvation"]["tail_floor_task_ids"] == []


def test_tail_floor_does_not_displace_an_incident_preempt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The reserved seat comes out of ordinary starved work, never the preempt lane."""
    import continue_task_dispatch as ctd

    _dispatch_env(
        monkeypatch,
        tmp_path,
        [
            _task(
                "ci_red",
                1,
                0.1,
                task_type="platform_ops",
                dispatch_lane="agent",
                dispatch_preempt=True,
            ),
            _task("starving_p1", 1, STARVATION_HOURS[1] + 5),
            _task("dreaming_p3", 3, STARVATION_HOURS[3] + 40),
        ],
        cap=2,
    )
    report = ctd.build_report(auto_refill=False, now=NOW)

    ids = [c["id"] for c in report["dispatch_candidates"]]
    assert ids[0] == "ci_red"
    assert ids[1] == "dreaming_p3"
    assert report["starvation"]["tail_floor_task_ids"] == ["dreaming_p3"]


def test_no_floor_when_the_tail_band_is_already_represented(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import continue_task_dispatch as ctd

    _dispatch_env(
        monkeypatch,
        tmp_path,
        [
            _task("p1_a", 1, STARVATION_HOURS[1] + 5),
            _task("dreaming_p3", 3, STARVATION_HOURS[3] + 40),
        ],
        cap=4,
    )
    report = ctd.build_report(auto_refill=False, now=NOW)

    assert [c["id"] for c in report["dispatch_candidates"]] == ["p1_a", "dreaming_p3"]
    assert report["starvation"]["tail_floor_task_ids"] == []
