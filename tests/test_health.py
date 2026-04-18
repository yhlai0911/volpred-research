from __future__ import annotations

import json
from pathlib import Path

from volpred.ops.health import health_snapshot


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_health_snapshot_includes_agent_cli_health(tmp_path: Path):
    storage_dir = tmp_path / "storage"
    _write_json(
        storage_dir / "reports" / "feed.json",
        [],
    )
    _write_json(
        storage_dir / "memory" / "open_questions.json",
        [],
    )
    _write_json(
        storage_dir / "paper_trading.json",
        {},
    )
    _write_json(
        storage_dir / ".failed_supabase_syncs.json",
        [],
    )
    _write_json(
        storage_dir / ".supabase_sync_state.json",
        {},
    )
    _write_json(
        storage_dir / "ops" / "scheduler_state.json",
        {"last_tick_at": "2026-04-18T00:00:00+00:00", "last_status": "ok"},
    )
    _write_json(
        storage_dir / "ops" / "agent_cli_health.json",
        {
            "generated_at": "2026-04-18T00:10:00+00:00",
            "overall_status": "degraded",
            "paths": {
                "claude_executor": {
                    "readiness": "blocked",
                    "reason_code": "auth_required",
                },
                "codex_executor": {
                    "readiness": "ready",
                    "reason_code": "ok",
                },
            },
        },
    )

    snapshot = health_snapshot(storage_dir=str(storage_dir))
    assert snapshot["agent_cli_health"]["overall_status"] == "degraded"
    assert snapshot["agent_cli_health"]["paths"]["claude_executor"]["reason_code"] == "auth_required"
