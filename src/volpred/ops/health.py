from __future__ import annotations

import os
import shutil
from datetime import datetime, timezone

from .common import load_json, project_path
from .diagnostics import warn
from .scheduler import get_scheduler_state

# ---------------------------------------------------------------------------
# Standalone health checks (migrated 2026-06-24 from the now-disabled cloud
# `platform-ops-patrol` routine, which pushed origin/main and forked git).
# Each returns a normalized status dict consumed by both `health_snapshot()`
# and the alert chain (`src/volpred/ops/alerts.py::_parse_*_state`).
# ---------------------------------------------------------------------------

STRATEGY_METRICS_STALE_HOURS = 26.0
PAPER_TRADING_GAP_NULL_THRESHOLD = 2  # >2 nulls in last 3 entries → gap alert
DISK_USAGE_ALERT_PCT = 85.0


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
    status = "stale" if age_hours > STRATEGY_METRICS_STALE_HOURS else "ok"
    return {
        "status": status,
        "exists": True,
        "age_hours": age_hours,
        "threshold_hours": STRATEGY_METRICS_STALE_HOURS,
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
    """Root-filesystem usage > 85% → alert."""
    target = project_path(storage_dir)
    try:
        usage = shutil.disk_usage(target)
        pct = round(usage.used / usage.total * 100.0, 2) if usage.total else None
    except OSError as exc:
        warn(
            "health_disk_usage",
            "disk_usage probe failed",
            path=str(target),
            err=str(exc),
        )
        return {"status": "unknown", "pct": None, "threshold_pct": DISK_USAGE_ALERT_PCT}
    if pct is None:
        return {"status": "unknown", "pct": None, "threshold_pct": DISK_USAGE_ALERT_PCT}
    return {
        "status": "alert" if pct > DISK_USAGE_ALERT_PCT else "ok",
        "pct": pct,
        "threshold_pct": DISK_USAGE_ALERT_PCT,
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
