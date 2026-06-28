from __future__ import annotations

import os
import shutil
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .common import load_json, project_path
from .diagnostics import warn
from .schedules import get_job_cron, previous_scheduled_fire
from .scheduler import get_scheduler_state

_TAIPEI = ZoneInfo("Asia/Taipei")
# strategy_metrics.json is refreshed by the daily_update job. Its schedule is
# resolved from canonical config (single source of truth) so the freshness check
# can never drift from the actual cron. daily_update does NOT run on Sunday, so a
# flat 26h staleness threshold false-fires every Sunday/early-Monday; the check is
# schedule-aware: stale only if the most recent SCHEDULED refresh (+grace) failed
# to update the file — never on a day the writer wasn't expected to run.
#
# 2026-06-28 root cause: scripts/cron_review.py hardcoded a duplicate daily_update
# cron ('0 6 * * *') that drifted from canonical ('3 8 * * 1-6'), false-flagging
# every Sunday. To avoid the same class of bug here, the schedule below is read
# from config via get_job_cron(); the hardcoded fallback is a crash-guard only.
_DAILY_UPDATE_JOB_ID = "daily_update"
_DAILY_UPDATE_CRON_FALLBACK = "3 8 * * 1-6"  # canonical as of 2026-06-28; last-resort only
_METRICS_REFRESH_HOUR_TPE = 8       # fallback only — must track _DAILY_UPDATE_CRON_FALLBACK
_METRICS_REFRESH_MINUTE_TPE = 3     # fallback only
_METRICS_REFRESH_GRACE_HOURS = 3.0  # piggy-back latency + run duration buffer


def _fallback_last_expected_metrics_refresh(now_utc: datetime) -> datetime:
    """Crash-guard used only when croniter/config resolution fails.

    Replicates the Mon-Sat 08:03 Taipei walk-back without croniter. Must stay in
    sync with _DAILY_UPDATE_CRON_FALLBACK; primary path derives from config."""
    cutoff = now_utc.astimezone(_TAIPEI) - timedelta(hours=_METRICS_REFRESH_GRACE_HOURS)
    probe = cutoff.replace(
        hour=_METRICS_REFRESH_HOUR_TPE, minute=_METRICS_REFRESH_MINUTE_TPE,
        second=0, microsecond=0,
    )
    if probe > cutoff:
        probe -= timedelta(days=1)
    while probe.weekday() == 6:  # Sunday — writer doesn't run
        probe -= timedelta(days=1)
    return probe.astimezone(timezone.utc)


def _last_expected_metrics_refresh(now_utc: datetime) -> datetime:
    """Most recent scheduled daily_update fire >= GRACE hours before now (UTC).

    Schedule is resolved from canonical config (get_job_cron) so it auto-follows
    the real cron — Sunday is exempt by construction (a Mon-Sat schedule's prior
    fire is Saturday). Falls back to a hardcoded Mon-Sat 08:03 walk-back only if
    config lookup or croniter is unavailable (warned, never silent)."""
    cron = get_job_cron(_DAILY_UPDATE_JOB_ID)
    if not cron:
        warn(
            "health_strategy_metrics",
            "daily_update cron absent from canonical schedule; using fallback",
            job_id=_DAILY_UPDATE_JOB_ID,
            fallback=_DAILY_UPDATE_CRON_FALLBACK,
        )
        cron = _DAILY_UPDATE_CRON_FALLBACK
    try:
        prev = previous_scheduled_fire(
            cron,
            now=now_utc.astimezone(_TAIPEI),
            tz=_TAIPEI,
            grace_hours=_METRICS_REFRESH_GRACE_HOURS,
        )
        return prev.astimezone(timezone.utc)
    except Exception as exc:  # croniter missing / malformed cron — crash-guard
        warn(
            "health_strategy_metrics",
            "previous_scheduled_fire failed; using hardcoded Mon-Sat walk-back",
            cron=cron,
            err=str(exc),
        )
        return _fallback_last_expected_metrics_refresh(now_utc)

# ---------------------------------------------------------------------------
# Standalone health checks (migrated 2026-06-24 from the now-disabled cloud
# `platform-ops-patrol` routine, which pushed origin/main and forked git).
# Each returns a normalized status dict consumed by both `health_snapshot()`
# and the alert chain (`src/volpred/ops/alerts.py::_parse_*_state`).
# ---------------------------------------------------------------------------

STRATEGY_METRICS_STALE_HOURS = 26.0
PAPER_TRADING_GAP_NULL_THRESHOLD = 2  # >2 nulls in last 3 entries → gap alert
DISK_USAGE_ALERT_PCT = 85.0
DISK_USAGE_MIN_FREE_GB = 50.0  # 雙條件：須同時 >85% 且 free < 50GB 才 alert（避免大碟誤報）


def check_strategy_metrics_freshness(storage_dir: str = "storage") -> dict:
    """storage/strategy_metrics.json mtime > 26h (or missing) → stale.

    The file is rewritten daily by the strategy-metrics refresh job; a stale
    mtime means that job stopped firing.
    """
    path = project_path(storage_dir) / "strategy_metrics.json"
    if not path.exists():
        return {
            "status": "stale",
            "exists": False,
            "age_hours": None,
            "threshold_hours": STRATEGY_METRICS_STALE_HOURS,
        }
    try:
        mtime = os.path.getmtime(path)
        age_hours = round((datetime.now(timezone.utc).timestamp() - mtime) / 3600.0, 2)
    except OSError as exc:
        warn(
            "health_strategy_metrics",
            "getmtime failed; treating as stale",
            path=str(path),
            err=str(exc),
        )
        return {
            "status": "stale",
            "exists": True,
            "age_hours": None,
            "threshold_hours": STRATEGY_METRICS_STALE_HOURS,
        }
    now_utc = datetime.now(timezone.utc)
    mtime_dt = datetime.fromtimestamp(mtime, timezone.utc)
    last_expected = _last_expected_metrics_refresh(now_utc)
    # Schedule-aware (2026-06-28): stale only if the most recent SCHEDULED
    # daily_update fire (canonical config cron) failed to update the file. Sunday
    # and early-Monday no longer false-fire because their previous scheduled run
    # is Saturday and the file is fresh relative to that.
    status = "stale" if mtime_dt < last_expected else "ok"
    cron = get_job_cron(_DAILY_UPDATE_JOB_ID) or _DAILY_UPDATE_CRON_FALLBACK
    return {
        "status": status,
        "exists": True,
        "age_hours": age_hours,
        "last_expected_refresh_utc": last_expected.isoformat(),
        "schedule": f"daily_update cron {cron} (Asia/Taipei)",
    }


def check_paper_trading_gaps(storage_dir: str = "storage") -> dict:
    """Per strategy, inspect the last 3 paper_trading entries; if >2 of their
    portfolio_return values are null → gap alert.

    One trailing null is normal weekend-settlement lag; only >2 (i.e. all 3 of
    the last 3) signals a stuck forward-tracking pipeline.
    """
    paper_trading = load_json(project_path(storage_dir) / "paper_trading.json", {})
    if not isinstance(paper_trading, dict):
        warn(
            "health_paper_trading",
            "paper_trading.json not a dict; skipping gap check",
            got_type=type(paper_trading).__name__,
        )
        return {"status": "ok", "gap_strategies": []}

    gap_strategies: list[dict] = []
    for name, payload in paper_trading.items():
        entries = (payload or {}).get("entries", []) if isinstance(payload, dict) else []
        if not isinstance(entries, list):
            warn(
                "health_paper_trading",
                "entries not a list; skipping strategy",
                strategy=str(name),
                got_type=type(entries).__name__,
            )
            continue
        last3 = entries[-3:]
        null_count = sum(
            1
            for e in last3
            if isinstance(e, dict) and e.get("portfolio_return") is None
        )
        if null_count > PAPER_TRADING_GAP_NULL_THRESHOLD:
            gap_strategies.append({"strategy": str(name), "null_count": null_count})

    return {
        "status": "gap" if gap_strategies else "ok",
        "gap_strategies": gap_strategies,
        "null_threshold": PAPER_TRADING_GAP_NULL_THRESHOLD,
    }


def check_disk_usage(storage_dir: str = "storage") -> dict:
    """Disk usage > 85% AND free < 50GB → alert (雙條件，避免大碟誤報)."""
    target = project_path(storage_dir)
    unknown = {
        "status": "unknown",
        "pct": None,
        "free_gb": None,
        "threshold_pct": DISK_USAGE_ALERT_PCT,
        "min_free_gb": DISK_USAGE_MIN_FREE_GB,
    }
    try:
        usage = shutil.disk_usage(target)
        pct = round(usage.used / usage.total * 100.0, 2) if usage.total else None
        free_gb = round(usage.free / 1e9, 2)
    except OSError as exc:
        warn(
            "health_disk_usage",
            "disk_usage probe failed",
            path=str(target),
            err=str(exc),
        )
        return unknown
    if pct is None:
        return unknown
    # 雙條件：僅在使用率高 *且* 絕對剩餘空間不足時才 alert，避免大碟
    # （如 926GB）在 85% 時仍有上百 GB free 卻誤報。
    breached = pct > DISK_USAGE_ALERT_PCT and free_gb < DISK_USAGE_MIN_FREE_GB
    return {
        "status": "alert" if breached else "ok",
        "pct": pct,
        "free_gb": free_gb,
        "threshold_pct": DISK_USAGE_ALERT_PCT,
        "min_free_gb": DISK_USAGE_MIN_FREE_GB,
    }


def health_snapshot(storage_dir: str = "storage") -> dict:
    storage = project_path(storage_dir)
    feed = load_json(storage / "reports" / "feed.json", [])
    open_questions = load_json(storage / "memory" / "open_questions.json", [])
    paper_trading = load_json(storage / "paper_trading.json", {})
    failed_syncs = load_json(storage / ".failed_supabase_syncs.json", [])
    sync_state = load_json(storage / ".supabase_sync_state.json", {})
    scheduler_state = get_scheduler_state(storage_dir=storage_dir)
    agent_cli_health = load_json(storage / "ops" / "agent_cli_health.json", {})
    event_ledger_dir = storage / "ops" / "event_ledger"
    rollback_dir = storage / "ops" / "rollback_points"

    total_entries = sum(len((strategy or {}).get("entries", [])) for strategy in paper_trading.values())
    rollback_points = sorted(rollback_dir.glob("*")) if rollback_dir.exists() else []

    return {
        "storage_dir": str(storage),
        "feed_items": len(feed),
        "reports": len(list((storage / "reports").glob("*.json"))) if (storage / "reports").exists() else 0,
        "open_questions": len(open_questions),
        "paper_trading_strategies": len(paper_trading),
        "paper_trading_entries": total_entries,
        "risk_forecast_exists": (storage / "risk_forecast.json").exists(),
        "failed_supabase_syncs": len(failed_syncs),
        "has_incremental_sync_state": bool(sync_state),
        "scheduler_last_tick_at": scheduler_state.get("last_tick_at"),
        "scheduler_last_status": scheduler_state.get("last_status"),
        "agent_cli_health": agent_cli_health if isinstance(agent_cli_health, dict) and agent_cli_health else None,
        "event_ledger_entries": len(list(event_ledger_dir.glob("*.json"))) if event_ledger_dir.exists() else 0,
        "rollback_points": len(rollback_points),
        "latest_rollback_point": rollback_points[-1].name if rollback_points else None,
        # 2026-06-24 migrated from cloud platform-ops-patrol (3 checks).
        "strategy_metrics_freshness": check_strategy_metrics_freshness(storage_dir),
        "paper_trading_gaps": check_paper_trading_gaps(storage_dir),
        "disk_usage": check_disk_usage(storage_dir),
    }
