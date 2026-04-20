#!/usr/bin/env python3
"""Universal piggy-back scheduler — triggered hourly by check_alerts cron.

Root-cause fix for macOS cron daemon reliability issue (2026-04-20):
the host cron daemon on this machine only reliably fires `0 * * * *` patterns
(confirmed via diagnostic test: `* * * * *` test cron never fired in 180s
window despite crontab -l showing the entry). All jobs with minute-offset or
DoW-filter patterns (`3 */2`, `0 8 * * 1`, `3 7 * * 2-6`, etc.) silently skip.

This module reads `config/runtime_schedules.json` as canonical schedule source,
tracks per-job last-run timestamps in `storage/ops/cron_last_run.json`, and
invokes each job's wrapper script when its next cron-computed fire time has
elapsed. Called from `check_alerts.py` at start of each hourly fire.

Contract:
- Only `host_crontab_managed != false` entries are dispatched here.
- `check_alerts` is explicitly skipped (it's the caller).
- Each job's last_run is updated ONLY on subprocess exit 0. On failure, the
  schedule re-evaluates next cycle so a transient failure doesn't silently
  skip a day.
- Subprocess invocations are time-bounded (default 600s) to prevent one
  hanging job from blocking others.
- Jobs invoked sequentially (not parallel) to avoid overwhelming the machine
  with concurrent yfinance / fred / LaTeX compiles.

Output: JSON status dict reporting which jobs fired, which skipped, any errors.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

try:
    from croniter import croniter
except ImportError:  # pragma: no cover
    croniter = None

# Host crontab expressions are in LOCAL time (macOS cron default). When we
# evaluate "is this job due?" via croniter, we must use the same local tz
# or specific-hour jobs like `0 8 * * 1` shift 8h from CST. Hardcoded
# CST because this is a Taiwan-based deployment; override via env var only
# if the box's actual local tz differs from canonical schedule intent.
LOCAL_TZ = ZoneInfo("Asia/Taipei")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "runtime_schedules.json"
LAST_RUN_PATH = PROJECT_ROOT / "storage" / "ops" / "cron_last_run.json"

# Jobs handled specially elsewhere (check_alerts itself + shared_scheduler_tick
# advisory) or that should not be invoked by this piggy-back.
SKIP_JOB_IDS = {
    "check_alerts",           # we ARE check_alerts — would recurse
    "shared_scheduler_tick",  # advisory-only in v12, host_crontab_managed=false
}

DEFAULT_SUBPROCESS_TIMEOUT_SEC = 600  # 10 min per job


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _local_now() -> datetime:
    return datetime.now(LOCAL_TZ)


def _load_last_run() -> dict[str, str]:
    if not LAST_RUN_PATH.exists():
        return {}
    try:
        data = json.loads(LAST_RUN_PATH.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_last_run(state: dict[str, str]) -> None:
    LAST_RUN_PATH.parent.mkdir(parents=True, exist_ok=True)
    LAST_RUN_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def _parse_iso(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _job_is_due(cron_expr: str, last_run: datetime | None, now_local: datetime) -> bool:
    """Return True if the job should fire now.

    Logic: find the most-recent cron fire time at or before `now_local`. If
    that time is strictly greater than `last_run`, a scheduled fire has been
    missed (or never happened yet).

    `now_local` MUST be timezone-aware in LOCAL_TZ (e.g. Asia/Taipei) because
    host crontab expressions are interpreted in local time by macOS cron,
    and our piggy-back must mirror that convention exactly.

    If `last_run` is None (never fired), consider due if any scheduled fire
    time exists in the 24h window before `now`.
    """
    if croniter is None:
        return False
    # Anchor 24h ago in epoch — ignores crons that would only fire further in
    # the past (prevents floods if last_run is very stale / missing).
    anchor_ts = now_local.timestamp() - 24 * 3600
    c = croniter(cron_expr, now_local)
    prev_fire_ts = c.get_prev()  # epoch seconds
    if prev_fire_ts < anchor_ts:
        return False
    prev_fire_utc = datetime.fromtimestamp(prev_fire_ts, tz=timezone.utc)
    if last_run is None:
        return True
    # last_run stored in UTC; normalize for comparison.
    if last_run.tzinfo is None:
        last_run = last_run.replace(tzinfo=timezone.utc)
    return prev_fire_utc > last_run


def run_due_jobs(subprocess_timeout: int = DEFAULT_SUBPROCESS_TIMEOUT_SEC) -> dict[str, Any]:
    """Dispatch due jobs. Returns summary dict for caller logging."""
    if not CONFIG_PATH.exists():
        return {"ok": False, "reason": "config_missing", "jobs": []}
    if croniter is None:
        return {"ok": False, "reason": "croniter_not_installed", "jobs": []}

    config = json.loads(CONFIG_PATH.read_text())
    items = (config.get("system_crontab") or {}).get("items") or []
    state = _load_last_run()
    now = _utc_now()
    now_local = _local_now()

    results = []
    for item in items:
        job_id = item.get("id")
        cron_expr = item.get("cron")
        wrapper = item.get("wrapper_script")
        managed = item.get("host_crontab_managed")
        log_rel = item.get("log_path") or f"storage/logs/cron/{job_id}.log"

        if not job_id or not cron_expr or not wrapper:
            continue
        if job_id in SKIP_JOB_IDS:
            continue
        if managed is False:
            continue

        wrapper_path = Path(wrapper) if wrapper.startswith("/") else PROJECT_ROOT / wrapper
        if not wrapper_path.exists():
            results.append({"job_id": job_id, "action": "skip", "reason": "wrapper_missing", "path": str(wrapper_path)})
            continue

        last_run = _parse_iso(state.get(job_id))
        if not _job_is_due(cron_expr, last_run, now_local):
            results.append({"job_id": job_id, "action": "skip", "reason": "not_due",
                           "last_run": state.get(job_id), "cron": cron_expr})
            continue

        # Invoke wrapper; capture stdout/stderr to job's own log file (same as
        # host cron would) so behavior is observationally identical.
        log_abs = PROJECT_ROOT / log_rel
        log_abs.parent.mkdir(parents=True, exist_ok=True)
        try:
            with log_abs.open("ab") as log_fp:
                start = _utc_now()
                log_fp.write(f"=== [{job_id}] piggy-back fire at {start.isoformat()} ===\n".encode())
                log_fp.flush()
                proc = subprocess.run(
                    [str(wrapper_path)],
                    stdout=log_fp,
                    stderr=subprocess.STDOUT,
                    timeout=subprocess_timeout,
                )
                end = _utc_now()
                log_fp.write(f"=== [{job_id}] exit {proc.returncode} at {end.isoformat()} (duration={(end-start).total_seconds():.1f}s) ===\n".encode())
            if proc.returncode == 0:
                state[job_id] = end.isoformat(timespec="seconds")
                results.append({"job_id": job_id, "action": "fired", "ok": True, "duration_sec": round((end - start).total_seconds(), 1)})
            else:
                results.append({"job_id": job_id, "action": "fired", "ok": False,
                               "exit_code": proc.returncode, "duration_sec": round((end - start).total_seconds(), 1)})
        except subprocess.TimeoutExpired:
            results.append({"job_id": job_id, "action": "fired", "ok": False, "reason": "timeout", "timeout_sec": subprocess_timeout})
        except Exception as exc:  # noqa: BLE001
            results.append({"job_id": job_id, "action": "fired", "ok": False, "reason": f"error:{exc}"})

    _save_last_run(state)

    # 2026-04-20: also expand event_jobs entries whose `not_before` has
    # arrived. `shared_scheduler_tick` was the intended call site for this
    # but v12 downgraded it to advisory-only (CLAUDE.md §control-plane) and
    # its wrapper never runs on this host (scheduler_tick.log size=0 since
    # 2026-04-19). Piggy-backing on hourly check_alerts ensures one_shot
    # event jobs (e.g. FOMC T-2 windows) materialize as control-plane tasks
    # within ~60 min of their `not_before` timestamp. Cost is cheap: iterates
    # event_jobs.items and no-ops pending/expired entries.
    event_expansion: dict[str, Any] = {"ok": False, "reason": "not_attempted"}
    try:
        import sys as _sys
        _src = PROJECT_ROOT / "src"
        if str(_src) not in _sys.path:
            _sys.path.insert(0, str(_src))
        from volpred.ops.event_jobs import expand_due_event_jobs  # type: ignore
        event_expansion = expand_due_event_jobs(storage_dir=str(PROJECT_ROOT / "storage"))
        event_expansion["ok"] = True
    except Exception as exc:  # noqa: BLE001
        event_expansion = {"ok": False, "reason": f"error:{exc}"}

    summary = {
        "ok": True,
        "ran_at": now.isoformat(timespec="seconds"),
        "fired_count": sum(1 for r in results if r.get("action") == "fired"),
        "skipped_count": sum(1 for r in results if r.get("action") == "skip"),
        "jobs": results,
        "event_expansion": event_expansion,
    }
    return summary


if __name__ == "__main__":
    summary = run_due_jobs()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
