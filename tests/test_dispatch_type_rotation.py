from __future__ import annotations

import importlib.util
from collections import Counter
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "continue_task_dispatch.py"
SPEC = importlib.util.spec_from_file_location("continue_task_dispatch_module", MODULE_PATH)
assert SPEC and SPEC.loader
dispatch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dispatch)


def _task(task_id: str, task_type: str, priority: int = 1) -> dict:
    return {
        "id": task_id,
        "title": task_id,
        "task_type": task_type,
        "priority": priority,
        "status": "pending",
    }


def test_categorize_prefers_less_recent_types_within_same_priority():
    tasks = [
        _task("exp-1", "experiment", priority=2),
        _task("exp-2", "experiment", priority=2),
        _task("exp-3", "experiment", priority=2),
        _task("exp-4", "experiment", priority=2),
        _task("exp-5", "experiment", priority=2),
        _task("exp-6", "experiment", priority=2),
        _task("trend-1", "trending_repost", priority=2),
        _task("event-1", "event_article", priority=2),
    ]

    recent_counts = Counter({"experiment": 6, "trending_repost": 0, "event_article": 0})
    cats = dispatch.categorize(tasks, recent_type_counts=recent_counts)
    ordered_ids = [t["id"] for t in cats["agentable"]]

    assert ordered_ids[:2] == ["event-1", "trend-1"]
    assert ordered_ids[2:] == ["exp-1", "exp-2", "exp-3", "exp-4", "exp-5", "exp-6"]


def test_categorize_keeps_p1_non_experiment_on_main_thread():
    tasks = [
        _task("event-1", "event_article", priority=1),
        _task("trend-1", "trending_repost", priority=1),
        _task("exp-1", "experiment", priority=1),
    ]

    cats = dispatch.categorize(tasks, recent_type_counts=Counter())

    assert [t["id"] for t in cats["agentable"]] == ["exp-1"]
    assert [t["id"] for t in cats["main_thread"]] == ["event-1", "trend-1"]


def test_build_report_exposes_disambiguated_pending_summary(monkeypatch):
    tasks = [
        _task("platform-1", "platform_ops", priority=3),
        _task("paper-1", "paper_review", priority=3),
        _task("event-1", "event_article", priority=1),
    ]

    monkeypatch.setattr(dispatch, "count_active_slots", lambda: {"worktrees": [], "active_agents": [], "occupied": 0})
    monkeypatch.setattr(dispatch, "load_pending_tasks", lambda: tasks)
    monkeypatch.setattr(dispatch, "load_recent_task_type_counts", lambda limit=10: Counter())
    monkeypatch.setattr(dispatch, "_maybe_refill", lambda *args, **kwargs: None)

    report = dispatch.build_report(auto_refill=False)

    assert report["pending_agentable"] == 2
    assert report["pending_main_thread"] == 1
    assert report["pending_blocked"] == 0
    assert report["pending_summary"] == {
        "agentable": 2,
        "main_thread": 1,
        "blocked": 0,
        "label": "agentable 2 / main_thread 1 / blocked 0",
    }
