"""急件（urgent）與一般排程的分離 —— boss Telegram msg 981, 2026-07-18。

Boss directive：「急件和一般排程應該要分開。急件就不進入排班直接派工，一般排程
才進入排班。」

出事的形狀（兩處，缺一不可）：

1. **ingest 端沒接線**。`request_fire()` 這條 out-of-band 立即派工路徑早就存在，
   email (`gmail_inbox_poll.py:754`) 與 CI red (`check_alerts.py:1168`) 都接上
   了，只有 Telegram 沒有 —— Telegram 進來的 P1 只 append 進 next_tasks.json 就
   結束，等下一班 hourly cron。

2. **派工端判定漏接**。PHASE A0 的過濾條件是列舉 task_type
   `(event_article, trending_repost, daily_digest)` 加 `source == 'user'`。
   Telegram 建出的 P1 是 `task_type=platform_ops` / `source=telegram`，兩條都不
   中，所以連被 A0 看到的資格都沒有。

實例：`assign_998ad2be`（source=telegram，A0 抓不到）與 `assign_33a9151f`
（source=user，抓得到但排在別人後面）16:49/17:42 建單，18:06 兩張都還 pending；
17:08 那班跑的是 K1730（P3 研究）。

這些測試把兩處都釘死，並且釘住「不要誤放行」那一半 —— 判定放寬最怕的是把一般
排程也當成急件，那等於取消排班。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from volpred.ops import next_tasks as nt  # noqa: E402
from volpred.ops.task_urgency import (  # noqa: E402
    LANE_SCHEDULED,
    LANE_TIME_CRITICAL,
    LANE_URGENT,
    classify,
    dispatch_lane,
    is_urgent,
    is_urgent_source,
)


def _task(task_id: str, **extra) -> dict:
    task = {
        "id": task_id,
        "task_type": "platform_ops",
        "priority": 1,
        "status": "pending",
        "source": "telegram",
        "created_at": "2026-07-18T08:47:16+00:00",
    }
    task.update(extra)
    return task


# --- 1. 判定：source + priority，不列舉 task_type -----------------------------

def test_telegram_p1_is_urgent_the_incident_condition() -> None:
    """本次事故的精確條件：source=telegram / task_type=platform_ops / P1。"""
    assert classify(_task("assign_998ad2be")) == LANE_URGENT
    assert is_urgent(_task("assign_998ad2be")) is True


def test_old_a0_filter_would_have_missed_it() -> None:
    """釘住回歸方向：舊的 task_type 列舉 + source=='user' 判不出這張單。"""
    task = _task("assign_998ad2be")
    old_hit = (
        task["task_type"] in ("event_article", "trending_repost", "daily_digest")
        or task["source"] == "user"
    )
    assert old_hit is False, "舊條件若也命中，這個測試就失去意義"
    assert is_urgent(task) is True


@pytest.mark.parametrize("source", [
    "telegram", "user", "user-assigned", "owner-telegram-749",
    "boss-telegram-msg110", "user-assigned (Telegram msg 447)",
    "telegram_remediation", "boss_directive_email_reply",
])
def test_human_ingress_source_variants_all_urgent(source: str) -> None:
    """source 是自由字串，歷史上人手寫過一堆變體 —— 全部都得認得。"""
    assert is_urgent_source(source) is True
    assert classify(_task("t", source=source)) == LANE_URGENT


@pytest.mark.parametrize("source", [
    "reader_facing_refill", "auto_discovered", "internal_alert_remediation_router",
    "gmail_inbox_poll", "scheduled", "agent", "compute_queue_followup",
    "event_expander", "hourly_dispatch", None, 123,
])
def test_machine_sources_are_not_urgent(source) -> None:
    """誤放行防線：機器 source 不得被當急件（否則等於取消排班）。"""
    assert is_urgent_source(source) is False
    assert classify(_task("t", source=source)) != LANE_URGENT


def test_token_match_not_substring() -> None:
    """token 比對而非 substring —— `router` 不得因為含 `oute` 之類而誤命中。"""
    assert is_urgent_source("internal_alert_remediation_router") is False
    assert is_urgent_source("browser_agent") is False
    assert is_urgent_source("boss") is True


# --- 2. lane 分離：急件 vs 時效排程 vs 一般排程 -------------------------------

def test_time_critical_types_still_recognised_no_regression() -> None:
    """2026-07-16 daily_digest 脫班案的修補不得被這次改動洗掉。"""
    for tt in ("event_article", "trending_repost", "daily_digest"):
        task = _task("x", task_type=tt, source="reader_facing_refill")
        assert classify(task) == LANE_TIME_CRITICAL


def test_non_p1_is_never_urgent() -> None:
    for prio in (2, 3, 4, None, "P1"):
        assert classify(_task("t", priority=prio)) == LANE_SCHEDULED


def test_dedicated_owner_types_excluded() -> None:
    """email_reply / telegram_reply 各有專屬 owner，A0 碰了就是 double-claim。"""
    assert classify(_task("t", task_type="telegram_reply")) == LANE_SCHEDULED
    assert classify(_task("t", task_type="email_reply", source="user")) == LANE_SCHEDULED


def test_lane_puts_all_urgent_before_time_critical_oldest_first() -> None:
    """一班要能連續清完：lane 是完整清單且 urgent 全部在前，不是只回最舊一張。"""
    tasks = [
        _task("digest_new", task_type="daily_digest", source="scheduled",
              created_at="2026-07-18T09:00:00+00:00"),
        _task("tg_new", created_at="2026-07-18T08:00:00+00:00"),
        _task("digest_old", task_type="daily_digest", source="scheduled",
              created_at="2026-07-18T01:00:00+00:00"),
        _task("tg_old", created_at="2026-07-18T02:00:00+00:00"),
        _task("plain", priority=3, source="auto_discovered"),
        _task("done", status="succeeded"),
    ]
    lane = dispatch_lane(tasks)
    assert [t["id"] for t in lane] == ["tg_old", "tg_new", "digest_old", "digest_new"]
    assert [t["lane"] for t in lane] == [LANE_URGENT, LANE_URGENT,
                                         LANE_TIME_CRITICAL, LANE_TIME_CRITICAL]


def test_lane_skips_non_pending_and_junk_rows() -> None:
    assert dispatch_lane([_task("a", status="in_progress"), "not-a-dict", None]) == []


# --- 3. ingest 端：急件入池 → request_fire ------------------------------------

def test_append_next_task_fires_for_telegram_p1(tmp_path, monkeypatch) -> None:
    """核心接線：source=telegram 的 P1 建立後 request_fire 必須被呼叫。"""
    queue = tmp_path / "next_tasks.json"
    queue.write_text("[]\n", encoding="utf-8")
    monkeypatch.setattr(nt, "CANONICAL_NEXT_TASKS", queue)

    fired: list[str] = []
    monkeypatch.setitem(
        sys.modules, "scripts.dispatch_supervisor.state",
        type(sys)("scripts.dispatch_supervisor.state"),
    )
    sys.modules["scripts.dispatch_supervisor.state"].request_fire = (
        lambda reason, **kw: fired.append(reason)
    )
    monkeypatch.setitem(
        sys.modules, "scripts.dispatch_supervisor",
        type(sys)("scripts.dispatch_supervisor"),
    )
    sys.modules["scripts.dispatch_supervisor"].state = sys.modules[
        "scripts.dispatch_supervisor.state"
    ]

    record = nt.append_next_task(
        title="瀏覽數不一致",
        description="boss 在 Telegram 問的",
        source="telegram",
        legacy_priority=1,
        path=queue,
    )

    assert record["priority"] == 1
    assert record["fire_requested"] is True
    assert fired == [f"telegram:{record['id']}"], "fire reason 要能回溯到 ingest 來源與 task"
    # 而且它同時要被 A0 判成急件 —— ingest 端與派工端必須看到同一件事
    assert is_urgent(record) is True
    assert [t["id"] for t in dispatch_lane(nt_load(queue))] == [record["id"]]


def test_append_next_task_does_not_fire_for_scheduled_work(tmp_path, monkeypatch) -> None:
    """一般排程不得觸發立即派工（否則 request_fire 變成每次 append 都燒一班）。"""
    queue = tmp_path / "next_tasks.json"
    queue.write_text("[]\n", encoding="utf-8")
    monkeypatch.setattr(nt, "CANONICAL_NEXT_TASKS", queue)

    def boom(*a, **k):  # pragma: no cover - 被呼叫就是 bug
        raise AssertionError("scheduled task must not request an out-of-band fire")

    stub = type(sys)("scripts.dispatch_supervisor.state")
    stub.request_fire = boom
    monkeypatch.setitem(sys.modules, "scripts.dispatch_supervisor.state", stub)
    pkg = type(sys)("scripts.dispatch_supervisor")
    pkg.state = stub
    monkeypatch.setitem(sys.modules, "scripts.dispatch_supervisor", pkg)

    for source, prio in (("agent", 1), ("telegram", 100), ("scheduled", 30)):
        rec = nt.append_next_task(
            title="t", description="d", source=source,
            legacy_priority=prio, path=queue,
        )
        assert not is_urgent(rec), (source, prio, rec["priority"])
        assert rec["fire_requested"] is False


def test_scratch_queue_never_wakes_the_real_supervisor(tmp_path) -> None:
    """寫進非正牌佇列（測試/暫存）不得叫醒真的 supervisor。"""
    scratch = tmp_path / "next_tasks.json"
    scratch.write_text("[]\n", encoding="utf-8")
    rec = nt.append_next_task(
        title="t", description="d", source="telegram",
        legacy_priority=1, path=scratch,
    )
    assert rec["fire_requested"] is False


def nt_load(path: Path) -> list[dict]:
    import json
    return json.loads(path.read_text(encoding="utf-8"))


# --- 4. prompt 端只當 pointer（anti-stacking：一個 concern 一個 owner） --------

def test_dispatch_prompt_delegates_a0_decision_to_the_script() -> None:
    """A0 不得再內嵌判定條件 —— 條件散在 prompt 散文裡正是這次漏掉的根因。"""
    prompt = (ROOT / "scripts" / "cron_hourly_dispatch_prompt.md").read_text(encoding="utf-8")
    assert "volpred.ops.task_urgency" in prompt, "A0 必須指向唯一判定 owner"
    a0 = prompt.split("PHASE A0")[1].split("PHASE A —")[0]
    assert "t.get('task_type') in ('event_article'" not in a0, "判定邏輯不得留在 prompt"
