"""msg 973 兩欄（已完成（本班）/ 已排程）必須是程式生成且有上限。"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from volpred.ops import report_sections as rs

TAIPEI = ZoneInfo("Asia/Taipei")
OWNER = "hourly-slot-1-deadbeef"
NOW = datetime(2026, 7, 18, 18, 30, tzinfo=TAIPEI)


def _task(tid, *, status="succeeded", by=OWNER, priority=1, title="t", completed_at="2026-07-18T10:00:00+00:00"):
    return {
        "id": tid,
        "title": title,
        "status": status,
        "priority": priority,
        "created_at": "2026-07-18T09:00:00+00:00",
        "completed_at": completed_at,
        "status_history": [{"to": status, "by": by}],
    }


def test_completed_only_counts_this_owner():
    tasks = [_task("mine"), _task("sibling", by="hourly-slot-2-cafe")]
    lines = rs.completed_this_shift(OWNER, tasks=tasks)
    assert len(lines) == 1 and lines[0].startswith("mine — ")


def test_completed_caps_and_reports_overflow():
    tasks = [_task(f"t{i}") for i in range(8)]
    lines = rs.completed_this_shift(OWNER, tasks=tasks)
    assert len(lines) == rs.MAX_ITEMS + 1
    assert lines[-1] == "+3 件"


def test_completed_without_owner_is_empty():
    # 沒有 owner token 就無法歸屬本班 — 寧可空白也不冒認別班的工
    assert rs.completed_this_shift(None, tasks=[_task("x")]) == []


def test_scheduled_merges_jobs_and_pending_with_cap():
    spec = {"session_crons": {"items": [{"id": f"job{i}", "cron": "*/5 * * * *"} for i in range(4)]}}
    tasks = [_task(f"p{i}", status="pending", priority=1, title=f"待辦 {i}") for i in range(6)]
    lines = rs.scheduled_next_24h(NOW, tasks=tasks, spec=spec)
    body = [ln for ln in lines if not ln.startswith("+")]
    assert len(body) <= rs.MAX_ITEMS
    # 兩個來源都要露臉：cron job 不能把 pending 擠光
    assert any("job" in ln for ln in body) and any(" P1 " in ln for ln in body)
    assert lines[-1] == "+3 件 pending P1-P2 待派"


def test_scheduled_skips_out_of_horizon_and_malformed_cron():
    spec = {
        "system_crontab": {
            "items": [
                {"id": "weekly", "cron": "0 9 * * 1"},  # 週一，超過 24h horizon
                {"id": "broken", "cron": "not a cron"},
                {"id": "soon", "cron": "0 * * * *"},
            ]
        }
    }
    lines = rs.scheduled_next_24h(NOW, tasks=[], spec=spec)
    assert len(lines) == 1 and "soon" in lines[0]


def test_pending_eta_is_next_hourly_dispatch_fire():
    shown, _ = rs.pending_hot_tasks(NOW, tasks=[_task("p", status="pending")])
    eta, _label = shown[0]
    assert (eta.hour, eta.minute) == (19, 7)


def test_pending_ignores_p3_and_lower():
    tasks = [_task("p3", status="pending", priority=3)]
    shown, overflow = rs.pending_hot_tasks(NOW, tasks=tasks)
    assert shown == [] and overflow == 0


def _empty_queue(tmp_path, monkeypatch):
    """Point the module at an empty queue file.

    render_sections() takes no tasks argument, so without this it reads the
    live storage/next_tasks.json — the file the supervisor rewrites every few
    minutes. These two tests assert on STRUCTURE (headers present, every line a
    str), which the live queue's contents cannot affect, so the dependency was
    never intentional; it just made the suite read a moving target and forced
    CI to run for every supervisor commit.
    """
    path = tmp_path / "next_tasks.json"
    path.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(rs, "NEXT_TASKS_PATH", path)
    return path


def test_render_sections_never_raises(monkeypatch, tmp_path):
    _empty_queue(tmp_path, monkeypatch)
    monkeypatch.setattr(rs, "scheduled_next_24h", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    out = rs.render_sections(OWNER, now=NOW)
    assert "📗 已完成（本班）" in out and "🗓 已排程" in out
    assert any("讀取失敗" in ln for ln in out)


def test_render_sections_empty_shows_placeholder(monkeypatch, tmp_path):
    _empty_queue(tmp_path, monkeypatch)
    out = rs.render_sections(OWNER, now=NOW)
    assert out[0] == "" and out[1] == "📗 已完成（本班）"
    assert all(isinstance(ln, str) for ln in out)
    # An empty queue must reach the reader as 「無」, not as a blank section.
    assert "　無" in out


@pytest.mark.parametrize("field", ["已完成", "已排程"])
def test_no_cli_flag_for_derived_fields(field):
    # 兩欄刻意沒有 CLI 旗標：可手打就會被手打
    src = (rs.PROJECT_ROOT / "scripts" / "progress_report.py").read_text(encoding="utf-8")
    assert f'--{field}' not in src
    assert "render_sections" in src


def test_long_task_id_squeezes_title_not_the_line():
    long_id = "alert_internal_silent_fallback_" + "a" * 40
    tasks = [_task(long_id, status="pending", title="標題" * 30)]
    shown, _ = rs.pending_hot_tasks(NOW, tasks=tasks)
    label = shown[0][1]
    assert label.startswith(long_id)  # id 保留全長，仍可複製查詢
    assert len(label) - len(long_id) < 25  # 標題被壓，不再把整行撐爆
