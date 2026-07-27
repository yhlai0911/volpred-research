"""Drain-first 水位閘 —— 自動任務生成的單一 admission owner（2026-07-21, boss Telegram msg 1237）。

Boss directive：「所以到底能不能把現有的任務先做完」。

## 為什麼需要這個模組

任務池單調膨脹，不是暫時尖峰。老闆自己實測的近 10 日 created/succeeded：

    121/56, 144/111, 99/69, 56/46, 55/48, 92/98, 82/61, 79/72, 64/55, 64/50

10 日累計 created 856 / succeeded 666，淨增約 +19/日。pending 189。派工端沒有問題
——問題是**生成端沒有煞車**：無論池子多深，refill / discovery 每天照樣產出。

半套的煞車早就存在，但只蓋住一個 caller：`continue_task_dispatch._maybe_refill`
的 `REFILL_FLOOR=4` early-return。它只管**它自己呼叫的**那四個 generator，而
`cron_research_backlog.sh` / `cron_reader_facing_refill.sh` 走自己的排程直接呼叫
同一批 generator，完全不看 pending。這就是為什麼池子照長。

## 閘門為什麼放在 generator entry point，不放 writer 層

writer 層（`next_tasks.append_task_record`）誘人但是錯的高度：

* 它同時承載**人的 ingress**（telegram / gmail / `volpred ops assign`）與機器 backlog。
  閘在那裡＝預設擋掉老闆指派，然後要維護一份永遠追不完的 `source` 豁免字串清單。
* 大宗生成器根本不走它 —— `refill_task_pool` / `generate_research_backlog` /
  `generate_diverse_tasks` / `dreaming_review` 走 `write_tasks_locked`。改閘
  `write_tasks_to_handle` 又會連 claim / status 同步 / 去重壓縮一起擋掉。

所以：**enforcement 在 5 個 generator entry point，writer 層只留 observability**
（`append_task_record` 在超水位時對機器來源印一行 warn，讓「繞過閘門的新 caller」
在 log 裡現形，而不是靜默灌水）。

## 白名單 = 老闆列的四種，對應到 kind

老闆的例外白名單：telegram_reply / email_reply / 時效性 P1 / 老闆直接指派。前三種
的判定 owner 是 `task_urgency`（不要在這裡重寫條件）。對應到 generator kind：

* ingress（telegram / gmail / ops assign）**根本不呼叫本模組** —— 它們走 writer
  gateway，天然不受閘。
* `reader_facing` 產出 event_article / trending_repost，正是 `task_urgency` 認定的
  ``time_critical``。時效過了價值歸零，池深不該讓它停 → **豁免**。

剩下四個 kind 才是真正被擋的：`refill_task_pool` / `research_backlog` /
`diverse_tasks` / `dreaming`。

## Latch，不是瞬時判斷

老闆的退出條件是「pending < 閾值 **且** 連續 3 日 succeeded >= created」——
兩條都滿足才解除。所以 drain-first 是有記憶的狀態，不是每次現算的布林：pending
在閾值邊界抖動時，若用瞬時判斷會一天開關數次，等於沒關。狀態存
``storage/ops/drain_first_state.json``。
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

TASKS_PATH_DEFAULT = "storage/next_tasks.json"
STATE_PATH_DEFAULT = "storage/ops/drain_first_state.json"
RULES_PATH_DEFAULT = "config/supervisor_rules.json"

#: 老闆建議值。改 config/supervisor_rules.json 的 pending_caps 即可覆寫（runtime 讀）。
DEFAULT_PENDING_CAP = 80
DEFAULT_EXIT_STREAK_DAYS = 3

#: 受閘的自動生成器。key = kind，value = 該 generator 的 entry point（給錯誤訊息用）。
GATED_KINDS = {
    "refill_task_pool": "scripts/refill_task_pool.py::refill",
    "research_backlog": "scripts/generate_research_backlog.py::generate",
    "diverse_tasks": "scripts/generate_diverse_tasks.py::generate",
    "dreaming": "scripts/dreaming_review.py::apply_auto_dispatch",
}

#: 豁免的 kind —— 產出是 task_urgency 認定的 time_critical，時效過了價值歸零。
EXEMPT_KINDS = {"reader_facing"}

#: writer 層 observability 用：機器來源的 source token。人的 ingress 不在此列，
#: 超水位時不對他們印 warn（老闆指派本來就該無視水位）。
MACHINE_SOURCE_TOKENS = frozenset(
    {
        "auto_discovered",
        "auto_remediation",
        "auto_research_fallback",
        "auto_journal_discovery_fallback",
        "auto_publish_drought_emergency",
        "research_backlog_auto",
        "diverse_gen",
        "dreaming",
        "internal_alert_remediation_router",
        "alert_remediation_bridge",
        "question_ops_maintain",
        "release_pool_audit_skip_materializer",
        "phase_z_gate_review",
        "dispatch_workspace_gate",
        "compute_queue_lazypack_failure",
        "daily_checkup_db_landing",
        "incident_adjudication",
        "incident_escalation",
        "reap_orphan_deliverables_held_ttl",
    }
)


@dataclass(frozen=True)
class Admission:
    """本次生成請求是否放行。``admitted=False`` 時 caller 必須直接 early-return。"""

    admitted: bool
    kind: str
    reason: str
    pending: int
    cap: int
    drain_first: bool

    def as_result(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        """組成 generator 慣用的 result dict（``{"ok":.., "added":0, "reason":..}``）。"""
        out = {
            "ok": True,
            "added": 0,
            "skipped": True,
            "reason": self.reason,
            "drain_first": self.drain_first,
            "pending": self.pending,
            "pending_cap": self.cap,
        }
        if extra:
            out.update(extra)
        return out


@dataclass
class PoolSnapshot:
    pending: int
    pending_by_priority: dict[str, int]
    daily: list[dict[str, Any]] = field(default_factory=list)

    @property
    def net_positive_streak(self) -> int:
        """連續幾個完整日 created > succeeded（由最近的完整日往回數）。"""
        streak = 0
        for row in self.daily:
            if row["created"] > row["succeeded"]:
                streak += 1
            else:
                break
        return streak

    def drain_streak_met(self, days: int) -> bool:
        """最近 ``days`` 個完整日是否**每日** succeeded >= created。"""
        if len(self.daily) < days:
            return False
        return all(row["succeeded"] >= row["created"] for row in self.daily[:days])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_day(value: Any) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        return None  # silent-ok: 歷史自由格式時間戳 → 不計入當日統計，不讓它炸掉閘門


def load_policy(rules_path: str | Path = RULES_PATH_DEFAULT) -> dict[str, Any]:
    """從 supervisor_rules.json 讀 ``pending_caps``（runtime 讀，改檔即生效）。"""
    policy = {
        "enabled": True,
        "pending_cap": DEFAULT_PENDING_CAP,
        "exit_streak_days": DEFAULT_EXIT_STREAK_DAYS,
    }
    p = Path(rules_path)
    if not p.exists():
        return policy
    try:
        rules = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return policy  # silent-ok: config 壞掉時用內建預設，閘門不該因設定檔而失效
    caps = rules.get("pending_caps")
    if isinstance(caps, dict):
        for key in ("enabled", "pending_cap", "exit_streak_days"):
            if key in caps:
                policy[key] = caps[key]
    return policy


def pool_snapshot(
    tasks: list[dict[str, Any]] | None = None,
    *,
    path: str | Path = TASKS_PATH_DEFAULT,
    window_days: int = 10,
    now: datetime | None = None,
) -> PoolSnapshot:
    """pending 水位 + 逐日 created/succeeded。

    ``daily`` 只含**完整日**（不含今天），最近的在最前面 —— 今天是進行中的部分資料，
    拿它跟整日的完成數比會系統性地看起來像淨增，退出條件永遠不會滿足。
    """
    if tasks is None:
        p = Path(path)
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = []
        tasks = raw if isinstance(raw, list) else []

    now = now or _now()
    today = now.date()
    days = [today - timedelta(days=i) for i in range(1, window_days + 1)]
    created: dict[date, int] = {d: 0 for d in days}
    succeeded: dict[date, int] = {d: 0 for d in days}

    pending = 0
    by_priority: dict[str, int] = {}
    for t in tasks:
        if not isinstance(t, dict):
            continue
        if t.get("status") == "pending":
            pending += 1
            key = f"p{t.get('priority', '?')}"
            by_priority[key] = by_priority.get(key, 0) + 1
        cday = _parse_day(t.get("created_at"))
        if cday in created:
            created[cday] += 1
        if t.get("status") == "succeeded":
            sday = _parse_day(t.get("completed_at"))
            if sday in succeeded:
                succeeded[sday] += 1

    daily = [
        {
            "date": d.isoformat(),
            "created": created[d],
            "succeeded": succeeded[d],
            "net": created[d] - succeeded[d],
        }
        for d in days
    ]
    return PoolSnapshot(
        pending=pending,
        pending_by_priority=dict(sorted(by_priority.items())),
        daily=daily,
    )


def _read_state(state_path: str | Path) -> dict[str, Any]:
    p = Path(state_path)
    if not p.exists():
        return {"active": False}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"active": False}  # silent-ok: state 壞掉 → 當作未啟動，下一次評估會重建
    return data if isinstance(data, dict) else {"active": False}


def _write_state(state_path: str | Path, state: dict[str, Any]) -> None:
    p = Path(state_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(p)


def evaluate_drain_first(
    *,
    snapshot: PoolSnapshot | None = None,
    tasks: list[dict[str, Any]] | None = None,
    path: str | Path = TASKS_PATH_DEFAULT,
    state_path: str | Path = STATE_PATH_DEFAULT,
    rules_path: str | Path = RULES_PATH_DEFAULT,
    persist: bool = True,
    now: datetime | None = None,
) -> dict[str, Any]:
    """算出（並持久化）drain-first latch 狀態。

    進入：``pending > cap``。
    解除：``pending < cap`` **且**最近 ``exit_streak_days`` 個完整日每日 succeeded >= created。
    兩者之間（例如 pending 恰好卡在 cap、或已降下來但吞吐還沒轉正）維持原狀 ——
    這正是要 latch 的理由：邊界抖動不該讓閘門一天開關數次。
    """
    now = now or _now()
    policy = load_policy(rules_path)
    snap = snapshot or pool_snapshot(tasks, path=path, now=now)
    prev = _read_state(state_path)
    was_active = bool(prev.get("active"))
    cap = int(policy["pending_cap"])
    streak_days = int(policy["exit_streak_days"])

    if not policy.get("enabled", True):
        active, transition = False, "disabled" if was_active else None
    elif snap.pending > cap:
        active = True
        transition = "entered" if not was_active else None
    elif was_active and snap.pending < cap and snap.drain_streak_met(streak_days):
        active, transition = False, "exited"
    else:
        active, transition = was_active, None

    state = {
        "active": active,
        "pending": snap.pending,
        "pending_by_priority": snap.pending_by_priority,
        "pending_cap": cap,
        "exit_streak_days": streak_days,
        "drain_streak_met": snap.drain_streak_met(streak_days),
        "net_positive_streak": snap.net_positive_streak,
        "daily": snap.daily[:streak_days],
        "updated_at": now.isoformat(),
        "entered_at": (
            now.isoformat() if transition == "entered" else prev.get("entered_at")
        ),
        "last_transition": transition or prev.get("last_transition"),
        "last_transition_at": (
            now.isoformat() if transition else prev.get("last_transition_at")
        ),
    }
    if not active:
        state["entered_at"] = None if transition == "exited" else state["entered_at"]
    if persist:
        _write_state(state_path, state)
    return state


def pool_admits_new_work(
    kind: str,
    *,
    tasks: list[dict[str, Any]] | None = None,
    path: str | Path = TASKS_PATH_DEFAULT,
    state_path: str | Path = STATE_PATH_DEFAULT,
    rules_path: str | Path = RULES_PATH_DEFAULT,
    persist: bool = True,
    now: datetime | None = None,
) -> Admission:
    """自動生成器的 admission gate。``admitted=False`` → caller 直接 early-return。

    ``kind`` 用 :data:`GATED_KINDS` / :data:`EXEMPT_KINDS` 的字串。未知 kind 一律
    當作受閘 —— 新 generator 預設進閘門，不是預設繞過（漏接的成本是池子繼續長，
    誤擋的成本只是一次沒補到）。
    """
    if kind in EXEMPT_KINDS:
        snap = pool_snapshot(tasks, path=path, now=now)
        return Admission(
            admitted=True,
            kind=kind,
            reason=f"exempt:{kind}（time_critical，時效過了價值歸零）",
            pending=snap.pending,
            cap=int(load_policy(rules_path)["pending_cap"]),
            drain_first=False,
        )

    snap = pool_snapshot(tasks, path=path, now=now)
    state = evaluate_drain_first(
        snapshot=snap,
        state_path=state_path,
        rules_path=rules_path,
        persist=persist,
        now=now,
    )
    active = bool(state["active"])
    cap = int(state["pending_cap"])
    if not active:
        return Admission(True, kind, "pool_ok", snap.pending, cap, False)
    return Admission(
        admitted=False,
        kind=kind,
        reason=(
            f"drain_first: pending={snap.pending} > cap={cap} —— 停止自動生成，"
            f"先清既有任務（退出條件：pending<{cap} 且連續 "
            f"{state['exit_streak_days']} 日 succeeded>=created）"
        ),
        pending=snap.pending,
        cap=cap,
        drain_first=True,
    )


def _source_tokens(source: Any) -> set[str]:
    text = str(source or "")
    token, tokens = [], set()
    for ch in text:
        if ch.isalnum():
            token.append(ch)
        elif token:
            tokens.add("".join(token).lower())
            token = []
    if token:
        tokens.add("".join(token).lower())
    return tokens


def _is_machine_source(source: Any) -> bool:
    """兩邊同樣 token 化後做子集比對。

    直接拿 :data:`MACHINE_SOURCE_TOKENS` 的字面值比 token 永遠不會中 —— tokenizer
    在非英數字元切開，``auto_discovered`` 進去出來是 ``{auto, discovered}``。子集
    比對同時吃得下歷史上的自由格式變體（``auto_discovered (refill)``），又不像
    substring 那樣誤命中。
    """
    tokens = _source_tokens(source)
    if not tokens:
        return False
    return any(_source_tokens(known) <= tokens for known in MACHINE_SOURCE_TOKENS)


def warn_if_over_cap(record: dict[str, Any], tasks: list[dict[str, Any]]) -> bool:
    """writer 層 observability —— **不擋**，只在機器來源超水位入池時印一行 warn。

    這是「有沒有人繞過閘門」的偵測器：閘門在 generator entry point，任何**新**的
    自動 caller 天然不會經過它。沒有這行，繞過是靜默的；有了它，繞過會在 log 現形。
    人的 ingress（telegram / gmail / 老闆指派）不印 —— 他們本來就該無視水位。
    """
    if not _is_machine_source(record.get("source")):
        return False
    pending = sum(
        1 for t in tasks if isinstance(t, dict) and t.get("status") == "pending"
    )
    cap = int(load_policy()["pending_cap"])
    if pending <= cap:
        return False
    print(
        f"[pool_pressure] WARN machine-generated task appended over cap "
        f"pending={pending} cap={cap} id={record.get('id')} "
        f"source={record.get('source')} type={record.get('task_type')} "
        "— 此 caller 未經 pool_admits_new_work 閘門",
        file=sys.stderr,
    )
    return True
