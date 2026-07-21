"""Regression tests for _promote_starved_article_tasks (2026-07-15 owner order).

Incident: 2026-07-14 evening — releasable drafts hit 0 while six pending
daily_article tasks sat at P3/P4 in next_tasks.json. `_draft_pool_deficit()`
counted them as in-flight stock (deficit=0, refill idle), but every hourly
dispatch picked ops P1/P2 instead, so the article pipeline starved all night
and publishing missed every slot after 16:00. Owner correction: 「你要補滿文章
補到最低門檻 不是一篇一篇補」 — a dry releasable pool must batch-promote the
starved tasks to P1, to the floor, in one pass.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "src"))

_spec = importlib.util.spec_from_file_location(
    "continue_task_dispatch", REPO / "scripts" / "continue_task_dispatch.py"
)
ctd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ctd)


def _task(tid: str, *, task_type: str = "daily_article", status: str = "pending", priority: int = 4) -> dict:
    return {"id": tid, "task_type": task_type, "status": status, "priority": priority, "title": tid}


def _write(tmp_path: Path, tasks: list[dict]) -> Path:
    p = tmp_path / "next_tasks.json"
    p.write_text(json.dumps(tasks, ensure_ascii=False), encoding="utf-8")
    return p


def _read(p: Path) -> list[dict]:
    return json.loads(p.read_text(encoding="utf-8"))


def test_incident_regression_batch_promotes_all_starved_articles(tmp_path, monkeypatch):
    """The exact 2026-07-14 shape: 6 pending P3/P4 article tasks -> ALL promoted in one call."""
    tasks = [_task(f"a{i}", priority=3 if i == 0 else 4) for i in range(6)]
    p = _write(tmp_path, tasks)
    monkeypatch.setattr(ctd, "NEXT_TASKS", p)

    promoted = ctd._promote_starved_article_tasks(ctd.DRAFT_POOL_FLOOR)

    assert promoted == 6
    after = _read(p)
    assert all(t["priority"] == 1 for t in after)
    assert all("auto-promoted" in (t.get("priority_note") or "") for t in after)


def test_promotion_respects_limit_and_skips_non_targets(tmp_path, monkeypatch):
    tasks = [
        _task("art1", priority=4),
        _task("art2", priority=3),
        _task("already_p1", priority=1),                      # untouched: already P1
        _task("ops", task_type="platform_ops", priority=4),   # untouched: not an article
        _task("done", status="succeeded", priority=4),        # untouched: terminal
        _task("art3", priority=4),
    ]
    p = _write(tmp_path, tasks)
    monkeypatch.setattr(ctd, "NEXT_TASKS", p)

    promoted = ctd._promote_starved_article_tasks(2)

    after = {t["id"]: t for t in _read(p)}
    assert promoted == 2
    assert after["art1"]["priority"] == 1
    assert after["art2"]["priority"] == 1
    assert after["art3"]["priority"] == 4  # limit reached before it
    assert after["ops"]["priority"] == 4
    assert after["done"]["priority"] == 4
    assert after["already_p1"].get("priority_note") is None


def test_no_pending_articles_promotes_nothing_and_leaves_file_untouched(tmp_path, monkeypatch):
    tasks = [_task("ops", task_type="platform_ops", priority=4)]
    p = _write(tmp_path, tasks)
    before = p.read_text(encoding="utf-8")
    monkeypatch.setattr(ctd, "NEXT_TASKS", p)

    assert ctd._promote_starved_article_tasks(6) == 0
    assert p.read_text(encoding="utf-8") == before


def test_missing_file_fails_open(tmp_path, monkeypatch):
    monkeypatch.setattr(ctd, "NEXT_TASKS", tmp_path / "nope.json")
    assert ctd._promote_starved_article_tasks(6) == 0


def test_promotion_is_deliberate_exception_to_machine_p1_clamp(tmp_path, monkeypatch):
    """Pin (2026-07-21 dispatch-lanes absorb): this promote path must KEEP writing
    P1 for machine-source tasks. The admission clamp
    (clamp_machine_priority_inflation) governs generators self-declaring P1 at
    creation; this actuator elevates AFTER measuring releasable==0 live, which is
    exactly the kind of real urgency the clamp exists to protect. If someone
    'absorbs' this write into append_task_record, the clamp would immediately cap
    the promotion back to P2 and drought escalation dies — this test fails first.
    """
    tasks = [
        {**_task("machine_art", priority=4), "source": "auto_discovered"},
        {**_task("emergency_art", priority=2), "source": "auto_publish_drought_emergency"},
    ]
    p = _write(tmp_path, tasks)
    monkeypatch.setattr(ctd, "NEXT_TASKS", p)

    promoted = ctd._promote_starved_article_tasks(ctd.DRAFT_POOL_FLOOR)

    assert promoted == 2
    after = {t["id"]: t for t in _read(p)}
    for tid in ("machine_art", "emergency_art"):
        assert after[tid]["priority"] == 1, "promote must not be routed through the admission clamp"
        assert "priority_capped_from" not in after[tid]
        assert "auto-promoted" in after[tid]["priority_note"]
