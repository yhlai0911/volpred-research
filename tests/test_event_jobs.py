from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts import continue_task_dispatch as dispatcher
from volpred.config import schedules as schedule_config
from volpred.ops import event_jobs
from volpred.ops.event_jobs import expand_due_event_jobs, gc_event_ledger, preview_event_jobs
from volpred.ops.local_control_plane import create_task, get_task


@pytest.fixture(autouse=True)
def _clear_schedule_cache():
    schedule_config.load_runtime_schedules.cache_clear()
    yield
    schedule_config.load_runtime_schedules.cache_clear()


def _write_runtime_schedules(
    path: Path,
    *,
    event_items: list[dict],
    timezone_name: str = "Asia/Taipei",
) -> None:
    payload = {
        "metadata": {
            "canonical_path": "config/runtime_schedules.json",
            "timezone": timezone_name,
            "updated_at": "2026-04-17",
        },
        "system_crontab": {"items": []},
        "remote_triggers": {"items": []},
        "session_crons": {"items": []},
        "event_jobs": {"items": event_items},
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_coerce_datetime_warns_when_runtime_timezone_invalid(tmp_path: Path, monkeypatch, capsys):
    config_path = tmp_path / "runtime_schedules.json"
    _write_runtime_schedules(
        config_path,
        event_items=[],
        timezone_name="Invalid/Timezone",
    )
    monkeypatch.setattr(schedule_config, "RUNTIME_SCHEDULES_PATH", config_path)
    schedule_config.load_runtime_schedules.cache_clear()

    parsed = event_jobs._coerce_datetime("2026-04-17T10:00:00")

    captured = capsys.readouterr()
    assert parsed == datetime(2026, 4, 17, 10, 0, tzinfo=timezone.utc)
    assert "[event_jobs] WARN invalid runtime timezone" in captured.out
    assert "Invalid/Timezone" in captured.out


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
    assert first["created"][0]["queue_created"] is True
    assert task["status"] == "pending"
    assert task["task_type"] == "event_article"
    assert task["dispatch_lane"] == "main_thread"
    assert task["deadline"] == (now + timedelta(hours=1)).isoformat()
    queue_path = tmp_path / "storage" / "next_tasks.json"
    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    assert [row["id"] for row in queue] == [task["id"]]

    # The production dispatcher reads this file, not storage/ops/tasks.
    monkeypatch.setattr(dispatcher, "NEXT_TASKS", queue_path)
    pending = dispatcher.load_pending_tasks()
    assert [row["id"] for row in pending] == [task["id"]]
    categorized = dispatcher.categorize(pending)
    assert [row["id"] for row in categorized["main_thread"]] == [task["id"]]
    assert categorized["agentable"] == []

    # New event work has one pending lifecycle.  The ledger is its audit receipt;
    # no second queued local-control-plane TaskRecord is created.
    state = get_task(task["id"], storage_dir=storage_dir)
    assert state is None

    second = expand_due_event_jobs(storage_dir=storage_dir, now=now)
    assert second["created"] == []
    assert any(item["reason"] == "already_materialized" for item in second["skipped"])
    assert len(json.loads(queue_path.read_text(encoding="utf-8"))) == 1

    preview = preview_event_jobs(storage_dir=storage_dir, now=now)
    assert preview["items"][0]["materialized"] is True
    assert preview["items"][0]["task_id"] == task["id"]


def test_existing_ledger_missing_queue_is_recovered(tmp_path: Path, monkeypatch):
    now = datetime(2026, 7, 10, 7, 0, tzinfo=timezone.utc)
    config_path = tmp_path / "runtime_schedules.json"
    item = {
        "id": "tsmc-revenue-2026-07-10-t0",
        "event_key": "TSMC_REVENUE_2026_07_10",
        "trigger_mode": "one_shot",
        "not_before": (now - timedelta(minutes=1)).isoformat(),
        "deadline": (now + timedelta(hours=36)).isoformat(),
        "dedupe_key": "tsmc-revenue-2026-07-10-t0:one_shot",
        "preferred_agent": "claude",
        "public_effect": "published",
        "task_template": {
            "title": "Event article: TSMC_REVENUE 2026-07-10 T+0",
            "description": "write the reaction article",
            "task_family": "content",
            "priority": 15,
            "preferred_agent": "claude",
            "approval_mode": "auto",
            "risk_level": "safe",
            "payload_patch": {
                "event_type": "TSMC_REVENUE",
                "event_date": "2026-07-10",
                "event_series_slot": "T+0",
            },
        },
    }
    _write_runtime_schedules(config_path, event_items=[item])
    monkeypatch.setattr(schedule_config, "RUNTIME_SCHEDULES_PATH", config_path)
    schedule_config.load_runtime_schedules.cache_clear()
    storage_dir = str(tmp_path / "storage")

    first = expand_due_event_jobs(storage_dir=storage_dir, now=now)
    task_id = first["created"][0]["task"]["id"]
    queue_path = tmp_path / "storage" / "next_tasks.json"
    queue_path.write_text("[]\n", encoding="utf-8")

    recovered = expand_due_event_jobs(storage_dir=storage_dir, now=now + timedelta(minutes=5))

    assert len(recovered["created"]) == 1
    assert recovered["created"][0]["reason"] == "recovered_missing_next_task"
    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    assert [row["id"] for row in queue] == [task_id]
    ledger_files = list((tmp_path / "storage" / "ops" / "event_ledger").glob("*.json"))
    assert len(ledger_files) == 1
    ledger = json.loads(ledger_files[0].read_text(encoding="utf-8"))
    assert ledger["next_task_id"] == task_id


def test_queue_written_before_ledger_is_healed_without_duplicate(tmp_path: Path, monkeypatch):
    now = datetime(2026, 7, 10, 7, 0, tzinfo=timezone.utc)
    config_path = tmp_path / "runtime_schedules.json"
    _write_runtime_schedules(
        config_path,
        event_items=[
            {
                "id": "fomc-2026-07-29-t2",
                "event_key": "FOMC_2026_07_29",
                "trigger_mode": "one_shot",
                "not_before": (now - timedelta(minutes=1)).isoformat(),
                "deadline": (now + timedelta(hours=6)).isoformat(),
                "dedupe_key": "fomc-2026-07-29-t2:one_shot",
                "task_template": {
                    "title": "Event article: FOMC T-2",
                    "description": "preview",
                    "task_family": "content",
                    "priority": 20,
                    "preferred_agent": "claude",
                    "approval_mode": "auto",
                    "risk_level": "safe",
                    "payload_patch": {
                        "event_type": "FOMC",
                        "event_date": "2026-07-29",
                        "event_series_slot": "T-2",
                    },
                },
            }
        ],
    )
    monkeypatch.setattr(schedule_config, "RUNTIME_SCHEDULES_PATH", config_path)
    schedule_config.load_runtime_schedules.cache_clear()
    storage_dir = str(tmp_path / "storage")
    first = expand_due_event_jobs(storage_dir=storage_dir, now=now)
    task_id = first["created"][0]["task"]["id"]
    ledger_files = list((tmp_path / "storage" / "ops" / "event_ledger").glob("*.json"))
    assert len(ledger_files) == 1
    ledger_files[0].unlink()

    healed = expand_due_event_jobs(storage_dir=storage_dir, now=now + timedelta(minutes=5))

    assert len(healed["created"]) == 1
    assert healed["created"][0]["queue_created"] is False
    queue = json.loads((tmp_path / "storage" / "next_tasks.json").read_text(encoding="utf-8"))
    assert [row["id"] for row in queue] == [task_id]
    assert len(list((tmp_path / "storage" / "ops" / "event_ledger").glob("*.json"))) == 1


def test_pending_event_auto_expires_but_claimed_event_wins_race(tmp_path: Path, monkeypatch):
    now = datetime(2026, 7, 10, 7, 0, tzinfo=timezone.utc)
    config_path = tmp_path / "runtime_schedules.json"
    item = {
        "id": "cpi-us-2026-07-14-t2",
        "event_key": "CPI_US_2026_07_14",
        "trigger_mode": "one_shot",
        "not_before": (now - timedelta(minutes=1)).isoformat(),
        "deadline": (now + timedelta(hours=1)).isoformat(),
        "dedupe_key": "cpi-us-2026-07-14-t2:one_shot",
        "task_template": {
            "title": "Event article: CPI T-2",
            "description": "preview",
            "task_family": "content",
            "priority": 20,
            "preferred_agent": "claude",
            "approval_mode": "auto",
            "risk_level": "safe",
            "payload_patch": {
                "event_type": "CPI_US",
                "event_date": "2026-07-14",
                "event_series_slot": "T-2",
            },
        },
    }
    _write_runtime_schedules(config_path, event_items=[item])
    monkeypatch.setattr(schedule_config, "RUNTIME_SCHEDULES_PATH", config_path)
    schedule_config.load_runtime_schedules.cache_clear()
    storage_dir = str(tmp_path / "storage")
    expand_due_event_jobs(storage_dir=storage_dir, now=now)
    queue_path = tmp_path / "storage" / "next_tasks.json"

    expired = expand_due_event_jobs(storage_dir=storage_dir, now=now + timedelta(hours=2))
    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    assert queue[0]["status"] == "expired"
    assert expired["expired_tasks"]["next_tasks"] == [queue[0]["id"]]

    # Re-open a fresh fixture and let claim win before the expiry sweep.
    second_storage = str(tmp_path / "claimed-storage")
    expand_due_event_jobs(storage_dir=second_storage, now=now)
    second_queue_path = tmp_path / "claimed-storage" / "next_tasks.json"
    claimed = json.loads(second_queue_path.read_text(encoding="utf-8"))
    claimed[0]["status"] = "claimed"
    claimed[0]["claimed_by"] = "hourly-test"
    second_queue_path.write_text(json.dumps(claimed), encoding="utf-8")

    race = expand_due_event_jobs(storage_dir=second_storage, now=now + timedelta(hours=2))
    claimed_after = json.loads(second_queue_path.read_text(encoding="utf-8"))
    assert claimed_after[0]["status"] == "claimed"
    assert race["expired_tasks"]["next_tasks"] == []


def test_legacy_unclaimed_event_receipt_auto_fails_after_deadline(tmp_path: Path, monkeypatch):
    now = datetime(2026, 7, 12, 12, 0, tzinfo=timezone.utc)
    config_path = tmp_path / "runtime_schedules.json"
    _write_runtime_schedules(config_path, event_items=[])
    monkeypatch.setattr(schedule_config, "RUNTIME_SCHEDULES_PATH", config_path)
    schedule_config.load_runtime_schedules.cache_clear()
    storage_dir = str(tmp_path / "storage")
    receipt = create_task(
        title="Event article: legacy queued receipt",
        description="pre-cutover receipt",
        source="schedule",
        task_family="content",
        payload={"event_key": "LEGACY_EVENT", "event_job_id": "legacy-event-t0"},
        created_by="event_expander",
        storage_dir=storage_dir,
    )
    ledger_root = tmp_path / "storage" / "ops" / "event_ledger"
    ledger_root.mkdir(parents=True, exist_ok=True)
    (ledger_root / "legacy.json").write_text(
        json.dumps(
            {
                "task_id": receipt["id"],
                "event_key": "LEGACY_EVENT",
                "deadline": (now - timedelta(minutes=1)).isoformat(),
                "gc_after": (now + timedelta(days=7)).isoformat(),
            }
        ),
        encoding="utf-8",
    )

    result = expand_due_event_jobs(storage_dir=storage_dir, now=now)

    state = get_task(receipt["id"], storage_dir=storage_dir)
    assert state is not None
    assert state["status"] == "failed"
    assert state["last_error"] == "deadline_expired_never_dispatched"
    assert state["claimed_by"] is None
    assert len(state["executions"]) == 1
    assert result["expired_tasks"]["legacy_receipts"] == [receipt["id"]]


def test_same_day_t0_becomes_visible_at_not_before_without_daily_scan(tmp_path: Path, monkeypatch):
    opens = datetime(2026, 7, 10, 7, 0, tzinfo=timezone.utc)  # 15:00 Asia/Taipei
    config_path = tmp_path / "runtime_schedules.json"
    _write_runtime_schedules(
        config_path,
        event_items=[
            {
                "id": "tsmc-revenue-2026-07-10-t0",
                "event_key": "TSMC_REVENUE_2026_07_10",
                "trigger_mode": "one_shot",
                "not_before": opens.isoformat(),
                "deadline": (opens + timedelta(hours=36)).isoformat(),
                "dedupe_key": "tsmc-revenue-2026-07-10-t0:one_shot",
                "task_template": {
                    "title": "Event article: TSMC_REVENUE T+0",
                    "description": "reaction",
                    "task_family": "content",
                    "priority": 15,
                    "preferred_agent": "claude",
                    "approval_mode": "auto",
                    "risk_level": "safe",
                    "payload_patch": {
                        "event_type": "TSMC_REVENUE",
                        "event_date": "2026-07-10",
                        "event_series_slot": "T+0",
                    },
                },
            }
        ],
    )
    monkeypatch.setattr(schedule_config, "RUNTIME_SCHEDULES_PATH", config_path)
    schedule_config.load_runtime_schedules.cache_clear()
    storage_dir = str(tmp_path / "storage")

    before = expand_due_event_jobs(storage_dir=storage_dir, now=opens - timedelta(seconds=1))
    assert before["created"] == []
    assert not (tmp_path / "storage" / "next_tasks.json").exists()

    at_open = expand_due_event_jobs(storage_dir=storage_dir, now=opens)
    assert len(at_open["created"]) == 1
    queue = json.loads((tmp_path / "storage" / "next_tasks.json").read_text(encoding="utf-8"))
    assert queue[0]["ref_event_job_id"] == "tsmc-revenue-2026-07-10-t0"
    assert queue[0]["status"] == "pending"


def test_reaction_coverage_is_preserved_in_single_owner(tmp_path: Path, monkeypatch):
    now = datetime(2026, 7, 3, 0, 0, tzinfo=timezone.utc)
    config_path = tmp_path / "runtime_schedules.json"
    _write_runtime_schedules(
        config_path,
        event_items=[
            {
                "id": "nfp-2026-07-03-t0",
                "event_key": "NFP_US_2026_07_03",
                "trigger_mode": "one_shot",
                "not_before": (now - timedelta(minutes=1)).isoformat(),
                "deadline": (now + timedelta(hours=36)).isoformat(),
                "dedupe_key": "nfp-2026-07-03-t0:one_shot",
                "task_template": {
                    "title": "Event article: NFP_US 2026-07-03 T+0",
                    "description": "reaction",
                    "task_family": "content",
                    "priority": 15,
                    "preferred_agent": "claude",
                    "approval_mode": "auto",
                    "risk_level": "safe",
                    "payload_patch": {
                        "event_type": "NFP_US",
                        "event_date": "2026-07-03",
                        "event_series_slot": "T+0",
                    },
                },
            }
        ],
    )
    monkeypatch.setattr(schedule_config, "RUNTIME_SCHEDULES_PATH", config_path)
    schedule_config.load_runtime_schedules.cache_clear()
    feed_path = tmp_path / "storage" / "reports" / "feed.json"
    feed_path.parent.mkdir(parents=True, exist_ok=True)
    feed_path.write_text(
        json.dumps(
            [
                {
                    "id": "mile_35eef830",
                    "status": "published",
                    "title": "6 月非農爆冷 5.7 萬，SPY 卻只動 0.13%",
                    "tags": ["NFP", "非農就業"],
                    "published_at": "2026-07-01T17:24:08+00:00",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = expand_due_event_jobs(storage_dir=str(tmp_path / "storage"), now=now)

    assert result["created"] == []
    covered = [row for row in result["skipped"] if row["reason"] == "reaction_already_covered"]
    assert covered[0]["covered_by"]["id"] == "mile_35eef830"
    assert not (tmp_path / "storage" / "next_tasks.json").exists()
    ledger_files = list((tmp_path / "storage" / "ops" / "event_ledger").glob("*.json"))
    assert len(ledger_files) == 1
    ledger = json.loads(ledger_files[0].read_text(encoding="utf-8"))
    assert ledger["disposition"] == "reaction_already_covered"
    audit = (tmp_path / "storage" / "logs" / "dedup_decisions.jsonl").read_text(
        encoding="utf-8"
    )
    assert "event_reaction_coverage" in audit


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


def test_gc_event_ledger_preserves_unexpired(tmp_path: Path):
    """GC must NOT touch ledger entries whose gc_after is still in the future."""
    now = datetime(2026, 4, 17, 2, 0, tzinfo=timezone.utc)
    storage_dir = str(tmp_path / "storage")
    ledger_root = tmp_path / "storage" / "ops" / "event_ledger"
    ledger_root.mkdir(parents=True, exist_ok=True)

    fresh = ledger_root / "fresh.json"
    fresh.write_text(
        json.dumps(
            {
                "dedupe_key": "future:event",
                "gc_after": (now + timedelta(days=3)).isoformat(),
            }
        ),
        encoding="utf-8",
    )
    stale = ledger_root / "stale.json"
    stale.write_text(
        json.dumps(
            {
                "dedupe_key": "past:event",
                "gc_after": (now - timedelta(hours=1)).isoformat(),
            }
        ),
        encoding="utf-8",
    )

    removed = gc_event_ledger(storage_dir=storage_dir, now=now)
    assert "stale.json" in removed
    assert "fresh.json" not in removed
    assert fresh.exists()
    assert not stale.exists()


def test_expand_due_event_jobs_skips_past_deadline(tmp_path: Path, monkeypatch):
    """Events whose deadline has fully passed must not be materialized."""
    now = datetime(2026, 4, 17, 2, 0, tzinfo=timezone.utc)
    config_path = tmp_path / "runtime_schedules.json"
    _write_runtime_schedules(
        config_path,
        event_items=[
            {
                "id": "expired_event",
                "event_key": "old_event",
                "trigger_mode": "one_shot",
                "not_before": (now - timedelta(days=2)).isoformat(),
                "deadline": (now - timedelta(hours=1)).isoformat(),
                "dedupe_key": "old_event:content",
                "preferred_agent": "claude",
                "public_effect": "published",
                "task_template": {
                    "title": "Late article",
                    "description": "should not run",
                    "task_family": "content",
                    "priority": 30,
                    "preferred_agent": "claude",
                    "approval_mode": "auto",
                    "risk_level": "safe",
                    "payload_patch": {},
                    "brief_template": "content.yaml",
                    "preconditions": [],
                },
            }
        ],
    )
    monkeypatch.setattr(schedule_config, "RUNTIME_SCHEDULES_PATH", config_path)
    schedule_config.load_runtime_schedules.cache_clear()

    result = expand_due_event_jobs(storage_dir=str(tmp_path / "storage"), now=now)
    assert result["created"] == []
    skip_reasons = [item.get("reason") for item in result["skipped"]]
    assert any("deadline" in str(r) or "expired" in str(r) for r in skip_reasons)


def test_expand_due_event_jobs_payload_patch_overlay(tmp_path: Path, monkeypatch):
    """payload_patch keys must overlay base task fields verbatim."""
    now = datetime(2026, 4, 17, 2, 0, tzinfo=timezone.utc)
    config_path = tmp_path / "runtime_schedules.json"
    _write_runtime_schedules(
        config_path,
        event_items=[
            {
                "id": "patched_event",
                "event_key": "fomc_patched",
                "trigger_mode": "one_shot",
                "not_before": (now - timedelta(minutes=10)).isoformat(),
                "deadline": (now + timedelta(hours=2)).isoformat(),
                "dedupe_key": "fomc_patched:content",
                "preferred_agent": "claude",
                "public_effect": "published",
                "task_template": {
                    "title": "FOMC patched",
                    "description": "patched body",
                    "task_family": "content",
                    "priority": 5,
                    "preferred_agent": "claude",
                    "approval_mode": "auto",
                    "risk_level": "safe",
                    "payload_patch": {
                        "experiment_id": "k_event_42",
                        "event_series_slot": "T-2",
                        "extra_meta": {"source": "macro_calendar"},
                    },
                    "brief_template": "content.yaml",
                    "preconditions": ["storage/macro/fomc.json"],
                },
            }
        ],
    )
    monkeypatch.setattr(schedule_config, "RUNTIME_SCHEDULES_PATH", config_path)
    schedule_config.load_runtime_schedules.cache_clear()

    result = expand_due_event_jobs(storage_dir=str(tmp_path / "storage"), now=now)
    assert len(result["created"]) == 1
    task = result["created"][0]["task"]
    state = get_task(task["id"], storage_dir=str(tmp_path / "storage"))
    assert state is None
    assert task["payload"]["experiment_id"] == "k_event_42"
    assert task["payload"]["event_series_slot"] == "T-2"
    assert task["payload"]["extra_meta"] == {"source": "macro_calendar"}
    assert task["payload"]["preconditions"] == ["storage/macro/fomc.json"]
