#!/usr/bin/env python3
"""Cron-run outcome review — what did the autonomous schedulers do?

The ops manager (interactive Claude session) has no heartbeat: cron jobs fire
and finish while the session is dormant. Without an explicit review step the
manager never "grasps" whether runs completed, succeeded, or need follow-up
(2026-05-21 user: "跑完沒有 你會知道嗎 你會去掌握嗎").

This script is that review. Run it FIRST thing every time the session becomes
active, and as part of every ops 巡檢. Reports per LaunchAgent scheduler:
  - runs count + last exit code (from launchctl — authoritative)
  - currently running?
  - last run banner timestamp + staleness vs expected cadence
  - recent git commits (proxy for what hourly_dispatch produced)

⚠️ TZ HARD RULE: cron log banners are MIXED — some emit UTC ISO
(`...T..+00:00`), some emit local `... CST`. Parsing a UTC stamp as local
adds a spurious +8h and false-flags healthy jobs as stale (this exact bug
hit ops_dashboard.py 2026-05-21, and v1 of this script). _parse_ts handles
both. A monitor that lies is worse than no monitor.
"""
from __future__ import annotations
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LOGS = REPO / "storage" / "logs" / "cron"
LAST_RUN_PATH = REPO / "storage" / "ops" / "cron_last_run.json"
TPE = timezone(timedelta(hours=8))

# job → (launchd label, log file, expected max gap hours before "stale",
#         piggy_back_id in cron_last_run.json — fallback when LaunchAgent runs=0
#         because piggy-back via check_alerts is the real fire path)
# 2026-05-27: market_cal / memory_health 的 LaunchAgent 從未可靠 fire（macOS cron
# 限制），實際靠 piggy-back via check_alerts. cron_review v1 只看 launchctl + log
# banner → 持續 false-flag stale 數天。Fix: piggy_back_id 從 cron_last_run.json
# 補 fallback timestamp。
JOBS = {
    "hourly_dispatch":  ("com.volpred.hourly-dispatch",      "hourly_dispatch.log", 2,   None),
    "compute_worker":   ("com.volpred.compute-worker",       "compute_worker.log",  1,   None),
    "check_alerts":     ("com.volpred.check-alerts",         "check_alerts.log",    2,   None),
    "collect_tw":       ("com.volpred.collect-tw-data",      "collect_tw.log",      30,  "collect_tw_data"),
    "collect_us":       ("com.volpred.collect-us-data",      "collect_us.log",      30,  "collect_us_data"),
    "daily_update":     ("com.volpred.daily-update",         "daily_update.log",    30,  "daily_update"),
    "release_pool":     ("com.volpred.release-pool",         "release_pool.log",    8,   "release_pool"),
    "market_cal":       ("com.volpred.market-calendar-sync", "market_cal.log",      200, "market_calendar_sync"),
    "memory_health":    ("com.volpred.memory-health-daily",  "memory_health.log",   30,  "memory_health_daily"),
    "work_summary":     ("com.volpred.work-summary",         "work_summary.log",    12,  None),
}


def _piggy_back_end(job_id: str) -> datetime | None:
    """Read piggy-back last-success timestamp from cron_last_run.json."""
    if not LAST_RUN_PATH.exists():
        return None
    try:
        state = json.loads(LAST_RUN_PATH.read_text())
    except (OSError, ValueError):
        return None
    raw = state.get(job_id) if isinstance(state, dict) else None
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(TPE)
    except ValueError:
        return None


def _parse_ts(ln: str) -> datetime | None:
    """Parse a banner timestamp → tz-aware datetime in TPE. Handles both
    UTC ISO (`2026-05-21T12:00:38.123+00:00`) and local (`2026-05-21 20:07:02
    CST` / no zone)."""
    m = re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?\+00:00", ln)
    if m:
        return datetime.fromisoformat(m.group(0)).astimezone(TPE)
    m = re.search(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}", ln)
    if m:
        return datetime.strptime(m.group(0).replace("T", " "),
                                 "%Y-%m-%d %H:%M:%S").replace(tzinfo=TPE)
    return None


def launchctl_state(label: str) -> dict:
    """Authoritative run-count / last-exit / running state from launchctl."""
    uid = os.getuid()
    try:
        out = subprocess.run(
            ["launchctl", "print", f"gui/{uid}/{label}"],
            capture_output=True, text=True, timeout=10,
        ).stdout
    except Exception as e:
        return {"error": str(e)}
    runs = re.search(r"runs = (\d+)", out)
    last_exit = re.search(r"last exit code = (\d+|\(never exited\))", out)
    pid = re.search(r"\bpid = (\d+)", out)
    return {
        "runs": int(runs.group(1)) if runs else None,
        "last_exit": last_exit.group(1) if last_exit else None,
        "running": bool(pid),
    }


def last_log_run(log_path: Path) -> dict:
    """Last run banner: start + end datetimes (tz-aware TPE), complete?

    `mtime` (log file modification time) is also returned as an authoritative
    last-activity floor: many wrappers (e.g. collect_tw) emit a completion
    marker that is NOT a parseable `===…(exit|end)…` banner (collect_tw uses
    `✓ 台股數據收集完成`), so banner-parsed `end` falsely reverts to an old
    run. The wrapper writes the log on every fire → mtime never lies about
    *when the job last ran*. Used by main() to override stale `end` for the
    staleness gap check (same fix philosophy as ops_dashboard.py health_cron,
    2026-05-29).
    """
    if not log_path.exists():
        return {"error": "log missing"}
    try:
        lines = log_path.read_text(errors="ignore").splitlines()
    except OSError as e:
        return {"error": str(e)}
    mtime = None
    try:
        mtime = datetime.fromtimestamp(log_path.stat().st_mtime, TPE)
    except OSError:
        pass
    start = end = None
    for ln in reversed(lines):
        if "===" not in ln:
            continue
        is_end = bool(re.search(r"\b(exit|end)\b", ln))
        ts = _parse_ts(ln)
        if ts is None:
            continue
        if is_end and end is None:
            end = ts
        elif not is_end:
            start = ts
            break
    return {"start": start, "end": end, "mtime": mtime,
            "complete": bool(end) and (start is None or end >= start)}


def git_commits_since(minutes: int = 75) -> list[str]:
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO), "log", f"--since={minutes} minutes ago",
             "--pretty=%h %s"], capture_output=True, text=True, timeout=10,
        ).stdout.strip()
        return [l for l in out.splitlines() if l]
    except Exception:
        return []


def main() -> int:
    now = datetime.now(TPE)
    print(f"=== cron 成果掌握 review — {now:%Y-%m-%d %H:%M:%S}（台灣時間）===\n")
    attention = []
    for job, (label, logname, max_gap_h, piggy_id) in JOBS.items():
        st = launchctl_state(label)
        lg = last_log_run(LOGS / logname)
        flags = []
        le = st.get("last_exit")
        if le not in (None, "0", "(never exited)"):
            flags.append(f"🔴 last exit {le}")
        end = lg.get("end")
        # piggy-back fallback: 若 log banner end 不存在或太舊，查 cron_last_run.json
        source = "log"
        if piggy_id:
            pb_end = _piggy_back_end(piggy_id)
            if pb_end and (end is None or pb_end > end):
                end = pb_end
                source = "piggy-back"
        # log-mtime override（2026-05-29）：wrapper 每次 fire 都寫 log，mtime 是
        # 權威「最後活動」floor。當 banner/piggy-back 抓到的 end 比 mtime 舊（例
        # collect_tw 完成標記非 ===banner，banner end 退回舊班），mtime 勝出 —
        # 修掉對 piggy_back_skip / 非標準 banner job 的假 stale + 假中斷。
        mtime = lg.get("mtime")
        if mtime and (end is None or mtime > end):
            end = mtime
            source = "log-mtime"
        when = "?"
        if end:
            suffix = {"log": "", "piggy-back": " (piggy-back)",
                      "log-mtime": " (log-mtime)"}.get(source, "")
            when = end.strftime("%Y-%m-%d %H:%M:%S") + suffix
            gap_h = (now - end).total_seconds() / 3600
            if gap_h > max_gap_h:
                flags.append(f"⚠️ 上次完成 {gap_h:.1f}h 前（>{max_gap_h}h）")
        elif lg.get("start"):
            when = lg["start"].strftime("%Y-%m-%d %H:%M:%S") + " (start)"
        if lg.get("start") and not lg.get("complete") and not st.get("running") and source == "log":
            flags.append("⚠️ 最後一班有 start 無 end（疑似中斷）")
        status = "running" if st.get("running") else "idle"
        line = f"{job:17} runs={st.get('runs')} exit={le} {status} | last: {when}"
        if flags:
            line += "  " + " ".join(flags)
            attention.append(f"{job}: {' '.join(flags)}")
        print("  " + line)

    commits = git_commits_since(75)
    print(f"\n近 75 分鐘 git commits（hourly_dispatch 產出代理）：{len(commits)} 筆")
    for c in commits[:8]:
        print("  " + c)

    print()
    if attention:
        print("🔴 需要掌握/處理：")
        for a in attention:
            print("  - " + a)
    else:
        print("✅ 所有 cron 排程器：last exit 0、無逾時、無中斷班。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
