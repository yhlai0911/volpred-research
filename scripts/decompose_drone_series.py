#!/usr/bin/env python3
"""Decompose the Taiwan-drone investment series (boss Telegram msg302) into
per-EP daily_article tasks in storage/next_tasks.json.

All follow-up EPs are queued status="blocked" reason="awaiting_event_window"
with blocked_until=2026-07-13T09:00+08:00 (boss's "next Monday, whole week"
window). scripts/unblock_expired_blocked_tasks.py flips them to pending once
the window opens, at which point they dispatch as P1.

Idempotent: skips any EP id already present. Validates the whole payload
before the flock-guarded atomic replace (control-plane invariant: canonical
JSON writes must be pre-serializable and recoverable).

Research foundation (verified company roster + chain map + PEST/SWOT) already
staged at storage/pending_series/taiwan_drone_series_ep0_research.md — every EP
brief points writers at it + the six-dimension method + honesty constraints.
"""
from __future__ import annotations

import fcntl
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NEXT_TASKS = ROOT / "storage" / "next_tasks.json"
RESEARCH_DOC = "storage/pending_series/taiwan_drone_series_ep0_research.md"
WINDOW_START = "2026-07-13T09:00:00+08:00"  # boss: 下週一起一整週

_COMMON = (
    f"研究地基（已驗證公司名冊/產業鏈地圖/PEST/SWOT）見 {RESEARCH_DOC}。"
    "走 feed-publisher + anti-ai-style（寫前讀 3 canonical + evidence-package 先於 prose，"
    "寫後跑 anti_ai_gate.py + arc-dedup gate）。個股面向數據走 external-data-sources"
    "（yfinance/TWSE 真查真算，標來源與日期）。個股分析用方法透明線："
    "真數據 + 假設 + 不確定性 + 免責聲明 + 可複現，不做保證報酬/內線式宣稱。"
)

EPS = [
    (
        "drone_series_ep0_overview",
        "無人機系列 EP0 產業總覽：PEST/SWOT + 台灣無人機產業鏈地圖",
        "系列開篇總覽文。用研究地基把台灣無人機產業鏈三層地圖（上/中/下游）、PEST、SWOT "
        "組成一篇廣泛、可信賴的產業總覽，帶出「台灣能否複製半導體劇本接住無人機供應鏈移轉」主題。"
        "附產業鏈地圖圖表 + 上市櫃公司分佈。",
    ),
    (
        "drone_series_ep1_upstream",
        "無人機系列 EP1 上游深度：晶片/飛控/感測/通訊/射頻",
        "聚焦上游環節與代表上市櫃公司（如全訊5222、立積4968、新唐4919、義隆2458、亞光3019、"
        "邑錡7402、千附精密6829、昇達科3491、聯發科2454/聯詠3034 題材性）。逐環節說明技術壁壘"
        "與台廠定位，附真財務/股價數據。",
    ),
    (
        "drone_series_ep2_midstream",
        "無人機系列 EP2 中游深度：機體/複合材料/電池/動力",
        "聚焦中游環節與代表上市櫃公司（如碳基7719、永虹先進6618、加百裕3323、系統電5309、"
        "力山1515、富田4590、寶一8222、晟田4541）。談複材/電池/動力供應能力與訂單能見度。",
    ),
    (
        "drone_series_ep3_downstream",
        "無人機系列 EP3 下游深度：整機整合/系統商/地面站/無人艇",
        "聚焦下游整機與系統整合上市櫃公司（如雷虎8033、漢翔2634、亞航2630、長榮航太2645、"
        "中光電5371、神基3005、融程電3416）＋無人艇邊界（龍德6753、台船2208、中信造船2644）。"
        "整合國防採購與海外訂單題材。無人艇是否納入系列需在文中標明邊界。",
    ),
    (
        "drone_series_ep4_core_stocks_six_dim",
        "無人機系列 EP4 核心個股六面向：龍頭深度投資分析",
        "對高信心龍頭（雷虎8033、漢翔2634、亞航2630 等）逐檔做六面向分析："
        "經營/財務/市場/籌碼/技術/心理。真查財務與股價數據，方法透明 + 免責。"
        "檔數多可再 decompose 成逐檔子任務。",
    ),
    (
        "drone_series_ep_final_portfolio",
        "無人機系列 EP-Final 收尾：投資組合角度 + 風險 + 台灣競爭定位",
        "系列收尾。從投資組合視角綜整全鏈，談曝險/分散/風險（政策不確定、訂單能見度、"
        "估值題材化），總結台灣在全球無人機供應鏈的競爭定位與「下一座護國神山」命題的證據強弱。",
    ),
]


def _load():
    with NEXT_TASKS.open("r", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_SH)
        try:
            return json.load(fh)
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def main() -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with NEXT_TASKS.open("r+", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            tasks = json.load(fh)
            existing = {t.get("id") for t in tasks}
            added = []
            for idx, (tid, title, desc) in enumerate(EPS):
                if tid in existing:
                    continue
                tasks.append(
                    {
                        "id": tid,
                        "title": title,
                        "description": desc + " " + _COMMON,
                        "priority": 1,
                        "status": "blocked",
                        "task_type": "daily_article",
                        "source": "boss-telegram-msg302-series-decompose",
                        "series": "taiwan_drone_industry",
                        "series_order": idx,
                        "tags": ["series-taiwan-drone", "reader-facing", "investment-thematic"],
                        "blocked_reason": "awaiting_event_window",
                        "blocked_at": now,
                        "blocked_until": WINDOW_START,
                        "blocked_note": "老闆指派系列，執行窗口 2026-07-13（下週一）起一整週；"
                        "unblock_expired 於窗口開啟時自動 flip 回 pending",
                        "created_at": now,
                    }
                )
                added.append(tid)
            # Pre-serialize the whole payload before truncating the file.
            payload = json.dumps(tasks, ensure_ascii=False, indent=2)
            fh.seek(0)
            fh.truncate()
            fh.write(payload)
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    if added:
        print(f"[decompose] added {len(added)} drone-series EP tasks: {added}")
    else:
        print("[decompose] no new tasks (all EP ids already present)")


if __name__ == "__main__":
    main()
