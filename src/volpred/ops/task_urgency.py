"""急件 vs 一般排程 —— 單一判定 owner（2026-07-18, boss Telegram msg 981）。

Boss directive：「急件和一般排程應該要分開。急件就不進入排班直接派工，一般排程
才進入排班。」

## 為什麼要有這個模組

底層機制早就對了：`scripts/dispatch_supervisor/state.request_fire()` 是 out-of-band
立即派工，`scheduler` 明確保證 requested fire 繞過所有 gate。email
(`gmail_inbox_poll.py`) 與 CI red (`check_alerts.py`) 都已接上。**只有 Telegram
沒接** —— Telegram 進來的 P1 只 append 進 `storage/next_tasks.json`，等下一班
hourly cron。這就是「email 急件立刻做、Telegram 急件等下一班」的全部原因。

第二個洞在派工端。`scripts/cron_hourly_dispatch_prompt.md` PHASE A0 的時效 P1
過濾條件是**列舉 task_type**：

    task_type in (event_article, trending_repost, daily_digest) or source == 'user'

Telegram 建出來的 P1 是 `task_type=platform_ops` / `source=telegram` —— 兩個條件
都不中，所以 A0 看不到它。2026-07-18 實例：`assign_998ad2be`（source=telegram，
A0 抓不到）與 `assign_33a9151f`（source=user，抓得到但排在別人後面），16:49/17:42
建單，18:06 兩張都還 pending。列舉 task_type 正是這次漏掉的根因。

## 判定模型：三條 lane，不是一個布林

急件（urgent）和「時效性排程任務」是兩件事，混成一個 whitelist 是原本的錯：

* ``urgent``        —— **人**（老闆）當下丟進來的活。用 **source + priority** 判，
                      不列舉 task_type。這種活不進排班，ingest 當下就 request_fire。
* ``time_critical`` —— 排程產生但**時效會過期**的活（event_article /
                      trending_repost / daily_digest）。它們 source 是
                      `reader_facing_refill` 之類的機器來源，靠 task_type 認得
                      出來，這裡保留 type 判定（2026-07-16 daily_digest 脫班案
                      的修補，移掉會回歸）。**只看 type、不看 priority**
                      （2026-07-21 dispatch-lanes R1）：時效性來自任務類型本身，
                      priority 數字打錯（手建 P2 event_article）不該讓它退回
                      scheduled lane 排隊等時效歸零。
* ``scheduled``     —— 其餘全部，走一般排班。

排序：urgent 全部（依 created_at）→ time_critical 全部（依 created_at）。一班
**連續清完整條 lane** 才進 PHASE A followup，不是每班只做最舊一張。

## source 用 token 比對，不用 substring

歷史 source 是自由字串，人手寫過 `boss-telegram-msg110` / `owner-telegram-749` /
`user-assigned (Telegram msg 447)` / `telegram_remediation` 等變體。純字串相等會
漏掉全部變體；substring 又會誤命中（`router` 內含 `outer`-類意外）。折衷是把
source 依非英數字元切成 token，再和 token 白名單做**完整 token** 比對。

## 有專屬 owner 的 task_type 不進本 lane

`email_reply` 由 PHASE 0 專門處理、`telegram_reply` 由 `telegram_responder.sh`
（task-routing.md：「不進一般 hourly/Codex claim」）處理。A0 若也把它們列進來就
是雙 owner ＝ double-claim race。它們被明確排除，且各自的 ingest 已經有自己的
即時路徑。

## 主線程 lane 同理 —— 但漏掉時是**餓死**，不只是 race（2026-07-20）

`dispatch_lane="main_thread"` 的任務保留給互動 session，`task_pool_claim` 的 claim
gate（`:495-509`，commit `f23d870c4` 11:48 落地）會直接拒絕 headless owner。本模組
當時完全不認得 lane，於是同一批任務**照樣被排進 A0 lane 最前面**。

後果比 double-claim 嚴重：PHASE A0 的規則是「lane 還有殘留 → 本班不進 PHASE A」。
這 7 張 `[refactor-master]` P1（03:12 建單，`source=user`）hourly fire 永遠 claim
不到、也就永遠清不掉 ⇒ **11:48 之後每一班 fire 都卡在 A0，一般排班工作全面餓死**。
實測：本班 12:17 fire 跑 `claim assign_caf5b087` 得 `reason=main_thread_lane`。

所以 lane 判定必須和 claim gate 用**同一套詞彙** —— 現在共用
`volpred.ops.next_tasks.is_agent_claimable_lane()`（該檔是 controlled-vocabulary
owner，同 `TASK_STATUSES` 的形狀）。這類任務歸入 `LANE_DEFERRED`：不進 A0 可動
lane、`is_urgent()` 回 False（不會叫醒一班誰都做不了的 fire），但 CLI 仍在
`deferred` 欄位獨立列出 —— 主線程的 backlog 要**可見**，不是消失。
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Iterable

from volpred.ops.next_tasks import is_agent_claimable_lane

LANE_URGENT = "urgent"
LANE_TIME_CRITICAL = "time_critical"
LANE_SCHEDULED = "scheduled"

#: A0 lane 的順序（urgent 先清完才輪到 time_critical）。
LANE_ORDER = (LANE_URGENT, LANE_TIME_CRITICAL)

#: 「人（老闆）當下丟進來」的 ingress source token。比對單位是 token，不是子字串。
URGENT_SOURCE_TOKENS = frozenset({"telegram", "user", "owner", "boss"})

#: 排程產生但時效會過期的 task_type（2026-07-16 daily_digest 脫班案）。
TIME_CRITICAL_TASK_TYPES = frozenset({"event_article", "trending_repost", "daily_digest"})

#: 有專屬派工 owner，A0 不得碰（否則 double-claim）。
DEDICATED_OWNER_TASK_TYPES = frozenset({"email_reply", "telegram_reply"})

#: 保留給互動主線程 / 已封鎖的 lane，headless fire claim 不到（見下方 LANE_DEFERRED）。
LANE_DEFERRED = "deferred"

#: 急件的 priority 門檻（P1 only —— boss 的「急件」定義就是 user-assigned P1）。
URGENT_PRIORITY = 1

_TOKEN_SPLIT = re.compile(r"[^0-9a-z]+")


def source_tokens(source: Any) -> frozenset[str]:
    """把自由字串 source 切成小寫 token 集合（`boss-telegram-msg110` → {boss, telegram, msg110}）。"""
    if not isinstance(source, str):
        return frozenset()
    return frozenset(t for t in _TOKEN_SPLIT.split(source.lower()) if t)


def is_urgent_source(source: Any) -> bool:
    """source 是否來自「人當下丟進來」的 ingress（telegram / user / owner / boss）。"""
    return bool(source_tokens(source) & URGENT_SOURCE_TOKENS)


def _priority(task: dict) -> int | None:
    raw = task.get("priority")
    try:
        return int(raw)
    except (TypeError, ValueError):  # silent-ok: 無法解析的 priority 一律視為「未定」交呼叫端判斷，不是失敗兜底
        return None


def classify(task: dict) -> str:
    """回傳 ``urgent`` / ``time_critical`` / ``scheduled``。不看 status。"""
    if not isinstance(task, dict):
        return LANE_SCHEDULED
    if not is_agent_claimable_lane(task):
        return LANE_DEFERRED  # 專屬 owner = 互動主線程，見 module docstring
    if task.get("task_type") in DEDICATED_OWNER_TASK_TYPES:
        return LANE_SCHEDULED  # 有專屬 owner，見 module docstring
    prio = _priority(task)
    if prio == URGENT_PRIORITY and is_urgent_source(task.get("source")):
        return LANE_URGENT
    # Type-only, no priority gate: perishability is a property of the task
    # type, not of the priority digit someone typed (module docstring §判定模型).
    if task.get("task_type") in TIME_CRITICAL_TASK_TYPES:
        return LANE_TIME_CRITICAL
    return LANE_SCHEDULED


def is_urgent(task: dict) -> bool:
    """急件 = 不進排班、ingest 當下就要 request_fire 的那一類。"""
    return classify(task) == LANE_URGENT


def dispatch_lane(tasks: Iterable[dict], *, pending_only: bool = True) -> list[dict]:
    """A0 lane：urgent 全部（舊→新）接 time_critical 全部（舊→新）。

    回傳的是原 task dict 的 shallow copy，多帶一個 ``lane`` 欄位。
    """
    out: list[tuple[int, str, dict]] = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        if pending_only and task.get("status") != "pending":
            continue
        lane = classify(task)
        if lane not in LANE_ORDER:
            continue
        record = dict(task)
        record["lane"] = lane
        out.append((LANE_ORDER.index(lane), str(task.get("created_at") or ""), record))
    out.sort(key=lambda row: (row[0], row[1]))
    return [row[2] for row in out]


def deferred_lane(tasks: Iterable[dict], *, pending_only: bool = True) -> list[dict]:
    """保留給互動主線程的 pending 任務（舊→新）。

    這些**不是** A0 可動的活，但要在報告裡看得見 —— headless fire 清不掉的
    backlog 若從報告消失，就沒有任何地方會提醒主線程它積了幾張。
    """
    out: list[tuple[str, dict]] = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        if pending_only and task.get("status") != "pending":
            continue
        if classify(task) != LANE_DEFERRED:
            continue
        record = dict(task)
        record["lane"] = LANE_DEFERRED
        out.append((str(task.get("created_at") or ""), record))
    out.sort(key=lambda row: row[0])
    return [row[1] for row in out]


def load_tasks(path: str | Path) -> list[dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("tasks", [])
    return [t for t in data if isinstance(t, dict)]


_REPORT_FIELDS = ("id", "lane", "task_type", "source", "priority", "created_at", "title")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="急件 / 時效 lane（PHASE A0 的判定 owner）")
    ap.add_argument("--tasks", default="storage/next_tasks.json")
    ap.add_argument("--all-statuses", action="store_true", help="不過濾 status=pending")
    args = ap.parse_args(argv)
    tasks = load_tasks(args.tasks)
    pending_only = not args.all_statuses
    lane = dispatch_lane(tasks, pending_only=pending_only)
    deferred = deferred_lane(tasks, pending_only=pending_only)
    print(json.dumps(
        {
            "count": len(lane),
            "urgent": sum(1 for t in lane if t["lane"] == LANE_URGENT),
            "time_critical": sum(1 for t in lane if t["lane"] == LANE_TIME_CRITICAL),
            "tasks": [{k: t.get(k) for k in _REPORT_FIELDS} for t in lane],
            # 主線程保留任務：headless fire claim 不到，不計入 count（否則 A0 的
            # 「清完整條 lane」永遠不成立 ⇒ 排班餓死），但必須看得見。
            "deferred_main_thread": len(deferred),
            "deferred": [{k: t.get(k) for k in _REPORT_FIELDS} for t in deferred],
        },
        ensure_ascii=False,
    ))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
