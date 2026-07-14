#!/usr/bin/env python3
"""ops_snapshot — session 定位的單一儀器（stdlib-only，<1s）。

refactor_plan_token_ops_waste WS1b（2026-07-14）：token 週報顯示 repo-navigation
bash 一週 1,945 則 / 10.1M billable —— 每個新 session 都用十幾則 ls / git status /
jq 重新自我定位。本 script 把「session 開頭需要知道的運營狀態」聚合成一份 compact
JSON，一次呼叫取代整輪翻抽屜。

用法：
    uv run python scripts/ops_snapshot.py            # compact JSON to stdout
    uv run python scripts/ops_snapshot.py --pretty   # 縮排版（人讀）

定位邊界（anti-stacking）：本 script 是「狀態定位」，不是健康裁決 ——
result-level 健康檢查的 owner 是 scripts/daily_checkup.py，alert 裁決的 owner 是
scripts/check_alerts.py。本 script 只讀不寫、不寄信、不判 breach。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
STORAGE = ROOT / "storage"
TPE = ZoneInfo("Asia/Taipei")


def _read_json(path: Path):
    try:
        return json.loads(path.read_text())
    except Exception as e:  # noqa: BLE001
        return {"_error": f"{type(e).__name__}: {e}"}


def _age_min(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        ts = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return round((datetime.now(timezone.utc) - ts).total_seconds() / 60, 1)
    except Exception as e:  # noqa: BLE001
        print(f"[ops_snapshot] WARN bad timestamp {iso!r}: {e}", file=sys.stderr)
        return None


def _git(args: list[str]) -> str:
    try:
        return subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=10
        ).stdout.strip()
    except Exception as e:  # noqa: BLE001
        return f"_error:{type(e).__name__}"


def backbone() -> dict:
    st = _read_json(STORAGE / "ops" / "dispatch_state.json")
    if "_error" in st:
        return {"error": st["_error"]}
    return {
        "heartbeat_age_min": _age_min(st.get("last_heartbeat_at")),
        "current_job": st.get("current_job"),
        "current_jobs_n": len(st.get("current_jobs") or []),
        "last_fire_age_min": _age_min(st.get("last_fire_at")),
        "auth_blocked": st.get("auth_blocked"),
        "last_completions": [
            {
                "at": c.get("completed_at") or c.get("finished_at"),
                "status": c.get("verdict") or c.get("status") or c.get("outcome"),
            }
            for c in (st.get("completions") or [])[-3:]
        ],
    }


def queue() -> dict:
    d = _read_json(STORAGE / "next_tasks.json")
    tasks = d.get("tasks", d) if isinstance(d, dict) else d
    if not isinstance(tasks, list):
        return {"error": "unexpected next_tasks shape"}
    out: dict[str, object] = {}
    pending = [t for t in tasks if t.get("status") == "pending"]
    by_prio: dict[str, int] = {}
    for t in pending:
        k = f"p{t.get('priority', '?')}"
        by_prio[k] = by_prio.get(k, 0) + 1
    out["pending"] = len(pending)
    out["pending_by_priority"] = dict(sorted(by_prio.items()))
    out["in_flight"] = sum(1 for t in tasks if t.get("status") in ("claimed", "in_progress"))
    out["blocked"] = sum(1 for t in tasks if t.get("status") == "blocked")
    out["top_pending"] = [
        {"id": t.get("id"), "p": t.get("priority"), "type": t.get("task_type")}
        for t in sorted(pending, key=lambda x: (x.get("priority", 9)))[:5]
    ]
    return out


def content_pool() -> dict:
    feed = STORAGE / "reports" / "feed.json"
    if not feed.exists():
        return {"error": "feed.json missing"}
    try:
        # 只數 status，不載整檔進 caller context —— 這正是本儀器存在的理由
        d = json.loads(feed.read_text())
        arts = d.get("articles", d) if isinstance(d, dict) else d
        drafts = sum(1 for a in arts if a.get("status") == "draft")
        published_today = sum(
            1
            for a in arts
            if a.get("status") == "published"
            and str(a.get("published_at", ""))[:10]
            == datetime.now(TPE).strftime("%Y-%m-%d")
        )
        return {"drafts": drafts, "published_today": published_today}
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}


def alerts_state() -> dict:
    dedup = _read_json(STORAGE / "ops" / "alert_dedup.json")
    alerts = dedup.get("alerts") or {}
    if not isinstance(alerts, dict):
        return {"recent": []}
    now_recent = []
    for v in alerts.values():
        age = _age_min(v.get("sent_at") or v.get("ts"))
        if age is not None and age < 24 * 60:
            now_recent.append(
                {"level": v.get("level"), "title": str(v.get("title", ""))[:60], "age_min": age}
            )
    now_recent.sort(key=lambda x: x["age_min"])
    return {"sent_last_24h": len(now_recent), "recent": now_recent[:5]}


def git_state() -> dict:
    ahead = _git(["rev-list", "--count", "origin/main..main"])
    dirty = _git(["status", "--porcelain"])
    wts = _git(["worktree", "list", "--porcelain"]).count("worktree ")
    return {
        "branch": _git(["rev-parse", "--abbrev-ref", "HEAD"]),
        "ahead_of_origin": ahead,
        "dirty_files": len(dirty.splitlines()) if dirty and not dirty.startswith("_error") else 0,
        "worktrees": wts,
        "head": _git(["log", "-1", "--format=%h %s"])[:80],
    }


def pointers() -> dict:
    hand = STORAGE / "ops" / "handoff_latest.md"
    out = {}
    if hand.exists():
        out["handoff_age_min"] = round(
            (datetime.now(timezone.utc).timestamp() - hand.stat().st_mtime) / 60, 1
        )
    out["health_instrument"] = "uv run python scripts/daily_checkup.py"
    out["dispatcher"] = "uv run python scripts/continue_task_dispatch.py --dry-run"
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pretty", action="store_true")
    args = ap.parse_args()
    snap = {
        "ts_taipei": datetime.now(TPE).strftime("%Y-%m-%d %H:%M:%S"),
        "backbone": backbone(),
        "queue": queue(),
        "content_pool": content_pool(),
        "alerts": alerts_state(),
        "git": git_state(),
        "pointers": pointers(),
    }
    print(json.dumps(snap, ensure_ascii=False, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
