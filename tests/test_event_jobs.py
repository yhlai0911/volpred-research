from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from volpred.config import schedules as schedule_config
from volpred.ops.event_jobs import expand_due_event_jobs, gc_event_ledger, preview_event_jobs
from volpred.ops.local_control_plane import get_task


@pytest.fixture(autouse=True)
def _clear_schedule_cache():
    schedule_config.load_runtime_schedules.cache_clear()
    yield
    schedule_config.load_runtime_schedules.cache_clear()


def _write_runtime_schedules(path: Path, *, event_items: list[dict]) -> None:
    payload = {
        "metadata": {
            "canonical_path": "config/runtime_schedules.json",
            "timezone": "Asia/Taipei",
            "updated_at": "2026-04-17",
        },
        "system_crontab": {"items": []},
        "remote_triggers": {"items": []},
        "session_crons": {"items": []},
        "event_jobs": {"items": event_items},
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_expand_due_event_jobs_materializes_once(tmp_path: Path, monkeypatch):
    now = datetime(2026, 4, 17, 2, 0, tzinfo=timezone.utc)
    config_path = tmp_path / "runtime_schedules.json"
    _write_runtime_schedules(
        config_path,
        event_items=[
            {
                "id": "cpi_article",
                "event_key": "us_cpi_20260513",
                "trigger_mode": "one_shot",
                "not_before": (now - timedelta(minutes=5)).isoformat(),
                "deadline": (now + timedelta(hours=1)).isoformat(),
                "dedupe_key": "us_cpi_20260513:content",
                "preferred_agent": "claude",
                "public_effect": "published",
                "task_template": {
                    "title": "CPI article",
                    "description": "write cpi article",
                    "task_family": "content",
                    "priority": 10,
                    "preferred_agent": "claude",
                    "approval_mode": "auto",
                    "risk_level": "safe",
                    "payload_patch": {"experiment_id": "k123"},
                    "brief_template": "content.yaml",
                    "preconditions": ["storage/macro/cpi.json"],
                },
            }
        ],
    )
    monkeypatch.setattr(schedule_config, "RUNTIME_SCHEDULES_PATH", config_path)
    schedule_config.load_runtime_schedules.cache_clear()

    storage_dir = str(tmp_path / "storage")
    first = expand_due_event_jobs(storage_dir=storage_dir, now=now)
    assert len(first["created"]) == 1
    task = first["created"][0]["task"]
    state = get_task(task["id"], storage_dir=storage_dir)
    assert state is not None
    assert state["payload"]["event_key"] == "us_cpi_20260513"
    assert state["payload"]["experiment_id"] == "k123"
    assert state["payload"]["preconditions"] == ["storage/macro/cpi.json"]

    second = expand_due_event_jobs(storage_dir=storage_dir, now=now)
    assert second["created"] == []
    assert any(item["reason"] == "already_materialized" for item in second["skipped"])

    preview = preview_event_jobs(storage_dir=storage_dir, now=now)
    assert preview["items"][0]["materialized"] is True
    assert preview["items"][0]["task_id"] == task["id"]


def test_preview_event_jobs_status_and_gc(tmp_path: Path, monkeypatch):
    now = datetime(2026, 4, 17, 2, 0, tzinfo=timezone.utc)
    config_path = tmp_path / "runtime_schedules.json"
    _write_runtime_schedules(
        config_path,
        event_items=[
            {
                "id": "future_event",
                "event_key": "fomc_20260618",
                "trigger_mode": "relative_to_event",
                "not_before": (now + timedelta(hours=2)).isoformat(),
                "deadline": (now + timedelta(hours=3)).isoformat(),
                "dedupe_key": "fomc_20260618:research",
                "preferred_agent": "claude",
                "public_effect": "none",
                "task_template": {
                    "title": "FOMC prep",
                    "description": "prepare note",
                    "task_family": "research",
                    "priority": 20,
                    "preferred_agent": "claude",
                    "approval_mode": "auto",
                    "risk_level": "safe",
                    "payload_patch": {},
                    "brief_template": "research.yaml",
                    "preconditions": [],
                },
            }
        ],
    )
    monkeypatch.setattr(schedule_config, "RUNTIME_SCHEDULES_PATH", config_path)
    schedule_config.load_runtime_schedules.cache_clear()

    storage_dir = str(tmp_path / "storage")
    preview = preview_event_jobs(storage_dir=storage_dir, now=now)
    assert preview["items"][0]["status"] == "pending"

    ledger_root = tmp_path / "storage" / "ops" / "event_ledger"
    ledger_root.mkdir(parents=True, exist_ok=True)
    stale_ledger = ledger_root / "stale.json"
    stale_ledger.write_text(
        json.dumps(
            {
                "dedupe_key": "old:event",
                "gc_after": (now - timedelta(days=1)).isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    removed = gc_event_ledger(storage_dir=storage_dir, now=now)
    assert removed == ["stale.json"]
    assert not stale_ledger.exists()
