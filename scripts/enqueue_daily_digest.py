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
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
NEXT_TASKS = ROOT / "storage" / "next_tasks.json"
FEED = ROOT / "storage" / "reports" / "feed.json"
TPE = ZoneInfo("Asia/Taipei")

DESCRIPTION = (
    "寫一篇『每日精選導讀』專題策展長文並立即發佈。這是 editorial curation 不是逐篇摘要。"
    "規格：(1) **先選定一個專題（theme）**（例：波動率模型複雜度天花板 / MOVE-VIX 跨資產分裂 / "
    "尾部風險 VaR 監管現實 / 研究誠實 audit），整篇圍繞單一 thesis；(2) **從過去累積的 archive "
    "撈同主題的 3-6 篇舊文**（用 grep/jq 掃 storage/reports/feed.json 的 title/tags），發佈日期須"
    "橫跨 >1 週、至少 3 篇來自當天以外 — **不可只挑今天/昨天剛發的湊數**；排除 digest 自身與每日建議"
    "類日報；(3) **掛一個最近時事/市場狀態 hook 開場**（當前 VIX 水位 / 近期 FOMC·NFP·CPI / MOVE-VIX "
    "分裂等，數據須取自真實 archive 文章或 results.json，不可臆造），把過去研究與當下市場連起來；"
    "(4) **串成有觀點的敘事弧**（演進/對照/反差，告訴讀者『這主題上我們做過什麼、結論如何演進、彼此"
    "如何呼應』），不是逐篇『這篇講 X、那篇講 Y』的並列摘要；(5) 文末才列本期精選連結"
    "（id + 一句話，連結 https://volpred.zeabur.app/v3/reports/<mile_id>）。"
    "輸出硬規則：reader-facing **必走 anti-ai-style**（寫前讀 prompt-templates、寫後跑 editor-sop "
    "9-checklist）+ 文末懶人包圖組；走 feed-publisher 正式入口發佈，**details.content_type 必設 "
    "'daily_digest'**（首頁 getDigestColumn 靠此辨識），**curated 來源文章 slug 須寫進 "
    "details.digest_articles 陣列**（前端側欄『本期精選』唯一資料源，每個 slug 須對應 archive 中"
    "真實存在的已發佈文章；陣列順序 = 顯示順序），tags 含 '精選導讀'，title 用專題式標題，"
    "**不可**以 '每日精選導讀｜' 起頭（前端區塊已顯示此標頭，重複會觸發 content-quality alert），"
    "也不可寫成『今日 N 篇摘要』；content 須為完整繁中 Markdown 單篇 essay 且至少含一張圖 "
    "![alt](url)；立即 published（非 draft）。正文每個數字須可對應實驗 results.json 或數據源，K 編號"
    "與資料來源要標清楚。"
)


def _today_str() -> str:
    return datetime.now(TPE).strftime("%Y-%m-%d")


def _warn_digest_enqueue(message: str, path: Path, exc: Exception | None = None) -> None:
    suffix = f" error={type(exc).__name__}: {exc}" if exc else ""
    print(f"[digest-enqueue] WARN {message}: path={path}{suffix}", file=sys.stderr)


def _load_json(path: Path, *, source_name: str) -> Any | None:
    if not path.exists():
        _warn_digest_enqueue(f"{source_name} JSON missing; aborting", path, FileNotFoundError(str(path)))
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        _warn_digest_enqueue(f"{source_name} JSON read failed; aborting", path, exc)
        return None


def _digest_published_today(today: str) -> bool | None:
    feed = _load_json(FEED, source_name="feed")
    if feed is None:
        return None
    if isinstance(feed, list):
        items = feed
    elif isinstance(feed, dict):
        items = feed.get("items", [])
    else:
        _warn_digest_enqueue(
            "feed JSON schema invalid; aborting",
            FEED,
            TypeError(f"expected list or dict, got {type(feed).__name__}"),
        )
        return None
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

    digest_published = _digest_published_today(today)
    if digest_published is None:
        print("[digest-enqueue] ERROR: feed source unavailable; abort to avoid duplicate digest", file=sys.stderr)
        return 1
    if digest_published:
        print(f"[digest-enqueue] skip: 今日({today}) digest 已發佈")
        return 0

    tasks = _load_json(NEXT_TASKS, source_name="next_tasks")
    if tasks is None:
        print("[digest-enqueue] ERROR: next_tasks source unavailable; abort（不亂建任務池）", file=sys.stderr)
        return 1
    if not isinstance(tasks, list):
        _warn_digest_enqueue(
            "next_tasks JSON schema invalid; aborting",
            NEXT_TASKS,
            TypeError(f"expected list, got {type(tasks).__name__}"),
        )
        print("[digest-enqueue] ERROR: next_tasks.json 非 list，abort（不亂改 schema）", file=sys.stderr)
        return 1

    if _digest_task_exists_today(tasks, task_id):
        print(f"[digest-enqueue] skip: 任務 {task_id} 已在池中")
        return 0

    task = {
        "id": task_id,
        "title": "[daily_digest] 寫一篇每日精選導讀專題策展並發佈",
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
