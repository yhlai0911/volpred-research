from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from volpred.cli import cli
from volpred.ops import feed_sync


ROOT = Path(__file__).resolve().parents[1]


def _invoke_feed_sync(monkeypatch, result: dict, *arguments: str):
    monkeypatch.setattr(
        "volpred.ops.feed_sync.sync_feed_to_supabase",
        lambda **_kwargs: result,
    )
    return CliRunner().invoke(
        cli,
        ["ops", "feed-sync", *arguments],
    )


def test_apply_exits_nonzero_when_projection_effect_failed(monkeypatch) -> None:
    result = _invoke_feed_sync(
        monkeypatch,
        {
            "mode": "apply",
            "clean": False,
            "acknowledged": False,
            "diff": {
                "insert": ["mile_failed"],
                "update": [],
                "delete": [],
            },
            "result": {
                "inserted": 0,
                "updated": 0,
                "deleted": 0,
                "skipped_deletes": 0,
                "failed": 1,
                "failures": [
                    {"slug": "mile_failed", "op": "insert"},
                ],
                "reconcile": None,
            },
        },
        "--apply",
        "--no-delete",
    )

    assert result.exit_code == 1
    assert '"failed": 1' in result.output
    assert "mile_failed" in result.output


def test_apply_exits_zero_after_all_projection_effects_acknowledge(
    monkeypatch,
) -> None:
    result = _invoke_feed_sync(
        monkeypatch,
        {
            "mode": "apply",
            "clean": False,
            "acknowledged": True,
            "diff": {
                "insert": ["mile_delivered"],
                "update": [],
                "delete": [],
            },
            "result": {
                "inserted": 1,
                "updated": 0,
                "deleted": 0,
                "skipped_deletes": 0,
                "failed": 0,
                "failures": [],
                "reconcile": None,
            },
        },
        "--apply",
        "--no-delete",
    )

    assert result.exit_code == 0, result.output
    assert '"failed": 0' in result.output


def test_quiet_clean_apply_remains_successful_and_silent(monkeypatch) -> None:
    result = _invoke_feed_sync(
        monkeypatch,
        {
            "mode": "apply",
            "clean": True,
            "acknowledged": True,
            "diff": {"insert": [], "update": [], "delete": []},
            "result": {
                "inserted": 0,
                "updated": 0,
                "deleted": 0,
                "skipped_deletes": 0,
                "failed": 0,
                "failures": [],
                "reconcile": None,
            },
        },
        "--apply",
        "--no-delete",
        "--quiet-when-clean",
    )

    assert result.exit_code == 0, result.output
    assert result.output == ""


def test_apply_result_exposes_aggregate_effect_acknowledgement(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        feed_sync,
        "compute_diff",
        lambda **_kwargs: {
            "insert": ["mile_failed"],
            "update": [],
            "delete": [],
            "real_delete": [],
        },
    )
    monkeypatch.setattr(
        feed_sync,
        "apply_diff",
        lambda *_args, **_kwargs: {
            "inserted": 0,
            "updated": 0,
            "deleted": 0,
            "skipped_deletes": 0,
            "failed": 1,
            "failures": [{"slug": "mile_failed", "op": "insert"}],
            "reconcile": None,
        },
    )

    result = feed_sync.sync_feed_to_supabase(
        dry_run=False,
        verbose=False,
    )

    assert result["acknowledged"] is False


def test_hourly_wrapper_propagates_the_feed_sync_exit_contract() -> None:
    schedules = json.loads(
        (ROOT / "config" / "runtime_schedules.json").read_text(
            encoding="utf-8"
        )
    )
    feed_job = next(
        item
        for item in schedules["system_crontab"]["items"]
        if item["id"] == "feed_sync"
    )
    wrapper = (ROOT / "scripts" / "cron_feed_sync.sh").read_text(
        encoding="utf-8"
    )

    assert feed_job["exit_semantics"].startswith(
        "0=clean or every attempted projection acknowledged"
    )
    assert 'cron_emit_exit "feed_sync" "$_ec" "$_start"' in wrapper
    assert 'exit "$_ec"' in wrapper
