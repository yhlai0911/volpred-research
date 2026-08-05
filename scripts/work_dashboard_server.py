#!/usr/bin/env python3
"""VolPred 工作監控 Dashboard — 本地零依賴 http server。

用戶 2026-05-29 要求:可視化監控 AI 的「過去 / 進行中 / 未來」工作,確認在運作,
可透過 dashboard 調整任務,且要「更有資訊性 + 工作排程 + 等等資訊都要」。

提供維度:
- 健康橫幅:系統狀態 + 4 個核心 daemon 存活 + slot 占用
- 工作排程:每個 cron job 的 cron 式 + 下次 fire + 上次執行 + piggy-back skip
- 進行中:claimed/running 任務 + agent
- 未來:待辦池(依優先序)
- 過去:近期完成任務 + git commits + 最近發佈文章
- 內容 pipeline:草稿池存量 + 最近發佈 + 最近釋出 + 資料新鮮度
- 任務調整:block / unblock(走既有 CLI)

用法:
  uv run python scripts/work_dashboard_server.py            # http://127.0.0.1:8787
  PORT=9000 uv run python scripts/work_dashboard_server.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

# WS-D1 (2026-07-20): liveness evidence merge is owned by volpred.ops.schedules.
# cron_last_run.json alone lies for launchd-direct jobs (daily_update marker froze
# at 2026-04-25 while the job ran healthy every morning) — the dashboard showed
# the boss a dead job for ~3 months.
from volpred.ops.schedules import job_liveness  # noqa: E402
TZ = ZoneInfo("Asia/Taipei")
NEXT_TASKS = ROOT / "storage" / "next_tasks.json"
WORK_LOG = ROOT / "storage" / "work_log.json"
DASHBOARD = ROOT / "storage" / "ops" / "dashboard_latest.json"
SCHEDULES = ROOT / "config" / "runtime_schedules.json"
CRON_LAST = ROOT / "storage" / "ops" / "cron_last_run.json"
FEED = ROOT / "storage" / "reports" / "feed.json"
RELEASE = ROOT / "storage" / ".release_settings.json"
CRON_LOG_DIR = ROOT / "storage" / "logs" / "cron"
ORG_ROOT = ROOT / "storage" / "org"
PORT = int(os.environ.get("PORT", "8787"))
ONGOING = {"claimed", "running", "active", "in_progress"}

# 排程工作的精簡中文說明（比 config description 更好讀;未列者 fallback 用 config）
JOB_DESC = {
    "collect_tw_data": "台股收盤後收集日頻與 5min 行情",
    "collect_us_data": "美股收盤後收集 SPY/GLD/VIX 等行情",
    "daily_update": "每日策略計算、Supabase 同步、績效重算",
    "release_pool": "依節奏從草稿池釋出文章到網站",
    "market_calendar_sync": "同步市場交易日曆與開休市狀態",
    "check_alerts": "每小時檢查告警 + 觸發 piggy-back 排程",
    "memory_health_daily": "每日檢查知識庫健康、防膨脹",
    "refresh_paper_snapshots": "週度更新論文數據快照 CSV",
    "release_settings_audit": "稽核釋出設定與 Supabase 是否漂移",
    "paper_sync_all": "偵測過期論文並同步 metadata + PDF",
    "populate_events_weekly": "自動掃未來 30 天事件填入 event_jobs",
    "research_backlog_daily": "掃研究待辦自動產生 K 實驗 brief",
    "audit_publish_sync": "稽核本地/Supabase/線上文章一致性",
    "audit_fb_pipeline": "稽核卡住未發的 FB 貼文",
    "ops_dashboard": "產生 ops 健康快照供巡檢",
    "boss_report_4h": "每 4h 寄營運 HTML 報告給老闆",
    "gmail_poll": "收 Gmail、把老闆回信轉成任務",
    "handoff_regen": "重生 handoff 文件 + 清理逾時 claim",
    "question_research": "巡會員提問、materialize 問答任務",
    "reader_facing_refill": "補事件/trending/會員問答候選池",
    "work_summary_6h": "（已退役 2026-07-20，併入 boss_report 20:10 日結）工作摘要 email",
    "log_rotate": "截斷過大的 log 檔（防 codex_loop.log 暴脹）",
    "codex_update": "週度更新 codex-cli 輔助 agent 到最新版",
    "shared_scheduler_tick": "（已退役 2026-07-20 ops-master D2）advisory shared scheduler",
    "continue_task_stub": "slot-aware 續跑心跳",
    "token_usage_daily": "（已退役 2026-07-20，落檔併入 token_report_daily 08:00）token 摘要",
    "ndc_indicator_refresh": "每月更新 NDC 景氣指標",
}

# 排程類型分類（色塊用）。id → category
JOB_CAT = {
    "collect_tw_data": "data", "collect_us_data": "data", "market_calendar_sync": "data",
    "refresh_paper_snapshots": "data", "populate_events_weekly": "data", "ndc_indicator_refresh": "data",
    "release_pool": "content", "reader_facing_refill": "content", "research_backlog_daily": "content",
    "daily_update": "sync", "audit_publish_sync": "sync", "audit_fb_pipeline": "sync",
    "release_settings_audit": "sync", "paper_sync_all": "sync",
    "check_alerts": "ops", "ops_dashboard": "ops", "memory_health_daily": "ops",
    "shared_scheduler_tick": "ops", "handoff_regen": "ops",
    "boss_report_4h": "report", "work_summary_6h": "report", "gmail_poll": "report",
    "question_research": "report", "token_usage_daily": "report",
    "log_rotate": "maint", "codex_update": "maint",
}
# category → (中文名, 色)
CAT_META = {
    "data": ("資料收集", "#1f6feb"),
    "content": ("內容/發佈", "#3fb950"),
    "sync": ("同步/稽核", "#d29922"),
    "ops": ("巡檢/告警", "#a371f7"),
    "report": ("回報/通訊", "#39c5cf"),
    "maint": ("維護", "#8b949e"),
    "other": ("其他", "#6e7681"),
}

# 待辦任務 task_type → 五大 Mission（CLAUDE.md）。色塊用。
# M1 文章 / M2 研究 / M3 論文 / M4 平台運營 / M5 曝光(=內容的 outcome,非獨立 task type)
TASK_MISSION = {
    "daily_article": ("M1 文章", "#3fb950"),
    "trending_repost": ("M1 文章·曝光", "#2ea043"),
    "event_article": ("M1 文章·事件", "#46954a"),
    "member_qa": ("M1 會員問答", "#56d364"),
    "experiment": ("M2 研究", "#1f6feb"),
    "paper_review": ("M3 論文", "#a371f7"),
    "paper_body": ("M3 論文", "#a371f7"),
    "paper_decision": ("M3 論文", "#a371f7"),
    "strategy_lifecycle": ("M4 策略上架", "#d29922"),
    "platform_ops": ("M4 平台", "#d29922"),
    "governance": ("M4 治理", "#bb8009"),
    "email_reply": ("M4 老闆回信", "#e3b341"),
}
MISSION_OTHER = ("其他", "#6e7681")


def _warn_dashboard(warnings: list[str], message: str, exc: Exception | None = None) -> None:
    detail = f"{message}: {type(exc).__name__}: {exc}" if exc else message
    warnings.append(detail)
    print(f"[work_dashboard] WARN {detail}", file=sys.stderr)


def _load(path: Path, default, warnings: list[str] | None = None):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        if warnings is not None:
            _warn_dashboard(warnings, f"JSON read failed; using default path={path}", exc)
        return default


def _now():
    return datetime.now(TZ)


def _next_fire_dt(cron_expr: str, warnings: list[str] | None = None, job_id: str | None = None):
    try:
        from croniter import croniter
        return croniter(cron_expr, _now()).get_next(datetime)
    except Exception as exc:
        if warnings is not None:
            _warn_dashboard(warnings, f"cron next-fire parse failed job={job_id or '?'} cron={cron_expr!r}", exc)
        return None


def _fmt_tw(dt):
    """回傳 (台灣時間實際時刻, 相對描述, 排序用 epoch, 每日時刻分鐘數)。"""
    if dt is None:
        return "?", "", 9e18, 9999
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    dt = dt.astimezone(TZ)
    now = _now()
    same_day = dt.date() == now.date()
    label = dt.strftime("%H:%M") if same_day else dt.strftime("%m/%d %H:%M")
    mins = int((dt - now).total_seconds() // 60)
    if mins < 60:
        rel = f"{mins}分後"
    elif mins < 1440:
        rel = f"{mins // 60}時{mins % 60}分後"
    else:
        rel = f"{mins // 1440}天後"
    return label, rel, dt.timestamp(), dt.hour * 60 + dt.minute


def _rel_time(iso: str):
    if not iso or iso == "?":
        return "?"
    try:
        t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        delta = datetime.now(timezone.utc) - t.astimezone(timezone.utc)
        s = int(delta.total_seconds())
        if s < 3600:
            return f"{s // 60}分前"
        if s < 86400:
            return f"{s // 3600}時前"
        return f"{s // 86400}天前"
    except Exception:
        return iso[:16]


def _daemon_alive(label: str, warnings: list[str] | None = None) -> bool:
    try:
        out = subprocess.run(["launchctl", "list"], capture_output=True, text=True, timeout=5).stdout
        return any(label in line for line in out.splitlines())
    except Exception as exc:
        if warnings is not None:
            _warn_dashboard(warnings, f"launchctl daemon probe failed label={label}", exc)
        return False


def _proc_count(pattern: str, warnings: list[str] | None = None) -> int:
    try:
        out = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True, timeout=5).stdout
        return len([x for x in out.split() if x.strip()])
    except Exception as exc:
        if warnings is not None:
            _warn_dashboard(warnings, f"process-count probe failed pattern={pattern!r}", exc)
        return -1


def _git_recent(n: int = 10, warnings: list[str] | None = None) -> list[dict]:
    try:
        out = subprocess.run(["git", "log", f"-{n}", "--format=%h\t%cr\t%s"],
                             cwd=ROOT, capture_output=True, text=True, timeout=10).stdout
        rows = []
        for line in out.strip().splitlines():
            p = line.split("\t", 2)
            if len(p) == 3:
                rows.append({"hash": p[0], "when": p[1], "subject": p[2][:88]})
        return rows
    except Exception as exc:
        if warnings is not None:
            _warn_dashboard(warnings, f"git recent commits read failed cwd={ROOT}", exc)
        return []


def _file_age(path: Path) -> str:
    try:
        mt = datetime.fromtimestamp(path.stat().st_mtime, TZ)
        delta = _now() - mt
        s = int(delta.total_seconds())
        return f"{s // 60}分前" if s < 3600 else (f"{s // 3600}時前" if s < 86400 else f"{s // 86400}天前")
    except Exception:
        return "?"


def _inbox_depth(inbox: Path) -> int:
    return len(list(inbox.glob("*.json"))) if inbox.is_dir() else 0


def _journal_last(path: Path) -> str:
    """Last substantive journal line (skips the markdown header)."""
    if not path.exists():
        return ""
    lines = [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines()
             if ln.strip() and not ln.startswith("#")]
    return lines[-1][:110] if lines else ""


def build_org(warnings: list[str]) -> dict:
    """Organization view: the disk-persisted manager + departments (storage/org).

    This is the canonical operating surface for the department architecture —
    Herdr panes are only an optional live-view when someone is at the terminal.
    """
    registry_path = ORG_ROOT / "registry.json"
    if not registry_path.exists():
        # Not an error: an uninitialized org is a legitimate state (pre-P0, or a
        # test//standby checkout). Only a registry that exists but cannot be read
        # is a real fault worth a warning.
        return {"available": False, "departments": [], "manager": {}}
    registry = _load(registry_path, None, warnings)
    if not isinstance(registry, dict) or "departments" not in registry:
        _warn_dashboard(warnings, f"org registry malformed path={registry_path}")
        return {"available": False, "departments": [], "manager": {}}

    depts = []
    for name, meta in sorted((registry.get("departments") or {}).items()):
        status = meta.get("status", "?")
        if status == "retired":
            continue
        ddir = ORG_ROOT / "departments" / name
        state = _load(ddir / "state.json", {}, warnings)
        if not isinstance(state, dict):
            _warn_dashboard(warnings, f"dept state not an object dept={name}")
            state = {}
        lease = _load(ORG_ROOT / "runtime" / f"{name}.lease.json", None, warnings) \
            if (ORG_ROOT / "runtime" / f"{name}.lease.json").exists() else None
        runner = ""
        if isinstance(lease, dict):
            runner = f"{lease.get('runner', '?')} · {lease.get('pane_id', '')}".strip(" ·")
        depts.append({
            "name": name,
            "title": meta.get("title") or name,
            "status": status,
            "runner": runner,
            "inbox": _inbox_depth(ddir / "inbox"),
            "task_types": meta.get("owned_task_types") or [],
            "cadence": meta.get("min_cadence") or "on-demand",
            "last_run": _rel_time(state["last_run"]) if state.get("last_run") else "未執行",
            "health": state.get("health", "?"),
            "journal": _journal_last(ddir / "journal.md"),
        })

    gate = {}
    receipts_dir = ORG_ROOT / "receipts"
    if receipts_dir.is_dir():
        newest = sorted(receipts_dir.glob("*.json"))[-1:]
        if newest:
            payload = _load(newest[0], {}, warnings)
            if isinstance(payload, dict):
                gate = {
                    "kind": payload.get("kind", "?"),
                    "fire": bool(payload.get("fire")),
                    "reasons": payload.get("reasons") or [],
                    "when": _rel_time(str(payload.get("at") or "")),
                }
    return {
        "available": True,
        "manager": {
            "inbox": _inbox_depth(ORG_ROOT / "manager" / "inbox"),
            "proposals": len(list((ORG_ROOT / "manager" / "outbox" / "proposals").glob("*.md")))
            if (ORG_ROOT / "manager" / "outbox" / "proposals").is_dir() else 0,
            "gate": gate,
        },
        "departments": depts,
    }


def build_work() -> dict:
    warnings: list[str] = []
    tasks = _load(NEXT_TASKS, [], warnings)
    if not isinstance(tasks, list):
        _warn_dashboard(warnings, f"next_tasks is not a list; using embedded tasks/default path={NEXT_TASKS}")
        tasks = tasks.get("tasks", []) if isinstance(tasks, dict) else []
    dash = _load(DASHBOARD, {}, warnings)
    scheds = _load(SCHEDULES, {}, warnings)
    last_run = _load(CRON_LAST, {}, warnings)
    feed = _load(FEED, [], warnings)
    if not isinstance(feed, list):
        _warn_dashboard(warnings, f"feed is not a list; using empty feed path={FEED}")
        feed = []
    release = _load(RELEASE, {}, warnings)

    ongoing = [{"id": t.get("id"), "title": (t.get("title") or "")[:78], "type": t.get("task_type"),
                "by": t.get("claimed_by"), "status": t.get("status")}
               for t in tasks if isinstance(t, dict) and (t.get("status") or "").lower() in ONGOING]

    pending = [t for t in tasks if isinstance(t, dict)
               and (t.get("status") or "").lower() in {"pending", "pending_main_thread"}]
    pending.sort(key=lambda t: (t.get("priority") or 9, str(t.get("id"))))
    future = []
    for t in pending[:30]:
        mname, mcolor = TASK_MISSION.get(t.get("task_type"), MISSION_OTHER)
        future.append({"id": t.get("id"), "title": (t.get("title") or "")[:78], "type": t.get("task_type"),
                       "priority": t.get("priority"), "status": t.get("status"),
                       "mission": mname, "color": mcolor})

    done = [t for t in tasks if isinstance(t, dict) and (t.get("status") or "").lower().startswith("succeeded")]
    done.sort(key=lambda t: str(t.get("completed_at") or ""), reverse=True)
    past_tasks = [{"title": (t.get("title") or "")[:78], "type": t.get("task_type"),
                   "when": _rel_time(t.get("completed_at") or ""), "result": (t.get("result") or "")[:130]}
                  for t in done[:12]]

    # 工作排程:cron + 下次 fire(台灣時間,依發生順序排序)+ 上次執行
    schedule = []
    for item in (scheds.get("system_crontab", {}) or {}).get("items", []):
        jid = item.get("id")
        # A resident daemon (telegram_poll) has no cron by design — it is always
        # running, so there is no "next fire". Parsing its empty cron produced a
        # spurious warning on every dashboard load.
        cron_expr = item.get("cron") or ""
        if cron_expr:
            ntw, nrel, nsort, nday = _fmt_tw(_next_fire_dt(cron_expr, warnings, str(jid or "?")))
        else:
            ntw, nrel, nsort, nday = "常駐", "持續運行", 9e18, 9999
        cat = JOB_CAT.get(jid, "other")
        cname, ccolor = CAT_META.get(cat, CAT_META["other"])
        # Single liveness source (WS-D1): marker + execution-log banner/mtime
        # merged by job_liveness — never the raw cron_last_run marker alone.
        live = job_liveness(item, marker_state=last_run, repo_root=ROOT)
        last_iso = live.last_activity.isoformat() if live.last_activity else ""
        schedule.append({
            "id": jid, "cron": cron_expr or "daemon",
            "label": item.get("label") or (item.get("description") or "")[:36],
            "desc": JOB_DESC.get(jid) or (item.get("description") or "")[:34],
            "cat": cname, "color": ccolor,
            "next_tw": ntw, "next_rel": nrel, "_sort": nsort, "_day": nday,
            "last": _rel_time(last_iso),
            "skip": bool(item.get("piggy_back_skip") or item.get("host_crontab_managed") is False),
        })
    schedule.sort(key=lambda s: s["_sort"])  # 預設依接下來發生順序

    # 內容 pipeline
    published = [a for a in feed if isinstance(a, dict) and (a.get("status") == "published")]
    drafts = [a for a in feed if isinstance(a, dict) and (a.get("status") == "draft")]
    published.sort(key=lambda a: str(a.get("published_at") or ""), reverse=True)
    content = {
        "draft": len(drafts), "published": len(published),
        "last_pub_title": (published[0].get("title") or "")[:60] if published else "?",
        "last_pub_when": _rel_time(published[0].get("published_at") or "") if published else "?",
        "last_release": _rel_time(release.get("last_released_at") or ""),
        "release_interval": release.get("interval_minutes", "?"),
        "data_tw": _file_age(CRON_LOG_DIR / "collect_tw.log"),
        "data_us": _file_age(CRON_LOG_DIR / "collect_us.log"),
        "data_fred": _file_age(CRON_LOG_DIR / "fred_backfill_guard.log"),
    }

    daemons = {
        # 2026-07-10: was `com.volpred.hourly-dispatch` — the LaunchAgent the
        # 2026-07-04 daemon cutover retired. Its plist still sits in
        # ~/Library/LaunchAgents but is UNLOADED, so `launchctl list` never
        # matches and this tile reported the (healthy, dispatching) hourly loop
        # as dead for six days. Third monitor to make the same mistake:
        # ops_dashboard fixed 2026-07-05, cron_review 2026-07-08, this one was
        # missed both times because neither sweep grepped the full population of
        # readers. Guarded by tests/test_work_dashboard_daemon_labels.py.
        "hourly_dispatch": _daemon_alive("com.volpred.dispatch-supervisor", warnings),
        "check_alerts": _daemon_alive("com.volpred.check-alerts", warnings),
        "compute_worker": _daemon_alive("com.volpred.compute-worker", warnings),
        "codex_loop": _proc_count("codex_loop.sh", warnings),
    }

    return {
        "generated": _now().strftime("%Y-%m-%d %H:%M:%S 台灣時間"),
        "health": {
            "overall": dash.get("overall_status", "?"),
            "breaches": dash.get("section_breaches", 0),
            "warning_count": len(warnings),
        },
        "warnings": warnings,
        "daemons": daemons,
        "slots": {"used": len(ongoing), "cap": 4},
        "counts": dict(Counter((t.get("status") or "?") for t in tasks if isinstance(t, dict))),
        "ongoing": ongoing, "future": future, "schedule": schedule,
        "org": build_org(warnings),
        "content": content, "past_tasks": past_tasks, "past_commits": _git_recent(warnings=warnings),
    }


def adjust_task(action: str, task_id: str, note: str = "") -> dict:
    if not task_id:
        return {"ok": False, "error": "missing task_id"}
    cmds = {
        "block": ["uv", "run", "python", "scripts/mark_task_blocked.py", "--id", task_id,
                  "--reason", "deprecated", "--note", note or "blocked via dashboard"],
        "unblock": ["uv", "run", "python", "scripts/mark_task_blocked.py", "--id", task_id, "--unblock"],
    }
    cmd = cmds.get(action)
    if not cmd:
        return {"ok": False, "error": f"unknown action {action!r}"}
    try:
        p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=60)
        return {"ok": p.returncode == 0, "stdout": p.stdout[-400:], "stderr": p.stderr[-300:]}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


HTML = r"""<!DOCTYPE html><html lang=zh-Hant><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>VolPred · AI 工作監控</title><style>
*{box-sizing:border-box}body{margin:0;font:13px/1.5 -apple-system,"PingFang TC",sans-serif;background:#0d1117;color:#e6edf3}
header{padding:12px 18px;background:#161b22;border-bottom:1px solid #30363d;display:flex;align-items:center;gap:14px;flex-wrap:wrap;position:sticky;top:0;z-index:5}
h1{font-size:15px;margin:0}h2{font-size:13px;margin:0;padding:9px 13px;background:#1c2230;border-bottom:1px solid #30363d;display:flex;justify-content:space-between}
.pill{padding:3px 9px;border-radius:11px;font-size:11px;font-weight:600}
.ok{background:#1a3a1a;color:#3fb950}.warn{background:#3a2f10;color:#d29922}.critical{background:#3a1518;color:#f85149}.dead{background:#3a1518;color:#f85149}
.muted{color:#8b949e;font-size:11px}
.strip{display:flex;gap:8px;flex-wrap:wrap;padding:8px 18px;background:#0d1117;border-bottom:1px solid #30363d;font-size:11px}
.chip{background:#161b22;border:1px solid #30363d;border-radius:7px;padding:4px 9px}
.chip b{color:#79c0ff}
.cols{display:grid;grid-template-columns:1.15fr 1fr 1.15fr;gap:12px;padding:14px;align-items:start}
@media(max-width:1100px){.cols{grid-template-columns:1fr}}
.col{background:#161b22;border:1px solid #30363d;border-radius:9px;overflow:hidden}
.card{padding:8px 13px;border-bottom:1px solid #21262d}.card:last-child{border-bottom:0}
.t{font-weight:600;margin-bottom:2px}
.tag{display:inline-block;background:#21304a;color:#79c0ff;padding:1px 6px;border-radius:8px;font-size:10px;margin-right:4px}
.res{color:#8b949e;font-size:11px;margin-top:2px}.hash{color:#79c0ff;font-family:ui-monospace,monospace}
.sched{display:grid;grid-template-columns:auto 1fr auto;gap:4px 8px;padding:8px 13px;font-size:11px;align-items:start;border-bottom:1px solid #21262d}
.sched:last-child{border-bottom:0}
.sched .cr{font-family:ui-monospace,monospace;color:#d2a8ff}.nx{color:#3fb950;text-align:right;white-space:nowrap}
.sched .nm{font-weight:600;color:#e6edf3}.sched .dsc{color:#9aa4af;font-size:10px}
.ct{display:inline-block;padding:0 5px;border-radius:7px;font-size:9px;font-weight:600}
button{background:#21262d;color:#e6edf3;border:1px solid #30363d;border-radius:6px;padding:2px 7px;font-size:10px;cursor:pointer;margin-left:4px}button:hover{background:#30363d}
.sbtn{font-size:10px;padding:2px 8px}.sbtn.on{background:#1f6feb;border-color:#1f6feb;color:#fff}
.orgbar{padding:7px 13px;border-bottom:1px solid #21262d;display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.orgbar h2{border:0;padding:0;margin:0;display:inline}
.orggrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(196px,1fr));gap:7px;padding:0 13px 9px}
.dept{border:1px solid #30363d;border-left-width:3px;border-radius:7px;padding:7px 9px;background:#0d1117}
.dept .dn{font-size:12px;font-weight:600;margin-bottom:3px}
.dept .dm{font-size:10px;color:#8b949e;line-height:1.5}
.dept .jn{font-size:10px;color:#6e7681;margin-top:4px;border-top:1px dashed #21262d;padding-top:3px}
.ibx{display:inline-block;min-width:16px;text-align:center;border-radius:9px;padding:0 5px;font-size:10px}
</style></head><body>
<header><h1>🤖 VolPred · AI 工作監控</h1><span id=health class=pill>…</span><span id=daemons></span>
<span class=muted id=gen></span><span class=muted style=margin-left:auto>每 15s 自動刷新</span></header>
<div class=strip id=strip></div>
<div class=orgbar><h2>🏢 組織 · 運營經理與部門</h2><span class=muted id=org-mgr></span></div>
<div class=orggrid id=org></div>
<div class=cols>
  <div class=col><h2><span>⏰ 工作排程 · 台灣時間</span><span><button id=sb-next class="sbtn on">下次時間</button><button id=sb-day class=sbtn>每日順序</button></span></h2><div id=schedule></div></div>
  <div class=col>
    <div style="border-bottom:1px solid #30363d"><h2><span>🔄 進行中</span><span class=muted id=on-n></span></h2><div id=ongoing></div></div>
    <h2><span>⏳ 未來(待辦池)</span><span class=muted id=fu-n></span></h2><div id=future></div>
  </div>
  <div class=col><h2><span>✅ 過去(完成 + commits)</span></h2><div id=past></div></div>
</div>
<script>
function esc(s){return (s==null?'':String(s)).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
function el(id){return document.getElementById(id)}
function card(title,tags,res,taskId,btn){
  let t=(tags||[]).map(x=>'<span class=tag>'+esc(x)+'</span>').join('');
  let b=btn&&taskId?'<button data-id="'+esc(taskId)+'" data-act="block">擱置</button>':'';
  return '<div class=card><div class=t>'+esc(title)+'</div>'+t+b+(res?'<div class=res>'+esc(res)+'</div>':'')+'</div>';
}
async function load(){
  let d; try{d=await (await fetch('/api/work')).json()}catch(e){return}
  el('gen').textContent='更新於 '+esc(d.generated);
  const h=el('health');h.textContent='系統 '+esc(d.health.overall)+' (breaches '+esc(d.health.breaches)+')';h.className='pill '+(d.health.overall||'muted');
  // daemons
  const dm=d.daemons;let ds='';
  ds+=dpill('hourly',dm.hourly_dispatch);ds+=dpill('alerts',dm.check_alerts);ds+=dpill('compute',dm.compute_worker);
  ds+='<span class="pill '+(dm.codex_loop>=1?'ok':'dead')+'">codex_loop×'+esc(dm.codex_loop)+'</span>';
  el('daemons').innerHTML=ds;
  // strip: slot + content + counts
  const c=d.content;
  el('strip').innerHTML=[
    chip('Slot',d.slots.used+'/'+d.slots.cap),
    d.warnings&&d.warnings.length?chip('Warnings',d.warnings.length):'',
    chip('草稿池',c.draft),chip('已發佈',c.published),
    chip('最近發佈',esc(c.last_pub_when)+' · '+esc(c.last_pub_title)),
    chip('最近釋出',esc(c.last_release)+' (每'+esc(c.release_interval)+'min)'),
    chip('台股資料',esc(c.data_tw)),chip('美股資料',esc(c.data_us)),chip('FRED',esc(c.data_fred)),
  ].join('');
  // org(運營經理 + 部門)
  renderOrg(d.org);
  // schedule
  SCHED=d.schedule; renderSchedule();
  // ongoing
  el('ongoing').innerHTML=d.ongoing.length?d.ongoing.map(t=>card(t.title,[t.type,'by '+(t.by||'?')],'',null,false)).join(''):'<div class=card><span class=muted>無 agent 進行中(slot 閒置)</span></div>';
  el('on-n').textContent=d.ongoing.length+' 活動';
  // future(依 mission 色塊)
  el('future').innerHTML=d.future.length?d.future.map(t=>
    '<div class=card style="border-left:3px solid '+esc(t.color)+'"><div class=t>'+esc(t.title)+'</div>'+
    '<span class=tag style="background:'+esc(t.color)+'22;color:'+esc(t.color)+'">'+esc(t.mission)+'</span>'+
    '<span class=tag>P'+esc(t.priority)+'</span><span class=tag>'+esc(t.type)+'</span>'+
    '<button data-id="'+esc(t.id)+'" data-act="block">擱置</button></div>').join(''):'<div class=card><span class=muted>待辦池無 pending(hourly-dispatch 自生)</span></div>';
  el('fu-n').textContent=d.future.length+' 待辦';
  // past
  let p=d.past_tasks.map(t=>card(t.title,[t.type,t.when],t.result,null,false)).join('');
  p+='<div class=card><b>📝 近期 commits</b></div>'+d.past_commits.map(x=>'<div class=card><span class=hash>'+esc(x.hash)+'</span> '+esc(x.subject)+' <span class=muted>· '+esc(x.when)+'</span></div>').join('');
  el('past').innerHTML=p;
  document.querySelectorAll('button[data-id]').forEach(b=>b.onclick=()=>adj(b.dataset.id,b.dataset.act));
}
function dpill(n,ok){return '<span class="pill '+(ok?'ok':'dead')+'">'+n+(ok?' ✓':' ✗')+'</span>'}
function chip(k,v){return '<span class=chip>'+esc(k)+': <b>'+esc(v)+'</b></span>'}
async function adj(id,action){
  if(!confirm(action+' 任務 '+id+'?'))return;
  let d;try{d=await (await fetch('/api/task',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action,id})})).json()}catch(e){alert('error');return}
  alert(d.ok?'已'+action+': '+id:'失敗: '+(d.error||d.stderr));load();
}
let SCHED=[], sortMode='next';
function renderSchedule(){
  let arr=SCHED.slice().sort((a,b)=> sortMode==='next' ? a._sort-b._sort : a._day-b._day);
  el('schedule').innerHTML=arr.map(s=>
    '<div class=sched style="border-left:3px solid '+esc(s.color)+'"><span class=cr>'+esc(s.cron)+'</span><span>'+
    '<span class=ct style="background:'+esc(s.color)+'22;color:'+esc(s.color)+'">'+esc(s.cat)+'</span> <span class=nm>'+esc(s.label)+'</span>'+(s.skip?' <span class=muted>(LA)</span>':'')+
    '<br><span class=dsc>'+esc(s.desc)+'</span><br><span class=muted>上次 '+esc(s.last)+'</span></span>'+
    '<span class=nx>'+esc(s.next_tw)+'<br><span class=muted>'+esc(s.next_rel)+'</span></span></div>').join('');
  el('sb-next').classList.toggle('on',sortMode==='next');el('sb-day').classList.toggle('on',sortMode==='day');
}
const DEPT_COLOR={research:'#58a6ff',publications:'#bc8cff',content:'#3fb950',member_success:'#f0883e',
  platform_eng:'#e3b341',governance:'#8b949e',growth:'#f778ba',resource_monitor:'#39c5cf'};
function renderOrg(o){
  if(!o||!o.available){
    el('org-mgr').textContent='組織未初始化(storage/org 不存在或無法讀取)';
    el('org').innerHTML='';return;
  }
  const m=o.manager||{},g=m.gate||{};
  let mgr='經理收件匣 '+esc(m.inbox)+' · 待批提案 '+esc(m.proposals);
  if(g.kind) mgr+=' · 上次判斷 '+(g.fire?'該喚醒':'無事跳過')+'('+esc(g.when)+')'+
    (g.reasons&&g.reasons.length?'：'+esc(g.reasons.join('；')):'');
  el('org-mgr').textContent=mgr;
  el('org').innerHTML=o.departments.map(function(t){
    const col=DEPT_COLOR[t.name]||'#30363d';
    const ibxCol=t.inbox>0?'#1f6feb':'#21262d';
    return '<div class=dept style="border-left-color:'+col+'">'+
      '<div class=dn>'+esc(t.title)+' <span class=ibx style="background:'+ibxCol+'">'+esc(t.inbox)+'</span></div>'+
      '<div class=dm>'+esc(t.name)+' · '+esc(t.status)+' · '+esc(t.cadence)+'</div>'+
      '<div class=dm>上次執行 '+esc(t.last_run||'—')+' · 狀態 '+esc(t.health)+'</div>'+
      (t.runner?'<div class=dm style="color:#3fb950">▶ 執行中 '+esc(t.runner)+'</div>':'')+
      (t.task_types.length?'<div class=dm>'+esc(t.task_types.join(', '))+'</div>':'')+
      (t.journal?'<div class=jn>'+esc(t.journal)+'</div>':'')+
    '</div>';
  }).join('')||'<div class=card><span class=muted>尚無 active 部門</span></div>';
}
el('sb-next').onclick=function(){sortMode='next';renderSchedule()};
el('sb-day').onclick=function(){sortMode='day';renderSchedule()};
load();setInterval(load,15000);
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", f"{ctype}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            self._send(200, HTML, "text/html")
        elif path == "/api/work":
            self._send(200, json.dumps(build_work(), ensure_ascii=False))
        else:
            self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self):
        if urlparse(self.path).path != "/api/task":
            self._send(404, json.dumps({"error": "not found"}))
            return
        try:
            n = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(n) or "{}")
        except Exception as exc:
            print(f"[work_dashboard] WARN invalid task POST body: {type(exc).__name__}: {exc}", file=sys.stderr)
            self._send(400, json.dumps({"ok": False, "error": str(exc)}))
            return
        r = adjust_task(payload.get("action", ""), payload.get("id", ""), payload.get("note", ""))
        self._send(200 if r.get("ok") else 400, json.dumps(r, ensure_ascii=False))

    def log_message(self, *a):
        pass


def main() -> int:
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"VolPred 工作監控 dashboard → http://127.0.0.1:{PORT}  (Ctrl-C 停)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
