from __future__ import annotations

import json
from pathlib import Path

from volpred.ops.health import health_snapshot


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_health_snapshot_has_no_retired_scheduler_or_cli_health_fields(tmp_path: Path):
    """2026-07-20 ops-master D2: the advisory scheduler lane and its live-smoke
    companion (sole writer of agent_cli_health.json) are retired; the health
    snapshot must not resurrect readouts of those dead state files."""
    storage_dir = tmp_path / "storage"
    _write_json(storage_dir / "reports" / "feed.json", [])
    _write_json(storage_dir / "memory" / "open_questions.json", [])
    _write_json(storage_dir / "paper_trading.json", {})
    _write_json(storage_dir / ".failed_supabase_syncs.json", [])
    _write_json(storage_dir / ".supabase_sync_state.json", {})
    # Stale artifacts from the retired lane must be ignored even if present.
    _write_json(
        storage_dir / "ops" / "scheduler_state.json",
        {"last_tick_at": "2026-04-18T00:00:00+00:00", "last_status": "ok"},
    )
    _write_json(
        storage_dir / "ops" / "agent_cli_health.json",
        {"generated_at": "2026-04-18T00:10:00+00:00", "overall_status": "degraded"},
    )

    snapshot = health_snapshot(storage_dir=str(storage_dir))
    assert "agent_cli_health" not in snapshot
    assert "scheduler_last_tick_at" not in snapshot
    assert "scheduler_last_status" not in snapshot
    assert snapshot["feed_items"] == 0
    assert snapshot["failed_supabase_syncs"] == 0
