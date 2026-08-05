#!/usr/bin/env python3
"""D43(1) 今日 token 實況盤點：小時分佈 × session 歸屬 × 效力 × 停擺窗。

重用部門既有工具 token_breakdown 的 turn 迭代與效力分類原語，不重寫 token 會計。
輸出 JSON 到 --out。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path("/Users/yhlai0911/volpred-research")
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "storage/org/departments/resource_monitor/tools"))

from token_usage_report import _billable_total, _usage_breakdown  # noqa: E402
import token_breakdown as tb  # noqa: E402

TPE = timezone(timedelta(hours=8))
TODAY = date(2026, 8, 5)
# 停擺窗（經理給定）：15:5x → 18:46 台灣時間，取 15:50 起算
OUTAGE_START = datetime(2026, 8, 5, 15, 50, tzinfo=TPE)
OUTAGE_END = datetime(2026, 8, 5, 18, 46, tzinfo=TPE)

DEPTS = [
    "resource_monitor", "platform_eng", "research", "content",
    "paper", "member_success", "governance", "manager",
]
DEPT_RE = re.compile("|".join(re.escape(d) for d in DEPTS))


def parse_ts(turn):
    ts = turn.get("timestamp")
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(TPE)


def turn_text(turn):
    """turn 內所有 tool input 的字串，供部門歸屬啟發式用。"""
    out = []
    for item in turn.get("content") or []:
        if isinstance(item, dict) and item.get("type") == "tool_use":
            try:
                out.append(json.dumps(item.get("input", {}), ensure_ascii=False))
            except (TypeError, ValueError):
                out.append(repr(item.get("input")))
    return " ".join(out)


def blank():
    return {"billable": 0, "turns": 0, "effects": defaultdict(int)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    # UTC 掃描窗要蓋住台灣 08-05 全日
    d0, d1 = date(2026, 8, 4), date(2026, 8, 6)

    by_hour = defaultdict(blank)
    by_session = defaultdict(blank)
    by_class = defaultdict(blank)
    by_provider = defaultdict(blank)
    outage = defaultdict(blank)          # session -> 停擺窗內
    session_meta = {}
    dept_hits = defaultdict(lambda: defaultdict(int))
    total = blank()

    for turn in tb.iter_attributed_turns(d0, d1):
        dt = parse_ts(turn)
        if dt is None or dt.date() != TODAY:
            continue
        bill = _billable_total(_usage_breakdown(turn.get("usage") or {}))
        if bill <= 0 and not (turn.get("content")):
            continue
        eff = tb._turn_effect(turn)
        sid = turn.get("session_id") or "?"
        prov = "codex" if turn.get("provider") == "codex" else "claude"
        key = f"{prov}:{sid}"

        for bucket in (by_hour[dt.strftime("%H")], by_session[key],
                       by_class[turn.get("agent_class", "?")],
                       by_provider[prov], total):
            bucket["billable"] += bill
            bucket["turns"] += 1
            bucket["effects"][eff] += 1

        meta = session_meta.setdefault(key, {
            "agent_class": turn.get("agent_class"),
            "agent_id": turn.get("agent_id"),
            "first": dt.isoformat(), "last": dt.isoformat(),
        })
        meta["last"] = max(meta["last"], dt.isoformat())
        meta["first"] = min(meta["first"], dt.isoformat())

        if prov == "claude":
            for m in set(DEPT_RE.findall(turn_text(turn))):
                dept_hits[key][m] += 1

        if OUTAGE_START <= dt < OUTAGE_END:
            b = outage[key]
            b["billable"] += bill
            b["turns"] += 1
            b["effects"][eff] += 1

    # 近 7 日每日 billable（並行倍數的對照基線）
    daily = defaultdict(int)
    daily_sessions = defaultdict(set)
    for turn in tb.iter_attributed_turns(date(2026, 7, 29), date(2026, 8, 6)):
        dt = parse_ts(turn)
        if dt is None:
            continue
        prov = "codex" if turn.get("provider") == "codex" else "claude"
        bill = _billable_total(_usage_breakdown(turn.get("usage") or {}))
        daily[f"{dt.date().isoformat()}|{prov}"] += bill
        daily_sessions[f"{dt.date().isoformat()}|{prov}"].add(turn.get("session_id"))

    def fin(b):
        return {"billable": b["billable"], "turns": b["turns"],
                "effects": dict(b["effects"])}

    payload = {
        "generated_at_tpe": datetime.now(TPE).isoformat(),
        "window": "Asia/Taipei 2026-08-05 00:00 → now",
        "outage_window_tpe": [OUTAGE_START.isoformat(), OUTAGE_END.isoformat()],
        "total": fin(total),
        "by_provider": {k: fin(v) for k, v in by_provider.items()},
        "by_hour": {k: fin(v) for k, v in sorted(by_hour.items())},
        "by_agent_class": {k: fin(v) for k, v in by_class.items()},
        "by_session": {
            k: {**fin(v), **session_meta.get(k, {}),
                "dept_signals": dict(sorted(dept_hits.get(k, {}).items(),
                                            key=lambda x: -x[1])[:4])}
            for k, v in sorted(by_session.items(), key=lambda x: -x[1]["billable"])
        },
        "outage_by_session": {
            k: {**fin(v), "dept_signals": dict(sorted(dept_hits.get(k, {}).items(),
                                                      key=lambda x: -x[1])[:4])}
            for k, v in sorted(outage.items(), key=lambda x: -x[1]["billable"])
        },
        "daily_billable_last_days": {
            k: {"billable": v, "sessions": len(daily_sessions[k])}
            for k, v in sorted(daily.items())
        },
    }
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("written", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
