#!/usr/bin/env python3
"""per-agent / per-model token 消耗分解 + 異常偵測（資源監控部 owned tool）。

為什麼不是直接讀 `storage/reports/token_usage/daily_*.json`：
那些日報只有 by_model / by_provider / by_category 三個維度，**沒有 agent 維度**
（誰花的：主線程？哪個 worktree 的 K 實驗？哪個 dispatch slot？Codex？）。
本工具重用 `scripts/token_usage_report.py` 的 telemetry 讀取與計價原語（不重寫
token 會計），只多加 agent 歸屬、session 壽命、效力（effectfulness）三個維度。

同時把「重算的每日真值」與「已落檔的日報」對照，偵測日報 pipeline 失真。

## v2（2026-08-05，工作項 item_20260805T074432202854Z）新增

1. **異常規則**（v1 只有「單日 > 2x 均值」，對長期霸佔完全盲）：
   - `agent_concentration`：單一 agent 佔窗口 billable > 20%
   - `session_longevity`：單一 session 壽命 > 48h
   - `idle_burn_session`：燒掉 >=1M billable 卻整窗零寫入的 session
   - `repeat_churn`：同一 session 內同 tool + 同輸入重複 >=5 次
2. **noop／空轉偵測**：turn 級的部門自有三分類（write / mutating_command /
   read_only）＋ `noop_text_only`（零 tool_use）。
3. **Codex fork 重複計數定案審計**（`codex_duplicate_audit`）：把去重鍵從
   「session_id ＋ 累計 tuple」換成「fork root ＋ 累計 tuple」重算，turn-level
   量出實際重複量，取代 v1 的「上界 60.1M」。
4. **上游 mission 佔比就地標註不可作 KPI**（見 `kpi_field_warnings`）。

用法：
    uv run python storage/org/departments/resource_monitor/tools/token_breakdown.py --days 7 [--end 2026-08-04] [--top 15] [--out PATH]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# storage/org/departments/resource_monitor/tools/<this> → parents[5] is the repo root
REPO_ROOT = Path(__file__).resolve().parents[5]
DEPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from token_usage_report import (  # noqa: E402
    DISPATCH_WORKDIR_ROOT,
    MISSION_OUTPUT_CATEGORIES,
    PRICING,
    _billable_total,
    _claude_project_slug,
    _codex_session_paths,
    _deduplicated_turns,
    _iter_codex_session_records,
    _primary_category,
    _scan_jsonl,
    _usage_breakdown,
    compute_cost_usd,
    discover_claude_project_dirs,
)

STORED_DAILY_DIR = REPO_ROOT / "storage" / "reports" / "token_usage"

# --- v2 異常門檻（部門 KPI 規則，改這裡就是改規則） ------------------------
AGENT_CONCENTRATION_PCT = 20.0      # 單一 agent 佔窗口 billable 上限
SESSION_LIFETIME_HOURS = 48.0       # 單一 session 壽命上限
DAILY_SPIKE_RATIO = 2.0             # 單日 vs 窗口均值（v1 既有規則）
IDLE_BURN_MIN_BILLABLE = 1_000_000  # 「燒得夠多才算異常」的地板
CHURN_MIN_REPEATS = 5               # 同 tool 同輸入重複幾次算空轉
CHURN_MIN_BILLABLE = 200_000        # 空轉 session 的 billable 地板


# --- agent 歸屬 -----------------------------------------------------------
# Claude Code 以 CWD 決定 project 目錄，所以目錄名唯一決定「這個 session 是誰」：
# 主 checkout = 主線程；.claude/worktrees/<slug> = 該 worktree 的實驗 agent；
# dispatch scratch = Operations Core worker。這是唯一不必猜的 agent 訊號。

def _agent_identity(project_dir_name: str, is_subagent: bool) -> tuple[str, str]:
    """回傳 (agent_class, agent_id)。"""
    main_name = _claude_project_slug(REPO_ROOT)
    worktree_prefix = _claude_project_slug(REPO_ROOT / ".claude" / "worktrees") + "-"
    dispatch_prefix = _claude_project_slug(DISPATCH_WORKDIR_ROOT) + "-"

    if project_dir_name == main_name:
        base_class, agent_id = "main_thread", "main_thread"
    elif project_dir_name.startswith(worktree_prefix):
        slug = project_dir_name[len(worktree_prefix):]
        base_class, agent_id = "worktree_agent", f"worktree:{slug}"
    elif project_dir_name.startswith(dispatch_prefix):
        slug = project_dir_name[len(dispatch_prefix):]
        base_class, agent_id = "dispatch_worker", f"dispatch:{slug}"
    else:
        # discover_claude_project_dirs 的 allowlist 是結構性的，出現第三種前綴
        # 代表 allowlist 或 runtime 佈局變了 — 記名而非靜默歸零。
        base_class, agent_id = "unclassified", f"unclassified:{project_dir_name}"

    if is_subagent:
        return f"{base_class}_subagent", agent_id + "/subagent"
    return base_class, agent_id


# --- v2：turn 效力分類（部門自有口徑，不用上游 MISSION_OUTPUT_CATEGORIES）---
# 為什麼另立一套：上游分類器是「任務類型」導向，主線程大量真實產出被歸進
# bash_other / investigation（v1 §5.4），拿它算「產出佔比」會嚴重低估主線程。
# 這裡改問一個**結構性、不需猜任務語意**的問題：這個 turn 有沒有真的改變世界？
#   write             — 有 Edit / Write / NotebookEdit 這類直接寫檔工具
#   mutating_command  — Bash 命中明確的變更型指令（commit / 重導向 / rm / ops CLI…）
#   read_only         — 其餘有工具的 turn（讀、搜尋、查詢）
#   noop_text_only    — 完全沒有 tool_use 的 turn
# 誠實邊界：`mutating_command` 的 pattern 是**保守**的白名單，一個會寫檔的
# python 腳本若沒命中 pattern 會被算成 read_only ⇒ `effectful_share_pct` 是
# **下界**，不是點估計。反過來 idle/noop 佔比是**上界**。

_WRITE_TOOLS = {"Edit", "Write", "NotebookEdit", "MultiEdit"}
_MUTATING_TOOLS = {
    "Artifact", "SendUserFile", "TaskCreate", "TaskUpdate", "CronCreate",
    "CronDelete", "ScheduleWakeup", "SendMessage", "PushNotification",
    "RemoteTrigger", "Workflow", "Agent",
}
_MUTATING_BASH_RE = re.compile(
    r"(git\s+(commit|push|merge|tag|worktree\s+add|add\b)"
    r"|>>?\s*[^\s|&]"                       # shell 重導向寫檔
    r"|\b(rm|mv|cp|mkdir|touch|chmod|ln)\b"
    r"|sed\s+-i|tee\b"
    r"|uv\s+run\s+volpred\s+ops"
    r"|dept_send\.py|git_writer_lock\.py|task_pool_claim\.py|progress_report\.py"
    r"|publish|deploy|supabase\s+(db|migration)"
    r")"
)


def _turn_effect(turn: dict) -> str:
    """回傳 write / mutating_command / read_only / noop_text_only / unknown_no_content。"""
    content = turn.get("content") or []
    if turn.get("provider") == "codex":
        # Codex telemetry 只有 token_count，沒有工具內容 —— 無法判定效力。
        # 不猜，獨立成一桶並在分母裡排除。
        return "unknown_no_content"
    saw_tool = False
    saw_read_only = False
    for item in content:
        if not isinstance(item, dict) or item.get("type") != "tool_use":
            continue
        saw_tool = True
        name = item.get("name", "")
        if name in _WRITE_TOOLS:
            return "write"
        if name in _MUTATING_TOOLS:
            return "mutating_command"
        if name == "Bash":
            inp = item.get("input") if isinstance(item.get("input"), dict) else {}
            if _MUTATING_BASH_RE.search(str(inp.get("command", ""))):
                return "mutating_command"
        saw_read_only = True
    if saw_tool and saw_read_only:
        return "read_only"
    return "noop_text_only"


def _tool_call_digests(turn: dict):
    """產出這個 turn 內每個 tool call 的 (tool_name, input digest)，供空轉偵測用。"""
    for item in turn.get("content") or []:
        if not isinstance(item, dict) or item.get("type") != "tool_use":
            continue
        name = item.get("name", "")
        try:
            payload = json.dumps(item.get("input", {}), sort_keys=True, ensure_ascii=False)
        except (TypeError, ValueError):
            payload = repr(item.get("input"))
        yield name, hashlib.sha1(
            f"{name}\x00{payload}".encode("utf-8", "replace")
        ).hexdigest()[:12]


def iter_attributed_turns(date_start: date, date_end: date):
    """產出帶 agent 歸屬的 turn（已按 msg_id 去重，與官方日報同口徑）。"""
    seen_record_ids: set[str] = set()

    for project_dir in discover_claude_project_dirs():
        sources = [(p, False) for p in sorted(project_dir.glob("*.jsonl"))]
        sources += [(p, True) for p in sorted(project_dir.glob("*/subagents/*.jsonl"))]
        for jsonl_path, is_subagent in sources:
            session_id = jsonl_path.stem
            if is_subagent:
                session_id = jsonl_path.parent.parent.name + "/" + jsonl_path.stem
            agent_class, agent_id = _agent_identity(project_dir.name, is_subagent)

            records = []
            for record in _scan_jsonl(
                jsonl_path, session_id, is_subagent, date_start, date_end
            ):
                rid = record.get("record_id")
                if isinstance(rid, str) and rid:
                    if rid in seen_record_ids:
                        continue
                    seen_record_ids.add(rid)
                records.append(record)
            for turn in _deduplicated_turns(records):
                turn["agent_class"] = agent_class
                turn["agent_id"] = agent_id
                yield turn

    for record in _iter_codex_session_records(date_start, date_end):
        yield {
            "usage": record["usage"],
            "model": record["model"],
            "date": record["date"],
            "timestamp": record["timestamp"],
            "provider": "codex",
            "session_id": record["session_id"],
            "is_subagent": False,
            "categories": [record["category"]],
            "content": [],
            "record_id": record.get("record_id"),
            "agent_class": "codex_worker",
            "agent_id": record["session_id"],
        }


# --- v2：Codex fork 重複計數審計 -------------------------------------------

def _codex_fork_root_index(date_start: date, date_end: date) -> dict:
    """建 session_meta.id → fork root id 的對照（只讀每檔的 session_meta 行）。

    2026-08-05 實測：窗內每個 rollout 檔的 `session_meta.id` **各自唯一**
    （2815 檔 → 2815 個 id），所以「session 身分改綁 session_meta.session_id」
    無法把 fork 收斂成同一個邏輯對話。真正的邏輯對話鍵是
    `forked_from_id` / `parent_thread_id` 往上追到底的 root。
    """
    parent: dict[str, str] = {}
    meta: dict[str, dict] = {}
    for path in _codex_session_paths(date_start, date_end):
        try:
            size = path.stat().st_size
            with path.open(encoding="utf-8") as handle:
                for line in handle:
                    if '"session_meta"' not in line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if obj.get("type") != "session_meta":
                        continue
                    payload = obj.get("payload") or {}
                    sid = str(payload.get("id") or path.stem)
                    src = payload.get("forked_from_id") or payload.get("parent_thread_id")
                    if src:
                        parent[sid] = str(src)
                    meta.setdefault(sid, {
                        "file": path.name,
                        "size_bytes": size,
                        "forked": bool(src),
                    })
                    break
        except OSError:
            continue

    def root_of(sid: str) -> str:
        seen = set()
        cur = sid
        while cur in parent and cur not in seen:
            seen.add(cur)
            cur = parent[cur]
        return cur

    return {"root_of": {sid: root_of(sid) for sid in meta}, "meta": meta}


def audit_codex_duplicates(date_start: date, date_end: date) -> dict:
    """turn-level 量出 Codex fork 造成的重複計數（取代 v1 的「上界」說法）。

    現行會計的去重鍵 = `codex:{session_id}:{累計 tuple}`；session_id 每檔唯一
    ⇒ fork 重放的同一段歷史跨檔去重失效。這裡把去重鍵換成
    `{fork root}:{累計 tuple}`（把 session_id 段抽掉），差額就是重複量。
    """
    index = _codex_fork_root_index(date_start, date_end)
    root_of = index["root_of"]
    meta = index["meta"]

    current_billable = 0
    current_records = 0
    dedup_seen: set[str] = set()
    dedup_billable = 0
    dedup_records = 0
    per_root = defaultdict(lambda: {
        "files": set(), "current_billable": 0, "dedup_billable": 0,
    })

    for record in _iter_codex_session_records(date_start, date_end):
        usage = _usage_breakdown(record["usage"])
        billable = _billable_total(usage)
        sid = str(record["session_id"]).split("/", 1)[-1]
        root = root_of.get(sid, sid)
        rid = str(record.get("record_id") or "")
        # record_id 形如 codex:<session_id>:<數字>:<數字>…，把身分段換成 root。
        parts = rid.split(":")
        tuple_part = ":".join(parts[2:]) if len(parts) > 2 else rid
        key = f"{root}:{tuple_part}"

        current_billable += billable
        current_records += 1
        bucket = per_root[root]
        bucket["files"].add(sid)
        bucket["current_billable"] += billable

        if key in dedup_seen:
            continue
        dedup_seen.add(key)
        dedup_billable += billable
        dedup_records += 1
        bucket["dedup_billable"] += billable

    duplicate_billable = current_billable - dedup_billable
    worst = sorted(
        (
            {
                "root_session_id": root,
                "rollout_files": len(v["files"]),
                "current_billable": v["current_billable"],
                "deduplicated_billable": v["dedup_billable"],
                "duplicate_billable": v["current_billable"] - v["dedup_billable"],
            }
            for root, v in per_root.items()
        ),
        key=lambda r: -r["duplicate_billable"],
    )[:10]

    return {
        "method": (
            "turn-level：對每筆 Codex token_count delta，把去重鍵從 "
            "'session_id + 累計tuple' 換成 'fork root + 累計tuple' 重算"
        ),
        "fork_root_key": "session_meta.forked_from_id / parent_thread_id 追到底",
        "session_meta_id_unique_per_rollout_file": len(meta),
        "forked_files_in_window": sum(1 for m in meta.values() if m["forked"]),
        "logical_conversations": len(per_root),
        "codex_sessions_counted_now": len(meta),
        "current_billable": current_billable,
        "deduplicated_billable": dedup_billable,
        "duplicate_billable": duplicate_billable,
        "duplicate_share_of_codex_pct": (
            round(100 * duplicate_billable / current_billable, 2) if current_billable else 0.0
        ),
        "records_current": current_records,
        "records_deduplicated": dedup_records,
        "worst_roots": worst,
        "status": "settled_measurement",
        "caveat": (
            "此為 turn-level 定值（同一 root 內累計 tuple 完全相同的 delta 只計一次），"
            "不是上界。fork 檔內真正新增的 turn 有不同的累計 tuple，會被保留。"
        ),
    }


def _blank():
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_create_tokens": 0,
        "messages": 0,
        "sessions": set(),
        "cost_usd": 0.0,
        "cost_priced_billable": 0,
        "mission_billable": 0,
    }


def _finalize(bucket: dict) -> dict:
    billable = _billable_total(bucket)
    out = {k: v for k, v in bucket.items() if k != "sessions"}
    out["sessions"] = len(bucket["sessions"])
    out["billable_total"] = billable
    out["cost_usd"] = round(bucket["cost_usd"], 4)
    # 價目表只涵蓋 Claude 模型；Codex/gpt-* 無公開對照 → 誠實標示覆蓋率，
    # 不用 0 冒充「免費」。
    out["cost_coverage_pct"] = (
        round(100 * bucket["cost_priced_billable"] / billable, 1) if billable else 0.0
    )
    # v1 §5.4：上游分類器低估主線程 ⇒ 這個欄位不可當 KPI，欄名就地標注。
    out["mission_output_share_pct_upstream_NOT_KPI"] = (
        round(100 * bucket["mission_billable"] / billable, 1) if billable else 0.0
    )
    return out


def _session_blank():
    return {
        "billable": 0,
        "turns": 0,
        "first_ts": None,
        "last_ts": None,
        "agent_id": None,
        "agent_class": None,
        "provider": None,
        "effects": defaultdict(int),
        "effect_billable": defaultdict(int),
        "tool_repeats": defaultdict(int),
        "models": defaultdict(int),
    }


def analyze(date_start: date, date_end: date, top: int) -> dict:
    dims = {
        "by_agent_class": defaultdict(_blank),
        "by_agent_id": defaultdict(_blank),
        "by_model": defaultdict(_blank),
        "by_provider": defaultdict(_blank),
        "by_category": defaultdict(_blank),
        "by_date": defaultdict(_blank),
    }
    cross = defaultdict(_blank)          # agent_class × model
    agent_models = defaultdict(lambda: defaultdict(int))
    sessions = defaultdict(_session_blank)
    effect_billable = defaultdict(int)
    effect_turns = defaultdict(int)
    totals = _blank()
    turns = 0

    for turn in iter_attributed_turns(date_start, date_end):
        usage = _usage_breakdown(turn["usage"])
        billable = _billable_total(usage)
        model = turn["model"]
        category = _primary_category(turn["categories"], turn.get("is_subagent", False))
        cost = compute_cost_usd(usage, model)
        mission = billable if category in MISSION_OUTPUT_CATEGORIES else 0
        turns += 1

        keys = {
            "by_agent_class": turn["agent_class"],
            "by_agent_id": turn["agent_id"],
            "by_model": model,
            "by_provider": turn["provider"],
            "by_category": category,
            "by_date": turn["date"].isoformat(),
        }
        targets = [dims[d][k] for d, k in keys.items()]
        targets.append(cross[f"{turn['agent_class']} | {model}"])
        targets.append(totals)
        for bucket in targets:
            for field, value in usage.items():
                bucket[field] += value
            bucket["messages"] += 1
            bucket["sessions"].add(turn["session_id"])
            bucket["mission_billable"] += mission
            if cost is not None:
                bucket["cost_usd"] += cost
                bucket["cost_priced_billable"] += billable
        agent_models[turn["agent_id"]][model] += billable

        # --- v2：session 壽命 / 效力 / 空轉 ---
        effect = _turn_effect(turn)
        effect_billable[effect] += billable
        effect_turns[effect] += 1

        sess = sessions[turn["session_id"]]
        sess["billable"] += billable
        sess["turns"] += 1
        sess["agent_id"] = turn["agent_id"]
        sess["agent_class"] = turn["agent_class"]
        sess["provider"] = turn["provider"]
        sess["effects"][effect] += 1
        sess["effect_billable"][effect] += billable
        sess["models"][model] += billable
        ts = turn.get("timestamp")
        if ts is not None:
            if sess["first_ts"] is None or ts < sess["first_ts"]:
                sess["first_ts"] = ts
            if sess["last_ts"] is None or ts > sess["last_ts"]:
                sess["last_ts"] = ts
        for tool_name, digest in _tool_call_digests(turn):
            sess["tool_repeats"][f"{tool_name}#{digest}"] += 1

    def rank(mapping, limit=None):
        rows = sorted(
            ((k, _finalize(v)) for k, v in mapping.items()),
            key=lambda kv: -kv[1]["billable_total"],
        )
        if limit:
            rows = rows[:limit]
        return {k: v for k, v in rows}

    by_date = rank(dims["by_date"])
    by_agent_id_all = rank(dims["by_agent_id"])
    daily_values = [v["billable_total"] for v in by_date.values()]
    mean_daily = sum(daily_values) / len(daily_values) if daily_values else 0.0
    window_billable = _billable_total(totals)

    # --- session 摘要 ---
    def session_rows():
        for sid, s in sessions.items():
            lifetime_h = None
            if s["first_ts"] and s["last_ts"]:
                lifetime_h = round(
                    (s["last_ts"] - s["first_ts"]).total_seconds() / 3600, 2
                )
            write_like = s["effect_billable"]["write"] + s["effect_billable"]["mutating_command"]
            judgeable = s["billable"] - s["effect_billable"]["unknown_no_content"]
            top_repeat = max(
                ((k, v) for k, v in s["tool_repeats"].items()),
                key=lambda kv: kv[1],
                default=(None, 0),
            )
            yield {
                "session_id": sid,
                "agent_id": s["agent_id"],
                "agent_class": s["agent_class"],
                "provider": s["provider"],
                "billable": s["billable"],
                "turns": s["turns"],
                "first_seen_utc": s["first_ts"].isoformat() if s["first_ts"] else None,
                "last_seen_utc": s["last_ts"].isoformat() if s["last_ts"] else None,
                "lifetime_within_window_hours": lifetime_h,
                "effect_turns": dict(s["effects"]),
                "effectful_billable": write_like,
                "effectful_share_pct_lower_bound": (
                    round(100 * write_like / judgeable, 1) if judgeable else None
                ),
                "top_repeated_tool_call": top_repeat[0],
                "top_repeated_tool_call_count": top_repeat[1],
            }

    all_sessions = sorted(session_rows(), key=lambda r: -r["billable"])

    # --- 異常規則 ---
    anomalies = []

    # R1（v1 既有）：單日 > 2x 窗口均值
    for day, row in sorted(by_date.items()):
        if mean_daily > 0 and row["billable_total"] > DAILY_SPIKE_RATIO * mean_daily:
            anomalies.append({
                "kind": "daily_spike",
                "rule": f"single day billable > {DAILY_SPIKE_RATIO}x window mean",
                "date": day,
                "billable_total": row["billable_total"],
                "window_mean": round(mean_daily, 1),
                "ratio_vs_mean": round(row["billable_total"] / mean_daily, 2),
            })

    # R2（v2 新增）：單一 agent 佔窗口 > 20%
    for agent_id, row in by_agent_id_all.items():
        share = 100 * row["billable_total"] / window_billable if window_billable else 0.0
        if share > AGENT_CONCENTRATION_PCT:
            anomalies.append({
                "kind": "agent_concentration",
                "rule": f"single agent billable share > {AGENT_CONCENTRATION_PCT}% of window",
                "agent_id": agent_id,
                "billable_total": row["billable_total"],
                "share_pct": round(share, 2),
            })

    # R3（v2 新增）：單一 session 壽命 > 48h
    for row in all_sessions:
        lifetime = row["lifetime_within_window_hours"]
        if lifetime is not None and lifetime > SESSION_LIFETIME_HOURS:
            anomalies.append({
                "kind": "session_longevity",
                "rule": f"single session lifetime > {SESSION_LIFETIME_HOURS}h",
                "session_id": row["session_id"],
                "agent_id": row["agent_id"],
                "lifetime_within_window_hours": lifetime,
                "billable_total": row["billable"],
                "share_pct": round(
                    100 * row["billable"] / window_billable, 2
                ) if window_billable else 0.0,
                "note": "壽命只在觀測窗內量測；跨窗 session 的真實壽命 >= 此值",
            })

    # R4（v2 新增）：燒得多但零寫入的 session（noop / 空轉）
    for row in all_sessions:
        if row["provider"] == "codex":
            continue  # Codex 無工具內容，無法判定效力 —— 不猜
        if row["billable"] >= IDLE_BURN_MIN_BILLABLE and row["effectful_billable"] == 0:
            anomalies.append({
                "kind": "idle_burn_session",
                "rule": (
                    f"session billable >= {IDLE_BURN_MIN_BILLABLE} with zero "
                    "write / mutating turns in window"
                ),
                "session_id": row["session_id"],
                "agent_id": row["agent_id"],
                "billable_total": row["billable"],
                "turns": row["turns"],
                "effect_turns": row["effect_turns"],
            })

    # R5（v2 新增）：同一 session 內同 tool 同輸入重複 >=5 次（鬼打牆）
    for row in all_sessions:
        tool_key = row["top_repeated_tool_call"]
        repeats = row["top_repeated_tool_call_count"]
        if (
            tool_key
            and repeats >= CHURN_MIN_REPEATS
            and row["billable"] >= CHURN_MIN_BILLABLE
        ):
            anomalies.append({
                "kind": "repeat_churn",
                "rule": (
                    f"same tool + identical input repeated >= {CHURN_MIN_REPEATS} "
                    f"times in one session (billable >= {CHURN_MIN_BILLABLE})"
                ),
                "session_id": row["session_id"],
                "agent_id": row["agent_id"],
                "tool_call": tool_key,
                "repeats": repeats,
                "billable_total": row["billable"],
            })

    # 落檔日報 vs 重算真值：日報 pipeline 是否誠實反映用量。
    stored_drift = []
    cursor = date_start
    while cursor < date_end:
        key = cursor.isoformat()
        recomputed = by_date.get(key, {}).get("billable_total", 0)
        path = STORED_DAILY_DIR / f"daily_{key}.json"
        if path.exists():
            with path.open(encoding="utf-8") as fh:
                stored = json.load(fh)["totals"]["billable_total"]
        else:
            stored = None
        stored_drift.append({
            "date": key,
            "stored_daily_billable": stored,
            "recomputed_billable": recomputed,
            "stored_report_exists": path.exists(),
            "understated_by": (recomputed - stored) if stored is not None else None,
        })
        cursor += timedelta(days=1)

    judgeable_billable = window_billable - effect_billable["unknown_no_content"]
    effectfulness = {
        "definition": (
            "部門自有結構性口徑：turn 內是否出現寫檔工具（write）或明確變更型 "
            "Bash/工具（mutating_command）。不使用上游任務分類器。"
        ),
        "denominator": "Claude turns only（Codex telemetry 無工具內容，另計）",
        "billable_by_effect": dict(effect_billable),
        "turns_by_effect": dict(effect_turns),
        "effectful_share_pct_lower_bound": (
            round(
                100
                * (effect_billable["write"] + effect_billable["mutating_command"])
                / judgeable_billable,
                2,
            )
            if judgeable_billable
            else None
        ),
        "noop_text_only_share_pct_upper_bound": (
            round(100 * effect_billable["noop_text_only"] / judgeable_billable, 2)
            if judgeable_billable
            else None
        ),
        "caveat": (
            "mutating_command 是保守白名單 ⇒ effectful 是下界、noop/read_only 是上界。"
        ),
    }

    return {
        "report_type": "per_agent_per_model_token_breakdown",
        "version": 2,
        "produced_by": "resource_monitor",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window": {
            "start_utc_date": date_start.isoformat(),
            "end_utc_date_exclusive": date_end.isoformat(),
            "days": (date_end - date_start).days,
            "boundary": "UTC calendar day (matches token_usage_report.py)",
        },
        "source": {
            "telemetry": "claude_code_and_codex_jsonl via scripts/token_usage_report.py",
            "agent_attribution": "Claude project directory (repo root / .claude/worktrees / dispatch scratch) + subagent path",
            "dedupe": "message.id per turn (same as official daily report)",
            "priced_models": sorted(PRICING),
        },
        "kpi_rules": {
            "daily_spike": f"single day billable > {DAILY_SPIKE_RATIO}x window mean",
            "agent_concentration": f"single agent > {AGENT_CONCENTRATION_PCT}% of window billable",
            "session_longevity": f"single session lifetime > {SESSION_LIFETIME_HOURS}h",
            "idle_burn_session": f"billable >= {IDLE_BURN_MIN_BILLABLE} with zero effectful turn",
            "repeat_churn": f"identical tool call repeated >= {CHURN_MIN_REPEATS} times in a session",
        },
        "kpi_field_warnings": {
            "mission_output_share_pct_upstream_NOT_KPI": (
                "上游分類器把主線程大量真實產出歸進 bash_other / investigation"
                "（v1 §5.4），此欄嚴重低估主線程，不可作 KPI、不可對外引用。"
                "改用 effectfulness.effectful_share_pct_lower_bound。"
            ),
            "anomalies.idle_burn_session_NOT_A_PASS": (
                "idle_burn 規則需要 turn 內的工具內容才能判定效力，而 Codex telemetry "
                "只有 token_count、不含工具內容，因此 Codex 的每一個 session 都被排除在"
                "這條規則的分母之外（本窗 Codex 佔 billable 的 76.4%）。所以 "
                "idle_burn 觸發 0 件的意思是「Claude 側沒有大額純燒 ＋ Codex 側無法量測」，"
                "**不是「全平台檢查通過」**。任何把 0 件讀成健康的敘述都是誤讀。"
            ),
            "effectfulness_bounds": (
                "effectful_share 是下界（mutating_command 用保守白名單，會寫檔但沒命中 "
                "pattern 的腳本被算成 read_only）；noop / read_only 是上界。引用時一律"
                "帶「下界／上界」字樣，不可寫成點估計。"
            ),
        },
        "totals": _finalize(totals) | {"turns": turns},
        "by_date": by_date,
        "by_agent_class": rank(dims["by_agent_class"]),
        "by_agent_id_top": dict(list(by_agent_id_all.items())[:top]),
        "by_model": rank(dims["by_model"]),
        "by_provider": rank(dims["by_provider"]),
        "by_category": rank(dims["by_category"], top),
        "agent_class_x_model": rank(cross, top),
        "agent_id_model_mix_top": {
            agent: dict(sorted(models.items(), key=lambda kv: -kv[1]))
            for agent, models in sorted(
                agent_models.items(), key=lambda kv: -sum(kv[1].values())
            )[:top]
        },
        "effectfulness": effectfulness,
        "sessions_top": all_sessions[:top],
        "session_count": len(all_sessions),
        "anomalies": anomalies,
        "codex_duplicate_audit": audit_codex_duplicates(date_start, date_end),
        "stored_daily_drift": stored_drift,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--end", default=None, help="last INCLUDED UTC date (default: yesterday UTC)")
    parser.add_argument("--top", type=int, default=15)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    if args.end:
        end_inclusive = date.fromisoformat(args.end)
    else:
        end_inclusive = datetime.now(timezone.utc).date() - timedelta(days=1)
    date_end = end_inclusive + timedelta(days=1)
    date_start = date_end - timedelta(days=args.days)

    report = analyze(date_start, date_end, args.top)
    out = args.out or (
        DEPT_DIR / "memory" / f"token_breakdown_{end_inclusive.isoformat()}_{args.days}d.json"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"saved: {out}")
    print(json.dumps(report["totals"], ensure_ascii=False, indent=2))
    print(json.dumps(report["kpi_rules"], ensure_ascii=False, indent=2))
    print(json.dumps(report["effectfulness"], ensure_ascii=False, indent=2))
    print(json.dumps(report["codex_duplicate_audit"], ensure_ascii=False, indent=2)[:2500])
    print(f"anomalies: {len(report['anomalies'])}")
    for item in report["anomalies"][:25]:
        print("  -", json.dumps(item, ensure_ascii=False)[:240])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
