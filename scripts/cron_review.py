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
import os
import re
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LOGS = REPO / "storage" / "logs" / "cron"
TPE = timezone(timedelta(hours=8))

# job → (launchd label, log file, expected max gap hours before "stale")
JOBS = {
    "hourly_dispatch":  ("com.volpred.hourly-dispatch",      "hourly_dispatch.log", 2),
    "compute_worker":   ("com.volpred.compute-worker",       "compute_worker.log",  1),
    "check_alerts":     ("com.volpred.check-alerts",         "check_alerts.log",    2),
    "collect_tw":       ("com.volpred.collect-tw-data",      "collect_tw.log",      30),
    "collect_us":       ("com.volpred.collect-us-data",      "collect_us.log",      30),
    "daily_update":     ("com.volpred.daily-update",         "daily_update.log",    30),
    "release_pool":     ("com.volpred.release-pool",         "release_pool.log",    8),
    "market_cal":       ("com.volpred.market-calendar-sync", "market_cal.log",      200),
    "memory_health":    ("com.volpred.memory-health-daily",  "memory_health.log",   30),
    "work_summary":     ("com.volpred.work-summary",         "work_summary.log",    12),
}


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
    """Last run banner: start + end datetimes (tz-aware TPE), complete?"""
    if not log_path.exists():
        return {"error": "log missing"}
    try:
        lines = log_path.read_text(errors="ignore").splitlines()
    except OSError as e:
        return {"error": str(e)}
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
    return {"start": start, "end": end,
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
    for job, (label, logname, max_gap_h) in JOBS.items():
        st = launchctl_state(label)
        lg = last_log_run(LOGS / logname)
        flags = []
        le = st.get("last_exit")
        if le not in (None, "0", "(never exited)"):
            flags.append(f"🔴 last exit {le}")
        end = lg.get("end")
        when = "?"
        if end:
            when = end.strftime("%Y-%m-%d %H:%M:%S")
            gap_h = (now - end).total_seconds() / 3600
            if gap_h > max_gap_h:
                flags.append(f"⚠️ 上次完成 {gap_h:.1f}h 前（>{max_gap_h}h）")
        elif lg.get("start"):
            when = lg["start"].strftime("%Y-%m-%d %H:%M:%S") + " (start)"
        if lg.get("start") and not lg.get("complete") and not st.get("running"):
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
