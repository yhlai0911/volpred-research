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
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
NEXT_TASKS = ROOT / "storage" / "next_tasks.json"
FEED = ROOT / "storage" / "reports" / "feed.json"
TPE = ZoneInfo("Asia/Taipei")

from volpred.canonical_write import guard_canonical_write  # noqa: E402
from volpred.ops.next_tasks import normalize_task_priorities  # noqa: E402

DESCRIPTION = (
    "寫一篇『每日精選導讀』專題策展長文並立即發佈。這是 editorial curation 不是逐篇摘要。"
    "規格：(1) **主題必須由『時事／近期重要宣告／近期熱門新聞／近期熱門標的』驅動，或框成回答一個具體"
    "投資議題**（例：『AI 資本支出爆增，科技股風險選擇權市場怎麼定價、該不該擔心？』『Fed 新主席放鷹，"
    "利率-波動率該怎麼讀？』『半導體修正，逢低還是走避？』）——**不是**挑一個純研究/方法論主題（如某模型"
    "複雜度天花板）當標的。時事/熱門標的/投資議題是骨幹，過去研究是用來論述、回答它的證據；(2) **從整個 "
    "archive（所有發過的文章、跨全部時間，不限本週）撈與該主題/議題相關的 5-8 篇**（grep/jq 掃 "
    "storage/reports/feed.json 的 title/tags），用這些過去研究**引導論述、建構對這個當下議題的回答/觀點**"
    "——**嚴禁只把這一兩週剛發的研究拿出來湊**（2026-07-01 boss 三次 + 2026-07-05 再糾正的核心錯誤：digest 不是本週研究 "
    "recap，是跨 archive 的主題專欄；此規則已進 `.claude/rules/publishing.md`「精選導讀策展硬規則」+ 機械 gate "
    "`publisher._audit_digest_archive_span`：來源文章發佈日期跨度 <14 天會被 publish 擋下）；排除 digest 自身與每日建議類日報；(3) 開場直接進當下的時事/標的情境"
    "（真實數據取自 archive 文章或 results.json，不可臆造），讓讀者一看就知道『這篇在回答我現在關心的什麼』；"
    "(4) **敘事弧 + 一個可帶走的具名方法（good 與 garbage 的唯一分野，2026-07-01 逐期 forensic 定論）**："
    "(a) **命名一個讀者記得住、帶得走、能複用的心智模型或比喻**（範例：VIX=溫度計不是計時器／訊號三關"
    "檢驗法／尾部風控的煞車距離），**先想好這個名字，整篇圍繞它組織**，不是寫完再補一個比喻；"
    "(b) **把一份具名、可操作的清單或檢查法放到最顯眼處當骨幹**（不是塞在結尾當補充）——讀者當天就能套用。"
    "(c) **深度對齊金標竿**：每篇引用的來源文章都要用足它的具體數字與 nuance（個股數值、季度時序、比值、百分位等），"
    "不可把好幾篇濃縮成幾句；篇幅目標 ≥ 第一期（約 4000+ 字），寧可深不可空。(d) **內文每段引用都要 inline 標註來源**："
    "邊論述邊用 markdown 連結標到那篇（像期 5：『在〈[文章標題](https://volpred.zeabur.app/v3/reports/<mile_id>)〉裡我們算過…』），"
    "不可只在文末列清單、讓讀者猜這段出自哪篇。"
    "敘事只是載體，『可用方法』才是重點；不是逐篇『這篇講 X、那篇講 Y』的並列摘要，也不是叫讀者自己去看原文。"
    "金標竿：mile_a1fd229a(期1)／mile_1597b341(期6)／mile_4901f7bc(期12)；反例（連貫但沒具名框架、洩氣）：期 4/5/8-11。"
    "(5) 文末才列本期精選連結"
    "（id + 一句話，連結 https://volpred.zeabur.app/v3/reports/<mile_id>）。"
    "輸出硬規則：reader-facing **必走 anti-ai-style**（寫前讀 prompt-templates、寫後跑 editor-sop "
    "9-checklist）+ **圖表分工（2026-07-01 boss 糾正）：來源研究的證據圖表要 inline 放在內文對應論證段落"
    "旁當實證佐證（哪段講 X，X 的圖就在那）；文末『懶人包圖組』必須是另生的『框架/重點合成摘要 poster』"
    "（例：把本篇框架做成一張 summary card），不可拿內文證據圖充數塞進懶人包**；走 feed-publisher 正式入口發佈，**details.content_type 必設 "
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


def _reconcile_stale_digest_task(task_id: str) -> None:
    """今日 digest 已發佈時，若同 id 的 daily_digest task 仍是未完成狀態，標 succeeded。

    根因（2026-07-08 fire 發現）：digest 於某小時發佈後，enqueue 的雙發防護只 skip 建新 task，
    但既有 pending/in_progress task 不會關閉 → 每天浪費一次 hourly dispatch cycle 才被人工對帳。
    本函式收編進 daily_digest 生命週期 owner（enqueue script），非新增 watchdog。
    fail-open：任何讀寫失敗只 warn 不 raise（不阻塞主流程）。
    """
    open_states = {"pending", "pending_main_thread", "in_progress", "claimed"}
    tasks = _load_json(NEXT_TASKS, source_name="next_tasks")
    if not isinstance(tasks, list):
        _warn_digest_enqueue("reconcile skip: next_tasks unreadable/非 list", NEXT_TASKS)
        return
    changed = False
    for t in tasks:
        if not isinstance(t, dict):
            continue
        if t.get("id") == task_id and str(t.get("status")) in open_states:
            t["status"] = "succeeded"
            t["result"] = (
                "auto-reconcile: 今日 digest 已發佈（feed content_type=daily_digest），"
                "stale task 由 enqueue_daily_digest 自動關閉，避免佔 hourly dispatch slot。"
            )
            changed = True
    if not changed:
        return
    guard_canonical_write(NEXT_TASKS)
    try:
        tmp = NEXT_TASKS.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(tasks, ensure_ascii=False, indent=2) + "\n")
        tmp.replace(NEXT_TASKS)
        print(f"[digest-enqueue] reconciled stale task {task_id} → succeeded")
    except OSError as exc:
        _warn_digest_enqueue("reconcile write failed", NEXT_TASKS, exc)


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
        _reconcile_stale_digest_task(task_id)
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
    normalize_task_priorities(tasks)
    guard_canonical_write(NEXT_TASKS)
    tmp = NEXT_TASKS.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(tasks, ensure_ascii=False, indent=2) + "\n")
    tmp.replace(NEXT_TASKS)
    print(f"[digest-enqueue] added {task_id} (P1 daily_digest); pool now {len(tasks)} tasks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
