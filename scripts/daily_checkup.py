#!/usr/bin/env python3
"""每日大體檢（daily full checkup）—— result-level 驗證，不是 exit-code 監控。

老闆 2026-06-30 硬性要求：「每天都要做一次大體檢 確認所有任務都有確實完成」。

根因（2026-06-30 多重 incident）：既有 ops_dashboard / check_alerts 只查「程式有沒有
報錯」（exit code / 檔案大小），不查「結果好不好」—— 所以沒報錯的爛文章（無圖無表）、
靜默落後的資料（daily_update 卡 6/26、collect_us、twse_orderflow 死 12 天）、卡 1 年的
頁面 cache，全部漏網，最後靠老闆當 QA 發現。本檢查補上 result-level 維度。

十一大維度（每個失敗都產生具體 finding，可被 alert 消費）：
1. data_freshness   — 所有資料收集 job 是否照排程跑 + 關鍵資料檔是否新鮮（時效性資料優先）
                      + DB 入庫驗證（canonical 最新 trade_date vs Supabase 端收據；
                      老闆 2026-07-20「抓完數據要確認資料庫已正確存入」）
2. cron_completion  — 所有排程 job 最近一輪是否真的 fire + exit0
3. content_pipeline — 草稿池 ≥ 門檻、今日有產出、published 文章皆含真圖表+數據表（非純散文）
4. live_freshness   — 線上 API 回傳的 data_date 是否 ≈ 最新交易日（抓「頁面卡舊資料」）
5. live_cache       — data-bearing 頁面是否被設成長效靜態快取（抓「網頁卡 cache」）
6. mission_progress — 研究 backlog / 實驗 / 論文是否在前進（非停滯）
7. alert_conditions — ops alert 是否存在未處理的 critical / warn
8. reader_metrics   — 讀者互動 metrics 是否已落地且足夠新鮮
9. dedup_calibration — 真實 90d feed 上的 arc/theme 固定 probes 與 threshold margin
10. reproducibility — 論文/feed 引用實驗的 report coverage、staleness 與 mismatch（唯讀）
11. worktree_reconcile — open 任務指向的 worktree 是否還在磁碟上（抓 k1709 型殭屍任務）

用法：
  uv run python scripts/daily_checkup.py            # 印報告
  uv run python scripts/daily_checkup.py --json     # JSON
  uv run python scripts/daily_checkup.py --alert    # 有 critical/warn 時 send-alert email
"""
from __future__ import annotations

import argparse
import datetime
import glob
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STORAGE = ROOT / "storage"
SITE = "https://volpred.zeabur.app"

# 時效性資料 job：照排程「應該」多久跑一次（小時）。超過 1.5× 視為 stale。
# 週末/假日不交易的 job 用較寬窗口；真正時效性（盤中/tick）窗口較緊。
DATA_JOBS_EXPECTED_H = {
    "daily_update": 26,            # 每日 08:03
    "daily_update_intraday": 26,   # 每日 14:00（台股盤後；2026-07-20 補監控，見下方 exit-code 檢查）
    "collect_tw": 30,              # 工作日 15:00
    "collect_us": 30,             # 週二-六 07:03（跳週一，故放寬）
    "fred_backfill_guard": 30,
    "radar_strategy_snapshot": 30,
    "indicator_arena_daily": 30,
    "populate_events": 200,        # 週度
}

# Result-level 資料檔新鮮度：某些資料沒有獨立 cron log（是別的 job 的子步驟），
# 改查實際落地的資料檔最新 mtime。weekend-aware → 窗口放寬到涵蓋 Fri→Mon gap。
# (job_name, glob, expected_h, parent_job)
DATA_FILE_JOBS = [
    # TWSE order-flow (MI_5MINS) 由 collect_tw_data.py 第 4 步 --date today 收，
    # 寫 data/intraday/twse_orderflow/，無獨立 log。80h 涵蓋週一早上(latest=週五15:00→~65h)。
    (
        "twse_orderflow",
        "data/intraday/twse_orderflow/*.csv",
        80,
        "collect_tw",
        "uv run python scripts/collect_twse_orderflow.py --date today  # 或回補 --backfill",
    ),
    # TAIFEX TX 官方 tick 衍生 RV 是 collect_tw 的子步驟；來源通常在午夜後落地，
    # 因此 15:00 會增量到當時最新可得檔。80h 同樣涵蓋週末與一日來源延遲。
    (
        "taifex_5min_rv",
        "data/intraday/taifex_5min_rv.csv",
        80,
        "collect_tw",
        "uv run python scripts/collect_taifex_tick.py",
    ),
]

# ── data_freshness sub-check: DB 入庫驗證（db_landing）───────────────────────
# 老闆 2026-07-20 指令：「抓完數據要確認資料庫已正確存入」。sync 端印 "synced N"
# 只是送出方的 exit-code 級證據；這裡直接查 Supabase 收到什麼（result-level 收據）：
# canonical 本地（storage/paper_trading.json）最新 trade_date + 當日 row 數
# vs DB 端最新 trade_date + 當日 row 數。不一致 = finding + 自動開 P1 修復單
# （actuator 原則：gate 無死局，finding 必附可執行 recovery CLI）。
# (table, date_col, local-state fn 名, recovery CLI)
DB_LANDING_TABLES = (
    ("market_daily", "trade_date", "_local_market_daily_state",
     "uv run python scripts/supabase_sync.py market-daily  # canonical 全量重推（idempotent upsert）"),
    ("paper_trades", "trade_date", "_local_paper_trades_state",
     "uv run python scripts/daily_update.py  # idempotent：publish 有 monotone gate，重跑只補 sync"),
)

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_now = datetime.datetime.now()


def _age_h(path: str | Path) -> float | None:
    try:
        return (_now - datetime.datetime.fromtimestamp(os.path.getmtime(path))).total_seconds() / 3600
    except OSError:
        return None  # silent-ok: best-effort mtime；檔不存在 → None（呼叫端自行視為無資料/stale）


def _finding(dim: str, severity: str, msg: str, recovery: str | None = None) -> dict:
    return {"dimension": dim, "severity": severity, "message": msg, "recovery": recovery}


# 排程未必每天跑（collect_tw 只跑週一到週五）。用固定小時窗口判 stale 會在週末
# 誤報：週日 17:00 距離週五 15:00 已 50h > 30×1.5。改成「有沒有錯過上一次排定的
# fire」——cron spec 從 config/runtime_schedules.json 讀，log stem 對應 job 名。
CRON_GRACE_H = 3.0  # job 起跑到寫 log 的容忍延遲


def _cron_map() -> dict[str, str]:
    """log stem → cron spec，取自 canonical runtime_schedules.json。"""
    try:
        spec = json.loads((ROOT / "config" / "runtime_schedules.json").read_text())
    except Exception as e:
        print(f"[daily_checkup] WARN 無法讀 runtime_schedules.json，data_freshness 退回固定窗口: {e}",
              file=sys.stderr)
        return {}
    out: dict[str, str] = {}

    def walk(node):
        if isinstance(node, dict):
            cron, log = node.get("cron"), node.get("log_path")
            if isinstance(cron, str) and isinstance(log, str):
                out[Path(log).stem] = cron
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(spec)
    return out


def _missed_fires(cron: str, log_mtime: datetime.datetime) -> int:
    """log 最後寫入之後、距今超過 grace 的排定 fire 數（0 = 沒漏班）。"""
    try:
        from croniter import croniter
    except ImportError as e:
        print(f"[daily_checkup] WARN croniter 不可用，退回固定窗口: {e}", file=sys.stderr)
        return -1
    cutoff = _now - datetime.timedelta(hours=CRON_GRACE_H)
    it = croniter(cron, log_mtime)
    missed = 0
    while missed < 10:
        nxt = it.get_next(datetime.datetime)
        if nxt > cutoff:
            break
        missed += 1
    return missed


_EXIT_RE = re.compile(r"exit (\d+) at .*?(?:\(duration=([\d.]+)s\))?\s*===")


def _last_exit(log: Path) -> tuple[int, float | None] | None:
    """log 尾端最後一筆 `exit N at ... (duration=Xs)` → (rc, duration_s)。

    2026-07-20：mtime 只證明 job「有寫 log」，不證明它「有成功」。
    daily_update_intraday 連續撞 600s watchdog（rc=142）卻天天更新 mtime，
    schedule-aware 檢查因此永遠判它新鮮 —— 靠老闆手動發現。見 error_log 2026-07-20。
    """
    try:
        with open(log, "rb") as fh:                # log 可達數百 KB，只讀尾端
            fh.seek(0, os.SEEK_END)
            fh.seek(max(0, fh.tell() - 16384))
            tail = fh.read().decode("utf-8", "ignore")
    except OSError:
        return None  # silent-ok: missing/unreadable log surfaces as its own freshness finding upstream
    hits = _EXIT_RE.findall(tail)
    if not hits:
        return None
    rc, dur = hits[-1]
    return int(rc), float(dur) if dur else None


# ── 1. data_freshness ───────────────────────────────────────────────────────
def check_data_freshness() -> list[dict]:
    out = []
    crons = _cron_map()
    for job, expected in DATA_JOBS_EXPECTED_H.items():
        log = STORAGE / "logs" / "cron" / f"{job}.log"
        a = _age_h(log)
        if a is None:
            out.append(_finding("data_freshness", "warn", f"{job}: 無 cron log（從未跑？）"))
            continue
        # 「有跑但失敗」與「根本沒跑」是兩種故障，各自獨立報。
        last = _last_exit(log)
        if last and last[0] != 0:
            rc, dur = last
            why = f"撞 watchdog timeout（duration={dur:.0f}s）" if rc == 142 else f"rc={rc}"
            out.append(_finding(
                "data_freshness", "critical",
                f"{job}: 最後一次執行失敗 —— {why}（{a:.0f}h 前）；log mtime 仍新，漏班檢查看不到",
                recovery=f"tail -40 storage/logs/cron/{job}.log  # 查失敗點，再跑對應 wrapper",
            ))
        cron = crons.get(job)
        missed = _missed_fires(cron, datetime.datetime.fromtimestamp(os.path.getmtime(log))) if cron else -1
        if missed >= 0:  # schedule-aware（primary）
            if missed >= 1:
                sev = "critical" if missed >= 3 else "warn"
                out.append(_finding(
                    "data_freshness", sev,
                    f"{job}: 漏跑 {missed} 班（cron `{cron}`，最後跑完 {a:.0f}h 前）—— 資料可能落後/漏",
                    recovery=f"uv run python scripts/{job}.py  # 或對應 wrapper",
                ))
            continue
        if a > expected * 1.5:  # fallback：無 cron spec 或 croniter 不可用
            sev = "critical" if a > expected * 3 else "warn"
            out.append(_finding(
                "data_freshness", sev,
                f"{job}: 已 {a:.0f}h 沒跑（預期 ≤{expected}h）—— 資料可能落後/漏",
                recovery=f"uv run python scripts/{job}.py  # 或對應 wrapper",
            ))
    # result-level：查實際資料檔最新 mtime（無獨立 cron log 的子步驟型 job）
    for job, pattern, expected, parent, recovery in DATA_FILE_JOBS:
        files = glob.glob(str(ROOT / pattern))
        if not files:
            out.append(_finding("data_freshness", "warn",
                                f"{job}: 資料目錄無檔（{pattern}）—— 從未收集？",
                                recovery=recovery))
            continue
        newest = max(files, key=lambda p: os.path.getmtime(p))
        a = _age_h(newest)
        if a is not None and a > expected * 1.5:
            sev = "critical" if a > expected * 3 else "warn"
            out.append(_finding(
                "data_freshness", sev,
                f"{job}: 最新資料檔已 {a:.0f}h（預期 ≤{expected}h，由 {parent} 子步驟收）—— 資料落後",
                recovery=recovery,
            ))
    # result-level：DB 入庫驗證（canonical vs Supabase 收據）
    out.extend(_db_landing_findings())
    return out


def _supabase_mod():
    """Resolve scripts/supabase_sync at call time（同 reproduce_check 的 import 慣例）。"""
    try:
        from scripts import supabase_sync
    except ModuleNotFoundError:  # direct ``python scripts/daily_checkup.py``
        import supabase_sync  # type: ignore[no-redef]
    return supabase_sync


def _local_market_daily_state() -> tuple[str | None, int, list[str]]:
    """canonical `_market_daily` 的（最新 trade_date, 該日 row 數, 全部日期）。"""
    pt = json.loads((STORAGE / "paper_trading.json").read_text())
    md = pt.get("_market_daily") or {}
    dates = sorted(d for d in md if isinstance(d, str) and _ISO_DATE_RE.match(d))
    if not dates:
        return None, 0, []
    return dates[-1], 1, dates  # 一天一 row（trade_date 是 conflict key）


def _local_paper_trades_state() -> tuple[str | None, int, list[str]]:
    """canonical 各策略 entries 的（全局最新 trade_date, 該日策略 row 數, 全部日期）。

    只有「latest 停在全局最新日」的策略計入當日 row 數 —— 已停更/下架策略的
    latest 停在舊日期，不會把 DB 端正常的部分入庫誤判成缺 row。
    """
    pt = json.loads((STORAGE / "paper_trading.json").read_text())
    latest_per_strategy: list[str] = []
    all_dates: set[str] = set()
    for key, val in pt.items():
        if key.startswith("_") or not isinstance(val, dict):
            continue
        dates = []
        for e in val.get("entries") or []:
            if not isinstance(e, dict):
                continue
            d = e.get("trade_date") or e.get("data_date") or e.get("date")
            if isinstance(d, str) and _ISO_DATE_RE.match(d):
                dates.append(d)
        if dates:
            latest_per_strategy.append(max(dates))
            all_dates.update(dates)
    if not latest_per_strategy:
        return None, 0, []
    latest = max(latest_per_strategy)
    return latest, sum(1 for d in latest_per_strategy if d == latest), sorted(all_dates)


def _db_landing_probe(ss, table: str, date_col: str) -> tuple[str | None, int]:
    """DB 端（最新 date, 該日 row 數）。失敗 raise —— 呼叫端轉 finding，不 silent。"""
    base = f"{ss.SUPABASE_URL}/rest/v1/{table}"
    req = urllib.request.Request(
        f"{base}?select={date_col}&order={date_col}.desc&limit=1", headers=ss.HEADERS)
    rows = json.loads(ss._urlopen(req, timeout=20).read().decode("utf-8"))
    if not rows:
        return None, 0
    latest = str(rows[0][date_col])
    req2 = urllib.request.Request(
        f"{base}?select={date_col}&{date_col}=eq.{latest}",
        headers={**ss.HEADERS, "Prefer": "count=exact", "Range-Unit": "items", "Range": "0-0"})
    resp = ss._urlopen(req2, timeout=20)
    content_range = (resp.headers.get("Content-Range") or "").rsplit("/", 1)[-1]
    if not content_range.isdigit():
        raise ValueError(f"unexpected Content-Range for {table}: {content_range!r}")
    return latest, int(content_range)


def _open_db_landing_repair_task(table: str, msg: str, recovery: str, local_latest: str) -> str:
    """開/確認 P1 修復單（actuator：finding 不留死局）。失敗 raise，呼叫端 fail-loud。

    dedup：id 以 (table, canonical 最新日) 為 key —— 缺口未解時每天重跑 checkup
    不會重複開單；缺口日推進（= 新 episode）才開新單。
    """
    from volpred.ops.next_tasks import append_task_record

    task_id = f"db_landing_repair_{table}_{local_latest}"
    record = {
        "id": task_id,
        "title": f"【P1 自動補救】DB 入庫落後：{table}",
        "description": (
            f"daily_checkup db_landing 偵測：{msg}\n\n"
            f"修復（正式 CLI，不手改 DB）：\n  {recovery}\n\n"
            "修完重跑 `uv run python scripts/daily_checkup.py` 驗證 finding 消失後才關單。"
        ),
        "task_type": "platform_ops",
        "priority": 1,
        "status": "pending",
        "source": "daily_checkup_db_landing",
        "created_at": _now.isoformat(),
        "trigger": "db_landing_mismatch",
    }
    _rec, created = append_task_record(
        record, path=STORAGE / "next_tasks.json", if_exists="skip")
    return f"已開修復單 {task_id}" if created else f"修復單已存在 {task_id}"


def _db_landing_findings() -> list[dict]:
    """result-level 入庫驗證：canonical vs Supabase。對齊 → 安靜；不一致 → finding+修復單。"""
    ss = _supabase_mod()
    if ss._remote_reads_blocked():
        # 測試/CI 明確封鎖遠端讀 —— 留 stderr trace（no-silent-fallback），不產 finding
        print("[daily_checkup] db_landing: remote reads blocked (VOLPRED_NO_REMOTE_READ=1) — skip",
              file=sys.stderr)
        return []
    if not ss.SUPABASE_URL or not ss.SUPABASE_KEY:
        return [_finding(
            "data_freshness", "warn",
            "db_landing: 缺 Supabase 憑證（.env.local）—— DB 入庫驗證無法執行",
            recovery="確認 .env.local 的 SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY")]
    out: list[dict] = []
    for table, date_col, local_fn, recovery in DB_LANDING_TABLES:
        try:
            local_latest, local_count, local_dates = globals()[local_fn]()
        except Exception as exc:  # silent-ok: not silent — warn finding below IS the trace
            out.append(_finding("data_freshness", "warn",
                                f"db_landing/{table}: canonical 讀取失敗: {exc}"))
            continue
        if local_latest is None:
            out.append(_finding("data_freshness", "warn",
                                f"db_landing/{table}: canonical（paper_trading.json）無可比對資料"))
            continue
        try:
            db_latest, db_count = _db_landing_probe(ss, table, date_col)
        except Exception as exc:  # silent-ok: not silent — warn finding below IS the trace
            out.append(_finding("data_freshness", "warn",
                                f"db_landing/{table}: DB 查詢失敗（無法驗證入庫）: {exc}"))
            continue
        msg, sev = None, "warn"
        if db_latest is None:
            sev = "critical"
            msg = f"DB 表全空，canonical 最新 {local_latest}（{len(local_dates)} 個資料日）完全沒入庫"
        elif db_latest < local_latest:
            behind = sum(1 for d in local_dates if d > db_latest)
            sev = "critical" if behind >= 3 else "warn"
            msg = (f"DB 落後 canonical：DB 最新 {db_latest} < 本地最新 {local_latest}"
                   f"（落後 {behind} 個資料日）")
        elif db_latest == local_latest and db_count < local_count:
            msg = (f"最新日 {local_latest} 入庫不完整：DB {db_count} row < "
                   f"canonical {local_count} row")
        elif db_latest > local_latest:
            msg = (f"DB 端最新 {db_latest} 比 canonical {local_latest} 新 —— "
                   "canonical 是 SoT，不應發生（查誰在直寫 DB）")
        if msg is None:
            continue  # 對齊 → 安靜
        try:
            receipt = _open_db_landing_repair_task(table, msg, recovery, local_latest)
        except Exception as exc:
            receipt = None
            out.append(_finding("data_freshness", "warn",
                                f"db_landing/{table}: 修復單建立失敗（actuator 故障，須人工開單）: {exc}"))
        full_msg = f"db_landing/{table}: {msg}" + (f" —— {receipt}" if receipt else "")
        out.append(_finding("data_freshness", sev, full_msg, recovery=recovery))
    return out


# ── 2. cron_completion ──────────────────────────────────────────────────────
def check_cron_completion() -> list[dict]:
    out = []
    for log in sorted(glob.glob(str(STORAGE / "logs" / "cron" / "*.log"))):
        name = Path(log).stem
        if name.endswith("_launchd") or name in ("cron_test", "continue_task_stub", "scheduler_tick"):
            continue  # 已遷移/廢棄
        try:
            tail = Path(log).read_text(errors="replace")[-3000:]
        except OSError:
            continue  # silent-ok: best-effort 讀 cron log；讀不到就跳過該 log
        exits = re.findall(r"exit (\d+)", tail)
        if exits and exits[-1] not in ("0", "142"):  # 142=self-heal
            # 排除 findings-as-exit 的 audit job
            if name.startswith("audit_") or "audit" in name:
                continue
            out.append(_finding("cron_completion", "warn",
                                f"{name}: 最近一輪 exit={exits[-1]}（非 0）",
                                recovery=f"tail storage/logs/cron/{name}.log"))
    return out


# ── 3. content_pipeline ─────────────────────────────────────────────────────
_CHART_RE = re.compile(r"!\[|<img|\.png|\.svg")
_TABLE_RE = re.compile(r"\|.*\|.*\n\s*\|?\s*[-:]")  # markdown table


def check_content_pipeline() -> list[dict]:
    out = []
    feed_path = STORAGE / "reports" / "feed.json"
    try:
        feed = json.loads(feed_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return [_finding("content_pipeline", "critical", f"feed.json 讀取失敗: {exc}")]
    arts = feed if isinstance(feed, list) else feed.get("items", [])
    drafts = [a for a in arts if a.get("status") == "draft"]
    if len(drafts) < 4:
        out.append(_finding("content_pipeline", "warn",
                            f"草稿池僅 {len(drafts)} 篇（門檻 4）—— Mission 1 缺產出",
                            recovery="主動派寫作 agent 補池（feed-publisher，新鮮非 spy 主題）"))
    # 近 7 天 published 文章是否皆含真圖表 + 數據表
    cutoff = _now - datetime.timedelta(days=7)
    chartless = []
    for a in arts:
        if a.get("status") != "published":
            continue
        ts = a.get("published_at") or a.get("created_at") or ""
        try:
            if datetime.datetime.fromisoformat(ts.replace("Z", "+00:00")).replace(tzinfo=None) < cutoff:
                continue
        except ValueError:
            continue  # silent-ok: 時間戳格式異常 → 保守跳過該文（不誤判為近期）
        if (a.get("audience") or "general") != "general":
            continue
        content = a.get("content") or a.get("description") or ""
        has_chart = bool(_CHART_RE.search(content))
        if not has_chart:
            chartless.append((a.get("id"), a.get("title", "")[:30]))
    if chartless:
        out.append(_finding("content_pipeline", "critical",
                            f"{len(chartless)} 篇近期 published general 文章正文無真圖表（純散文）: "
                            f"{chartless[:3]}",
                            recovery="走正規 feed-publisher 流程把圖嵌進 content（![](url)）+ 補數據表"))
    return out


# ── 4. live_freshness ───────────────────────────────────────────────────────
def _get_json(url: str, timeout: int = 25):
    req = urllib.request.Request(url, headers={"User-Agent": "checkup"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, json.loads(r.read()), dict(r.headers)


# 「線上績效該有多新」不是日曆問題，是排程問題。資料鏈是：
#   collect_us（週二~六 07:03 台北）收前一個已收盤的美股 session
#   → daily_update（週一~六 08:03）重算 paper_trading 並推上站
# 網站要到 daily_update 跑完才看得到新 session，所以錨點是 daily_update，不是 collect_us。
# 任一時刻**應該**已經在線上的最新 data_date = 上一班跑完的 daily_update 推上去的那個
# NYSE session —— 跟「今天幾號」「過了幾天」無關。
#
# 舊判準（now - data_date > 3 個日曆天）暗含「檢查一定在資料更新之後跑」的假設。這假設是
# 錯的：daily-checkup 排 09:40，但 launchd 會在睡眠喚醒後補跑漏掉的班（2026-07-14 04:52
# 就補跑過一次）。週二凌晨補跑時，線上本來就只該有上週五的數字 —— 4 個日曆天 —— 於是它
# 在一個設計上完全正常的時點寄了警報給老闆。同一個粗判準也會漏報：週間真的落後 2 個
# session 卻只有 3 個日曆天，剛好躲過 >3。誤報與漏報同源，調門檻救不了，要換判準本身。
PUBLISH_GRACE_H = 1.0  # daily_update 起跑到線上反映的容忍延遲


def _expected_live_session(now: datetime.datetime) -> datetime.date | None:
    """此刻「應該」已經上線的最新美股 session；判不出來回 None（呼叫端退回舊判準）。"""
    cron = _cron_map().get("daily_update")
    if not cron:
        print("[daily_checkup] WARN runtime_schedules 查無 daily_update cron，"
              "live_freshness 退回日曆天判準", file=sys.stderr)
        return None
    try:
        from croniter import croniter
        import exchange_calendars as xcals
    except ImportError as exc:
        print(f"[daily_checkup] WARN {exc} —— live_freshness 退回日曆天判準", file=sys.stderr)
        return None
    try:
        # 上一班「已經跑完」（含推上站的 grace）的 daily_update。還在 grace 內的那班不算數。
        it = croniter(cron, now)
        fire = it.get_prev(datetime.datetime)
        if (now - fire).total_seconds() / 3600 < PUBLISH_GRACE_H:
            fire = it.get_prev(datetime.datetime)
        # 那一班推上去的是它開跑前最後一個已收盤的 session（美股當地日 = 台北日 - 1）。
        nyse = xcals.get_calendar("XNYS")
        prior = fire.date() - datetime.timedelta(days=1)
        sessions = nyse.sessions_in_range(prior - datetime.timedelta(days=14), prior)
        if len(sessions) == 0:
            print("[daily_checkup] WARN NYSE 日曆在該區間無 session，"
                  "live_freshness 退回日曆天判準", file=sys.stderr)
            return None
        return sessions[-1].date()
    except Exception as exc:  # noqa: BLE001
        print(f"[daily_checkup] WARN 交易日曆/cron 解析失敗: {exc} —— "
              "live_freshness 退回日曆天判準", file=sys.stderr)
        return None


def _sessions_behind(latest: datetime.date, expected: datetime.date) -> int:
    """latest 之後到 expected 為止漏掉幾個交易日。"""
    try:
        import exchange_calendars as xcals
        nyse = xcals.get_calendar("XNYS")
        return len(nyse.sessions_in_range(latest + datetime.timedelta(days=1), expected))
    except Exception as exc:  # noqa: BLE001
        print(f"[daily_checkup] WARN session 差距計算失敗: {exc}，改用日曆天近似", file=sys.stderr)
        return (expected - latest).days


def check_live_freshness() -> list[dict]:
    out = []
    try:
        _, d, _ = _get_json(f"{SITE}/api/portfolio-overview")
    except Exception as exc:  # noqa: BLE001
        return [_finding("live_freshness", "warn", f"portfolio-overview 抓取失敗: {exc}")]
    items = d.get("items", d if isinstance(d, list) else [])
    dates = []
    for it in items[:5]:
        e = (it.get("paper_trading") or {}).get("entries") or []
        if e:
            dates.append(e[-1].get("data_date") or e[-1].get("trade_date"))
    if not dates:
        return out
    try:
        latest = datetime.date.fromisoformat(max(d for d in dates if d))
    except ValueError as exc:
        return [_finding("live_freshness", "warn", f"線上績效 data_date 格式無法解析: {exc}")]

    expected = _expected_live_session(_now)
    if expected is None:  # fallback：croniter / 交易日曆不可用時的粗判準（會誤報，僅保底）
        age_days = (_now.date() - latest).days
        if age_days > 3:
            out.append(_finding("live_freshness", "warn",
                                f"線上績效最新 data_date={latest}（已 {age_days} 天，粗判準）"
                                "—— 頁面顯示舊資料",
                                recovery="跑 daily_update + 確認頁面非靜態快取（見 live_cache）"))
        return out

    if latest >= expected:
        return out
    behind = _sessions_behind(latest, expected)
    sev = "critical" if behind >= 2 else "warn"
    out.append(_finding(
        "live_freshness", sev,
        f"線上績效最新 data_date={latest}，但應已收到 {expected}"
        f"（落後 {behind} 個交易日）—— 頁面顯示舊資料",
        recovery="查 collect_us 是否漏班（storage/logs/cron/collect_us.log）→ "
                 "跑 daily_update + 確認頁面非靜態快取（見 live_cache）",
    ))
    return out


# ── 5. live_cache ───────────────────────────────────────────────────────────
def check_live_cache() -> list[dict]:
    out = []
    for path in ["/portfolio", "/v3/portfolio", "/v3", "/admin/paper-trading"]:
        try:
            req = urllib.request.Request(SITE + path, headers={"User-Agent": "checkup"})
            with urllib.request.urlopen(req, timeout=20) as r:
                cc = r.headers.get("cache-control", "")
        except Exception:  # noqa: BLE001
            continue  # silent-ok: 單頁探測失敗跳過該頁（網路/單頁 500 不該擋整體大體檢）
        m = re.search(r"s-maxage=(\d+)", cc)
        if m and int(m.group(1)) > 3600:  # >1h 靜態快取的 data 頁
            out.append(_finding("live_cache", "warn",
                                f"{path}: s-maxage={m.group(1)}（>{int(m.group(1))//86400}天靜態快取）"
                                f"—— 換版/資料更新後使用者卡舊版",
                                recovery="該 data 頁加 export const dynamic='force-dynamic'（或短 revalidate）"))
    return out


# ── 6. mission_progress ─────────────────────────────────────────────────────
def check_mission_progress() -> list[dict]:
    out = []
    nt = STORAGE / "next_tasks.json"
    try:
        tasks = json.loads(nt.read_text())
    except (OSError, json.JSONDecodeError):
        tasks = []
    pending = [t for t in tasks if t.get("status") in (None, "pending", "queued")]
    if len(pending) < 3:
        out.append(_finding("mission_progress", "warn",
                            f"pending 任務僅 {len(pending)} 件 —— backlog 偏薄，需主動生研究議題/派工",
                            recovery="派 journal-discovery / autonomous-research 生新方向"))
    # id 完整性 invariant（2026-07-07 platform_ops_null_id_task_hygiene）：
    # 某些 receipt writer 曾 append id=null 的 row，導致 jq test() 報錯 + 無法追蹤。
    # 零額外 IO（tasks 已 load）；未來若再生 null-id 這裡自動 surface + 附 recovery。
    null_id = [t for t in tasks if isinstance(t, dict) and t.get("id") is None]
    if null_id:
        out.append(_finding("mission_progress", "warn",
                            f"next_tasks.json 有 {len(null_id)} 筆 id=null —— jq test() 報錯 + 無法追蹤",
                            recovery="uv run python scripts/backfill_null_task_ids.py --apply"))
    # blocked >30d 必須 escalate-or-close（2026-07-14 refactor_plan_token_ops_waste
    # WS2c：46 筆 blocked 有 36 筆滯留 1-2 個月無人收割）。有 blocked_until 的
    # 有 auto-recheck 出口不算 rot；無 until 且 30 天沒動的浮出。
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    cutoff = _dt.now(_tz.utc) - _td(days=30)
    rotting = []
    for t in tasks:
        if not isinstance(t, dict) or t.get("status") != "blocked" or t.get("blocked_until"):
            continue
        ts_raw = t.get("blocked_at") or t.get("created_at")
        if not ts_raw:
            rotting.append(t.get("id"))
            continue
        try:
            ts = _dt.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=_tz.utc)
            if ts < cutoff:
                rotting.append(t.get("id"))
        except ValueError:
            rotting.append(t.get("id"))
    if rotting:
        out.append(_finding(
            "mission_progress", "warn",
            f"{len(rotting)} 筆 blocked 任務滯留 >30 天且無 blocked_until 出口"
            f"（前 5：{rotting[:5]}）—— escalate-or-close，不可無限停放",
            recovery="逐筆裁決：可自主解的解、需 owner 的併決策 email、死的 closed_no_action/expired",
        ))
    return out


# ── 7. reader_metrics ───────────────────────────────────────────────────────
# 讀者互動回饋迴圈（platform_ops_reader_metrics_feedback_loop_c9，2026-07-05）：
# scripts/pull_reader_metrics.py 每日落地 storage/analytics/latest.json；
# 這裡只驗證「有沒有跑、跑得新不新鮮」，不重算 Supabase 查詢本身。
READER_METRICS_STALE_H = 48


def check_reader_metrics() -> list[dict]:
    out = []
    path = STORAGE / "analytics" / "latest.json"
    if not path.exists():
        out.append(_finding(
            "reader_metrics", "warn",
            "storage/analytics/latest.json 不存在 —— 讀者互動回饋迴圈尚未跑過",
            recovery="uv run python scripts/pull_reader_metrics.py --top 20 --days 30",
        ))
        return out
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        out.append(_finding("reader_metrics", "warn", f"latest.json 讀取失敗: {exc}"))
        return out
    gen_at = data.get("generated_at")
    age_h = None
    try:
        generated_at = datetime.datetime.fromisoformat(str(gen_at).replace("Z", "+00:00"))
        if generated_at.tzinfo is None:
            age_h = (_now - generated_at).total_seconds() / 3600
        else:
            age_h = (
                datetime.datetime.now(datetime.timezone.utc)
                - generated_at.astimezone(datetime.timezone.utc)
            ).total_seconds() / 3600
    except (ValueError, TypeError):
        pass  # silent-ok: 缺/壞 timestamp 下面就地判 stale（age_h=None）
    if age_h is None or age_h > READER_METRICS_STALE_H:
        age_str = f"{age_h:.0f}h" if age_h is not None else "未知（timestamp 缺或壞）"
        out.append(_finding(
            "reader_metrics", "warn",
            f"reader metrics 已 {age_str} 未更新（門檻 {READER_METRICS_STALE_H}h）",
            recovery="uv run python scripts/pull_reader_metrics.py --top 20 --days 30",
        ))
        return out
    top = data.get("top_articles") or []
    if top:
        top3 = "; ".join(
            f"{(a.get('title') or a.get('slug') or '未命名')[:24]}(score={a.get('score')})"
            for a in top[:3]
        )
        out.append(_finding("reader_metrics", "info", f"top-3 讀者互動: {top3}"))
    else:
        out.append(_finding("reader_metrics", "info", "近期無讀者互動資料（articles_with_activity=0）"))
    return out


def check_alert_conditions() -> list[dict]:
    """Surface the 24 conditions `volpred.ops.alerts` already owns.

    2026-07-10 23:09: this checkup printed `overall=ok / 全部維度通過` while
    `build_alert_condition_report()` had a live breach (`dispatch_supervisor_stale_code`,
    the daemon's state file had lost its boot time). Two health surfaces, neither
    aware of the other — and this one is what the PDCA skill tells you to run
    before claiming the platform is healthy. It was blind to every alert condition.

    This is a READER, not a second alerter: `alerts.py` decides what a breach is,
    `check_alerts.py` (hourly) owns emailing it, and this surfaces it to whoever
    is looking. Adding a third opinion would be the stacking the anti-stacking
    rule forbids.
    """
    from volpred.ops.alerts import build_alert_condition_report

    report = build_alert_condition_report(storage_dir="storage")
    out: list[dict] = []
    for cond in report["conditions"]:
        if not cond.get("breached"):
            continue
        severity = "critical" if cond.get("level") == "critical" else "warn"
        out.append(
            _finding(
                "alert_conditions",
                severity,
                f"{cond['id']}: {cond.get('title', '')}",
                recovery="uv run volpred ops check-alerts --storage-dir storage",
            )
        )
    return out


# ── 9. dedup_calibration ───────────────────────────────────────────────────
def check_dedup_calibration() -> list[dict]:
    """Warn when live-corpus dedup behaviour drifts outside calibrated bounds."""
    feed_path = STORAGE / "reports" / "feed.json"
    try:
        feed = json.loads(feed_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [_finding("dedup_calibration", "warn", f"feed.json 讀取失敗: {exc}")]
    if not isinstance(feed, list):
        return [_finding("dedup_calibration", "warn", "feed.json 不是 list，校準無法執行")]

    from volpred.ops.topic_dedup import audit_topic_dedup_calibration

    try:
        audit = audit_topic_dedup_calibration(feed)
    except Exception as exc:  # noqa: BLE001 — structured warning, never silent
        return [
            _finding(
                "dedup_calibration",
                "warn",
                f"arc/theme 校準執行失敗: {type(exc).__name__}: {exc}",
                recovery="uv run python scripts/daily_checkup.py --json  # 檢查 dedup_calibration",
            )
        ]
    if audit["ok"]:
        return []
    metrics = audit["metrics"]
    summary = (
        f"corpus={metrics['corpus_size']}, AI saturation="
        f"{metrics['incident_saturation']} (threshold={metrics['theme_threshold']}, "
        f"margin={metrics['incident_margin']}), NFP control="
        f"{metrics['nfp_control_saturation']}, FOMC theme="
        f"{metrics['fomc_theme_saturation']} / hard="
        f"{metrics['fomc_hard_matches']}"
    )
    return [
        _finding(
            "dedup_calibration",
            "warn",
            f"arc/theme 校準漂移：{'; '.join(audit['issues'])}；{summary}",
            recovery="uv run python scripts/daily_checkup.py --json  # 檢查 dedup_calibration",
        )
    ]


# ── 10. reproducibility ─────────────────────────────────────────────────────
def check_reproducibility() -> list[dict]:
    """Project the pure inventory/status scan into alert-compatible findings."""
    try:
        from scripts import reproduce_check
    except ModuleNotFoundError:  # direct ``python scripts/daily_checkup.py``
        import reproduce_check  # type: ignore[no-redef]

    status = reproduce_check.build_status(ROOT, feed_limit=60)
    if status.get("schema_version") != reproduce_check.STATUS_SCHEMA:
        raise ValueError(f"unexpected reproducibility status schema: {status.get('schema_version')}")
    findings: list[dict] = []
    for issue in status.get("issues", []):
        severity = issue.get("severity")
        if severity not in {"critical", "warn"}:
            continue
        sample = ", ".join(issue.get("experiment_ids", []))
        suffix = f"（例：{sample}）" if sample else ""
        findings.append(
            _finding(
                "reproducibility",
                severity,
                f"{issue.get('code')}: {issue.get('message')}{suffix}",
                recovery=issue.get("recovery"),
            )
        )
    return findings


_WORKTREE_REF = re.compile(r"\.claude/worktrees/([A-Za-z0-9._-]+)")


def check_worktree_reconcile() -> list[dict]:
    """Open tasks whose worktree no longer exists on disk.

    k1709 sat status=blocked from 2026-07-14 to 2026-07-19 pointing at
    .claude/worktrees/dispatch-slot-2-c873d04d-k1709. The directory was gone, so
    the task could never run; nothing looked for that, so it never closed either
    — a pure zombie. This dimension is the missing feedback loop: it reconciles
    task references against what is actually on disk.

    The branch is what decides severity. Checkout gone but branch alive => the
    commits are still reachable, so it is a bookkeeping problem (warn). Branch
    gone too => the work is reachable only via reflog and is on the clock before
    gc, which is the artifact-loss case (critical, per
    feedback_no_research_artifact_loss).

    in_progress is excluded on purpose: a task actively repairing a vanished
    worktree necessarily names it, and flagging the repair as the disease is how
    a checkup trains its reader to ignore it.
    """
    out = []
    nt = STORAGE / "next_tasks.json"
    try:
        tasks = json.loads(nt.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return [_finding("worktree_reconcile", "warn", f"讀不到 next_tasks.json: {exc}")]

    wt_dir = ROOT / ".claude" / "worktrees"
    try:
        refs = subprocess.run(
            ["git", "-C", str(ROOT), "for-each-ref", "--format=%(refname:short)"],
            capture_output=True, text=True, timeout=20, check=True,
        ).stdout.split()
    except (subprocess.SubprocessError, OSError) as exc:
        refs = []
        out.append(_finding("worktree_reconcile", "warn", f"讀不到 git refs（branch 存活無法判定）: {exc}"))

    for t in tasks:
        if t.get("status") not in ("pending", "blocked", "queued"):
            continue
        names = set(_WORKTREE_REF.findall(json.dumps(t, ensure_ascii=False)))
        missing = sorted(n for n in names if not (wt_dir / n).exists())
        if not missing:
            continue
        # A worktree named wt/<name> or exp/<slug> may still have its branch.
        orphaned = [n for n in missing if not any(n in r for r in refs)]
        sev = "critical" if orphaned else "warn"
        detail = f"branch 也不存在（成果僅存 reflog）: {orphaned}" if orphaned else "branch 尚存，commits 可救回"
        out.append(_finding(
            "worktree_reconcile", sev,
            f"殭屍任務 {t.get('id')} [{t.get('status')}] 指向已消失的 worktree {missing} —— {detail}",
            recovery=("查 git reflog / merge-base 裁定 commits 是否已進 main；"
                      "已合併→關單並註明，未合併→依 feedback_no_research_artifact_loss 復原。禁止直接關單了事"),
        ))

    try:
        wt_list = subprocess.run(
            ["git", "-C", str(ROOT), "worktree", "list", "--porcelain"],
            capture_output=True, text=True, timeout=20, check=True,
        ).stdout
        prunable = wt_list.count("prunable")
        if prunable:
            out.append(_finding(
                "worktree_reconcile", "warn",
                f"git worktree 有 {prunable} 條 stale 註冊（目錄已不存在但註冊還在）",
                recovery="uv run python scripts/git_writer_lock.py run -- worktree prune",
            ))
    except (subprocess.SubprocessError, OSError) as exc:
        out.append(_finding("worktree_reconcile", "warn", f"worktree list 失敗: {exc}"))

    return out


#: The checkup's dimensions, in report order. Every entry must have a matching
#: module-level ``check_<name>``. This is a public constant rather than a dict
#: built inside ``run_all`` so that tests can enumerate the real list instead of
#: hand-copying it: 2026-07-20 the ``worktree_reconcile`` dimension was added to
#: ``run_all`` but not to the stub tuple in
#: ``test_run_all_turns_reproducibility_checker_exception_into_warning``, so the
#: real checker kept running inside a unit test. It is environment-dependent —
#: on a dev box the worktrees exist and it stays quiet, on CI the clone has
#: neither the checkouts nor the branches and it returns *critical* — so the test
#: passed locally and failed only on CI, which is the worst place to find out.
CHECKUP_DIMENSIONS = (
    "data_freshness",
    "cron_completion",
    "content_pipeline",
    "live_freshness",
    "live_cache",
    "mission_progress",
    "alert_conditions",
    "reader_metrics",
    "dedup_calibration",
    "reproducibility",
    "worktree_reconcile",
)


def _checker(name: str):
    """Resolve ``check_<name>`` at call time so monkeypatching still takes effect."""
    return globals()[f"check_{name}"]


def run_all() -> dict:
    findings = []
    for name in CHECKUP_DIMENSIONS:
        try:
            findings.extend(_checker(name)())
        except Exception as exc:  # noqa: BLE001 — fail-open per no-silent-fallback：印出
            findings.append(_finding(name, "warn", f"檢查本身失敗: {exc}"))
    crit = [f for f in findings if f["severity"] == "critical"]
    warn = [f for f in findings if f["severity"] == "warn"]
    overall = "critical" if crit else ("warn" if warn else "ok")
    return {
        "generated_at": _now.isoformat(),
        "overall": overall,
        "critical_count": len(crit),
        "warn_count": len(warn),
        "findings": findings,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--alert", action="store_true")
    args = ap.parse_args()
    report = run_all()
    out_dir = STORAGE / "ops" / "checkup"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{_now:%Y%m%d}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"每日大體檢 {_now:%Y-%m-%d %H:%M} — overall={report['overall']} "
              f"(critical={report['critical_count']}, warn={report['warn_count']})")
        _SEVERITY_MARK = {"critical": "🔴", "warn": "🟡", "info": "ℹ️"}
        for f in report["findings"]:
            mark = _SEVERITY_MARK.get(f["severity"], "🟡")
            print(f"  {mark} [{f['dimension']}] {f['message']}")
            if f["recovery"]:
                print(f"      ↳ recovery: {f['recovery']}")
        if report["overall"] == "ok":
            print("  ✅ 全部維度通過")
    if args.alert and report["overall"] in ("critical", "warn"):
        lines = [f"# 每日大體檢 — overall={report['overall']}", ""]
        for f in report["findings"]:
            lines.append(f"- [{f['severity']}][{f['dimension']}] {f['message']}")
            if f["recovery"]:
                lines.append(f"  - recovery: {f['recovery']}")
        tmp = out_dir / f"alert_{_now:%Y%m%d_%H%M}.md"
        tmp.write_text("\n".join(lines), encoding="utf-8")
        # subprocess + arg list（非 shell）避免 command injection（security hook 要求）
        level = "critical" if report["overall"] == "critical" else "warn"
        title = (f"每日大體檢 {_now:%m-%d}: {report['critical_count']} critical / "
                 f"{report['warn_count']} warn")
        subprocess.run(
            ["uv", "run", "volpred", "ops", "send-alert", "--level", level,
             "--title", title, "--body-md", str(tmp)],
            cwd=str(ROOT), check=False,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
