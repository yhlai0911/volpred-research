from datetime import datetime, timezone
import json
from pathlib import Path

from volpred.ops.work import WorkerOffer
from volpred.ops.work_shadow_observer import (
    observe_canonical_work_shadow,
    observe_work_shadow,
)


def test_observer_appends_one_receipt_from_one_frozen_three_source_snapshot(
    tmp_path: Path,
) -> None:
    next_tasks = [
        {
            "id": "scheduled_candidate",
            "status": "pending",
            "task_type": "platform_ops",
            "title": "Observe me",
            "priority": 1,
            "source": "user",
            "created_at": "2026-07-26T06:00:00+00:00",
        }
    ]
    task_records: list[dict[str, object]] = []
    ops_jobs: list[dict[str, object]] = []
    reads = {"next_tasks": 0, "task_records": 0, "ops_jobs": 0}

    def read_next_tasks() -> list[dict[str, object]]:
        reads["next_tasks"] += 1
        return next_tasks

    def read_task_records() -> list[dict[str, object]]:
        reads["task_records"] += 1
        return task_records

    def read_ops_jobs() -> list[dict[str, object]]:
        reads["ops_jobs"] += 1
        return ops_jobs

    receipt_path = observe_work_shadow(
        next_tasks_reader=read_next_tasks,
        task_records_reader=read_task_records,
        ops_jobs_reader=read_ops_jobs,
        observation_directory=tmp_path / "observations",
        observation_id="scheduled_20260726T061500Z",
        observed_at=datetime(2026, 7, 26, 6, 15, tzinfo=timezone.utc),
        offer=WorkerOffer(
            worker_id="scheduled-shadow",
            capabilities=frozenset({"code"}),
            attestations=frozenset(),
            lease_seconds=300,
        ),
    )

    assert reads == {"next_tasks": 1, "task_records": 1, "ops_jobs": 1}
    assert receipt_path == (
        tmp_path
        / "observations"
        / "scheduled_20260726T061500Z.json"
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["schema_version"] == "work-shadow-replay.v3"
    assert receipt["observation_id"] == "scheduled_20260726T061500Z"
    assert receipt["snapshot"]["source_counts"] == {
        "next_tasks": 1,
        "task_records": 0,
        "ops_jobs": 0,
    }
    assert receipt["legacy_selection"]["snapshot_sha256"] == (
        receipt["coordinator_selection"]["snapshot_sha256"]
    )
    assert next_tasks[0]["id"] == "scheduled_candidate"


def test_canonical_observer_reads_live_queue_without_mutating_it(
    tmp_path: Path,
) -> None:
    queue_path = tmp_path / "storage" / "next_tasks.json"
    queue_path.parent.mkdir(parents=True)
    queue_path.write_text(
        json.dumps(
            [
                {
                    "id": "canonical_candidate",
                    "status": "pending",
                    "task_type": "platform_ops",
                    "title": "Canonical observation",
                    "priority": 1,
                    "source": "user",
                    "created_at": "2026-07-26T06:00:00+00:00",
                    "parent_task_id": "parent_1",
                }
            ]
        ),
        encoding="utf-8",
    )
    original_queue = queue_path.read_bytes()

    receipt_path = observe_canonical_work_shadow(
        project_root=tmp_path,
        task_records_reader=lambda: [
            {
                "id": "parent_1",
                "status": "succeeded",
                "task_family": "ops",
                "title": "Relevant parent",
                "priority": 3,
                "source": "user",
                "approval_mode": "auto",
                "risk_level": "safe",
                "public_effect": "none",
                "created_at": "2026-07-25T06:00:00+00:00",
            },
            {
                "id": "unrelated_history",
                "status": "migrated",
            },
        ],
        ops_jobs_reader=lambda: [
            {
                "id": "active_job",
                "action": "health_check",
                "scope": "local",
                "source": "system",
                "requested_by": "scheduler",
                "payload": {},
                "dry_run": True,
                "priority": 5,
                "status": "queued",
                "created_at": "2026-07-26T06:30:00+00:00",
            },
            {
                "id": "unrelated_terminal_job",
                "status": "succeeded",
                "dry_run": False,
            },
        ],
        observed_at=datetime(2026, 7, 26, 7, 15, tzinfo=timezone.utc),
        observation_id="scheduled_20260726T071500Z",
    )

    assert queue_path.read_bytes() == original_queue
    assert receipt_path == (
        tmp_path
        / "storage"
        / "ops"
        / "work_shadow_observations"
        / "scheduled_20260726T071500Z.json"
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["snapshot"]["source_counts"] == {
        "next_tasks": 1,
        "task_records": 1,
        "ops_jobs": 1,
    }
