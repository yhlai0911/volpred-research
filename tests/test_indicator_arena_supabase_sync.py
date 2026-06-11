from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from volpred.indicators.supabase_sync import (
    build_registry_rows,
    build_signal_rows,
    build_review_rows,
    sync_indicator_arena,
)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _seed_storage(tmp_path: Path) -> Path:
    storage = tmp_path / "storage"
    arena = storage / "indicator_arena"
    arena.mkdir(parents=True, exist_ok=True)

    registry = [
        {
            "indicator_id": "demo_indicator",
            "name_zh": "示範指標",
            "league": "direction",
            "signal_rule": "demo rule with lag",
            "target": "SPY next-day return sign",
            "horizon_days": 1,
            "data_sources": {"SPY": {"provider": "yfinance"}},
            "k_refs": ["K999"],
            "oos_evidence": {"K999": {"dm_t": -2.5}},
            "caveats": "demo",
            "status": "active",
            "status_since": "2026-06-11T00:00:00Z",
            "listed_at": "2026-06-11T00:00:00Z",
            "delisted_at": None,
            "status_history": [{"status": "active", "since": "2026-06-11T00:00:00Z"}],
        }
    ]
    (arena / "registry.json").write_text(json.dumps(registry, ensure_ascii=False), encoding="utf-8")

    _write_jsonl(
        arena / "signals" / "2026-06.jsonl",
        [
            {
                "signal_id": "demo_indicator:2026-06-11",
                "indicator_id": "demo_indicator",
                "as_of_ts": "2026-06-11T05:00:00+00:00",
                "emitted_at": "2026-06-11T05:10:00+00:00",
                "prediction": {"direction": "up"},
                "horizon_days": 1,
                "expires_at": "2026-06-12T05:00:00+00:00",
                "resolve_after": "2026-06-12T20:00:00+00:00",
                "data_hash": "abc123",
                "code_version": "deadbee",
                "indicator_value": 0.42,
                "inputs_snapshot": {"spy_ret": 0.01},
            }
        ],
    )

    _write_jsonl(
        arena / "reviews" / "2026-06.jsonl",
        [
            {
                "review_id": "demo_indicator:2026-06-11:review",
                "signal_id": "demo_indicator:2026-06-11",
                "indicator_id": "demo_indicator",
                "reviewed_at": "2026-06-12T20:05:00+00:00",
                "realized": {"actual_return": 0.012},
                "hit": True,
                "econ_value_bps": 120.0,
                "data_source_asof": "2026-06-12T20:03:00+00:00",
                "correction_of": None,
                "league": "direction",
            }
        ],
    )
    return storage


def test_build_rows_from_local_storage(tmp_path: Path):
    storage = _seed_storage(tmp_path)
    registry_rows = build_registry_rows(storage)
    signal_rows = build_signal_rows(storage)
    review_rows = build_review_rows(storage)

    assert len(registry_rows) == 1
    assert registry_rows[0]["indicator_id"] == "demo_indicator"
    assert len(signal_rows) == 1
    assert signal_rows[0]["published_at"] == "2026-06-11T05:10:00+00:00"
    assert signal_rows[0]["target_date"] == "2026-06-12"
    assert len(review_rows) == 1
    assert review_rows[0]["review_id"].endswith(":review")


def test_sync_indicator_arena_dry_run_preview(tmp_path: Path):
    storage = _seed_storage(tmp_path)
    result = sync_indicator_arena(storage_dir=storage, dry_run=True)
    assert result["ok"] is True
    assert result["indicator_registry"] == 1
    assert result["daily_signals"] == 1
    assert result["outcome_reviews"] == 1
    assert result["preview"]["indicator_registry"][0]["indicator_id"] == "demo_indicator"


def test_sync_indicator_arena_uses_upsert_fn(tmp_path: Path):
    storage = _seed_storage(tmp_path)
    calls: list[tuple[str, list[dict]]] = []

    def fake_upsert(table: str, rows: list[dict]) -> bool:
        calls.append((table, rows))
        return True

    result = sync_indicator_arena(storage_dir=storage, dry_run=False, upsert_fn=fake_upsert)
    assert result["ok"] is True
    assert [name for name, _ in calls] == ["indicator_registry", "daily_signals", "outcome_reviews"]


def test_indicator_arena_cli_sync_supabase_dry_run(tmp_path: Path):
    storage = _seed_storage(tmp_path)
    from volpred.indicators.cli import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["sync-supabase", "--storage-dir", str(storage), "--dry-run"])
    assert result.exit_code == 0
    assert "indicator_registry" in result.output


def test_ops_indicator_arena_sync_command_dry_run(tmp_path: Path):
    storage = _seed_storage(tmp_path)
    from volpred.cli import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["ops", "indicator-arena-sync", "--storage-dir", str(storage), "--dry-run"])
    assert result.exit_code == 0
    assert "daily_signals" in result.output
