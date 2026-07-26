from __future__ import annotations

import hashlib
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
    schema_version: str = "work-shadow-replay.v4",
    queue_owner_mode: str = "queued_execution",
    queue_owner_gate_enabled: bool = False,
    queue_owner_state_path: str = "/repo/storage/ops/task_pool_mode.json",
    queue_owner_state_sha256: str = "a" * 64,
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    snapshot_sha = f"{index + 1:064x}"
    receipt = {
        "schema_version": schema_version,
        "observation_id": f"scheduled_{index:02d}",
        "observed_at": observed_at.isoformat(),
        "recorded_at": observed_at.isoformat(),
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
    if schema_version == "work-shadow-replay.v4":
        receipt["queue_owner_evidence"] = {
            "schema_version": "task-pool-owner-evidence.v1",
            "mode": queue_owner_mode,
            "gate_enabled": queue_owner_gate_enabled,
            "state_path": queue_owner_state_path,
            "state_sha256": queue_owner_state_sha256,
            "state_byte_count": 64,
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
        queue_owner_mode="queued_execution",
        required_window=timedelta(days=7),
        max_gap=timedelta(hours=26),
    )

    assert report.ready_for_cutover is True
    assert report.reason_codes == ()
    assert report.observation_count == 8
    assert report.covered_dimensions == REQUIRED_DIMENSIONS


def test_only_receipts_bound_to_current_owner_state_count_toward_window(
    tmp_path: Path,
) -> None:
    observations = tmp_path / "observations"
    for index in range(8):
        _write_receipt(
            observations,
            index=index,
            observed_at=START + timedelta(days=index),
            queue_owner_mode="direct_execution",
            queue_owner_gate_enabled=True,
            queue_owner_state_sha256="d" * 64,
        )
    _write_receipt(
        observations,
        index=8,
        observed_at=START + timedelta(days=8),
        queue_owner_state_sha256="b" * 64,
    )

    report = assess_shadow_observation_directory(
        observations,
        assessed_at=START + timedelta(days=8, hours=1),
        queue_owner_mode="queued_execution",
        queue_owner_gate_enabled=False,
        queue_owner_state_path="/repo/storage/ops/task_pool_mode.json",
        queue_owner_state_sha256="b" * 64,
        required_window=timedelta(days=7),
        max_gap=timedelta(hours=26),
    )

    assert report.ready_for_cutover is False
    assert report.observation_count == 1
    assert report.recorded_from == (START + timedelta(days=8)).isoformat()
    assert report.reason_codes == ("observation_window_too_short",)


def test_pre_owner_evidence_receipts_do_not_poison_new_window(
    tmp_path: Path,
) -> None:
    observations = tmp_path / "observations"
    _write_receipt(
        observations,
        index=0,
        observed_at=START - timedelta(days=1),
        schema_version="work-shadow-replay.v3",
    )
    for index in range(1, 9):
        _write_receipt(
            observations,
            index=index,
            observed_at=START + timedelta(days=index - 1),
            queue_owner_state_sha256="b" * 64,
        )

    report = assess_shadow_observation_directory(
        observations,
        assessed_at=START + timedelta(days=7, hours=1),
        queue_owner_mode="queued_execution",
        queue_owner_gate_enabled=False,
        queue_owner_state_path="/repo/storage/ops/task_pool_mode.json",
        queue_owner_state_sha256="b" * 64,
        required_window=timedelta(days=7),
        max_gap=timedelta(hours=26),
    )

    assert report.ready_for_cutover is True
    assert report.observation_count == 8


def test_malformed_receipt_fails_closed_instead_of_crashing(tmp_path: Path) -> None:
    observations = tmp_path / "observations"
    observations.mkdir()
    (observations / "broken.json").write_text("{not-json", encoding="utf-8")

    report = assess_shadow_observation_directory(
        observations,
        assessed_at=START,
        queue_owner_mode="queued_execution",
        required_window=timedelta(days=7),
        max_gap=timedelta(hours=26),
    )

    assert report.ready_for_cutover is False
    assert report.reason_codes == ("invalid_receipt",)
    assert report.observation_count == 1


def test_v4_receipt_without_owner_evidence_fails_closed(
    tmp_path: Path,
) -> None:
    observations = tmp_path / "observations"
    _write_receipt(observations, index=0, observed_at=START)
    receipt_path = observations / "scheduled_00.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    del receipt["queue_owner_evidence"]
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    report = assess_shadow_observation_directory(
        observations,
        assessed_at=START,
        queue_owner_mode="queued_execution",
        required_window=timedelta(days=7),
        max_gap=timedelta(hours=26),
    )

    assert report.ready_for_cutover is False
    assert report.reason_codes == ("invalid_receipt",)


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
        queue_owner_mode="queued_execution",
        required_window=timedelta(days=7),
        max_gap=timedelta(hours=26),
    )

    assert report.ready_for_cutover is False
    assert report.reason_codes == (
        "selection_evidence_mismatch",
        "blocking_selection_difference",
    )


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
        queue_owner_mode="queued_execution",
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
        queue_owner_mode="queued_execution",
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
        queue_owner_mode="queued_execution",
        required_window=timedelta(days=7),
        max_gap=timedelta(hours=26),
    )

    assert report.ready_for_cutover is False
    assert report.reason_codes == ("duplicate_observation_id",)


def test_work_shadow_assess_cli_emits_machine_verdict(
    tmp_path: Path,
    monkeypatch,
) -> None:
    observations = tmp_path / "observations"
    mode_state = tmp_path / "storage" / "ops" / "task_pool_mode.json"
    mode_state.parent.mkdir(parents=True)
    mode_state.write_text(
        json.dumps({"enabled": False, "mode": "queued_execution"}),
        encoding="utf-8",
    )
    mode_bytes = mode_state.read_bytes()
    for index in range(8):
        _write_receipt(
            observations,
            index=index,
            observed_at=START + timedelta(days=index),
            queue_owner_state_path=str(mode_state.resolve()),
            queue_owner_state_sha256=hashlib.sha256(mode_bytes).hexdigest(),
        )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("volpred.ops.common.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        "volpred.cli._work_shadow_assessment_time",
        lambda: START + timedelta(days=7, hours=1),
        raising=False,
    )

    result = CliRunner().invoke(
        cli,
        [
            "ops",
            "work-shadow-assess",
            "--observation-dir",
            str(observations),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema_version"] == "work-shadow-assessment.v1"
    assert payload["ready_for_cutover"] is True
    assert payload["reason_codes"] == []
    assert payload["observation_count"] == 8
    assert payload["queue_owner_mode"] == "queued_execution"
    assert payload["queue_owner_state_sha256"]

    help_result = CliRunner().invoke(
        cli,
        ["ops", "work-shadow-assess", "--help"],
    )
    assert help_result.exit_code == 0
    assert "--assessed-at" not in help_result.output
    assert "--required-days" not in help_result.output
    assert "--max-gap-hours" not in help_result.output
    assert "--queue-owner-mode" not in help_result.output


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
        queue_owner_mode="queued_execution",
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
        queue_owner_mode="queued_execution",
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
        queue_owner_mode="queued_execution",
        required_window=timedelta(days=7),
        max_gap=timedelta(hours=26),
    )

    assert report.ready_for_cutover is False
    assert report.reason_codes == ("invalid_receipt",)


def test_direct_execution_mode_cannot_reuse_queue_shadow_evidence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    observations = tmp_path / "observations"
    for index in range(8):
        _write_receipt(
            observations,
            index=index,
            observed_at=START + timedelta(days=index),
        )
    mode_state = tmp_path / "storage" / "ops" / "task_pool_mode.json"
    mode_state.parent.mkdir(parents=True)
    mode_state.write_text(
        json.dumps({"enabled": True, "mode": "direct_execution"}),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("volpred.ops.common.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        "volpred.cli._work_shadow_assessment_time",
        lambda: START + timedelta(days=7, hours=1),
        raising=False,
    )

    result = CliRunner().invoke(
        cli,
        [
            "ops",
            "work-shadow-assess",
            "--observation-dir",
            str(observations),
        ],
    )

    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert payload["ready_for_cutover"] is False
    assert payload["reason_codes"] == [
        "queue_owner_mode_not_queued_execution",
        "no_observations",
        "missing_reconciliation_dimension",
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
        queue_owner_mode="queued_execution",
        required_window=timedelta(days=7),
        max_gap=timedelta(hours=26),
    )

    assert report.ready_for_cutover is False
    assert report.reason_codes == ("observation_gap_exceeded",)
    assert report.max_observed_gap_seconds == 3 * 24 * 60 * 60


def test_future_observations_fail_closed(tmp_path: Path) -> None:
    observations = tmp_path / "observations"
    for index in range(8):
        _write_receipt(
            observations,
            index=index,
            observed_at=START + timedelta(days=index),
        )

    report = assess_shadow_observation_directory(
        observations,
        assessed_at=START - timedelta(seconds=1),
        queue_owner_mode="queued_execution",
        required_window=timedelta(days=7),
        max_gap=timedelta(hours=26),
    )

    assert report.ready_for_cutover is False
    assert report.reason_codes == ("observation_in_future",)


def test_each_receipt_must_reconcile_its_own_queue_row_count(
    tmp_path: Path,
) -> None:
    observations = tmp_path / "observations"
    for index in range(8):
        _write_receipt(
            observations,
            index=index,
            observed_at=START + timedelta(days=index),
        )
    incomplete_path = observations / "scheduled_03.json"
    incomplete = json.loads(incomplete_path.read_text(encoding="utf-8"))
    incomplete["comparisons"] = []
    incomplete_path.write_text(json.dumps(incomplete), encoding="utf-8")

    report = assess_shadow_observation_directory(
        observations,
        assessed_at=START + timedelta(days=7, hours=1),
        queue_owner_mode="queued_execution",
        required_window=timedelta(days=7),
        max_gap=timedelta(hours=26),
    )

    assert report.ready_for_cutover is False
    assert report.reason_codes == (
        "receipt_row_count_mismatch",
        "selection_evidence_mismatch",
    )


def test_each_candidate_must_carry_every_required_dimension(
    tmp_path: Path,
) -> None:
    observations = tmp_path / "observations"
    for index in range(8):
        _write_receipt(
            observations,
            index=index,
            observed_at=START + timedelta(days=index),
        )
    incomplete_path = observations / "scheduled_03.json"
    incomplete = json.loads(incomplete_path.read_text(encoding="utf-8"))
    incomplete["comparisons"][0]["dimensions"].pop()
    incomplete_path.write_text(json.dumps(incomplete), encoding="utf-8")

    report = assess_shadow_observation_directory(
        observations,
        assessed_at=START + timedelta(days=7, hours=1),
        queue_owner_mode="queued_execution",
        required_window=timedelta(days=7),
        max_gap=timedelta(hours=26),
    )

    assert report.ready_for_cutover is False
    assert report.reason_codes == ("candidate_dimension_incomplete",)


def test_unregistered_policy_change_cannot_whitelist_a_difference(
    tmp_path: Path,
) -> None:
    observations = tmp_path / "observations"
    for index in range(8):
        _write_receipt(
            observations,
            index=index,
            observed_at=START + timedelta(days=index),
        )
    forged_path = observations / "scheduled_04.json"
    forged = json.loads(forged_path.read_text(encoding="utf-8"))
    claim_dimension = forged["comparisons"][0]["dimensions"][1]
    claim_dimension["matches"] = False
    claim_dimension["classification"] = "policy_change"
    claim_dimension["classification_reason_code"] = "invented_policy"
    claim_dimension["evidence_refs"] = ["contract://invented"]
    forged_path.write_text(json.dumps(forged), encoding="utf-8")

    report = assess_shadow_observation_directory(
        observations,
        assessed_at=START + timedelta(days=7, hours=1),
        queue_owner_mode="queued_execution",
        required_window=timedelta(days=7),
        max_gap=timedelta(hours=26),
    )

    assert report.ready_for_cutover is False
    assert report.reason_codes == ("unregistered_policy_change",)


def test_registered_policy_change_with_evidence_is_explained(
    tmp_path: Path,
) -> None:
    observations = tmp_path / "observations"
    for index in range(8):
        _write_receipt(
            observations,
            index=index,
            observed_at=START + timedelta(days=index),
        )
    explained_path = observations / "scheduled_04.json"
    explained = json.loads(explained_path.read_text(encoding="utf-8"))
    claim_dimension = explained["comparisons"][0]["dimensions"][1]
    claim_dimension["matches"] = False
    claim_dimension["classification"] = "policy_change"
    claim_dimension["classification_reason_code"] = (
        "coordinator_inline_lease_contract"
    )
    claim_dimension["legacy_reason_codes"] = ["eligible"]
    claim_dimension["coordinator_reason_codes"] = ["live_claim"]
    claim_dimension["evidence_refs"] = [
        "next_tasks:task-1#claim_ownership",
        "contract://work-selection/claim-ownership",
        (
            "snapshot://sha256/"
            f"{explained['snapshot']['sha256']}"
        ),
        (
            "oracle://work-selection/"
            "coordinator_inline_lease_contract"
        ),
    ]
    explained_path.write_text(json.dumps(explained), encoding="utf-8")

    report = assess_shadow_observation_directory(
        observations,
        assessed_at=START + timedelta(days=7, hours=1),
        queue_owner_mode="queued_execution",
        required_window=timedelta(days=7),
        max_gap=timedelta(hours=26),
    )

    assert report.ready_for_cutover is True
    assert report.reason_codes == ()


def test_registered_label_without_oracle_prerequisites_is_not_explained(
    tmp_path: Path,
) -> None:
    observations = tmp_path / "observations"
    for index in range(8):
        _write_receipt(
            observations,
            index=index,
            observed_at=START + timedelta(days=index),
        )
    mislabeled_path = observations / "scheduled_04.json"
    mislabeled = json.loads(mislabeled_path.read_text(encoding="utf-8"))
    claim_dimension = mislabeled["comparisons"][0]["dimensions"][1]
    claim_dimension["matches"] = False
    claim_dimension["classification"] = "policy_change"
    claim_dimension["classification_reason_code"] = (
        "coordinator_inline_lease_contract"
    )
    claim_dimension["evidence_refs"] = [
        "contract://work-selection/claim-ownership"
    ]
    mislabeled_path.write_text(json.dumps(mislabeled), encoding="utf-8")

    report = assess_shadow_observation_directory(
        observations,
        assessed_at=START + timedelta(days=7, hours=1),
        queue_owner_mode="queued_execution",
        required_window=timedelta(days=7),
        max_gap=timedelta(hours=26),
    )

    assert report.ready_for_cutover is False
    assert report.reason_codes == ("unregistered_policy_change",)


def test_duplicate_candidate_identity_blocks_row_reconciliation(
    tmp_path: Path,
) -> None:
    observations = tmp_path / "observations"
    for index in range(8):
        _write_receipt(
            observations,
            index=index,
            observed_at=START + timedelta(days=index),
        )
    duplicate_path = observations / "scheduled_05.json"
    duplicate = json.loads(duplicate_path.read_text(encoding="utf-8"))
    duplicate["snapshot"]["source_counts"]["next_tasks"] = 2
    duplicate["comparisons"].append(duplicate["comparisons"][0])
    duplicate_path.write_text(json.dumps(duplicate), encoding="utf-8")

    report = assess_shadow_observation_directory(
        observations,
        assessed_at=START + timedelta(days=7, hours=1),
        queue_owner_mode="queued_execution",
        required_window=timedelta(days=7),
        max_gap=timedelta(hours=26),
    )

    assert report.ready_for_cutover is False
    assert report.reason_codes == ("duplicate_candidate_identity",)


def test_backdated_replay_clock_cannot_fake_seven_recorded_days(
    tmp_path: Path,
) -> None:
    observations = tmp_path / "observations"
    recorded_start = START + timedelta(days=7)
    for index in range(8):
        _write_receipt(
            observations,
            index=index,
            observed_at=START + timedelta(days=index),
        )
        path = observations / f"scheduled_{index:02d}.json"
        receipt = json.loads(path.read_text(encoding="utf-8"))
        receipt["schema_version"] = "work-shadow-replay.v4"
        receipt["recorded_at"] = (
            recorded_start + timedelta(seconds=index)
        ).isoformat()
        path.write_text(json.dumps(receipt), encoding="utf-8")

    report = assess_shadow_observation_directory(
        observations,
        assessed_at=recorded_start + timedelta(minutes=1),
        queue_owner_mode="queued_execution",
        required_window=timedelta(days=7),
        max_gap=timedelta(hours=26),
    )

    assert report.ready_for_cutover is False
    assert report.reason_codes == (
        "observation_window_too_short",
        "replay_clock_not_live",
    )


def test_selection_difference_must_match_selector_views(
    tmp_path: Path,
) -> None:
    observations = tmp_path / "observations"
    for index in range(8):
        _write_receipt(
            observations,
            index=index,
            observed_at=START + timedelta(days=index),
        )
    forged_path = observations / "scheduled_04.json"
    forged = json.loads(forged_path.read_text(encoding="utf-8"))
    snapshot_sha = forged["snapshot"]["sha256"]
    forged["selection_difference"] = {
        "legacy_selected_candidate_ref": "ghost:A",
        "coordinator_selected_candidate_ref": "ghost:B",
        "classification": "policy_change",
        "classification_reason_code": "coordinator_ranking_contract",
        "evidence_refs": [
            "contract://work-selection/selection-outcome",
            "contract://work-selection/priority",
            f"snapshot://sha256/{snapshot_sha}",
            (
                "oracle://work-selection/"
                "coordinator_ranking_contract"
            ),
        ],
    }
    forged_path.write_text(json.dumps(forged), encoding="utf-8")

    report = assess_shadow_observation_directory(
        observations,
        assessed_at=START + timedelta(days=7, hours=1),
        queue_owner_mode="queued_execution",
        required_window=timedelta(days=7),
        max_gap=timedelta(hours=26),
    )

    assert report.ready_for_cutover is False
    assert report.reason_codes == ("selection_evidence_mismatch",)


def test_changed_selector_views_require_a_difference_receipt(
    tmp_path: Path,
) -> None:
    observations = tmp_path / "observations"
    for index in range(8):
        _write_receipt(
            observations,
            index=index,
            observed_at=START + timedelta(days=index),
        )
    missing_path = observations / "scheduled_04.json"
    missing = json.loads(missing_path.read_text(encoding="utf-8"))
    missing["coordinator_selection"]["selected_candidate_ref"] = None
    missing["coordinator_selection"]["eligible_candidate_refs"] = []
    missing_path.write_text(json.dumps(missing), encoding="utf-8")

    report = assess_shadow_observation_directory(
        observations,
        assessed_at=START + timedelta(days=7, hours=1),
        queue_owner_mode="queued_execution",
        required_window=timedelta(days=7),
        max_gap=timedelta(hours=26),
    )

    assert report.ready_for_cutover is False
    assert report.reason_codes == ("selection_evidence_mismatch",)


def test_winner_change_cannot_borrow_unrelated_candidate_policy(
    tmp_path: Path,
) -> None:
    observations = tmp_path / "observations"
    for index in range(8):
        _write_receipt(
            observations,
            index=index,
            observed_at=START + timedelta(days=index),
        )
    borrowed_path = observations / "scheduled_04.json"
    borrowed = json.loads(borrowed_path.read_text(encoding="utf-8"))
    snapshot_sha = borrowed["snapshot"]["sha256"]
    original = borrowed["comparisons"][0]
    second = json.loads(json.dumps(original))
    second["candidate_ref"] = "next_tasks:task-2"
    third = json.loads(json.dumps(original))
    third["candidate_ref"] = "next_tasks:task-3"
    claim_dimension = third["dimensions"][1]
    claim_dimension["matches"] = False
    claim_dimension["classification"] = "policy_change"
    claim_dimension["classification_reason_code"] = (
        "coordinator_inline_lease_contract"
    )
    claim_dimension["legacy_reason_codes"] = ["eligible"]
    claim_dimension["coordinator_reason_codes"] = ["live_claim"]
    claim_dimension["evidence_refs"] = [
        "next_tasks:task-3#claim_ownership",
        "contract://work-selection/claim-ownership",
        f"snapshot://sha256/{snapshot_sha}",
        (
            "oracle://work-selection/"
            "coordinator_inline_lease_contract"
        ),
    ]
    borrowed["snapshot"]["source_counts"]["next_tasks"] = 3
    borrowed["comparisons"] = [original, second, third]
    borrowed["legacy_selection"]["eligible_candidate_refs"] = [
        "next_tasks:task-1",
        "next_tasks:task-2",
        "next_tasks:task-3",
    ]
    borrowed["coordinator_selection"]["selected_candidate_ref"] = (
        "next_tasks:task-2"
    )
    borrowed["coordinator_selection"]["eligible_candidate_refs"] = [
        "next_tasks:task-1",
        "next_tasks:task-2",
        "next_tasks:task-3",
    ]
    borrowed["selection_difference"] = {
        "legacy_selected_candidate_ref": "next_tasks:task-1",
        "coordinator_selected_candidate_ref": "next_tasks:task-2",
        "classification": "policy_change",
        "classification_reason_code": (
            "coordinator_inline_lease_contract"
        ),
        "evidence_refs": [
            "contract://work-selection/selection-outcome",
            *claim_dimension["evidence_refs"],
        ],
    }
    borrowed_path.write_text(json.dumps(borrowed), encoding="utf-8")

    report = assess_shadow_observation_directory(
        observations,
        assessed_at=START + timedelta(days=7, hours=1),
        queue_owner_mode="queued_execution",
        required_window=timedelta(days=7),
        max_gap=timedelta(hours=26),
    )

    assert report.ready_for_cutover is False
    assert report.reason_codes == ("unregistered_policy_change",)


def test_selection_views_must_match_comparison_eligibility(
    tmp_path: Path,
) -> None:
    observations = tmp_path / "observations"
    for index in range(8):
        _write_receipt(
            observations,
            index=index,
            observed_at=START + timedelta(days=index),
        )
    inconsistent_path = observations / "scheduled_04.json"
    inconsistent = json.loads(
        inconsistent_path.read_text(encoding="utf-8")
    )
    comparison = inconsistent["comparisons"][0]
    comparison["legacy_eligible"] = False
    comparison["coordinator_eligible"] = False
    inconsistent_path.write_text(
        json.dumps(inconsistent),
        encoding="utf-8",
    )

    report = assess_shadow_observation_directory(
        observations,
        assessed_at=START + timedelta(days=7, hours=1),
        queue_owner_mode="queued_execution",
        required_window=timedelta(days=7),
        max_gap=timedelta(hours=26),
    )

    assert report.ready_for_cutover is False
    assert report.reason_codes == ("selection_evidence_mismatch",)
