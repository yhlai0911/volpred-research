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


def _event_item(
    event_id: str,
    *,
    event_type: str,
    event_date: str,
    slot: str,
    not_before: str,
    deadline: str,
) -> dict:
    return {
        "id": event_id,
        "event_key": f"{event_type}_{event_date.replace('-', '_')}",
        "trigger_mode": "one_shot",
        "not_before": not_before,
        "deadline": deadline,
        "dedupe_key": f"{event_id}:one_shot",
        "preferred_agent": "claude",
        "public_effect": "published",
        "task_template": {
            "title": f"Event article: {event_type} {slot}",
            "description": "reader-facing event article",
            "task_family": "content",
            "priority": 15,
            "preferred_agent": "claude",
            "approval_mode": "auto",
            "risk_level": "safe",
            "payload_patch": {
                "event_type": event_type,
                "event_date": event_date,
                "event_series_slot": slot,
            },
        },
    }


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
    assert task["dispatch_lane"] == "agent"
    assert task["topology"] == "inline"
    assert "claude-worker-only" in task["tags"]
    assert "main-thread-only" not in task["tags"]
    assert task["deadline"] == (now + timedelta(hours=1)).isoformat()
    queue_path = tmp_path / "storage" / "next_tasks.json"
    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    assert [row["id"] for row in queue] == [task["id"]]

    # The production dispatcher reads this file, not storage/ops/tasks.
    monkeypatch.setattr(dispatcher, "NEXT_TASKS", queue_path)
    pending = dispatcher.load_pending_tasks()
    assert [row["id"] for row in pending] == [task["id"]]
    categorized = dispatcher.categorize(pending)
    assert categorized["main_thread"] == []
    assert [row["id"] for row in categorized["agentable"]] == [task["id"]]

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


def test_pending_generator_row_is_migrated_from_main_thread_to_claude_worker(
    tmp_path: Path, monkeypatch
) -> None:
    now = datetime(2026, 7, 30, 4, 35, tzinfo=timezone.utc)
    config_path = tmp_path / "runtime_schedules.json"
    item = _event_item(
        "fomc-2026-07-29-t0",
        event_type="FOMC",
        event_date="2026-07-29",
        slot="T+0",
        not_before=(now - timedelta(minutes=1)).isoformat(),
        deadline=(now + timedelta(hours=24)).isoformat(),
    )
    _write_runtime_schedules(config_path, event_items=[item])
    monkeypatch.setattr(schedule_config, "RUNTIME_SCHEDULES_PATH", config_path)
    schedule_config.load_runtime_schedules.cache_clear()
    storage_dir = str(tmp_path / "storage")

    first = expand_due_event_jobs(storage_dir=storage_dir, now=now)
    queue_path = tmp_path / "storage" / "next_tasks.json"
    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    queue[0]["dispatch_lane"] = "main_thread"
    queue[0].pop("topology", None)
    queue[0]["tags"] = [
        tag for tag in queue[0]["tags"] if tag != "claude-worker-only"
    ] + ["main-thread-only"]
    queue_path.write_text(json.dumps(queue), encoding="utf-8")

    second = expand_due_event_jobs(
        storage_dir=storage_dir,
        now=now + timedelta(minutes=5),
    )

    assert first["created"][0]["task"]["id"] == (
        "event_article_fomc_2026-07-29_tplus0"
    )
    assert second["created"] == []
    assert second["skipped"][0]["queue_updated"] is True
    migrated = json.loads(queue_path.read_text(encoding="utf-8"))[0]
    assert migrated["dispatch_lane"] == "agent"
    assert migrated["preferred_agent"] == "claude"
    assert migrated["topology"] == "inline"
    assert "claude-worker-only" in migrated["tags"]
    assert "main-thread-only" not in migrated["tags"]


def test_legacy_receipt_is_cancelled_before_canonical_row_becomes_pending(
    tmp_path: Path, monkeypatch
):
    now = datetime(2026, 7, 10, 7, 0, tzinfo=timezone.utc)
    item = _event_item(
        "tsmc-revenue-2026-07-10-t0",
        event_type="TSMC_REVENUE",
        event_date="2026-07-10",
        slot="T+0",
        not_before=(now - timedelta(minutes=1)).isoformat(),
        deadline=(now + timedelta(hours=36)).isoformat(),
    )
    config_path = tmp_path / "runtime_schedules.json"
    _write_runtime_schedules(config_path, event_items=[item])
    monkeypatch.setattr(schedule_config, "RUNTIME_SCHEDULES_PATH", config_path)
    schedule_config.load_runtime_schedules.cache_clear()
    storage_dir = str(tmp_path / "storage")
    legacy = create_task(
        title="Event article: legacy TSMC receipt",
        description="pre-cutover event receipt",
        source="schedule",
        task_family="content",
        payload={"event_job_id": item["id"], "event_key": item["event_key"]},
        created_by="event_expander",
        storage_dir=storage_dir,
    )
    ledger_root = tmp_path / "storage" / "ops" / "event_ledger"
    ledger_root.mkdir(parents=True, exist_ok=True)
    ledger_path = event_jobs._ledger_path(item["dedupe_key"], storage_dir=storage_dir)
    ledger_path.write_text(
        json.dumps(
            {
                "task_id": legacy["id"],
                "dedupe_key": item["dedupe_key"],
                "event_key": item["event_key"],
                "deadline": item["deadline"],
                "gc_after": (now + timedelta(days=8)).isoformat(),
            }
        ),
        encoding="utf-8",
    )

    result = expand_due_event_jobs(storage_dir=storage_dir, now=now)

    assert len(result["created"]) == 1
    canonical_id = result["created"][0]["task"]["id"]
    legacy_state = get_task(legacy["id"], storage_dir=storage_dir)
    assert legacy_state is not None
    assert legacy_state["status"] == "cancelled"
    assert legacy_state["migration_candidate_id"] == canonical_id
    assert legacy_state["claimed_by"] is None
    assert legacy_state["executions"][0]["result_status"] == "cancelled"
    assert legacy_state["executions"][0]["signal_payload"]["reason"] == (
        "canonical_event_migration_prepared"
    )
    queue = json.loads((tmp_path / "storage" / "next_tasks.json").read_text(encoding="utf-8"))
    assert [(row["id"], row["status"]) for row in queue] == [(canonical_id, "pending")]
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert ledger["receipt_task_id"] == legacy["id"]
    assert ledger["next_task_id"] == canonical_id
    assert ledger["legacy_receipt_disposition"] == "canonical_event_migration_prepared"


def test_cutover_discovers_all_duplicate_legacy_receipts(tmp_path: Path):
    now = datetime(2026, 7, 10, 7, 0, tzinfo=timezone.utc)
    item = _event_item(
        "tsmc-revenue-2026-07-10-t0",
        event_type="TSMC_REVENUE",
        event_date="2026-07-10",
        slot="T+0",
        not_before=(now - timedelta(minutes=1)).isoformat(),
        deadline=(now + timedelta(hours=12)).isoformat(),
    )
    storage_dir = str(tmp_path / "storage")
    receipts = [
        create_task(
            title=f"Event article: duplicate legacy {index}",
            description="pre-cutover duplicate",
            source="schedule",
            task_family="content",
            payload={"event_job_id": item["id"], "event_key": item["event_key"]},
            created_by="event_expander",
            storage_dir=storage_dir,
        )
        for index in range(2)
    ]
    active_path = (
        tmp_path / "storage" / "ops" / "tasks" / f"{receipts[1]['id']}.json"
    )
    active = json.loads(active_path.read_text(encoding="utf-8"))
    active["status"] = "claimed"
    active["claimed_by"] = "legacy-worker"
    active["claimed_at"] = now.isoformat()
    active_path.write_text(json.dumps(active), encoding="utf-8")
    ledger = {"task_id": receipts[0]["id"]}

    result = event_jobs._prepare_legacy_receipt_cutover(
        item,
        ledger,
        storage_dir=storage_dir,
        now=now,
    )

    assert result["proceed"] is False
    assert result["reason"] == "legacy_receipt_conflict:claimed"
    assert set(ledger["receipt_task_ids"]) == {row["id"] for row in receipts}
    states = {row["id"]: get_task(row["id"], storage_dir=storage_dir) for row in receipts}
    assert states[receipts[0]["id"]]["status"] == "cancelled"
    assert states[receipts[1]["id"]]["status"] == "claimed"


def test_claimed_legacy_receipt_suppresses_existing_canonical_lifecycle(
    tmp_path: Path, monkeypatch
):
    now = datetime(2026, 7, 10, 7, 0, tzinfo=timezone.utc)
    item = _event_item(
        "fomc-2026-07-11-t0",
        event_type="FOMC",
        event_date="2026-07-11",
        slot="T+0",
        not_before=(now - timedelta(minutes=1)).isoformat(),
        deadline=(now + timedelta(hours=12)).isoformat(),
    )
    config_path = tmp_path / "runtime_schedules.json"
    _write_runtime_schedules(config_path, event_items=[item])
    monkeypatch.setattr(schedule_config, "RUNTIME_SCHEDULES_PATH", config_path)
    schedule_config.load_runtime_schedules.cache_clear()
    storage_dir = str(tmp_path / "storage")
    legacy_event_job_id = "fomc-2026-07-10-t0"
    legacy = create_task(
        title="Event article: claimed legacy FOMC",
        description="pre-cutover event receipt",
        source="schedule",
        task_family="content",
        payload={"event_job_id": legacy_event_job_id, "event_key": item["event_key"]},
        created_by="event_expander",
        storage_dir=storage_dir,
    )
    legacy_path = tmp_path / "storage" / "ops" / "tasks" / f"{legacy['id']}.json"
    claimed = json.loads(legacy_path.read_text(encoding="utf-8"))
    claimed["status"] = "claimed"
    claimed["claimed_by"] = "legacy-worker"
    claimed["claimed_at"] = now.isoformat()
    legacy_path.write_text(json.dumps(claimed), encoding="utf-8")
    ledger_path = event_jobs._ledger_path(item["dedupe_key"], storage_dir=storage_dir)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(
        json.dumps(
            {
                "task_id": legacy["id"],
                "deadline": item["deadline"],
                "gc_after": (now + timedelta(days=8)).isoformat(),
            }
        ),
        encoding="utf-8",
    )
    queue_path = tmp_path / "storage" / "next_tasks.json"
    old_canonical = event_jobs.build_pending_event_task(
        item,
        now=now,
        storage_dir=storage_dir,
    )
    old_canonical["id"] = "event_article_fomc_2026-07-10_tplus0"
    old_canonical["ref_event_job_id"] = legacy_event_job_id
    queue_path.write_text(
        json.dumps([old_canonical]), encoding="utf-8"
    )

    result = expand_due_event_jobs(storage_dir=storage_dir, now=now)

    assert result["created"] == []
    assert any(
        row["reason"] == "legacy_receipt_conflict:claimed" for row in result["skipped"]
    )
    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    assert queue[0]["status"] == "superseded"
    assert queue[0]["superseded_by"] == legacy["id"]
    assert queue[0]["result"] == "legacy_event_receipt_already_active"
    legacy_state = get_task(legacy["id"], storage_dir=storage_dir)
    assert legacy_state is not None
    assert legacy_state["status"] == "claimed"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert ledger["canonical_conflict_disposition"] == (
        "canonical_suppressed_for_active_legacy"
    )


def test_dual_active_event_lifecycle_is_reported_without_killing_either(tmp_path: Path):
    now = datetime(2026, 7, 10, 7, 0, tzinfo=timezone.utc)
    item = _event_item(
        "fomc-2026-07-10-t0",
        event_type="FOMC",
        event_date="2026-07-10",
        slot="T+0",
        not_before=(now - timedelta(minutes=1)).isoformat(),
        deadline=(now + timedelta(hours=12)).isoformat(),
    )
    storage_dir = str(tmp_path / "storage")
    queue_path = tmp_path / "storage" / "next_tasks.json"
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    canonical = event_jobs.build_pending_event_task(
        item,
        now=now,
        storage_dir=storage_dir,
    )
    canonical["status"] = "in_progress"
    canonical["claimed_by"] = "canonical-worker"
    queue_path.write_text(json.dumps([canonical]), encoding="utf-8")

    result = event_jobs._suppress_canonical_for_legacy_conflict(
        item,
        legacy_receipt_id="task_legacy_active",
        storage_dir=storage_dir,
        now=now,
    )

    assert result["changed"] is False
    assert result["reason"] == "dual_active_lifecycle_conflict:in_progress"
    saved = json.loads(queue_path.read_text(encoding="utf-8"))[0]
    assert saved["status"] == "in_progress"
    assert saved["claimed_by"] == "canonical-worker"


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
    queue_path = tmp_path / "storage" / "next_tasks.json"
    queued = json.loads(queue_path.read_text(encoding="utf-8"))
    queued[0]["description"] = "obsolete generic 3-layer dedup brief"
    queue_path.write_text(json.dumps(queued), encoding="utf-8")
    ledger_files = list((tmp_path / "storage" / "ops" / "event_ledger").glob("*.json"))
    assert len(ledger_files) == 1
    ledger_files[0].unlink()

    healed = expand_due_event_jobs(storage_dir=storage_dir, now=now + timedelta(minutes=5))

    assert len(healed["created"]) == 1
    assert healed["created"][0]["queue_created"] is False
    queue = json.loads((tmp_path / "storage" / "next_tasks.json").read_text(encoding="utf-8"))
    assert [row["id"] for row in queue] == [task_id]
    assert "--event-key FOMC_2026_07_29 --event-series-slot T-2" in queue[0]["description"]
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


def test_legacy_expiry_discovers_unlinked_duplicate_receipts(tmp_path: Path, monkeypatch):
    now = datetime(2026, 7, 12, 12, 0, tzinfo=timezone.utc)
    config_path = tmp_path / "runtime_schedules.json"
    _write_runtime_schedules(config_path, event_items=[])
    monkeypatch.setattr(schedule_config, "RUNTIME_SCHEDULES_PATH", config_path)
    schedule_config.load_runtime_schedules.cache_clear()
    storage_dir = str(tmp_path / "storage")
    event_job_id = "legacy-nfp-duplicate-t0"
    receipts = [
        create_task(
            title=f"Event article: duplicate legacy NFP {index}",
            description="pre-cutover duplicate",
            source="schedule",
            task_family="content",
            payload={"event_job_id": event_job_id, "event_key": "NFP_DUPLICATE"},
            created_by="event_expander",
            storage_dir=storage_dir,
        )
        for index in range(3)
    ]
    claimed_path = (
        tmp_path / "storage" / "ops" / "tasks" / f"{receipts[2]['id']}.json"
    )
    claimed = json.loads(claimed_path.read_text(encoding="utf-8"))
    claimed["status"] = "claimed"
    claimed["claimed_by"] = "legacy-worker"
    claimed["claimed_at"] = (now - timedelta(minutes=5)).isoformat()
    claimed_path.write_text(json.dumps(claimed), encoding="utf-8")
    ledger_root = tmp_path / "storage" / "ops" / "event_ledger"
    ledger_root.mkdir(parents=True, exist_ok=True)
    (ledger_root / "legacy-duplicates.json").write_text(
        json.dumps(
            {
                # Pre-cutover shape: only one of the duplicate receipts was linked.
                "task_id": receipts[0]["id"],
                "event_key": "NFP_DUPLICATE",
                "deadline": (now - timedelta(minutes=1)).isoformat(),
                "gc_after": (now + timedelta(days=7)).isoformat(),
            }
        ),
        encoding="utf-8",
    )

    result = expand_due_event_jobs(storage_dir=storage_dir, now=now)

    states = [get_task(row["id"], storage_dir=storage_dir) for row in receipts]
    assert [state["status"] for state in states] == ["failed", "failed", "claimed"]
    assert set(result["expired_tasks"]["legacy_receipts"]) == {
        receipts[0]["id"],
        receipts[1]["id"],
    }


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
                    "published_at": "2026-07-03T00:00:00+00:00",
                    "event_key": "NFP_US_2026_07_03",
                    "event_type": "NFP_US",
                    "event_date": "2026-07-03",
                    "event_series_slot": "T+0",
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
    queue = json.loads((tmp_path / "storage" / "next_tasks.json").read_text(encoding="utf-8"))
    assert queue == []
    ledger_files = list((tmp_path / "storage" / "ops" / "event_ledger").glob("*.json"))
    assert len(ledger_files) == 1
    ledger = json.loads(ledger_files[0].read_text(encoding="utf-8"))
    assert ledger["disposition"] == "reaction_already_covered"
    audit = (tmp_path / "storage" / "logs" / "dedup_decisions.jsonl").read_text(
        encoding="utf-8"
    )
    assert "event_reaction_coverage" in audit


def test_fomc_pre_event_article_cannot_cover_tplus0_reaction(
    tmp_path: Path,
    monkeypatch,
):
    """2026-07-29 live regression: future-tense preview suppressed the decision."""

    release_at = datetime(
        2026,
        7,
        29,
        18,
        0,
        tzinfo=timezone.utc,
    )
    item = _event_item(
        "fomc-2026-07-29-t0",
        event_type="FOMC",
        event_date="2026-07-29",
        slot="T+0",
        not_before=release_at.isoformat(),
        deadline=(release_at + timedelta(hours=36)).isoformat(),
    )
    config_path = tmp_path / "runtime_schedules.json"
    _write_runtime_schedules(config_path, event_items=[item])
    monkeypatch.setattr(
        schedule_config,
        "RUNTIME_SCHEDULES_PATH",
        config_path,
    )
    schedule_config.load_runtime_schedules.cache_clear()
    storage_dir = tmp_path / "storage"
    feed_path = storage_dir / "reports" / "feed.json"
    feed_path.parent.mkdir(parents=True, exist_ok=True)
    feed_path.write_text(
        json.dumps(
            [
                {
                    "id": "mile_bbd72c0b",
                    "status": "published",
                    "title": (
                        "Fed 拍板加四大雲端交卷的這一週，"
                        "幣圈那盞燈到底能不能看"
                    ),
                    "description": "聯準會今晚就要拍板利率，市場等消息。",
                    "tags": ["Fed", "事件週"],
                    "published_at": "2026-07-29T02:01:34+00:00",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = expand_due_event_jobs(
        storage_dir=str(storage_dir),
        now=release_at,
    )

    assert len(result["created"]) == 1
    assert result["created"][0]["task"]["id"] == (
        "event_article_fomc_2026-07-29_tplus0"
    )
    assert not any(
        row["reason"] == "reaction_already_covered"
        for row in result["skipped"]
    )


def test_unrelated_article_tag_cannot_cover_cpi_reaction(tmp_path: Path, monkeypatch):
    """Regression: generic `通膨` tag on oil/gold must not suppress CPI T+0."""
    now = datetime(2026, 7, 14, 14, 0, tzinfo=timezone.utc)
    item = _event_item(
        "cpi-us-2026-07-14-t0",
        event_type="CPI_US",
        event_date="2026-07-14",
        slot="T+0",
        not_before=(now - timedelta(minutes=1)).isoformat(),
        deadline=(now + timedelta(hours=36)).isoformat(),
    )
    config_path = tmp_path / "runtime_schedules.json"
    _write_runtime_schedules(config_path, event_items=[item])
    monkeypatch.setattr(schedule_config, "RUNTIME_SCHEDULES_PATH", config_path)
    schedule_config.load_runtime_schedules.cache_clear()
    storage_dir = tmp_path / "storage"
    feed_path = storage_dir / "reports" / "feed.json"
    feed_path.parent.mkdir(parents=True, exist_ok=True)
    feed_path.write_text(
        json.dumps(
            [
                {
                    "id": "mile_5dd7c135",
                    "status": "published",
                    "title": "油價跳漲，金價卻連摔兩天：避風港有沒有上班",
                    "tags": ["黃金", "避險", "通膨", "風險管理"],
                    "published_at": "2026-07-14T03:24:06+00:00",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = expand_due_event_jobs(storage_dir=str(storage_dir), now=now)

    assert len(result["created"]) == 1
    assert result["created"][0]["task"]["id"] == "event_article_cpi_us_2026-07-14_tplus0"
    queue = json.loads((storage_dir / "next_tasks.json").read_text(encoding="utf-8"))
    assert [row["id"] for row in queue] == ["event_article_cpi_us_2026-07-14_tplus0"]


def test_explicit_cpi_title_keyword_still_covers_legacy_reaction():
    feed = [
        {
            "id": "mile_cpi_reaction",
            "status": "published",
            "title": "美國 CPI 低於預期，公債殖利率回落",
            "tags": [],
            "published_at": "2026-07-14T14:30:00+00:00",
        }
    ]

    hit = event_jobs.reaction_already_covered(
        "CPI_US",
        datetime(2026, 7, 14, 12, 30, tzinfo=timezone.utc),
        feed,
        event_key="CPI_US_2026_07_14",
        requested_slot="T+0",
        release_at=datetime(2026, 7, 14, 12, 30, tzinfo=timezone.utc),
    )

    assert hit == {"id": "mile_cpi_reaction", "match": "title_keyword"}


def test_legacy_title_candidate_is_advisory_and_does_not_retire_event_task(
    tmp_path: Path,
    monkeypatch,
):
    now = datetime(2026, 7, 14, 14, 0, tzinfo=timezone.utc)
    item = _event_item(
        "cpi-us-2026-07-14-t0",
        event_type="CPI_US",
        event_date="2026-07-14",
        slot="T+0",
        not_before=(now - timedelta(minutes=1)).isoformat(),
        deadline=(now + timedelta(hours=36)).isoformat(),
    )
    config_path = tmp_path / "runtime_schedules.json"
    _write_runtime_schedules(config_path, event_items=[item])
    monkeypatch.setattr(schedule_config, "RUNTIME_SCHEDULES_PATH", config_path)
    schedule_config.load_runtime_schedules.cache_clear()
    storage_dir = tmp_path / "storage"
    feed_path = storage_dir / "reports" / "feed.json"
    feed_path.parent.mkdir(parents=True, exist_ok=True)
    feed_path.write_text(
        json.dumps(
            [
                {
                    "id": "mile_legacy_cpi_reaction",
                    "status": "published",
                    "title": "美國 CPI 低於預期，殖利率回落",
                    "published_at": now.isoformat(),
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = expand_due_event_jobs(storage_dir=str(storage_dir), now=now)

    assert [row["task"]["id"] for row in result["created"]] == [
        "event_article_cpi_us_2026-07-14_tplus0"
    ]
    decision = json.loads(
        (storage_dir / "logs" / "dedup_decisions.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[-1]
    )
    assert decision["decision"] == "warn"
    assert decision["reason"] == "legacy_reaction_candidate_advisory"


def test_legacy_event_title_before_release_cannot_cover_reaction():
    release_at = datetime(2026, 7, 29, 18, 0, tzinfo=timezone.utc)
    feed = [
        {
            "id": "mile_fomc_scenario",
            "status": "published",
            "title": "FOMC 情境分析",
            "published_at": "2026-07-29T02:01:00+00:00",
        }
    ]

    hit = event_jobs.reaction_already_covered(
        "FOMC",
        datetime(2026, 7, 29, 0, 0, tzinfo=timezone.utc),
        feed,
        event_key="FOMC_2026_07_29",
        requested_slot="T+0",
        release_at=release_at,
    )

    assert hit is None


def test_structured_tplus0_cannot_cover_tplus1():
    feed = [
        {
            "id": "mile_fomc_tplus0",
            "status": "published",
            "title": "FOMC 決議與即時市場反應",
            "event_key": "FOMC_2026_07_29",
            "event_type": "FOMC",
            "event_date": "2026-07-29",
            "event_series_slot": "T+0",
            "published_at": "2026-07-29T18:05:00+00:00",
        }
    ]

    hit = event_jobs.reaction_already_covered(
        "FOMC",
        datetime(2026, 7, 29, 18, 0, tzinfo=timezone.utc),
        feed,
        event_key="FOMC_2026_07_29",
        requested_slot="T+1",
        release_at=datetime(2026, 7, 29, 18, 0, tzinfo=timezone.utc),
    )

    assert hit is None


def test_claimed_event_task_is_immutable_during_reconcile(
    tmp_path: Path,
    monkeypatch,
):
    now = datetime(2026, 7, 10, 7, 0, tzinfo=timezone.utc)
    item = _event_item(
        "fomc-2026-07-29-t2",
        event_type="FOMC",
        event_date="2026-07-29",
        slot="T-2",
        not_before=(now - timedelta(minutes=1)).isoformat(),
        deadline=(now + timedelta(hours=6)).isoformat(),
    )
    config_path = tmp_path / "runtime_schedules.json"
    _write_runtime_schedules(config_path, event_items=[item])
    monkeypatch.setattr(schedule_config, "RUNTIME_SCHEDULES_PATH", config_path)
    schedule_config.load_runtime_schedules.cache_clear()
    storage_dir = str(tmp_path / "storage")
    first = expand_due_event_jobs(storage_dir=storage_dir, now=now)
    assert first["created"]
    queue_path = tmp_path / "storage" / "next_tasks.json"
    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    queue[0]["status"] = "claimed"
    queue[0]["claimed_by"] = "worker-1"
    queue[0]["description"] = "worker-owned brief"
    queue[0].pop("event_series_slot")
    queue_path.write_text(json.dumps(queue), encoding="utf-8")

    expand_due_event_jobs(storage_dir=storage_dir, now=now + timedelta(minutes=1))

    saved = json.loads(queue_path.read_text(encoding="utf-8"))[0]
    assert saved["description"] == "worker-owned brief"
    assert "event_series_slot" not in saved
    assert saved["claimed_by"] == "worker-1"


def test_reaction_coverage_supersedes_existing_pending_row(tmp_path: Path, monkeypatch):
    now = datetime(2026, 7, 3, 0, 0, tzinfo=timezone.utc)
    item = _event_item(
        "nfp-2026-07-03-t0",
        event_type="NFP_US",
        event_date="2026-07-03",
        slot="T+0",
        not_before=(now - timedelta(minutes=1)).isoformat(),
        deadline=(now + timedelta(hours=36)).isoformat(),
    )
    config_path = tmp_path / "runtime_schedules.json"
    _write_runtime_schedules(config_path, event_items=[item])
    monkeypatch.setattr(schedule_config, "RUNTIME_SCHEDULES_PATH", config_path)
    schedule_config.load_runtime_schedules.cache_clear()
    storage_dir = str(tmp_path / "storage")

    first = expand_due_event_jobs(storage_dir=storage_dir, now=now)
    task_id = first["created"][0]["task"]["id"]
    feed_path = tmp_path / "storage" / "reports" / "feed.json"
    feed_path.parent.mkdir(parents=True, exist_ok=True)
    feed_path.write_text(
        json.dumps(
            [
                {
                    "id": "mile_nfp_reaction",
                    "status": "published",
                    "title": "非農就業結果出爐",
                    "tags": ["NFP"],
                    "published_at": now.isoformat(),
                    "event_key": "NFP_US_2026_07_03",
                    "event_type": "NFP_US",
                    "event_date": "2026-07-03",
                    "event_series_slot": "T+0",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    second = expand_due_event_jobs(storage_dir=storage_dir, now=now + timedelta(minutes=5))

    assert second["created"] == []
    assert any(row["reason"] == "reaction_already_covered" for row in second["skipped"])
    queue = json.loads((tmp_path / "storage" / "next_tasks.json").read_text(encoding="utf-8"))
    assert queue[0]["id"] == task_id
    assert queue[0]["status"] == "superseded"
    assert queue[0]["covered_by"]["id"] == "mile_nfp_reaction"
    ledger_path = event_jobs._ledger_path(item["dedupe_key"], storage_dir=storage_dir)
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert ledger["disposition"] == "reaction_already_covered"
    assert ledger["next_task_id"] == task_id


def test_covered_reaction_cancels_legacy_without_fake_successor(tmp_path: Path, monkeypatch):
    now = datetime(2026, 7, 3, 0, 0, tzinfo=timezone.utc)
    item = _event_item(
        "nfp-2026-07-03-t0",
        event_type="NFP_US",
        event_date="2026-07-03",
        slot="T+0",
        not_before=(now - timedelta(minutes=1)).isoformat(),
        deadline=(now + timedelta(hours=36)).isoformat(),
    )
    config_path = tmp_path / "runtime_schedules.json"
    _write_runtime_schedules(config_path, event_items=[item])
    monkeypatch.setattr(schedule_config, "RUNTIME_SCHEDULES_PATH", config_path)
    schedule_config.load_runtime_schedules.cache_clear()
    storage_dir = str(tmp_path / "storage")
    legacy = create_task(
        title="Event article: legacy NFP",
        description="pre-cutover receipt",
        source="schedule",
        task_family="content",
        payload={"event_job_id": item["id"], "event_key": item["event_key"]},
        created_by="event_expander",
        storage_dir=storage_dir,
    )
    ledger_path = event_jobs._ledger_path(item["dedupe_key"], storage_dir=storage_dir)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(
        json.dumps(
            {
                "task_id": legacy["id"],
                "deadline": item["deadline"],
                "gc_after": (now + timedelta(days=8)).isoformat(),
            }
        ),
        encoding="utf-8",
    )
    feed_path = tmp_path / "storage" / "reports" / "feed.json"
    feed_path.parent.mkdir(parents=True, exist_ok=True)
    feed_path.write_text(
        json.dumps(
            [
                {
                    "id": "mile_nfp_done",
                    "status": "published",
                    "title": "非農結果出爐",
                    "tags": ["NFP"],
                    "published_at": now.isoformat(),
                    "event_key": "NFP_US_2026_07_03",
                    "event_type": "NFP_US",
                    "event_date": "2026-07-03",
                    "event_series_slot": "T+0",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = expand_due_event_jobs(storage_dir=storage_dir, now=now)

    assert result["created"] == []
    state = get_task(legacy["id"], storage_dir=storage_dir)
    assert state is not None
    assert state["status"] == "cancelled"
    assert "superseded_by" not in state
    assert state["migration_candidate_id"] == event_jobs._event_task_id(item)
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert ledger["disposition"] == "reaction_already_covered"
    assert ledger["covered_by"]["id"] == "mile_nfp_done"
    assert not ledger.get("next_task_id")


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


@pytest.mark.parametrize(
    "corrupt_payload",
    ['{"task_id":', '{"gc_after":"not-an-iso-date"}', "[]"],
)
def test_corrupt_ledger_is_rebuilt_without_duplicate_queue_row(
    corrupt_payload: str, tmp_path: Path, monkeypatch
):
    now = datetime(2026, 7, 10, 7, 0, tzinfo=timezone.utc)
    item = _event_item(
        "cpi-2026-07-10-t2",
        event_type="CPI_US",
        event_date="2026-07-10",
        slot="T-2",
        not_before=(now - timedelta(minutes=1)).isoformat(),
        deadline=(now + timedelta(hours=12)).isoformat(),
    )
    config_path = tmp_path / "runtime_schedules.json"
    _write_runtime_schedules(config_path, event_items=[item])
    monkeypatch.setattr(schedule_config, "RUNTIME_SCHEDULES_PATH", config_path)
    schedule_config.load_runtime_schedules.cache_clear()
    storage_dir = str(tmp_path / "storage")
    first = expand_due_event_jobs(storage_dir=storage_dir, now=now)
    task_id = first["created"][0]["task"]["id"]
    ledger_path = event_jobs._ledger_path(item["dedupe_key"], storage_dir=storage_dir)
    ledger_path.write_text(corrupt_payload, encoding="utf-8")

    recovered = expand_due_event_jobs(storage_dir=storage_dir, now=now + timedelta(minutes=5))

    assert recovered["created"] == []
    queue = json.loads((tmp_path / "storage" / "next_tasks.json").read_text(encoding="utf-8"))
    assert [row["id"] for row in queue] == [task_id]
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert ledger["next_task_id"] == task_id
    assert ledger["dedupe_key"] == item["dedupe_key"]


def test_invalid_not_before_skips_only_bad_event(tmp_path: Path, monkeypatch):
    now = datetime(2026, 7, 10, 7, 0, tzinfo=timezone.utc)
    bad = _event_item(
        "bad-window",
        event_type="CPI_US",
        event_date="2026-07-10",
        slot="T-2",
        not_before="not-an-iso-date",
        deadline=(now + timedelta(hours=12)).isoformat(),
    )
    good = _event_item(
        "good-window",
        event_type="FOMC",
        event_date="2026-07-10",
        slot="T-2",
        not_before=(now - timedelta(minutes=1)).isoformat(),
        deadline=(now + timedelta(hours=12)).isoformat(),
    )
    config_path = tmp_path / "runtime_schedules.json"
    _write_runtime_schedules(config_path, event_items=[bad, good])
    monkeypatch.setattr(schedule_config, "RUNTIME_SCHEDULES_PATH", config_path)
    schedule_config.load_runtime_schedules.cache_clear()

    result = expand_due_event_jobs(storage_dir=str(tmp_path / "storage"), now=now)

    assert [row["task"]["ref_event_job_id"] for row in result["created"]] == ["good-window"]
    assert any(
        row["id"] == "bad-window" and row["reason"] == "invalid_event_window"
        for row in result["skipped"]
    )


def test_missing_event_id_cannot_attach_to_unrelated_queue_row(tmp_path: Path, monkeypatch):
    now = datetime(2026, 7, 10, 7, 0, tzinfo=timezone.utc)
    malformed = _event_item(
        "temporary-id",
        event_type="CPI_US",
        event_date="2026-07-10",
        slot="T-2",
        not_before=(now - timedelta(minutes=1)).isoformat(),
        deadline=(now + timedelta(hours=12)).isoformat(),
    )
    malformed.pop("id")
    config_path = tmp_path / "runtime_schedules.json"
    _write_runtime_schedules(config_path, event_items=[malformed])
    monkeypatch.setattr(schedule_config, "RUNTIME_SCHEDULES_PATH", config_path)
    schedule_config.load_runtime_schedules.cache_clear()
    storage_dir = tmp_path / "storage"
    queue_path = storage_dir / "next_tasks.json"
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    unrelated = {"id": "ordinary-platform-task", "task_type": "platform_ops", "status": "pending"}
    queue_path.write_text(json.dumps([unrelated]), encoding="utf-8")

    result = expand_due_event_jobs(storage_dir=str(storage_dir), now=now)

    assert result["created"] == []
    assert {"id": None, "reason": "missing_id"} in result["skipped"]
    assert json.loads(queue_path.read_text(encoding="utf-8")) == [unrelated]


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
