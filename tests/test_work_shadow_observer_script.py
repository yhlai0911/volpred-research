import json

from scripts import observe_work_shadow as observer_script


def test_scheduled_entrypoint_logs_a_bounded_receipt_summary(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(
        observer_script,
        "run_observation",
        lambda: {
            "schema_version": "work-shadow-replay.v3",
            "observation_id": "scheduled_1",
            "recorded_at": "2026-07-26T06:30:00+00:00",
            "receipt_path": "/tmp/scheduled_1.json",
            "snapshot": {
                "source_counts": {
                    "next_tasks": 1,
                    "task_records": 2,
                    "ops_jobs": 3,
                }
            },
            "selection_difference": {
                "classification": "legacy_corruption"
            },
            "reconciliation_issues": [{"code": "missing_parent"}],
            "comparisons": [{"payload": "must stay in the receipt"}],
        },
    )

    assert observer_script.main() == 0

    output = json.loads(capsys.readouterr().out)
    assert output == {
        "schema_version": "work-shadow-observer-run.v1",
        "observation_id": "scheduled_1",
        "recorded_at": "2026-07-26T06:30:00+00:00",
        "receipt_path": "/tmp/scheduled_1.json",
        "source_counts": {
            "next_tasks": 1,
            "task_records": 2,
            "ops_jobs": 3,
        },
        "selection_difference_classification": "legacy_corruption",
        "reconciliation_issue_count": 1,
    }
