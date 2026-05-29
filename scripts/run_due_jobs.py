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
PENDING_SESSIONS_PATH = PROJECT_ROOT / "storage" / "ops" / "pending_sessions.json"

# Jobs handled specially elsewhere (check_alerts itself + shared_scheduler_tick
# advisory) or that should not be invoked by this piggy-back.
SKIP_JOB_IDS = {
    "check_alerts",           # we ARE check_alerts — would recurse
    "shared_scheduler_tick",  # advisory-only in v12, host_crontab_managed=false
    # 2026-05-17: daily_update hangs (likely Supabase sync stall) — exceeded
    # 240s subprocess cap repeatedly → killed check_alerts wrapper at 300s for
    # 5 consecutive hours. Disabled from piggy-back; daily_update has its own
    # host cron entry `3 8 * * 1-6`. Re-enable only after daily_update hang
    # root-cause is fixed (see docs/error_log.md 2026-05-17 entry).
    "daily_update",
}

DEFAULT_SUBPROCESS_TIMEOUT_SEC = 240  # 4 min per job (under check_alerts 300s wrapper cap)
# 2026-05-17 fix: was 600s but check_alerts.sh wrapper SIGALRM cap is 300s.
# Any single hanging job took full 600s while wrapper killed parent at 300s →
# 5 hours of consecutive HANG-KILLED. Keep 240 < 300 with 60s headroom for
# the rest of check_alerts (alert eval ~0.7s + report formatting).
# Long jobs (daily_update can take 5-10min) should run via direct host cron
# (configured separately), NOT via this piggy-back fan-out.


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


def _load_pending_sessions() -> dict[str, Any]:
    default_state = {
        "schema_version": 1,
        "description": "Due session_crons recorded while Claude Code session is offline; replay on next session startup.",
        "jobs": {},
    }
    if not PENDING_SESSIONS_PATH.exists():
        return default_state
    try:
        data = json.loads(PENDING_SESSIONS_PATH.read_text())
        if not isinstance(data, dict):
            return default_state
        jobs = data.get("jobs")
        if not isinstance(jobs, dict):
            jobs = {}
        # Legacy migration: older buggy payloads could write top-level
        # `pending` / `session_crons` objects instead of canonical `jobs`.
        for legacy_key in ("pending", "session_crons"):
            legacy = data.get(legacy_key)
            if isinstance(legacy, dict):
                for job_id, job in legacy.items():
                    if job_id not in jobs and isinstance(job, dict):
                        jobs[job_id] = job
        data["schema_version"] = int(data.get("schema_version", 1) or 1)
        data["description"] = str(data.get("description") or default_state["description"])
        data["jobs"] = jobs
        return data
    except (OSError, ValueError):
        return default_state


def _save_pending_sessions(state: dict[str, Any]) -> None:
    PENDING_SESSIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    PENDING_SESSIONS_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n")


def _write_pending_sessions(
    session_items: list[dict[str, Any]],
    last_run_state: dict[str, str],
    now_local: datetime,
    now_utc: datetime,
) -> dict[str, Any]:
    """Scan session_crons.items; record due entries to pending_sessions.json.

    De-dupe: a job records only if either (a) it has never fired in
    `cron_last_run.json` or per-job pending history, or (b) its most recent
    cron fire time is newer than the last recorded `replayed_at` for that
    job. This prevents the hourly piggy-back from rewriting the same due
    window every hour when session is offline for multiple cron fires.
    """
    pending = _load_pending_sessions()
    jobs_state = pending.get("jobs") or {}
    updates: list[str] = []
    skipped: list[str] = []

    for item in session_items:
        job_id = item.get("id")
        cron_expr = item.get("cron")
        if not job_id or not cron_expr:
            continue
        if not item.get("recurring", True):
            continue  # one-shot (e.g. codex_quota_resume) handled separately

        job_pending = jobs_state.get(job_id) or {}
        # reference: prefer last replayed_at if any, else last fire recorded
        # in cron_last_run.json (rare for session crons but harmless), else None
        last_ref_iso = (
            job_pending.get("replayed_at")
            or job_pending.get("recorded_at")
            or last_run_state.get(job_id)
        )
        last_ref = _parse_iso(last_ref_iso)
        if not _job_is_due(cron_expr, last_ref, now_local):
            skipped.append(job_id)
            continue

        jobs_state[job_id] = {
            "cron": cron_expr,
            "prompt": (item.get("prompt") or "")[:500],
            "description": item.get("description"),
            "recorded_at": now_utc.isoformat(timespec="seconds"),
            "replayed_at": job_pending.get("replayed_at"),
            "recorded_count": int(job_pending.get("recorded_count", 0)) + 1,
        }
        updates.append(job_id)

    pending["jobs"] = jobs_state
    pending["last_scanned_at"] = now_utc.isoformat(timespec="seconds")
    _save_pending_sessions(pending)

    return {
        "ok": True,
        "recorded": updates,
        "skipped": skipped,
        "total_pending_jobs": sum(
            1 for j in jobs_state.values()
            if (j.get("recorded_at") or "") > (j.get("replayed_at") or "")
        ),
    }


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
        piggy_back_skip = item.get("piggy_back_skip")
        log_rel = item.get("log_path") or f"storage/logs/cron/{job_id}.log"

        if not job_id or not cron_expr or not wrapper:
            continue
        if job_id in SKIP_JOB_IDS:
            continue
        if managed is False:
            continue
        # piggy_back_skip=true means host crontab already fires this item
        # reliably; piggy-back must not double-fire. Distinct from
        # host_crontab_managed=false (which removes from host crontab too).
        # Set true for items whose host-cron pattern is empirically reliable
        # (e.g. `3 7 * * 2-6` collect_us — verified double-fire in 2026-05-29
        # incident: host cron 07:03 + piggy-back 00:00 UTC = 2 fetches/day).
        if piggy_back_skip is True:
            results.append({"job_id": job_id, "action": "skip",
                            "reason": "piggy_back_skip_host_managed"})
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

    # 2026-04-25: session_crons drift coverage. `session_crons.items` in
    # runtime_schedules.json describes 9 recurring crons (daily_planning /
    # continue_task / question_research / platform_patrol / git_sync /
    # knowledge_index_check / token_usage_daily / ndc_indicator_refresh /
    # codex_quota_resume) that depend on a live Claude Code session to fire
    # (CronCreate-backed). macOS CronCreate is unreliable and sessions close,
    # so these can silently miss for days. Piggy-back records each due session
    # cron to pending_sessions.json so the next session startup can replay
    # missed windows. Like continue_task_stub, this writes intent, not code
    # execution — the main-thread (or session_startup.md) decides how to act.
    session_items = (config.get("session_crons") or {}).get("items") or []
    session_pending = _write_pending_sessions(session_items, state, now_local, now)

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
        "session_pending": session_pending,
    }
    return summary


if __name__ == "__main__":
    summary = run_due_jobs()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
