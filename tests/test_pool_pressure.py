"""drain-first 水位閘（boss Telegram msg 1237, 2026-07-21）。

回歸重點是**latch**與**白名單**：閘門若用瞬時判斷，pending 在閾值邊界抖動時一天
開關數次等於沒關；白名單若擋到 telegram/gmail/老闆指派，急件就死在門外。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from volpred.ops import next_tasks
from volpred.ops.pool_pressure import (
    Admission,
    evaluate_drain_first,
    load_policy,
    pool_admits_new_work,
    pool_snapshot,
    warn_if_over_cap,
)

NOW = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)


def _task(status="pending", created_days_ago=0, completed_days_ago=None, **kw):
    rec = {
        "id": kw.pop("id", f"t{created_days_ago}_{status}_{completed_days_ago}"),
        "status": status,
        "created_at": (NOW - timedelta(days=created_days_ago)).isoformat(),
    }
    if completed_days_ago is not None:
        rec["completed_at"] = (NOW - timedelta(days=completed_days_ago)).isoformat()
    rec.update(kw)
    return rec


@pytest.fixture
def rules(tmp_path):
    p = tmp_path / "rules.json"
    p.write_text(json.dumps({"pending_caps": {"enabled": True, "pending_cap": 10,
                                              "exit_streak_days": 3}}), encoding="utf-8")
    return p


def _pending(n, **kw):
    return [_task(id=f"p{i}", priority=1, **kw) for i in range(n)]


def test_snapshot_excludes_today_from_daily():
    """今天是進行中的部分資料 —— 拿它跟整日完成數比會系統性看起來像淨增，
    退出條件永遠不滿足。"""
    tasks = [_task(created_days_ago=0) for _ in range(50)] + [
        _task(status="succeeded", created_days_ago=1, completed_days_ago=1)
    ]
    snap = pool_snapshot(tasks, now=NOW)
    assert all(row["date"] != NOW.date().isoformat() for row in snap.daily)
    assert snap.daily[0]["created"] == 1 and snap.daily[0]["succeeded"] == 1


def test_snapshot_counts_pending_by_priority():
    tasks = _pending(3) + [_task(id="x", status="succeeded", completed_days_ago=1)]
    snap = pool_snapshot(tasks, now=NOW)
    assert snap.pending == 3
    assert snap.pending_by_priority == {"p1": 3}


def test_gate_blocks_when_over_cap(tmp_path, rules):
    state = tmp_path / "state.json"
    adm = pool_admits_new_work("refill_task_pool", tasks=_pending(11),
                               state_path=state, rules_path=rules, now=NOW)
    assert isinstance(adm, Admission) and not adm.admitted
    assert adm.drain_first and adm.pending == 11
    assert json.loads(state.read_text())["active"] is True


def test_gate_admits_under_cap(tmp_path, rules):
    adm = pool_admits_new_work("refill_task_pool", tasks=_pending(5),
                               state_path=tmp_path / "s.json", rules_path=rules, now=NOW)
    assert adm.admitted and adm.reason == "pool_ok"


def test_unknown_kind_is_gated_not_exempt(tmp_path, rules):
    """新 generator 預設進閘門 —— 漏接的成本是池子繼續長，誤擋只是一次沒補到。"""
    adm = pool_admits_new_work("some_new_generator", tasks=_pending(11),
                               state_path=tmp_path / "s.json", rules_path=rules, now=NOW)
    assert not adm.admitted


def test_reader_facing_is_exempt(tmp_path, rules):
    """time_critical 內容時效過了價值歸零，池深不該擋。"""
    adm = pool_admits_new_work("reader_facing", tasks=_pending(999),
                               state_path=tmp_path / "s.json", rules_path=rules, now=NOW)
    assert adm.admitted and adm.reason.startswith("exempt:")


def test_latch_holds_when_pending_drops_but_throughput_still_negative(tmp_path, rules):
    """pending 掉回閾值下、但吞吐還沒轉正 → 仍不放行。這是 latch 的全部理由。"""
    state = tmp_path / "state.json"
    pool_admits_new_work("diverse_tasks", tasks=_pending(11), state_path=state,
                         rules_path=rules, now=NOW)
    # 淨增仍為正的三天
    tasks = _pending(5) + [_task(id=f"c{d}_{i}", created_days_ago=d)
                           for d in (1, 2, 3) for i in range(4)]
    adm = pool_admits_new_work("diverse_tasks", tasks=tasks, state_path=state,
                               rules_path=rules, now=NOW)
    assert not adm.admitted, "pending 降下來但吞吐未轉正，不該解除 drain-first"


def test_latch_releases_when_both_conditions_met(tmp_path, rules):
    state = tmp_path / "state.json"
    pool_admits_new_work("diverse_tasks", tasks=_pending(11), state_path=state,
                         rules_path=rules, now=NOW)
    tasks = _pending(5)
    for d in (1, 2, 3):  # 每日 succeeded(2) >= created(1)
        tasks.append(_task(id=f"c{d}", created_days_ago=d))
        tasks += [_task(id=f"s{d}_{i}", status="succeeded", created_days_ago=d + 5,
                        completed_days_ago=d) for i in range(2)]
    adm = pool_admits_new_work("diverse_tasks", tasks=tasks, state_path=state,
                               rules_path=rules, now=NOW)
    assert adm.admitted
    persisted = json.loads(state.read_text())
    assert persisted["active"] is False and persisted["last_transition"] == "exited"


def test_exit_needs_every_day_in_streak(tmp_path, rules):
    """「連續 3 日」是每日都要滿足，不是 3 日總和 —— 一天爆量會被總和掩蓋。"""
    tasks = _pending(5)
    tasks += [_task(id=f"c1_{i}", created_days_ago=1) for i in range(9)]
    tasks += [_task(id=f"s1_{i}", status="succeeded", created_days_ago=9,
                    completed_days_ago=1) for i in range(3)]
    for d in (2, 3):
        tasks += [_task(id=f"s{d}_{i}", status="succeeded", created_days_ago=9,
                        completed_days_ago=d) for i in range(3)]
    snap = pool_snapshot(tasks, now=NOW)
    assert not snap.drain_streak_met(3)


def test_disabled_policy_releases_latch(tmp_path):
    rules = tmp_path / "r.json"
    rules.write_text(json.dumps({"pending_caps": {"enabled": False, "pending_cap": 10}}),
                     encoding="utf-8")
    adm = pool_admits_new_work("refill_task_pool", tasks=_pending(999),
                               state_path=tmp_path / "s.json", rules_path=rules, now=NOW)
    assert adm.admitted


def test_load_policy_falls_back_on_broken_config(tmp_path):
    """設定檔壞掉不該讓閘門失效 —— 那正是最需要它的時候。"""
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert load_policy(bad)["pending_cap"] == 80


def test_net_positive_streak():
    tasks = []
    for d in (1, 2, 3):
        tasks += [_task(id=f"c{d}_{i}", created_days_ago=d) for i in range(3)]
    tasks += [_task(id=f"s4_{i}", status="succeeded", created_days_ago=9,
                    completed_days_ago=4) for i in range(2)]
    tasks.append(_task(id="c4", created_days_ago=4))
    assert pool_snapshot(tasks, now=NOW).net_positive_streak == 3


def test_writer_warn_fires_for_machine_source(capsys, monkeypatch, rules):
    monkeypatch.setattr("volpred.ops.pool_pressure.load_policy",
                        lambda *a, **k: {"pending_cap": 10, "enabled": True,
                                         "exit_streak_days": 3})
    fired = warn_if_over_cap({"id": "x", "source": "auto_discovered"}, _pending(11))
    assert fired and "[pool_pressure] WARN" in capsys.readouterr().err


def test_writer_warns_when_pool_pressure_check_crashes(monkeypatch, capsys):
    def _raise(_task, _tasks):
        raise RuntimeError("injected pool-pressure failure")

    monkeypatch.setattr("volpred.ops.pool_pressure.warn_if_over_cap", _raise)

    next_tasks._warn_if_over_pending_cap(
        {"id": "task-1"},
        [{"id": "task-1", "status": "pending"}],
    )

    captured = capsys.readouterr()
    assert "[next_tasks_pool_pressure] WARN" in captured.err
    assert "injected pool-pressure failure" in captured.err


@pytest.mark.parametrize("source", ["user", "telegram", "gmail_inbox_poll",
                                    "user-assigned (Telegram msg 447)"])
def test_writer_warn_silent_for_human_ingress(source, monkeypatch, capsys):
    """老闆指派 / 急件本來就該無視水位，不該被 warn 汙染 log。"""
    monkeypatch.setattr("volpred.ops.pool_pressure.load_policy",
                        lambda *a, **k: {"pending_cap": 10, "enabled": True,
                                         "exit_streak_days": 3})
    assert warn_if_over_cap({"id": "x", "source": source}, _pending(11)) is False
    assert capsys.readouterr().err == ""


def test_evaluate_persist_false_leaves_no_state(tmp_path, rules):
    """體檢是觀測者，不該順手改 latch。"""
    state = tmp_path / "s.json"
    evaluate_drain_first(tasks=_pending(11), state_path=state, rules_path=rules,
                         persist=False, now=NOW)
    assert not state.exists()


# ── 組成 cap：platform_ops share 二層閘（2026-08-05 owner 指令）──────────────


def _mixed_pool(platform_n, article_n):
    rows = [
        _task(id=f"po{i}", priority=2, task_type="platform_ops")
        for i in range(platform_n)
    ]
    rows += [
        _task(id=f"art{i}", priority=2, task_type="daily_article")
        for i in range(article_n)
    ]
    return rows


def test_platform_ops_share_cap_blocks_dreaming_when_pool_is_ops_heavy(
    tmp_path, rules
):
    """總水位正常（8 < cap 10）但 75% 是 platform_ops → dreaming 停產。
    這是 owner 抱怨「pending 幾乎都平台維運」的機械答案：生成端先停。"""
    adm = pool_admits_new_work(
        "dreaming", tasks=_mixed_pool(6, 2),
        state_path=tmp_path / "s.json", rules_path=rules, now=NOW,
    )
    assert not adm.admitted
    assert not adm.drain_first, "組成 cap 不是總水位 latch，兩者語義要分開"
    assert "platform_ops_share" in adm.reason


def test_platform_ops_share_cap_spares_article_generators(tmp_path, rules):
    """同一個 ops-heavy 池，refill（產文章/實驗）必須照常放行 ——
    組成要靠 mission generator 拉回來，全停等於凍結。"""
    adm = pool_admits_new_work(
        "refill_task_pool", tasks=_mixed_pool(6, 2),
        state_path=tmp_path / "s.json", rules_path=rules, now=NOW,
    )
    assert adm.admitted and adm.reason == "pool_ok"


def test_platform_ops_share_cap_admits_dreaming_when_composition_healthy(
    tmp_path, rules
):
    adm = pool_admits_new_work(
        "dreaming", tasks=_mixed_pool(2, 6),
        state_path=tmp_path / "s.json", rules_path=rules, now=NOW,
    )
    assert adm.admitted and adm.reason == "pool_ok"


def test_platform_ops_share_cap_is_configurable(tmp_path):
    """pending_caps.platform_ops_share_cap 覆寫生效（runtime 讀）。"""
    rules_p = tmp_path / "rules.json"
    rules_p.write_text(json.dumps({"pending_caps": {
        "enabled": True, "pending_cap": 10, "exit_streak_days": 3,
        "platform_ops_share_cap": 0.9,
    }}), encoding="utf-8")
    adm = pool_admits_new_work(
        "dreaming", tasks=_mixed_pool(6, 2),
        state_path=tmp_path / "s.json", rules_path=rules_p, now=NOW,
    )
    assert adm.admitted, "share 75% < 覆寫後 cap 90% → 放行"
