import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from volpred.cli import cli
from volpred.ops.work_migration import (
    LegacySnapshotLoadError,
    load_legacy_snapshots,
)


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_load_legacy_snapshots_returns_all_three_sources(tmp_path: Path) -> None:
    next_tasks = tmp_path / "next_tasks.json"
    task_records = tmp_path / "task_records.json"
    ops_jobs = tmp_path / "ops_jobs.json"
    _write_json(next_tasks, [{"id": "next_1"}])
    _write_json(task_records, [{"id": "record_1"}])
    _write_json(ops_jobs, [{"id": "job_1"}])

    snapshots = load_legacy_snapshots(
        next_tasks_path=next_tasks,
        task_records_path=task_records,
        ops_jobs_path=ops_jobs,
    )

    assert snapshots.next_tasks == ({"id": "next_1"},)
    assert snapshots.task_records == ({"id": "record_1"},)
    assert snapshots.ops_jobs == ({"id": "job_1"},)


def test_load_legacy_snapshots_reports_non_utf8_source_stably(
    tmp_path: Path,
) -> None:
    next_tasks = tmp_path / "next_tasks.json"
    task_records = tmp_path / "task_records.json"
    ops_jobs = tmp_path / "ops_jobs.json"
    next_tasks.write_bytes(b"[\xff]")
    _write_json(task_records, [])
    _write_json(ops_jobs, [])

    with pytest.raises(LegacySnapshotLoadError) as caught:
        load_legacy_snapshots(
            next_tasks_path=next_tasks,
            task_records_path=task_records,
            ops_jobs_path=ops_jobs,
        )

    assert caught.value.code == "invalid_snapshot"
    assert caught.value.source_system == "next_tasks"
    assert caught.value.detail == "snapshot is not readable UTF-8 JSON"


def test_load_legacy_snapshots_rejects_malformed_json_stably(
    tmp_path: Path,
) -> None:
    next_tasks = tmp_path / "next_tasks.json"
    task_records = tmp_path / "task_records.json"
    ops_jobs = tmp_path / "ops_jobs.json"
    _write_json(next_tasks, [])
    task_records.write_text("[", encoding="utf-8")
    _write_json(ops_jobs, [])

    with pytest.raises(LegacySnapshotLoadError) as caught:
        load_legacy_snapshots(
            next_tasks_path=next_tasks,
            task_records_path=task_records,
            ops_jobs_path=ops_jobs,
        )

    assert caught.value.source_system == "task_records"
    assert caught.value.detail == "snapshot is not valid JSON"


def test_load_legacy_snapshots_reports_unreadable_source_stably(
    tmp_path: Path,
) -> None:
    missing_next_tasks = tmp_path / "missing-next-tasks.json"
    task_records = tmp_path / "task_records.json"
    ops_jobs = tmp_path / "ops_jobs.json"
    _write_json(task_records, [])
    _write_json(ops_jobs, [])

    with pytest.raises(LegacySnapshotLoadError) as caught:
        load_legacy_snapshots(
            next_tasks_path=missing_next_tasks,
            task_records_path=task_records,
            ops_jobs_path=ops_jobs,
        )

    assert caught.value.source_system == "next_tasks"
    assert caught.value.detail == "snapshot is not readable"


def test_load_legacy_snapshots_requires_top_level_array(tmp_path: Path) -> None:
    next_tasks = tmp_path / "next_tasks.json"
    task_records = tmp_path / "task_records.json"
    ops_jobs = tmp_path / "ops_jobs.json"
    _write_json(next_tasks, [])
    _write_json(task_records, [])
    _write_json(ops_jobs, {"id": "not-an-array"})

    with pytest.raises(LegacySnapshotLoadError) as caught:
        load_legacy_snapshots(
            next_tasks_path=next_tasks,
            task_records_path=task_records,
            ops_jobs_path=ops_jobs,
        )

    assert caught.value.source_system == "ops_jobs"
    assert caught.value.detail == "snapshot must be a JSON array"


def test_load_legacy_snapshots_requires_each_item_to_be_an_object(
    tmp_path: Path,
) -> None:
    next_tasks = tmp_path / "next_tasks.json"
    task_records = tmp_path / "task_records.json"
    ops_jobs = tmp_path / "ops_jobs.json"
    _write_json(next_tasks, [{"id": "valid"}, 7])
    _write_json(task_records, [])
    _write_json(ops_jobs, [])

    with pytest.raises(LegacySnapshotLoadError) as caught:
        load_legacy_snapshots(
            next_tasks_path=next_tasks,
            task_records_path=task_records,
            ops_jobs_path=ops_jobs,
        )

    assert caught.value.source_system == "next_tasks"
    assert caught.value.detail == "snapshot items must be JSON objects"


def test_import_cli_uses_loader_issue_for_invalid_snapshot(
    tmp_path: Path,
) -> None:
    next_tasks = tmp_path / "next_tasks.json"
    task_records = tmp_path / "task_records.json"
    ops_jobs = tmp_path / "ops_jobs.json"
    _write_json(next_tasks, {"id": "not-an-array"})
    _write_json(task_records, [])
    _write_json(ops_jobs, [])

    result = CliRunner().invoke(
        cli,
        [
            "ops",
            "work-import-legacy",
            "--dry-run",
            "--next-tasks-snapshot",
            str(next_tasks),
            "--task-records-snapshot",
            str(task_records),
            "--ops-jobs-snapshot",
            str(ops_jobs),
        ],
    )

    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert payload["issues"] == [
        {
            "code": "invalid_snapshot",
            "source_system": "next_tasks",
            "record_id": None,
            "detail": "snapshot must be a JSON array",
        }
    ]


def test_shadow_cli_uses_loader_error_and_does_not_create_receipt(
    tmp_path: Path,
) -> None:
    next_tasks = tmp_path / "next_tasks.json"
    task_records = tmp_path / "task_records.json"
    ops_jobs = tmp_path / "ops_jobs.json"
    observations = tmp_path / "observations"
    _write_json(next_tasks, [{"id": "valid"}, "not-an-object"])
    _write_json(task_records, [])
    _write_json(ops_jobs, [])

    result = CliRunner().invoke(
        cli,
        [
            "ops",
            "work-shadow-replay",
            "--next-tasks-snapshot",
            str(next_tasks),
            "--task-records-snapshot",
            str(task_records),
            "--ops-jobs-snapshot",
            str(ops_jobs),
            "--observation-dir",
            str(observations),
            "--observation-id",
            "must_not_exist",
            "--observed-at",
            "2026-07-23T09:30:00+00:00",
            "--worker-id",
            "scheduled-shadow",
        ],
    )

    assert result.exit_code == 1
    assert result.output == (
        "Error: next_tasks [invalid_snapshot]: "
        "snapshot items must be JSON objects\n"
    )
    assert not observations.exists()
