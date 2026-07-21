"""R1 dispatch-lanes（2026-07-21）：lane rank 是候選排序的最外層。

出事的形狀：`task_urgency`（2026-07-18 建，急件判定唯一 owner）判得出 boss 急件，
但 `continue_task_dispatch.py` 的排序完全沒 import 它 —— 排序只有 priority +
餓死保護 + 輪替。於是 boss 的 Telegram P1 request_fire 叫醒了 worker，worker
挑的卻是「餓最久的系統 P1」：實測 pending 181、P1 33 個，boss 來源只有 8 個，
新急件在 25 個 generator 自封 P1 後面排隊。

這些測試釘死三件事：
1. lane rank 最外層 —— boss 急件 → time-critical → 其餘（含餓死鎖定）。
2. 餓死保護的 tail-floor reserve 只在 lane head 之後的剩餘 slots 內運作，
   不得把 urgent / time-critical 擠掉。
3. 池內沒有 urgent / time-critical 時，行為與舊排序完全一致（不誤傷排班）。
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import continue_task_dispatch as ctd  # noqa: E402
from continue_task_dispatch import STARVATION_HOURS  # noqa: E402
from volpred.ops.task_urgency import (  # noqa: E402
    LANE_SCHEDULED,
    LANE_TIME_CRITICAL,
    LANE_URGENT,
)

NOW = datetime(2026, 7, 21, 6, 0, tzinfo=timezone.utc)


def _task(task_id: str, *, priority=1, age_hours: float = 0.5, **extra) -> dict:
    task: dict = {
        "id": task_id,
        "priority": priority,
        "task_type": "platform_ops",
        "dispatch_lane": "agent",
        "status": "pending",
        "source": "auto_discovered",
        "created_at": (NOW - timedelta(hours=age_hours)).isoformat(),
    }
    task.update(extra)
    return task


def _env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, tasks: list[dict], cap: int) -> None:
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


def test_boss_urgent_outranks_starved_machine_p1_the_incident_condition(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """本次事故的精確形狀：餓死 4 天的系統 P1 不得排在新鮮 boss 急件之前。

    順序必須是 boss P1 → time-critical event_article（即使只有 P2）→ 餓死系統 P1。
    """
    starved_sys = _task("sys_p1_starved", age_hours=96.0)  # 4 天，遠超 P1 的 6h 線
    boss = _task("assign_boss", source="telegram-999", age_hours=0.2)
    event = _task(
        "event_cpi", priority=2, task_type="event_article",
        source="reader_facing_refill", age_hours=1.0,
    )

    _env(monkeypatch, tmp_path, [starved_sys, boss, event], cap=4)
    report = ctd.build_report(auto_refill=False, now=NOW)

    assert [c["id"] for c in report["dispatch_candidates"]] == [
        "assign_boss", "event_cpi", "sys_p1_starved",
    ]
    assert [c["lane"] for c in report["dispatch_candidates"]] == [
        LANE_URGENT, LANE_TIME_CRITICAL, LANE_SCHEDULED,
    ]
    # 餓死鎖定仍然成立（scheduled lane 有餓死任務），但鎖不住 lane head。
    assert report["starvation"]["locked"] is True
    assert report["lanes"] == {
        "urgent_pending": 1,
        "time_critical_pending": 1,
        "lane_head_task_ids": ["assign_boss", "event_cpi"],
    }


def test_urgent_lane_is_fifo_oldest_first(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """urgent 之間 FIFO：老急件先清（boss 先問的先答）。"""
    newer = _task("boss_new", source="telegram", age_hours=0.1)
    older = _task("boss_old", source="user-assigned", age_hours=3.0)

    _env(monkeypatch, tmp_path, [newer, older], cap=4)
    report = ctd.build_report(auto_refill=False, now=NOW)

    assert [c["id"] for c in report["dispatch_candidates"]] == ["boss_old", "boss_new"]


def test_starved_tail_floor_reserve_cannot_evict_the_lane_head(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """tail-floor reserve 只在 lane head 之後的剩餘 slots 內運作。

    cap=4、boss 急件占 1 席 → scheduled 剩 3 席：3 張餓死 P1 擠滿它們，
    tail-floor 把最後一張換成最餓的 P3 —— 換的是 scheduled 的最後一席，
    boss 急件的第一位不動。
    """
    boss = _task("assign_boss", source="telegram-999", age_hours=0.2)
    p1s = [
        _task(f"p1_{i}", age_hours=STARVATION_HOURS[1] + 10 - i, task_type="member_qa")
        for i in range(3)
    ]
    tail_p3 = _task("dreaming_tail_p3", priority=3, age_hours=STARVATION_HOURS[3] + 12)

    _env(monkeypatch, tmp_path, [boss, *p1s, tail_p3], cap=4)
    report = ctd.build_report(auto_refill=False, now=NOW)

    ids = [c["id"] for c in report["dispatch_candidates"]]
    assert len(ids) == 4
    assert ids[0] == "assign_boss", "reserve 不得劫走 urgent 的第一位"
    assert ids[-1] == "dreaming_tail_p3", "tail band 仍保有 scheduled 的最後一席"
    assert ids[1:3] == ["p1_0", "p1_1"]
    assert report["starvation"]["tail_floor_task_ids"] == ["dreaming_tail_p3"]


def test_lane_head_consumes_slots_before_scheduled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """slot 不夠時 lane head 先吃滿：cap=1 只派 boss 急件，餓死 P1 等下一班。"""
    boss = _task("assign_boss", source="telegram-999", age_hours=0.2)
    starved_sys = _task("sys_p1_starved", age_hours=96.0)

    _env(monkeypatch, tmp_path, [starved_sys, boss], cap=1)
    report = ctd.build_report(auto_refill=False, now=NOW)

    assert [c["id"] for c in report["dispatch_candidates"]] == ["assign_boss"]


def test_no_urgent_no_time_critical_keeps_legacy_ordering(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """誤傷防線：池內全是機器排程時，行為與舊排序完全一致。"""
    fresh_p1 = _task("fresh_p1", age_hours=0.5)
    fresh_p2 = _task("fresh_p2", priority=2, age_hours=0.3, task_type="experiment")

    _env(monkeypatch, tmp_path, [fresh_p2, fresh_p1], cap=4)
    report = ctd.build_report(auto_refill=False, now=NOW)

    assert report["lanes"]["urgent_pending"] == 0
    assert report["lanes"]["time_critical_pending"] == 0
    assert report["lanes"]["lane_head_task_ids"] == []
    assert report["starvation"]["locked"] is False
    assert [c["id"] for c in report["dispatch_candidates"]] == ["fresh_p1", "fresh_p2"]
