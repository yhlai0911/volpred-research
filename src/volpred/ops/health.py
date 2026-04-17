from __future__ import annotations

from .common import load_json, project_path
from .scheduler import get_scheduler_state


def health_snapshot(storage_dir: str = "storage") -> dict:
    storage = project_path(storage_dir)
    feed = load_json(storage / "reports" / "feed.json", [])
    open_questions = load_json(storage / "memory" / "open_questions.json", [])
    paper_trading = load_json(storage / "paper_trading.json", {})
    failed_syncs = load_json(storage / ".failed_supabase_syncs.json", [])
    sync_state = load_json(storage / ".supabase_sync_state.json", {})
    scheduler_state = get_scheduler_state(storage_dir=storage_dir)
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
        "event_ledger_entries": len(list(event_ledger_dir.glob("*.json"))) if event_ledger_dir.exists() else 0,
        "rollback_points": len(rollback_points),
        "latest_rollback_point": rollback_points[-1].name if rollback_points else None,
    }
