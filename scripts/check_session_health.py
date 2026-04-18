#!/usr/bin/env python3
"""
Session Health Check — 檢查當前 active sessions 是否需要 /clear

判定條件（命中任一就提示）：
  - lifetime_cost > $200（單一 session 累積超過此值）
  - lifetime_duration > 24h（session 跨日，cache 開始膨脹）
  - cache_read_tokens > 1B（單 session cache 讀取超過 10 億）
  - messages > 1500

用法：
  uv run python scripts/check_session_health.py             # 純文字輸出
  uv run python scripts/check_session_health.py --json      # JSON 輸出
  uv run python scripts/check_session_health.py --quiet     # 只在有警告時輸出（適合掛 cron）

可掛 cron 每小時跑一次，當有警告時會輸出非空，配合 mail/notify 即可。
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from session_drill_down import analyze_session, CLAUDE_PROJECTS_DIR

# 判定門檻
THRESHOLD_LIFETIME_COST = 200.0
THRESHOLD_LIFETIME_HOURS = 24.0
THRESHOLD_CACHE_READ = 1_000_000_000
THRESHOLD_MESSAGES = 1500

# 判定 active：mtime 在過去 N 分鐘內
ACTIVE_WINDOW_MIN = 60


def find_active_sessions():
    """掃出最近 ACTIVE_WINDOW_MIN 分鐘內有更新的 session。"""
    if not CLAUDE_PROJECTS_DIR.exists():
        return []
    now = datetime.now(timezone.utc)
    actives = []
    for p in CLAUDE_PROJECTS_DIR.glob("*.jsonl"):
        mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
        if (now - mtime).total_seconds() / 60 <= ACTIVE_WINDOW_MIN:
            actives.append(p)
    return actives


def evaluate(s: dict):
    """回傳 list of warnings; 空 list 代表健康。"""
    warns = []
    cost = s.get("lifetime_cost_usd", 0)
    msgs = s.get("lifetime_messages", 0)
    cr = s.get("lifetime_cache_read", 0)
    first = s.get("lifetime_first_ts")
    last = s.get("lifetime_last_ts")
    hours = (last - first).total_seconds() / 3600 if first and last else 0

    if cost > THRESHOLD_LIFETIME_COST:
        warns.append(f"lifetime_cost ${cost:.0f} > ${THRESHOLD_LIFETIME_COST:.0f}")
    if hours > THRESHOLD_LIFETIME_HOURS:
        warns.append(f"lifetime_duration {hours:.1f}h > {THRESHOLD_LIFETIME_HOURS:.0f}h")
    if cr > THRESHOLD_CACHE_READ:
        warns.append(f"cache_read {cr/1e9:.2f}B > {THRESHOLD_CACHE_READ/1e9:.1f}B tokens")
    if msgs > THRESHOLD_MESSAGES:
        warns.append(f"messages {msgs} > {THRESHOLD_MESSAGES}")
    return warns


def main():
    ap = argparse.ArgumentParser(description="Active session health check")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true", help="只在有警告時輸出（cron-friendly）")
    args = ap.parse_args()

    active = find_active_sessions()
    today = datetime.now(timezone.utc).date()

    findings = []
    for path in active:
        s = analyze_session(path, date_filter=today)
        if not s:
            # 不是今天才動但近期被 touch（rare），跑 lifetime
            s = analyze_session(path)
            if not s:
                continue
        warns = evaluate(s)
        findings.append({
            "session_id": s["session_id"],
            "lifetime_cost_usd": round(s.get("lifetime_cost_usd", 0), 2),
            "lifetime_messages": s.get("lifetime_messages", 0),
            "lifetime_hours": round(
                ((s["lifetime_last_ts"] - s["lifetime_first_ts"]).total_seconds() / 3600)
                if s.get("lifetime_first_ts") and s.get("lifetime_last_ts") else 0, 1
            ),
            "cache_read_billion": round(s.get("lifetime_cache_read", 0) / 1e9, 2),
            "warnings": warns,
            "needs_clear": bool(warns),
        })

    has_warnings = any(f["needs_clear"] for f in findings)

    if args.json:
        print(json.dumps({
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "active_sessions": len(findings),
            "any_warnings": has_warnings,
            "findings": findings,
        }, ensure_ascii=False, indent=2))
        return

    if args.quiet and not has_warnings:
        return

    if not findings:
        print("No active sessions in the last hour.")
        return

    print(f"# Session Health Check — {datetime.now().astimezone().isoformat(timespec='minutes')}")
    print(f"Active sessions (last {ACTIVE_WINDOW_MIN}min): {len(findings)}\n")
    for f in findings:
        flag = "⚠️ " if f["needs_clear"] else "✅ "
        print(f"{flag}`{f['session_id'][:8]}` — ${f['lifetime_cost_usd']} / "
              f"{f['lifetime_messages']:,} msgs / {f['lifetime_hours']}h / "
              f"cache={f['cache_read_billion']}B")
        for w in f["warnings"]:
            print(f"    • {w}")
    if has_warnings:
        print("\n建議：在該 session 跑 `/clear` 開新對話，避免 cache 進一步膨脹。")


if __name__ == "__main__":
    main()
