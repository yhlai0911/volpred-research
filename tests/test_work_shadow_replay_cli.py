import json
from pathlib import Path

from click.testing import CliRunner

from volpred.cli import cli


def _write_snapshot(path: Path, records: list[dict[str, object]]) -> bytes:
    path.write_text(json.dumps(records), encoding="utf-8")
    return path.read_bytes()


def test_shadow_replay_cli_writes_only_an_append_only_observation(
    tmp_path: Path,
) -> None:
    next_tasks = tmp_path / "next_tasks.json"
    task_records = tmp_path / "task_records.json"
    ops_jobs = tmp_path / "ops_jobs.json"
    observations = tmp_path / "observations"
    original_bytes = {
        next_tasks: _write_snapshot(
            next_tasks,
            [
                {
                    "id": "shadow_candidate",
                    "status": "pending",
                    "task_type": "platform_ops",
                    "title": "Replay me",
                    "priority": 1,
                    "source": "user",
                    "created_at": "2026-07-23T09:00:00+00:00",
                }
            ],
        ),
        task_records: _write_snapshot(task_records, []),
        ops_jobs: _write_snapshot(ops_jobs, []),
    }

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
            "scheduled_20260723T093000Z",
            "--observed-at",
            "2026-07-23T09:30:00+00:00",
            "--worker-id",
            "scheduled-shadow",
            "--capability",
            "code",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema_version"] == "work-shadow-replay.v1"
    assert payload["observation_id"] == "scheduled_20260723T093000Z"
    assert payload["legacy_selection"]["snapshot_sha256"] == (
        payload["coordinator_selection"]["snapshot_sha256"]
    )
    receipt_path = Path(payload["receipt_path"])
    assert receipt_path == (
        observations / "scheduled_20260723T093000Z.json"
    )
    assert json.loads(receipt_path.read_text(encoding="utf-8"))[
        "observation_id"
    ] == "scheduled_20260723T093000Z"
    assert {
        path: path.read_bytes() for path in original_bytes
    } == original_bytes
    assert sorted(path.name for path in observations.iterdir()) == [
        "scheduled_20260723T093000Z.json"
    ]
