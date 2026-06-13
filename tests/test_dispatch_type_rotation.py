from __future__ import annotations

import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path
from types import ModuleType

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


def test_maybe_refill_uses_live_agentable_count_not_raw_added(monkeypatch):
    """Regression: 2026-06-08 pool exhaustion.

    Stage-1 diverse_gen may add only main-thread-only paper_review tasks.
    Those count as `added`, but they do not raise the live agentable pool.
    `_maybe_refill` must continue into later stages based on refreshed
    agentable pending count, otherwise research backlog never fires.
    """
    diverse_mod = ModuleType("generate_diverse_tasks")
    article_mod = ModuleType("refill_task_pool")
    research_mod = ModuleType("generate_research_backlog")
    event_mod = ModuleType("refill_reader_facing_pool")

    diverse_mod.generate = lambda dry_run=False: {
        "ok": True,
        "added": 2,
        "added_ids": ["paper_review_mile_a", "paper_review_mile_b"],
        "by_type": {"paper_review": 2},
    }
    event_mod.refill_event_candidates = lambda horizon_days=14: {"added": []}
    article_mod.refill = lambda target, dry_run=False: {"ok": True, "added": 0, "reason": "no_new_candidates_passing_filter"}
    research_mod.generate = lambda dry_run=False, max_new=0: {
        "ok": True,
        "added": 1,
        "added_ids": ["K1302"],
    }

    monkeypatch.setitem(sys.modules, "generate_diverse_tasks", diverse_mod)
    monkeypatch.setitem(sys.modules, "refill_reader_facing_pool", event_mod)
    monkeypatch.setitem(sys.modules, "refill_task_pool", article_mod)
    monkeypatch.setitem(sys.modules, "generate_research_backlog", research_mod)

    counts = iter([0, 0, 1])
    monkeypatch.setattr(dispatch, "_current_agentable_count", lambda: next(counts))

    result = dispatch._maybe_refill(0, auto_refill=True)

    assert result["added"] == 3
    assert "K1302" in result["added_ids"]
    assert result["by_type"]["paper_review"] == 2
    assert result["by_type"]["experiment_autonomous"] == 1


def test_maybe_refill_runs_event_refill_before_article_backfill(monkeypatch):
    diverse_mod = ModuleType("generate_diverse_tasks")
    article_mod = ModuleType("refill_task_pool")
    research_mod = ModuleType("generate_research_backlog")
    event_mod = ModuleType("refill_reader_facing_pool")

    diverse_mod.generate = lambda dry_run=False: {"ok": True, "added": 0, "added_ids": [], "by_type": {}}
    event_mod.refill_event_candidates = lambda horizon_days=14: {
        "added": ["event_article_cpi_us_2026-06-11_tminus2"]
    }
    article_mod.refill = lambda target, dry_run=False: {"ok": True, "added": 0, "reason": "no_new_candidates_passing_filter"}
    research_mod.generate = lambda dry_run=False, max_new=0: {"ok": True, "added": 0}

    monkeypatch.setitem(sys.modules, "generate_diverse_tasks", diverse_mod)
    monkeypatch.setitem(sys.modules, "refill_reader_facing_pool", event_mod)
    monkeypatch.setitem(sys.modules, "refill_task_pool", article_mod)
    monkeypatch.setitem(sys.modules, "generate_research_backlog", research_mod)

    counts = iter([0, 1, 1])
    monkeypatch.setattr(dispatch, "_current_agentable_count", lambda: next(counts))

    result = dispatch._maybe_refill(0, auto_refill=True)

    assert result["by_type"]["event_article"] == 1
    assert "event_article_cpi_us_2026-06-11_tminus2" in result["added_ids"]


def test_maybe_refill_materializes_pool_dry_diagnostic(monkeypatch, tmp_path):
    """Regression: pool empty + every refill source dry must not no-op.

    2026-06-13 hourly handoff showed pending=0 while diverse/event/article/
    research refill all added zero. The dispatcher used to return
    `no_new_signal`, leaving the next hourly tick with nothing to claim.
    """
    diverse_mod = ModuleType("generate_diverse_tasks")
    article_mod = ModuleType("refill_task_pool")
    research_mod = ModuleType("generate_research_backlog")
    event_mod = ModuleType("refill_reader_facing_pool")

    diverse_mod.generate = lambda dry_run=False: {"ok": True, "added": 0, "added_ids": [], "by_type": {}}
    event_mod.refill_event_candidates = lambda horizon_days=14: {"added": []}
    article_mod.refill = lambda target, dry_run=False: {"ok": True, "added": 0, "reason": "no_new_candidates_passing_filter"}
    research_mod.generate = lambda dry_run=False, max_new=0: {
        "ok": True,
        "added": 0,
        "reason": "all_already_covered_or_in_progress",
    }

    next_tasks = tmp_path / "next_tasks.json"
    next_tasks.write_text("[]\n", encoding="utf-8")
    monkeypatch.setattr(dispatch, "NEXT_TASKS", next_tasks)
    monkeypatch.setitem(sys.modules, "generate_diverse_tasks", diverse_mod)
    monkeypatch.setitem(sys.modules, "refill_reader_facing_pool", event_mod)
    monkeypatch.setitem(sys.modules, "refill_task_pool", article_mod)
    monkeypatch.setitem(sys.modules, "generate_research_backlog", research_mod)
    monkeypatch.setattr(dispatch, "_current_agentable_count", lambda: 0)

    result = dispatch._maybe_refill(0, auto_refill=True)

    assert result["added"] == 1
    assert result["by_type"]["platform_ops"] == 1
    assert result["added_ids"][0].startswith("platform_ops_dispatch_pool_dry_diagnostic_")

    tasks = json.loads(next_tasks.read_text(encoding="utf-8"))
    assert tasks[0]["task_type"] == "platform_ops"
    assert tasks[0]["status"] == "pending"
