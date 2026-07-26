from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import pytest

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
    mode_path = tmp_path / "storage" / "ops" / "task_pool_mode.json"
    mode_path.parent.mkdir(parents=True)
    mode_path.write_text(
        json.dumps({"enabled": True, "mode": "direct_execution"}),
        encoding="utf-8",
    )
    mode_bytes = mode_path.read_bytes()

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
    assert receipt["schema_version"] == "work-shadow-replay.v4"
    assert receipt["queue_owner_evidence"] == {
        "schema_version": "task-pool-owner-evidence.v1",
        "mode": "direct_execution",
        "gate_enabled": True,
        "state_path": str(mode_path.resolve()),
        "state_sha256": hashlib.sha256(mode_bytes).hexdigest(),
        "state_byte_count": len(mode_bytes),
    }
    assert receipt["snapshot"]["source_counts"] == {
        "next_tasks": 1,
        "task_records": 1,
        "ops_jobs": 1,
    }


def test_canonical_observer_scopes_task_id_alias_with_production_identity(
    tmp_path: Path,
) -> None:
    queue_path = tmp_path / "storage" / "next_tasks.json"
    queue_path.parent.mkdir(parents=True)
    queue_path.write_text(
        json.dumps(
            [
                {
                    "task_id": "canonical_alias",
                    "status": "pending",
                    "task_type": "platform_ops",
                    "title": "Alias identity",
                    "priority": 1,
                    "source": "user",
                    "created_at": "2026-07-26T06:00:00+00:00",
                }
            ]
        ),
        encoding="utf-8",
    )
    mode_path = tmp_path / "storage" / "ops" / "task_pool_mode.json"
    mode_path.parent.mkdir(parents=True)
    mode_path.write_text(
        json.dumps({"enabled": False, "mode": "queued_execution"}),
        encoding="utf-8",
    )

    receipt_path = observe_canonical_work_shadow(
        project_root=tmp_path,
        task_records_reader=lambda: [
            {
                "task_id": "canonical_alias",
                "status": "succeeded",
                "task_family": "ops",
                "title": "Matching terminal receipt",
                "priority": 3,
                "source": "user",
                "approval_mode": "auto",
                "risk_level": "safe",
                "public_effect": "none",
                "created_at": "2026-07-25T06:00:00+00:00",
            }
        ],
        ops_jobs_reader=lambda: [],
        observed_at=datetime(2026, 7, 26, 7, 30, tzinfo=timezone.utc),
        observation_id="scheduled_task_id_alias",
    )

    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["snapshot"]["source_counts"]["task_records"] == 1


@pytest.mark.parametrize(
    "status",
    ("queued", "claimed", "running", "awaiting_approval", "blocked"),
)
def test_canonical_observer_retains_every_nonterminal_task_record(
    tmp_path: Path,
    status: str,
) -> None:
    queue_path = tmp_path / "storage" / "next_tasks.json"
    queue_path.parent.mkdir(parents=True)
    queue_path.write_text("[]", encoding="utf-8")
    mode_path = tmp_path / "storage" / "ops" / "task_pool_mode.json"
    mode_path.parent.mkdir(parents=True)
    mode_path.write_text(
        json.dumps({"enabled": False, "mode": "queued_execution"}),
        encoding="utf-8",
    )

    receipt_path = observe_canonical_work_shadow(
        project_root=tmp_path,
        task_records_reader=lambda: [
            {
                "id": f"{status}_task",
                "status": status,
                "task_family": "ops",
                "title": f"{status} task",
                "priority": 3,
                "source": "user",
                "approval_mode": "auto",
                "risk_level": "safe",
                "public_effect": "none",
                "created_at": "2026-07-26T06:00:00+00:00",
            }
        ],
        ops_jobs_reader=lambda: [],
        observed_at=datetime(2026, 7, 26, 8, 15, tzinfo=timezone.utc),
        observation_id=f"scheduled_{status}",
    )

    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["snapshot"]["source_counts"]["task_records"] == 1
