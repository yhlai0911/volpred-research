#!/usr/bin/env python3
"""Observe daily_update LaunchAgent reliability over a fixed 1-week window.

Purpose:
  2026-05-25 incident: LaunchAgent `com.volpred.daily-update` did not fire on
  Monday 2026-05-25 08:03 Asia/Taipei, likely because macOS was asleep.
  User instruction (via email task): observe 2026-05-26 .. 2026-06-01 first,
  then decide whether to re-enable piggy-back fallback.

This script is intentionally observational. Before the window closes it should
produce a "pending observation" verdict, not a premature architecture change.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

try:
    from croniter import croniter
except ImportError:  # pragma: no cover
    croniter = None

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCHEDULES_PATH = PROJECT_ROOT / "config" / "runtime_schedules.json"
LOG_PATH = PROJECT_ROOT / "storage" / "logs" / "cron" / "daily_update.log"
OUT_PATH = PROJECT_ROOT / "storage" / "ops" / "daily_update_launchagent_observation.json"
LOCAL_TZ = ZoneInfo("Asia/Taipei")

WINDOW_START = datetime(2026, 5, 26, 0, 0, tzinfo=LOCAL_TZ)
WINDOW_END = datetime(2026, 6, 1, 23, 59, 59, tzinfo=LOCAL_TZ)
LAUNCHAGENT_LABEL = "com.volpred.daily-update"


@dataclass(frozen=True)
class LaunchctlStatus:
    runs: int | None
    last_exit: str | None
    running: bool


def _load_schedule() -> str:
    payload = json.loads(SCHEDULES_PATH.read_text(encoding="utf-8"))
    for item in (payload.get("system_crontab", {}) or {}).get("items", []):
        if item.get("id") == "daily_update":
            cron = item.get("cron")
            if cron:
                return str(cron)
    raise KeyError("daily_update cron not found in runtime_schedules.json")


def _launchctl_status() -> LaunchctlStatus:
    uid = str(subprocess.check_output(["id", "-u"], text=True).strip())
    out = subprocess.run(
        ["launchctl", "print", f"gui/{uid}/{LAUNCHAGENT_LABEL}"],
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout
    runs = re.search(r"runs = (\d+)", out)
    last_exit = re.search(r"last exit code = (\d+|\(never exited\))", out)
    pid = re.search(r"\bpid = (\d+)", out)
    return LaunchctlStatus(
        runs=int(runs.group(1)) if runs else None,
        last_exit=last_exit.group(1) if last_exit else None,
        running=bool(pid),
    )


def _parse_log_end_times() -> list[datetime]:
    if not LOG_PATH.exists():
        return []
    out: list[datetime] = []
    for line in LOG_PATH.read_text(encoding="utf-8", errors="ignore").splitlines():
        if "=== [daily_update] exit " not in line:
            continue
        match = re.search(r"at (\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:[+-]\d{4}))", line)
        if not match:
            continue
        ts = datetime.strptime(match.group(1), "%Y-%m-%dT%H:%M:%S%z").astimezone(LOCAL_TZ)
        out.append(ts)
    return out


def _expected_fire_points(cron_expr: str, *, start: datetime, end: datetime) -> list[datetime]:
    if croniter is None:
        return []
    cur = start
    itr = croniter(cron_expr, cur)
    points: list[datetime] = []
    while True:
        nxt = itr.get_next(datetime)
        if nxt.tzinfo is None:
            nxt = nxt.replace(tzinfo=LOCAL_TZ)
        nxt = nxt.astimezone(LOCAL_TZ)
        if nxt > end:
            break
        points.append(nxt)
    return points


def _match_observed_dates(expected: list[datetime], observed_end_times: list[datetime], *, as_of: datetime) -> dict[str, Any]:
    observed_dates = {ts.date().isoformat(): ts for ts in observed_end_times if ts <= as_of}
    rows: list[dict[str, Any]] = []
    misses = 0
    for fire in expected:
        if fire > as_of:
            status = "future"
            observed = None
        else:
            observed = observed_dates.get(fire.date().isoformat())
            if observed is None:
                status = "missing"
                misses += 1
            else:
                status = "observed"
        rows.append(
            {
                "expected_fire_at": fire.isoformat(timespec="seconds"),
                "expected_date": fire.date().isoformat(),
                "status": status,
                "observed_exit_at": observed.isoformat(timespec="seconds") if observed else None,
            }
        )
    return {"rows": rows, "miss_count_so_far": misses}


def build_report(*, as_of: datetime | None = None) -> dict[str, Any]:
    now = as_of or datetime.now(LOCAL_TZ)
    cron_expr = _load_schedule()
    launchctl = _launchctl_status()
    observed_end_times = _parse_log_end_times()
    expected = _expected_fire_points(cron_expr, start=WINDOW_START, end=WINDOW_END)
    matching = _match_observed_dates(expected, observed_end_times, as_of=now)

    window_closed = now >= WINDOW_END
    miss_count = matching["miss_count_so_far"]
    if not window_closed:
        recommendation = "DEFER_DECISION_UNTIL_WINDOW_CLOSE"
        verdict = "PENDING_OBSERVATION"
    elif miss_count >= 1:
        recommendation = "REENABLE_PIGGY_BACK_WITH_LOCK"
        verdict = "MISS_DETECTED"
    else:
        recommendation = "KEEP_LAUNCHAGENT_ONLY"
        verdict = "NO_MISS_DETECTED"

    return {
        "task_id": "daily_update_launchagent_observation_2026-06-01",
        "generated_at": now.isoformat(timespec="seconds"),
        "window": {
            "start": WINDOW_START.isoformat(timespec="seconds"),
            "end": WINDOW_END.isoformat(timespec="seconds"),
            "window_closed": window_closed,
        },
        "schedule": {
            "cron": cron_expr,
            "launchagent_label": LAUNCHAGENT_LABEL,
        },
        "launchctl_status": asdict(launchctl),
        "log_observation": {
            "log_path": str(LOG_PATH.relative_to(PROJECT_ROOT)),
            "observed_exit_count": len(observed_end_times),
            "latest_observed_exit": observed_end_times[-1].isoformat(timespec="seconds") if observed_end_times else None,
        },
        "observation_rows": matching["rows"],
        "miss_count_so_far": miss_count,
        "decision": {
            "verdict": verdict,
            "recommendation": recommendation,
            "rule": ">=1 missing fire over the observation window => re-enable piggy-back with lock; otherwise keep LaunchAgent-only.",
        },
        "notes": [
            "This observer uses log exit banners as the primary evidence of actual completion.",
            "launchctl runs=0 / last exit=(never exited) can still be unhelpful for this LaunchAgent, so do not use launchctl alone as a gate.",
            "Re-run this script after 2026-06-01 local close to finalize the decision.",
        ],
    }


def main() -> None:
    report = build_report()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
