#!/usr/bin/env python3
"""每日精選導讀 = 例行任務（boss directive 2026-06-22）。

它本來不是排程任務（06-21 上線首發後就沒有任何機制每天重生），導致 06-22 沒有。
本腳本「冪等地」每天把一個 daily_digest 任務排進 next_tasks，讓（已修好的）hourly
dispatch 接手寫作 + 發佈。冪等：今天已發 digest 或池中已有今日 digest 任務 → skip。

排程：runtime_schedules `digest_daily_enqueue`（每日 09:00 台北，走 piggy-back
run_due_jobs）。實際寫作由 dispatch agent 依本檔 description 的 brief 執行。

用法：
  uv run python scripts/enqueue_daily_digest.py            # apply
  uv run python scripts/enqueue_daily_digest.py --dry-run  # 預覽
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
NEXT_TASKS = ROOT / "storage" / "next_tasks.json"
FEED = ROOT / "storage" / "reports" / "feed.json"
TPE = ZoneInfo("Asia/Taipei")

DESCRIPTION = (
    "寫今日『每日精選導讀』編輯專欄並立即發佈。規格：(1) 統整近一日平台已發佈的研究/"
    "策略/市場文章，挑 3-5 則做有觀點的編輯導讀（不是流水帳摘要）；(2) reader-facing，"
    "**必走 anti-ai-style**（寫前讀 prompt-templates、寫後跑 editor-sop 9-checklist）；"
    "(3) 走 feed-publisher 正式入口發佈，**details.content_type 必設 'daily_digest'**"
    "（首頁 getDigestColumn 靠此辨識），tags 含 '精選導讀'，title 以 '每日精選導讀｜' 起頭；"
    "(4) 事件驅動／時效內容立即 published（非 draft）。資料來源與對應 K 編號要標清楚。"
)


def _today_str() -> str:
    return datetime.now(TPE).strftime("%Y-%m-%d")


def _load(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return default


def _digest_published_today(today: str) -> bool:
    feed = _load(FEED, [])
    items = feed if isinstance(feed, list) else feed.get("items", [])
    for it in items:
        if not isinstance(it, dict):
            continue
        pub = str(it.get("published_at") or "")[:10]
        if pub != today:
            continue
        details = it.get("details") or {}
        if str(details.get("content_type", "")) == "daily_digest" or "每日精選導讀" in str(it.get("title", "")):
            return True
    return False


def _digest_task_exists_today(tasks: list, task_id: str) -> bool:
    for t in tasks:
        if not isinstance(t, dict):
            continue
        # 同 id（今天）任何狀態都算已存在；或當天還在進行中的 daily_digest 任務
        if t.get("id") == task_id:
            return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    today = _today_str()
    task_id = f"daily_digest_{today.replace('-', '')}"

    if _digest_published_today(today):
        print(f"[digest-enqueue] skip: 今日({today}) digest 已發佈")
        return 0

    tasks = _load(NEXT_TASKS, [])
    if not isinstance(tasks, list):
        print("[digest-enqueue] ERROR: next_tasks.json 非 list，abort（不亂改 schema）", file=sys.stderr)
        return 1

    if _digest_task_exists_today(tasks, task_id):
        print(f"[digest-enqueue] skip: 任務 {task_id} 已在池中")
        return 0

    task = {
        "id": task_id,
        "title": "[daily_digest] 寫今日每日精選導讀專欄並發佈",
        "description": DESCRIPTION,
        "task_type": "daily_digest",
        "priority": 1,
        "status": "pending",
        "dispatch_lane": "agent",
        "created_at": datetime.now(TPE).isoformat(),
        "source": "scheduled",
        "tags": ["daily_digest", "reader_facing", "精選導讀"],
    }

    if args.dry_run:
        print(f"[digest-enqueue] DRY-RUN would add: {task_id} (today={today})")
        return 0

    tasks.append(task)
    tmp = NEXT_TASKS.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(tasks, ensure_ascii=False, indent=2))
    tmp.replace(NEXT_TASKS)
    print(f"[digest-enqueue] added {task_id} (P1 daily_digest); pool now {len(tasks)} tasks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
