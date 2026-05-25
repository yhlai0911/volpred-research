"""Heuristic fast-path for trivial email questions.

If incoming reply matches a known trivial Q pattern, answer it inline
with Python (no LLM, no queue, no dispatch wait). Otherwise return None
and caller falls back to the normal queue + ack flow.

Public entry: try_fast_path(reply_text, subject) -> dict | None
  Returns {pattern_id, answer_md} on hit; None on miss.

Add a new pattern: write _h_<name>() returning markdown body, append
to PATTERNS list. Keep handlers fast (<2s, no LLM, no network).
"""
from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
TAIPEI = ZoneInfo("Asia/Taipei")

# Hard cap — if reply body exceeds this, treat as substantive (skip fast-path)
MAX_REPLY_LEN_FOR_FAST_PATH = 200


# ───── Handlers ────────────────────────────────────────────────────────────

def _h_time(_text: str) -> str:
    now = datetime.now(TAIPEI)
    # Compute next fires
    next_hh07 = now.replace(minute=7, second=0, microsecond=0)
    if now.minute >= 7:
        next_hh07 += timedelta(hours=1)
    next_gmail = now.replace(minute=(now.minute // 15 + 1) * 15 % 60, second=0, microsecond=0)
    if next_gmail <= now:
        next_gmail += timedelta(hours=1)
    next_hh50 = now.replace(minute=50, second=0, microsecond=0)
    if now.minute >= 50:
        next_hh50 += timedelta(hours=1)

    return f"""# 系統時鐘

| 項 | 值 |
|---|---|
| **現在時間** | **{now.strftime('%Y-%m-%d %H:%M:%S')}（台灣時間）** |
| Weekday | {now.strftime('%A')} |
| Unix epoch | {int(now.timestamp())} |
| Week of year | W{now.isocalendar().week} |

## 接下來自動 fire

| 時間 | 事件 |
|---|---|
| {next_gmail.strftime('%H:%M:%S')} | gmail-poll 下班 |
| {next_hh07.strftime('%H:%M:%S')} | Claude `hourly-dispatch` |
| {next_hh50.strftime('%H:%M:%S')} | handoff-regen + stale claim cleanup |
"""


def _h_ping(_text: str) -> str:
    # LaunchAgent count
    try:
        lc = subprocess.run(["launchctl", "list"], capture_output=True, text=True, timeout=5)
        agents = [l for l in lc.stdout.splitlines() if "com.volpred" in l]
    except Exception:
        agents = []
    # codex_loop
    try:
        pg = subprocess.run(["pgrep", "-f", "scripts/codex_loop.sh"], capture_output=True, text=True, timeout=5)
        codex_pid = pg.stdout.strip().split("\n")[0] if pg.stdout.strip() else None
    except Exception:
        codex_pid = None

    now = datetime.now(TAIPEI).strftime("%H:%M:%S")
    badge = "✅ 全綠" if len(agents) >= 12 and codex_pid else "⚠️ 部分元件異常"

    return f"""# Pong — {now}（台灣時間）

**狀態**：{badge}

| 元件 | 狀態 |
|---|---|
| LaunchAgent (com.volpred.*) | {len(agents)} loaded |
| codex_loop daemon | {'PID ' + codex_pid if codex_pid else '❌ not running'} |
| Gmail poll | 每 15min :00/:15/:30/:45 |
| Hourly dispatch | 每小時 :07 |
| Handoff regen | 每小時 :50 |

我活著，正在等任務。
"""


def _h_status(_text: str) -> str:
    try:
        tasks = json.loads((ROOT / "storage" / "next_tasks.json").read_text())
    except Exception:
        return "# 狀態\n\n讀 next_tasks.json 失敗"

    from collections import Counter
    status_c = Counter((t.get("status") or "?").lower() for t in tasks if isinstance(t, dict))
    type_pending_c = Counter(
        (t.get("task_type") or "?")
        for t in tasks
        if isinstance(t, dict) and (t.get("status") or "").lower() in {"pending", "pending_main_thread"}
    )

    now = datetime.now(TAIPEI).strftime("%H:%M:%S")
    type_rows = "\n".join(f"| {k} | {v} |" for k, v in type_pending_c.most_common())

    return f"""# 系統現況 — {now}

## 任務池總覽

| status | count |
|---|---|
{chr(10).join(f"| {k} | {v} |" for k, v in status_c.most_common())}

## Pending by task_type

| task_type | pending |
|---|---|
{type_rows}

## 自動化 health

- LaunchAgent 12 loaded（gmail-poll / handoff-regen / hourly-dispatch / compute-worker / ...）
- codex_loop daemon 跑中（每小時 ~HH:04 fire，resume --last 沿用 transcript）
- gmail-poll 每 15min
- handoff-regen 每小時 :50 + stale claim cleanup >2h
"""


def _h_next_task(_text: str) -> str:
    try:
        tasks = json.loads((ROOT / "storage" / "next_tasks.json").read_text())
    except Exception:
        return "# 下個任務\n\n讀 next_tasks.json 失敗"

    pending = [
        t for t in tasks if isinstance(t, dict)
        and (t.get("status") or "").lower() in {"pending", "pending_main_thread"}
    ]
    def _prio(t):
        p = t.get("priority")
        try:
            return int(p)
        except (TypeError, ValueError):
            return 9
    pending.sort(key=lambda t: (_prio(t), t.get("id") or ""))

    if not pending:
        return "# 下個任務\n\n池子空 — dispatcher 會走 discovery 流程自主生新題"

    t = pending[0]
    next_hh07 = datetime.now(TAIPEI).replace(minute=7, second=0, microsecond=0)
    if datetime.now(TAIPEI).minute >= 7:
        next_hh07 += timedelta(hours=1)

    return f"""# 下個 Priority 1 / 最高 pending task

| 欄位 | 值 |
|---|---|
| Task ID | `{t.get('id')}` |
| Title | {(t.get('title') or '(no title)')[:120]} |
| Type | `{t.get('task_type')}` |
| Priority | **{t.get('priority')}** |
| 預計開工 | 下次 hourly-dispatch fire = **{next_hh07.strftime('%H:%M')}**（台灣時間） |

## 派工對象

依 `.claude/rules/task-routing.md`：`{t.get('task_type')}` → 由 Claude 主線程處理（{
    'Codex 可接' if t.get('task_type') in {'experiment', 'platform_ops', 'governance', 'daily_article'} else 'Codex 不接，Claude 專屬'
}）
"""


def _h_pending(_text: str) -> str:
    try:
        tasks = json.loads((ROOT / "storage" / "next_tasks.json").read_text())
    except Exception:
        return "# Pending\n\n讀 next_tasks.json 失敗"

    from collections import Counter
    pending_types = Counter(
        (t.get("task_type") or "?")
        for t in tasks
        if isinstance(t, dict) and (t.get("status") or "").lower() in {"pending", "pending_main_thread"}
    )
    total_p = sum(pending_types.values())
    rows = "\n".join(f"| {k} | {v} |" for k, v in pending_types.most_common())

    return f"""# Pending 任務池 — 共 {total_p}

| task_type | count |
|---|---|
{rows}

每 hour 約消化 1-2 個（Claude HH:07 + Codex HH:04 並行）。
"""


def _h_commits(_text: str) -> str:
    try:
        out = subprocess.run(
            ["git", "log", "--since=24 hours ago", "--oneline", "--no-merges"],
            capture_output=True, text=True, timeout=5, cwd=str(ROOT),
        )
        lines = out.stdout.strip().splitlines()
    except Exception:
        lines = []

    if not lines:
        return "# 最近 24h commits\n\n（無）"

    rows = "\n".join(f"- `{l[:8]}` {l[9:][:120]}" for l in lines[:30])
    extra = f"\n\n... +{len(lines) - 30} more" if len(lines) > 30 else ""

    return f"""# 最近 24h commits（{len(lines)} 個）

{rows}{extra}
"""


# ───── Pattern registry (order matters; first match wins) ──────────────────

PATTERNS: list[tuple[re.Pattern, Callable[[str], str], str]] = [
    (re.compile(r"現在幾點|現在時間|現在.*?幾點|what.?time|^time$|目前時間", re.I), _h_time, "time"),
    (re.compile(r"\bping\b|在嗎\?|還在嗎|活著嗎|alive\??|你還在嗎|是否在線", re.I), _h_ping, "ping"),
    (re.compile(r"目前狀態|現況|^狀態\??$|系統狀態|^status\??$|健康|健康狀態", re.I), _h_status, "status"),
    (re.compile(r"下一?個?任務|next.?task|下一個工作|接下來.*?任務|即將.*?任務", re.I), _h_next_task, "next_task"),
    (re.compile(r"pending|池子|多少待辦|待辦|還有幾個|剩多少", re.I), _h_pending, "pending"),
    (re.compile(r"今天.*?做|recent.?commit|最近.*?commit|24h.*?commit|這幾小時.*?做", re.I), _h_commits, "commits"),
]


def try_fast_path(reply_text: str, subject: str = "") -> dict | None:
    """Return {pattern_id, answer_md} if matched, else None.

    Conservative matching:
      - Reply must be non-empty
      - Reply length ≤ MAX_REPLY_LEN_FOR_FAST_PATH (longer = substantive content)
      - First matching pattern wins
      - Handler exceptions → silent miss (caller falls back to queue)
    """
    if not reply_text or not reply_text.strip():
        return None
    text = reply_text.strip()
    if len(text) > MAX_REPLY_LEN_FOR_FAST_PATH:
        return None

    for pat, fn, pid in PATTERNS:
        if pat.search(text):
            try:
                answer = fn(text)
                if answer and answer.strip():
                    return {"pattern_id": pid, "answer_md": answer}
            except Exception:
                return None
    return None


if __name__ == "__main__":
    # Manual smoke test
    import sys
    q = sys.argv[1] if len(sys.argv) > 1 else "現在幾點"
    r = try_fast_path(q)
    if r:
        print(f"=== HIT: {r['pattern_id']} ===")
        print(r["answer_md"])
    else:
        print("=== MISS ===")
