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
    LANE_DEFERRED,
    LANE_SCHEDULED,
    LANE_TIME_CRITICAL,
    LANE_URGENT,
    classify,
    deferred_lane,
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


def test_time_critical_is_type_only_not_priority_gated() -> None:
    """2026-07-21 R1：時效性來自 type 本身，priority 打錯不得讓它退回 scheduled。

    手建 P2 event_article 若因不是 P1 而排進 scheduled lane，等排到時時效已歸零
    —— dispatcher 的 lane rank 與 A0 lane 都必須把它當 time_critical。
    """
    for prio in (2, 3, "P2"):
        task = _task("x", task_type="event_article", source="reader_facing_refill",
                     priority=prio)
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


# --- 5. dedicated-owner 邊界：telegram_reply 不是漏網之魚 ---------------------
#
# 2026-07-19 記：`scripts/telegram_poll.py` 自己組 record 直寫 canonical queue、
# 不經 `append_next_task()`，看起來就是第 1 節罵的那種「ingest 端沒接線」——
# source=telegram + priority=1 全中。實際查證後不是：它建的是 `telegram_reply`，
# 有專屬 owner（`_spawn_responder()` 即時處理，spawn 失敗則由 poll 迴圈在
# `RETRY_AGE_THRESHOLD_SEC`=120s 內重派），本來就不歸 hourly dispatcher 管。
#
# 這一節存在的唯一理由：本次維護時真的照著「補接線」改下去了，是既有測試把它擋
# 回來的。下一個人會踩同一個坑，所以把邊界連同理由一起釘死，而不是只留註解。

def test_dedicated_owner_reply_types_are_not_urgent(monkeypatch, tmp_path) -> None:
    """telegram_reply / email_reply 即使 source+priority 全中也不得進 urgent lane。"""
    for task_type in ("telegram_reply", "email_reply"):
        record = _task("t", task_type=task_type, source="telegram", priority=1)
        assert is_urgent(record) is False, (
            f"{task_type} 有專屬 owner，進 urgent lane 會和 owner 重複 claim"
        )
        assert dispatch_lane([record]) == [], f"{task_type} 不得出現在 A0 lane"


def test_telegram_poll_does_not_wire_an_urgent_fire() -> None:
    """釘住上面那個結論的實作面：telegram_poll 不該呼叫 fire helper。

    呼叫了會是 no-op（`is_urgent` 對 telegram_reply 一律 False），而 no-op 的接線
    比沒接線更糟 —— 它讀起來像已經處理好了。
    """
    src = (ROOT / "scripts" / "telegram_poll.py").read_text(encoding="utf-8")
    assert "request_urgent_fire" not in src.replace("_request_urgent_fire", ""), (
        "telegram_reply 有專屬 owner，不該請 hourly out-of-band fire"
    )
    assert "_spawn_responder" in src, "專屬 owner 消失的話，上面的豁免就不再成立"


# --- 6. main_thread lane：漏掉時是餓死，不只是 double-claim（2026-07-20）------
#
# `dispatch_lane="main_thread"` 保留給互動 session，claim gate（commit f23d870c4,
# 11:48）會拒絕 headless owner。本模組當時不認得 lane，照樣把這些任務排進 A0 最
# 前面。A0 的規則是「lane 還有殘留 → 本班不進 PHASE A」，而 hourly fire 永遠
# claim 不到這些任務 ⇒ 11:48 起每一班 fire 都卡死，一般排班全面餓死。
#
# 實例：7 張 [refactor-master] P1（source=user，03:12 建單）在 12:17 那班仍讓
# `claim` 回 reason=main_thread_lane。

def _main_thread_task(task_id: str = "assign_caf5b087", **extra) -> dict:
    extra.setdefault("dispatch_lane", "main_thread")
    return _task(task_id, source="user", **extra)


def test_main_thread_lane_task_is_not_in_a0_lane() -> None:
    """事故的精確形狀：source+priority 全中，但 headless fire claim 不到。"""
    task = _main_thread_task()
    assert is_urgent_source(task["source"]) is True, "前提：urgency 判定本身會命中"
    assert classify(task) == LANE_DEFERRED
    assert is_urgent(task) is False, "claim 不到的任務不該叫醒一班誰都做不了的 fire"
    assert dispatch_lane([task]) == [], "進了 A0 lane = 每班 fire 都清不掉 ⇒ 餓死"


@pytest.mark.parametrize("lane", ["main", "main_thread", "main-thread", "manual", "interactive"])
def test_all_main_thread_spellings_excluded(lane: str) -> None:
    """詞彙不一致正是根因 —— 4 種拼法（含連字號）都得認得。"""
    assert dispatch_lane([_main_thread_task(dispatch_lane=lane)]) == []


def test_agent_lane_and_unset_lane_still_dispatchable() -> None:
    """誤擋防線：擋錯邊會把整個佇列凍住（絕大多數任務沒有 lane 欄位）。"""
    assert classify(_task("t", source="user")) == LANE_URGENT, "未設 lane 必須照舊可派"
    for lane in ("agent", "auto", "headless", "worker", ""):
        task = _task("t", source="user", dispatch_lane=lane)
        assert classify(task) == LANE_URGENT, f"lane={lane!r} 是可派的，不得被擋"


def test_deferred_tasks_stay_observable() -> None:
    """不進 A0 ≠ 消失 —— 主線程 backlog 若從報告消失就沒人會發現它在積。"""
    tasks = [_main_thread_task("a"), _task("b", source="user")]
    assert [t["id"] for t in deferred_lane(tasks)] == ["a"]
    assert [t["id"] for t in dispatch_lane(tasks)] == ["b"]


def test_claim_gate_and_urgency_share_one_vocabulary() -> None:
    """兩邊各留一套字面值就是這次的根因，釘住「同一個 owner」。

    2026-07-21 incident-lifecycle P4 收編升級：owner 從「共用 canonical set」
    進一步收成單一 predicate ``is_main_thread_reserved``（status
    pending_main_thread 與 dispatch_lane 兩個欄位一起判）。claim gate 與
    request_fire 讀不同欄位，正是 assign_10927b4e「永遠沒有合法執行者卻被
    hourly fire」的根因（refactor_plan_incident_lifecycle.md 附註）。
    """
    src = (ROOT / "scripts" / "task_pool_claim.py").read_text(encoding="utf-8")
    assert "is_main_thread_reserved" in src, "claim gate 必須用唯一 owner predicate"
    assert 'lane == "main_thread"' not in src, "不得回退成單一字面值比對"
    assert 'existing_status == "pending_main_thread"' not in src, (
        "status 判定不得在 claim gate 留第二份 —— owner 是 is_main_thread_reserved"
    )


# --- 7. admission 端：機器來源 P1 夾制（2026-07-21 dispatch-lanes R2） ---------
#
# 2026-07-21 實測：pending 181、P1 33 個，boss 來源只有 8 個 —— 25 個是產生器
# 自封的 P1。P1 語意是「boss 當下要的 + 時效性」；機器自封 P1 等於取消 priority，
# boss 新急件在 33 張 P1 裡排隊。gateway（append_task_record）夾制：機器來源、
# 非時效類、非 dedicated-owner ingress 的 P1 → P2 + `priority_capped_from: 1`。
# 只 clamp 不 block（writer 層不能 block —— 邊界同 pool_pressure docstring）。

def _append(tmp_path, **extra) -> dict:
    queue = tmp_path / "next_tasks.json"
    record = _task(extra.pop("id", "adm_t1"), **extra)
    rec, created = nt.append_task_record(record, path=queue)
    assert created is True
    return rec


def test_machine_p1_is_clamped_to_p2_with_stamp(tmp_path, capsys) -> None:
    rec = _append(tmp_path, source="auto_discovered")
    assert rec["priority"] == 2
    assert rec["priority_capped_from"] == 1
    # 落地的也要是夾過的（不是只改記憶體 copy）
    persisted = nt_load(tmp_path / "next_tasks.json")
    assert persisted[0]["priority"] == 2
    assert persisted[0]["priority_capped_from"] == 1
    assert "task_admission" in capsys.readouterr().err, "夾制必須可觀測（no-silent-fallback）"


@pytest.mark.parametrize("source", [
    "agent", "orphan_closeout", "auto_publish_drought_emergency",
    "internal_alert_remediation_router",
])
def test_known_machine_p1_inflators_all_clamped(tmp_path, source: str) -> None:
    """2026-07-21 盤點到的自封 P1 產生器 source，一個都不能漏。"""
    rec = _append(tmp_path, source=source)
    assert rec["priority"] == 2
    assert rec["priority_capped_from"] == 1


def test_boss_p1_is_not_clamped(tmp_path) -> None:
    rec = _append(tmp_path, source="boss-telegram-msg110")
    assert rec["priority"] == 1
    assert "priority_capped_from" not in rec
    assert is_urgent(rec) is True, "夾制不得誤傷急件 lane"


def test_machine_time_critical_p1_is_not_clamped(tmp_path) -> None:
    """時效任務依 2026-07-12 boss 指令必須 P1 —— 機器源也一樣。"""
    for i, tt in enumerate(("event_article", "trending_repost", "daily_digest")):
        rec = _append(tmp_path, id=f"tc_{i}", task_type=tt, source="reader_facing_refill")
        assert rec["priority"] == 1, tt
        assert "priority_capped_from" not in rec


def test_dedicated_owner_ingress_p1_is_not_clamped(tmp_path) -> None:
    """email_reply / telegram_reply 有專屬 owner，priority 對它們是 pass-through。"""
    for i, tt in enumerate(("email_reply", "telegram_reply")):
        rec = _append(tmp_path, id=f"own_{i}", task_type=tt, source="gmail_inbox_poll")
        assert rec["priority"] == 1, tt
        assert "priority_capped_from" not in rec


def test_machine_p2_passes_untouched(tmp_path) -> None:
    """夾制只針對 P1；P2 以下不動（否則整個 priority 階梯都被壓扁）。"""
    rec = _append(tmp_path, source="auto_discovered", priority=2)
    assert rec["priority"] == 2
    assert "priority_capped_from" not in rec
