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

Thresholds load from `config/token_policy.json > session_health`.
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from session_drill_down import analyze_session, CLAUDE_PROJECTS_DIR

DEFAULT_POLICY = {
    "lifetime_cost_usd": 200.0,
    "lifetime_hours": 24.0,
    "cache_read_tokens": 1_000_000_000,
    "messages": 1500,
    "active_window_minutes": 60,
}
POLICY_PATH = Path(__file__).resolve().parents[1] / "config" / "token_policy.json"


def load_session_health_policy() -> dict:
    """Load session-health thresholds from config/token_policy.json with safe fallback."""
    if not POLICY_PATH.exists():
        return dict(DEFAULT_POLICY)
    try:
        payload = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    except ValueError:
        return dict(DEFAULT_POLICY)
    section = payload.get("session_health") if isinstance(payload, dict) else None
    if not isinstance(section, dict):
        return dict(DEFAULT_POLICY)
    return {
        "lifetime_cost_usd": float(section.get("lifetime_cost_usd", DEFAULT_POLICY["lifetime_cost_usd"])),
        "lifetime_hours": float(section.get("lifetime_hours", DEFAULT_POLICY["lifetime_hours"])),
        "cache_read_tokens": int(section.get("cache_read_tokens", DEFAULT_POLICY["cache_read_tokens"])),
        "messages": int(section.get("messages", DEFAULT_POLICY["messages"])),
        "active_window_minutes": int(section.get("active_window_minutes", DEFAULT_POLICY["active_window_minutes"])),
    }


def find_active_sessions(active_window_min: int):
    """掃出最近 active_window_min 分鐘內有更新的 session。"""
    if not CLAUDE_PROJECTS_DIR.exists():
        return []
    now = datetime.now(timezone.utc)
    actives = []
    for p in CLAUDE_PROJECTS_DIR.glob("*.jsonl"):
        mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
        if (now - mtime).total_seconds() / 60 <= active_window_min:
            actives.append(p)
    return actives


def evaluate(s: dict, policy: dict):
    """回傳 list of warnings; 空 list 代表健康。"""
    warns = []
    cost = s.get("lifetime_cost_usd", 0)
    msgs = s.get("lifetime_messages", 0)
    cr = s.get("lifetime_cache_read", 0)
    first = s.get("lifetime_first_ts")
    last = s.get("lifetime_last_ts")
    hours = (last - first).total_seconds() / 3600 if first and last else 0

    if cost > policy["lifetime_cost_usd"]:
        warns.append(f"lifetime_cost ${cost:.0f} > ${policy['lifetime_cost_usd']:.0f}")
    if hours > policy["lifetime_hours"]:
        warns.append(f"lifetime_duration {hours:.1f}h > {policy['lifetime_hours']:.0f}h")
    if cr > policy["cache_read_tokens"]:
        warns.append(f"cache_read {cr/1e9:.2f}B > {policy['cache_read_tokens']/1e9:.1f}B tokens")
    if msgs > policy["messages"]:
        warns.append(f"messages {msgs} > {policy['messages']}")
    return warns


def main():
    ap = argparse.ArgumentParser(description="Active session health check")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true", help="只在有警告時輸出（cron-friendly）")
    args = ap.parse_args()

    policy = load_session_health_policy()
    active_window_min = policy["active_window_minutes"]
    active = find_active_sessions(active_window_min=active_window_min)
    today = datetime.now(timezone.utc).date()

    findings = []
    for path in active:
        s = analyze_session(path, date_filter=today)
        if not s:
            # 不是今天才動但近期被 touch（rare），跑 lifetime
            s = analyze_session(path)
            if not s:
                continue
        warns = evaluate(s, policy)
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
            "policy_path": str(POLICY_PATH),
            "policy": policy,
            "active_sessions": len(findings),
            "any_warnings": has_warnings,
            "findings": findings,
        }, ensure_ascii=False, indent=2))
        return

    if args.quiet and not has_warnings:
        return

    if not findings:
        print(f"No active sessions in the last {active_window_min} minutes.")
        return

    print(f"# Session Health Check — {datetime.now().astimezone().isoformat(timespec='minutes')}")
    print(f"Active sessions (last {active_window_min}min): {len(findings)}\n")
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
