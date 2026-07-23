import json
from pathlib import Path

from click.testing import CliRunner

from volpred.cli import cli


def _write_snapshot(path: Path, records: list[dict[str, object]]) -> bytes:
    path.write_text(json.dumps(records), encoding="utf-8")
    return path.read_bytes()


def test_legacy_import_cli_is_explicit_dry_run_and_never_mutates_snapshots(
    tmp_path: Path,
) -> None:
    next_tasks = tmp_path / "next_tasks.json"
    task_records = tmp_path / "task_records.json"
    ops_jobs = tmp_path / "ops_jobs.json"
    original_bytes = {
        next_tasks: _write_snapshot(
            next_tasks,
            [
                {
                    "id": "preview_only",
                    "status": "pending",
                    "task_type": "platform_ops",
                    "title": "Preview legacy work",
                    "priority": 1,
                    "source": "user",
                    "created_at": "2026-07-23T09:00:00+00:00",
                }
            ],
        ),
        task_records: _write_snapshot(task_records, []),
        ops_jobs: _write_snapshot(ops_jobs, []),
    }

    runner = CliRunner()
    arguments = [
        "ops",
        "work-import-legacy",
        "--next-tasks-snapshot",
        str(next_tasks),
        "--task-records-snapshot",
        str(task_records),
        "--ops-jobs-snapshot",
        str(ops_jobs),
    ]
    without_dry_run = runner.invoke(cli, arguments)
    assert without_dry_run.exit_code == 2
    assert "--dry-run" in without_dry_run.output

    before_names = {path.name for path in tmp_path.iterdir()}
    result = runner.invoke(cli, [*arguments, "--dry-run"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["mode"] == "dry_run"
    assert payload["ready"] is True
    assert payload["candidate_count"] == 1
    assert payload["issue_count"] == 0
    assert {path.name for path in tmp_path.iterdir()} == before_names
    assert {
        path: path.read_bytes() for path in original_bytes
    } == original_bytes


def test_legacy_import_cli_exits_nonzero_when_reconciliation_fails(
    tmp_path: Path,
) -> None:
    next_tasks = tmp_path / "next_tasks.json"
    task_records = tmp_path / "task_records.json"
    ops_jobs = tmp_path / "ops_jobs.json"
    _write_snapshot(
        next_tasks,
        [
            {
                "id": "unknown",
                "status": "new_unmapped_state",
                "task_type": "platform_ops",
                "title": "Must not pass",
                "priority": 1,
                "source": "agent",
                "created_at": "2026-07-23T09:00:00+00:00",
            }
        ],
    )
    _write_snapshot(task_records, [])
    _write_snapshot(ops_jobs, [])

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
    assert payload["ready"] is False
    assert payload["issues"][0]["code"] == "unknown_status"


def test_legacy_import_cli_returns_json_for_invalid_snapshot_shape(
    tmp_path: Path,
) -> None:
    next_tasks = tmp_path / "next_tasks.json"
    task_records = tmp_path / "task_records.json"
    ops_jobs = tmp_path / "ops_jobs.json"
    next_tasks.write_text('{"not":"an array"}', encoding="utf-8")
    _write_snapshot(task_records, [])
    _write_snapshot(ops_jobs, [])

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
    assert payload["mode"] == "dry_run"
    assert payload["ready"] is False
    assert payload["candidate_count"] == 0
    assert payload["issue_count"] == 1
    assert payload["issues"][0]["code"] == "invalid_snapshot"
    assert payload["issues"][0]["source_system"] == "next_tasks"


def test_legacy_import_cli_returns_json_for_non_utf8_snapshot(
    tmp_path: Path,
) -> None:
    next_tasks = tmp_path / "next_tasks.json"
    task_records = tmp_path / "task_records.json"
    ops_jobs = tmp_path / "ops_jobs.json"
    next_tasks.write_bytes(b"[\xff]")
    _write_snapshot(task_records, [])
    _write_snapshot(ops_jobs, [])

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
    assert payload["ready"] is False
    assert payload["issues"] == [
        {
            "code": "invalid_snapshot",
            "source_system": "next_tasks",
            "record_id": None,
            "detail": "snapshot is not readable UTF-8 JSON",
        }
    ]
