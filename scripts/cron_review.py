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

# job → (launchd label, log file, fallback max gap hours, piggy_back_id, cron_expr)
#
# 2026-05-27: market_cal / memory_health 的 LaunchAgent 從未可靠 fire（macOS cron
# 限制），實際靠 piggy-back via check_alerts. cron_review v1 只看 launchctl + log
# banner → 持續 false-flag stale 數天。Fix: piggy_back_id 從 cron_last_run.json
# 補 fallback timestamp。
#
# 2026-06-08 (3-strike fix): collect_tw / collect_us 是 weekday-only cron
# (`0 15 * * 1-5` / `3 7 * * 2-6`)。原本只用通用 max_gap_h（30h）→ 週六日
# last fire 必超 30h false-flag stale。Boss report 因此反覆寄假警報 → 老闆 6/8
# 直接寫信「立刻徹底解決 warning」。Wrong domain model：staleness 不是 wallclock
# 函數，是 cron schedule 函數。Fix: 新增 cron_expr 欄位，用 croniter 算
# expected_last_fire = get_prev(now)；actual_last_fire >= expected_last_fire -
# slack → OK；否則 stale。cron_expr 缺省 fallback 回舊 max_gap_h 行為。
JOBS = {
    "hourly_dispatch":  ("com.volpred.hourly-dispatch",      "hourly_dispatch.log", 2,   None,                    "7 * * * *"),
    "compute_worker":   ("com.volpred.compute-worker",       "compute_worker.log",  1,   None,                    "*/15 * * * *"),
    "check_alerts":     ("com.volpred.check-alerts",         "check_alerts.log",    2,   None,                    "0 * * * *"),
    "collect_tw":       ("com.volpred.collect-tw-data",      "collect_tw.log",      30,  "collect_tw_data",       "0 15 * * 1-5"),
    "collect_us":       ("com.volpred.collect-us-data",      "collect_us.log",      30,  "collect_us_data",       "3 7 * * 2-6"),
    "daily_update":     ("com.volpred.daily-update",         "daily_update.log",    30,  "daily_update",          "0 6 * * *"),
    "release_pool":     ("com.volpred.release-pool",         "release_pool.log",    8,   "release_pool",          "7 */3 * * *"),
    "market_cal":       ("com.volpred.market-calendar-sync", "market_cal.log",      200, "market_calendar_sync",  "0 8 * * 1"),
    "memory_health":    ("com.volpred.memory-health-daily",  "memory_health.log",   30,  "memory_health_daily",   "30 5 * * *"),
    "work_summary":     ("com.volpred.work-summary",         "work_summary.log",    12,  None,                    "5 6 * * *"),
}

# Slack: 容許 actual_last_fire 比 expected_last_fire 慢多少還算 OK。
# expected = croniter prev(now)。多數 cron 在排定分鐘的 0-60s 內 fire；piggy-back
# 則靠 hourly check_alerts → 最大延遲 1h。給 2h slack 涵蓋 piggy-back lag + LaunchAgent
# missed-on-sleep 後在下次 wakeup 補跑的 ±10min。再大要懷疑真 stale。
_SLACK_HOURS = 2.0


def _warn_cron_review(message: str, path: Path, exc: Exception | None = None) -> None:
    suffix = f": path={path}"
    if exc is not None:
        suffix += f" error={type(exc).__name__}: {exc}"
    print(f"[cron_review] WARN {message}{suffix}", file=sys.stderr)


def _piggy_back_end(job_id: str) -> datetime | None:
    """Read piggy-back last-success timestamp from cron_last_run.json."""
    if not LAST_RUN_PATH.exists():
        return None
    try:
        state = json.loads(LAST_RUN_PATH.read_text())
    except (OSError, ValueError) as exc:
        _warn_cron_review("piggy-back state read failed; ignoring fallback timestamp", LAST_RUN_PATH, exc)
        return None
    if not isinstance(state, dict):
        _warn_cron_review("piggy-back state schema is not an object; ignoring fallback timestamp", LAST_RUN_PATH)
        return None
    raw = state.get(job_id) if isinstance(state, dict) else None
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone(TPE)
    except ValueError as exc:
        _warn_cron_review(
            f"piggy-back timestamp parse failed for job_id={job_id}; ignoring fallback timestamp",
            LAST_RUN_PATH,
            exc,
        )
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
    except OSError as exc:
        _warn_cron_review("log mtime stat failed; continuing without mtime fallback", log_path, exc)
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


def expected_prev_fire(now: datetime, cron_expr: str | None) -> datetime | None:
    """Croniter prev fire time aligned to now's tz. None if cron_expr 缺省。"""
    if not cron_expr:
        return None
    try:
        from croniter import croniter
        itr = croniter(cron_expr, now)
        prev = itr.get_prev(datetime)
        if prev.tzinfo is None:
            prev = prev.replace(tzinfo=now.tzinfo)
        return prev
    except Exception:
        return None


def _expected_last_fire(cron_expr: str | None, now: datetime) -> datetime | None:
    """Backward-compatible wrapper for older call sites."""
    return expected_prev_fire(now, cron_expr)


def is_stale(
    *,
    now: datetime,
    last_end: datetime,
    cron_expr: str | None,
    fallback_max_gap_h: float,
) -> tuple[bool, str | None]:
    """Return whether a job is stale and the human-readable flag to print."""
    gap_h = (now - last_end).total_seconds() / 3600
    expected = expected_prev_fire(now, cron_expr)
    if expected is not None:
        threshold = expected - timedelta(hours=_SLACK_HOURS)
        if last_end < threshold:
            miss_h = (expected - last_end).total_seconds() / 3600
            return True, (
                f"⚠️ 上次完成 {gap_h:.1f}h 前；預期 {expected:%Y-%m-%d %H:%M} "
                f"該 fire（已 miss {miss_h:.1f}h）"
            )
        return False, None
    if gap_h > fallback_max_gap_h:
        return True, f"⚠️ 上次完成 {gap_h:.1f}h 前（>{fallback_max_gap_h}h）"
    return False, None


def main() -> int:
    now = datetime.now(TPE)
    print(f"=== cron 成果掌握 review — {now:%Y-%m-%d %H:%M:%S}（台灣時間）===\n")
    attention = []
    for job, (label, logname, max_gap_h, piggy_id, cron_expr) in JOBS.items():
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
            stale, stale_flag = is_stale(
                now=now,
                last_end=end,
                cron_expr=cron_expr,
                fallback_max_gap_h=max_gap_h,
            )
            if stale and stale_flag:
                flags.append(stale_flag)
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
