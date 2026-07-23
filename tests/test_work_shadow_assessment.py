from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from click.testing import CliRunner

from volpred.cli import cli
from volpred.ops.work_shadow_assessment import (
    assess_shadow_observation_directory,
)


START = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)
REQUIRED_DIMENSIONS = (
    "priority",
    "claim_ownership",
    "parent",
    "deadline",
    "terminal_disposition",
)


def _write_receipt(
    directory: Path,
    *,
    index: int,
    observed_at: datetime,
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    snapshot_sha = f"{index + 1:064x}"
    receipt = {
        "schema_version": "work-shadow-replay.v2",
        "observation_id": f"scheduled_{index:02d}",
        "observed_at": observed_at.isoformat(),
        "selection_scope": "next_tasks",
        "snapshot": {
            "sha256": snapshot_sha,
            "byte_count": 100 + index,
            "source_counts": {
                "next_tasks": 1,
                "task_records": 0,
                "ops_jobs": 0,
            },
        },
        "legacy_selection": {
            "policy": "legacy",
            "snapshot_sha256": snapshot_sha,
            "selected_candidate_ref": "next_tasks:task-1",
            "eligible_candidate_refs": ["next_tasks:task-1"],
        },
        "coordinator_selection": {
            "policy": "work_coordinator",
            "snapshot_sha256": snapshot_sha,
            "selected_candidate_ref": "next_tasks:task-1",
            "eligible_candidate_refs": ["next_tasks:task-1"],
        },
        "selection_difference": None,
        "comparisons": [
            {
                "candidate_ref": "next_tasks:task-1",
                "legacy_eligible": True,
                "coordinator_eligible": True,
                "dimensions": [
                    {
                        "name": name,
                        "legacy": {"value": "same"},
                        "coordinator": {"value": "same"},
                        "matches": True,
                        "classification": None,
                        "classification_reason_code": None,
                        "legacy_reason_codes": [],
                        "coordinator_reason_codes": [],
                        "evidence_refs": [f"contract://{name}"],
                    }
                    for name in REQUIRED_DIMENSIONS
                ],
            }
        ],
        "reconciliation_issues": [],
    }
    (directory / f"scheduled_{index:02d}.json").write_text(
        json.dumps(receipt),
        encoding="utf-8",
    )


def test_seven_continuous_clean_days_are_ready_for_cutover(tmp_path: Path) -> None:
    observations = tmp_path / "observations"
    for index in range(8):
        _write_receipt(
            observations,
            index=index,
            observed_at=START + timedelta(days=index),
        )

    report = assess_shadow_observation_directory(
        observations,
        assessed_at=START + timedelta(days=7, hours=1),
        queue_owner_mode="legacy_queue_shadow",
        required_window=timedelta(days=7),
        max_gap=timedelta(hours=26),
    )

    assert report.ready_for_cutover is True
    assert report.reason_codes == ()
    assert report.observation_count == 8
    assert report.covered_dimensions == REQUIRED_DIMENSIONS


def test_malformed_receipt_fails_closed_instead_of_crashing(tmp_path: Path) -> None:
    observations = tmp_path / "observations"
    observations.mkdir()
    (observations / "broken.json").write_text("{not-json", encoding="utf-8")

    report = assess_shadow_observation_directory(
        observations,
        assessed_at=START,
        queue_owner_mode="legacy_queue_shadow",
        required_window=timedelta(days=7),
        max_gap=timedelta(hours=26),
    )

    assert report.ready_for_cutover is False
    assert report.reason_codes == ("invalid_receipt",)
    assert report.observation_count == 1


def test_unexplained_selector_drift_blocks_cutover(tmp_path: Path) -> None:
    observations = tmp_path / "observations"
    for index in range(8):
        _write_receipt(
            observations,
            index=index,
            observed_at=START + timedelta(days=index),
        )
    drift_path = observations / "scheduled_03.json"
    drift = json.loads(drift_path.read_text(encoding="utf-8"))
    drift["selection_difference"] = {
        "legacy_selected_candidate_ref": "next_tasks:task-1",
        "coordinator_selected_candidate_ref": None,
        "classification": "implementation_bug",
        "classification_reason_code": "unregistered_selector_reason_pair",
        "evidence_refs": ["snapshot://drift"],
    }
    drift_path.write_text(json.dumps(drift), encoding="utf-8")

    report = assess_shadow_observation_directory(
        observations,
        assessed_at=START + timedelta(days=7, hours=1),
        queue_owner_mode="legacy_queue_shadow",
        required_window=timedelta(days=7),
        max_gap=timedelta(hours=26),
    )

    assert report.ready_for_cutover is False
    assert report.reason_codes == ("blocking_selection_difference",)


def test_simultaneous_queue_owner_evidence_blocks_cutover(
    tmp_path: Path,
) -> None:
    observations = tmp_path / "observations"
    for index in range(8):
        _write_receipt(
            observations,
            index=index,
            observed_at=START + timedelta(days=index),
        )
    conflict_path = observations / "scheduled_04.json"
    conflict = json.loads(conflict_path.read_text(encoding="utf-8"))
    conflict["reconciliation_issues"] = [
        {
            "classification": "legacy_corruption",
            "code": "simultaneous_claim",
            "source_system": "next_tasks",
            "record_id": "task-1",
            "detail": "two active claim owners",
            "evidence_ref": "snapshot://owner-conflict",
        }
    ]
    conflict_path.write_text(json.dumps(conflict), encoding="utf-8")

    report = assess_shadow_observation_directory(
        observations,
        assessed_at=START + timedelta(days=7, hours=1),
        queue_owner_mode="legacy_queue_shadow",
        required_window=timedelta(days=7),
        max_gap=timedelta(hours=26),
    )

    assert report.ready_for_cutover is False
    assert report.reason_codes == ("reconciliation_issue_present",)


def test_blocking_dimension_difference_is_not_hidden_by_same_winner(
    tmp_path: Path,
) -> None:
    observations = tmp_path / "observations"
    for index in range(8):
        _write_receipt(
            observations,
            index=index,
            observed_at=START + timedelta(days=index),
        )
    mismatch_path = observations / "scheduled_05.json"
    mismatch = json.loads(mismatch_path.read_text(encoding="utf-8"))
    claim_dimension = mismatch["comparisons"][0]["dimensions"][1]
    claim_dimension["matches"] = False
    claim_dimension["classification"] = "implementation_bug"
    claim_dimension["classification_reason_code"] = "silent_owner_fallback"
    mismatch_path.write_text(json.dumps(mismatch), encoding="utf-8")

    report = assess_shadow_observation_directory(
        observations,
        assessed_at=START + timedelta(days=7, hours=1),
        queue_owner_mode="legacy_queue_shadow",
        required_window=timedelta(days=7),
        max_gap=timedelta(hours=26),
    )

    assert report.ready_for_cutover is False
    assert report.reason_codes == ("blocking_dimension_difference",)


def test_duplicate_observation_identity_blocks_cutover(tmp_path: Path) -> None:
    observations = tmp_path / "observations"
    for index in range(8):
        _write_receipt(
            observations,
            index=index,
            observed_at=START + timedelta(days=index),
        )
    duplicate = json.loads(
        (observations / "scheduled_03.json").read_text(encoding="utf-8")
    )
    duplicate["observed_at"] = (
        START + timedelta(days=3, hours=1)
    ).isoformat()
    (observations / "duplicate.json").write_text(
        json.dumps(duplicate),
        encoding="utf-8",
    )

    report = assess_shadow_observation_directory(
        observations,
        assessed_at=START + timedelta(days=7, hours=1),
        queue_owner_mode="legacy_queue_shadow",
        required_window=timedelta(days=7),
        max_gap=timedelta(hours=26),
    )

    assert report.ready_for_cutover is False
    assert report.reason_codes == ("duplicate_observation_id",)


def test_work_shadow_assess_cli_emits_machine_verdict(tmp_path: Path) -> None:
    observations = tmp_path / "observations"
    for index in range(8):
        _write_receipt(
            observations,
            index=index,
            observed_at=START + timedelta(days=index),
        )

    result = CliRunner().invoke(
        cli,
        [
            "ops",
            "work-shadow-assess",
            "--observation-dir",
            str(observations),
            "--assessed-at",
            (START + timedelta(days=7, hours=1)).isoformat(),
            "--queue-owner-mode",
            "legacy_queue_shadow",
            "--required-days",
            "7",
            "--max-gap-hours",
            "26",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema_version"] == "work-shadow-assessment.v1"
    assert payload["ready_for_cutover"] is True
    assert payload["reason_codes"] == []
    assert payload["observation_count"] == 8


def test_duplicate_observation_timestamp_blocks_cutover(tmp_path: Path) -> None:
    observations = tmp_path / "observations"
    for index in range(8):
        _write_receipt(
            observations,
            index=index,
            observed_at=START + timedelta(days=index),
        )
    duplicate_time_path = observations / "scheduled_04.json"
    duplicate_time = json.loads(
        duplicate_time_path.read_text(encoding="utf-8")
    )
    duplicate_time["observed_at"] = (
        START + timedelta(days=3)
    ).isoformat()
    duplicate_time_path.write_text(
        json.dumps(duplicate_time),
        encoding="utf-8",
    )

    report = assess_shadow_observation_directory(
        observations,
        assessed_at=START + timedelta(days=7, hours=1),
        queue_owner_mode="legacy_queue_shadow",
        required_window=timedelta(days=7),
        max_gap=timedelta(hours=26),
    )

    assert report.ready_for_cutover is False
    assert report.reason_codes == ("duplicate_observed_at",)


def test_snapshot_identity_mismatch_blocks_tampered_receipt(
    tmp_path: Path,
) -> None:
    observations = tmp_path / "observations"
    for index in range(8):
        _write_receipt(
            observations,
            index=index,
            observed_at=START + timedelta(days=index),
        )
    tampered_path = observations / "scheduled_06.json"
    tampered = json.loads(tampered_path.read_text(encoding="utf-8"))
    tampered["coordinator_selection"]["snapshot_sha256"] = "f" * 64
    tampered_path.write_text(json.dumps(tampered), encoding="utf-8")

    report = assess_shadow_observation_directory(
        observations,
        assessed_at=START + timedelta(days=7, hours=1),
        queue_owner_mode="legacy_queue_shadow",
        required_window=timedelta(days=7),
        max_gap=timedelta(hours=26),
    )

    assert report.ready_for_cutover is False
    assert report.reason_codes == ("snapshot_identity_mismatch",)


def test_missing_source_count_evidence_is_invalid(tmp_path: Path) -> None:
    observations = tmp_path / "observations"
    for index in range(8):
        _write_receipt(
            observations,
            index=index,
            observed_at=START + timedelta(days=index),
        )
    incomplete_path = observations / "scheduled_02.json"
    incomplete = json.loads(incomplete_path.read_text(encoding="utf-8"))
    del incomplete["snapshot"]["source_counts"]["ops_jobs"]
    incomplete_path.write_text(json.dumps(incomplete), encoding="utf-8")

    report = assess_shadow_observation_directory(
        observations,
        assessed_at=START + timedelta(days=7, hours=1),
        queue_owner_mode="legacy_queue_shadow",
        required_window=timedelta(days=7),
        max_gap=timedelta(hours=26),
    )

    assert report.ready_for_cutover is False
    assert report.reason_codes == ("invalid_receipt",)


def test_direct_execution_mode_cannot_reuse_queue_shadow_evidence(
    tmp_path: Path,
) -> None:
    observations = tmp_path / "observations"
    for index in range(8):
        _write_receipt(
            observations,
            index=index,
            observed_at=START + timedelta(days=index),
        )

    result = CliRunner().invoke(
        cli,
        [
            "ops",
            "work-shadow-assess",
            "--observation-dir",
            str(observations),
            "--assessed-at",
            (START + timedelta(days=7, hours=1)).isoformat(),
            "--queue-owner-mode",
            "direct_execution",
        ],
    )

    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert payload["ready_for_cutover"] is False
    assert payload["reason_codes"] == [
        "queue_owner_mode_not_legacy_shadow"
    ]


def test_short_or_gapped_window_is_not_continuous(tmp_path: Path) -> None:
    observations = tmp_path / "observations"
    for index, day in enumerate((0, 1, 2, 5, 6, 7)):
        _write_receipt(
            observations,
            index=index,
            observed_at=START + timedelta(days=day),
        )

    report = assess_shadow_observation_directory(
        observations,
        assessed_at=START + timedelta(days=7, hours=1),
        queue_owner_mode="legacy_queue_shadow",
        required_window=timedelta(days=7),
        max_gap=timedelta(hours=26),
    )

    assert report.ready_for_cutover is False
    assert report.reason_codes == ("observation_gap_exceeded",)
    assert report.max_observed_gap_seconds == 3 * 24 * 60 * 60
