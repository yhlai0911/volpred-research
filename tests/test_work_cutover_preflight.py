from dataclasses import replace

import pytest

from volpred.ops.work import WorkItemView, WorkSnapshot
from volpred.ops.work.legacy import LegacySnapshots
from volpred.ops.work_cutover import prepare_work_ownership_cutover
from volpred.ops.work_migration import preview_legacy_snapshots
from volpred.ops.work_projection import project_legacy_next_tasks
from volpred.ops.work_shadow_assessment import ShadowObservationAssessment


OWNER_STATE_SHA256 = "a" * 64
LEGACY_SNAPSHOT_SHA256 = "c" * 64


def _ready_assessment() -> ShadowObservationAssessment:
    return ShadowObservationAssessment(
        ready_for_cutover=True,
        reason_codes=(),
        observation_count=8,
        covered_dimensions=(
            "priority",
            "claim_ownership",
            "parent",
            "deadline",
            "terminal_disposition",
        ),
        assessed_at="2026-07-23T13:00:00+00:00",
        queue_owner_mode="queued_execution",
        queue_owner_gate_enabled=False,
        queue_owner_state_path="/repo/storage/ops/task_pool_mode.json",
        queue_owner_state_sha256=OWNER_STATE_SHA256,
        observed_from="2026-07-16T12:00:00+00:00",
        observed_through="2026-07-23T12:00:00+00:00",
        recorded_from="2026-07-16T12:00:00+00:00",
        recorded_through="2026-07-23T12:00:00+00:00",
        required_window_seconds=7 * 24 * 60 * 60,
        max_gap_seconds=26 * 60 * 60,
        max_observed_gap_seconds=24 * 60 * 60,
    )


def _legacy_row() -> dict[str, object]:
    return {
        "id": "task-1",
        "status": "pending",
        "task_type": "platform_ops",
        "title": "Cut over the queue owner",
        "priority": 1,
        "source": "user",
        "created_at": "2026-07-16T12:00:00+00:00",
        "updated_at": "2026-07-16T12:00:00+00:00",
        "required_capabilities": ["code"],
        "required_attestations": [],
        "risk": "safe",
        "approval": "auto",
    }


def _staged_snapshot() -> WorkSnapshot:
    return WorkSnapshot(
        items=(
            WorkItemView(
                id="task-1",
                idempotency_key="legacy:next_tasks:task-1",
                source="user",
                kind="platform_ops",
                title="Cut over the queue owner",
                priority=1,
                required_capabilities=frozenset({"code"}),
                required_attestations=frozenset(),
                risk="safe",
                approval="auto",
                payload_ref="legacy:next_tasks:task-1",
                status="pending",
                version=1,
                created_at="2026-07-16T12:00:00+00:00",
                updated_at="2026-07-16T12:00:00+00:00",
            ),
        )
    )


def test_preflight_binds_clean_soak_owner_cas_and_projection_identity() -> None:
    import_report = preview_legacy_snapshots(
        LegacySnapshots(next_tasks=(_legacy_row(),))
    )
    projection = project_legacy_next_tasks(_staged_snapshot())

    manifest = prepare_work_ownership_cutover(
        assessment=_ready_assessment(),
        import_report=import_report,
        projection=projection,
        expected_queue_owner_state_sha256=OWNER_STATE_SHA256,
        legacy_snapshot_sha256=LEGACY_SNAPSHOT_SHA256,
    )

    assert manifest.schema_version == "work-owner-cutover-manifest.v1"
    assert manifest.legacy_row_count == 1
    assert manifest.coordinator_row_count == 1
    assert manifest.queue_owner_state_sha256 == OWNER_STATE_SHA256
    assert manifest.legacy_snapshot_sha256 == LEGACY_SNAPSHOT_SHA256
    assert manifest.projection_sha256 == projection.sha256
    assert len(manifest.sha256) == 64


def test_preflight_rejects_an_assessment_that_is_not_ready() -> None:
    assessment = replace(
        _ready_assessment(),
        ready_for_cutover=False,
        reason_codes=("observation_window_too_short",),
    )

    with pytest.raises(
        ValueError,
        match="shadow assessment is not ready for cutover",
    ):
        prepare_work_ownership_cutover(
            assessment=assessment,
            import_report=preview_legacy_snapshots(
                LegacySnapshots(next_tasks=(_legacy_row(),))
            ),
            projection=project_legacy_next_tasks(_staged_snapshot()),
            expected_queue_owner_state_sha256=OWNER_STATE_SHA256,
            legacy_snapshot_sha256=LEGACY_SNAPSHOT_SHA256,
        )


def test_preflight_rejects_owner_state_that_changed_after_assessment() -> None:
    with pytest.raises(
        ValueError,
        match="queue owner state changed after shadow assessment",
    ):
        prepare_work_ownership_cutover(
            assessment=_ready_assessment(),
            import_report=preview_legacy_snapshots(
                LegacySnapshots(next_tasks=(_legacy_row(),))
            ),
            projection=project_legacy_next_tasks(_staged_snapshot()),
            expected_queue_owner_state_sha256="b" * 64,
            legacy_snapshot_sha256=LEGACY_SNAPSHOT_SHA256,
        )


def test_preflight_rejects_an_import_report_with_reconciliation_issues() -> None:
    malformed = _legacy_row()
    malformed["source"] = "unknown-producer"

    with pytest.raises(
        ValueError,
        match="legacy import is not ready for cutover",
    ):
        prepare_work_ownership_cutover(
            assessment=_ready_assessment(),
            import_report=preview_legacy_snapshots(
                LegacySnapshots(next_tasks=(malformed,))
            ),
            projection=project_legacy_next_tasks(_staged_snapshot()),
            expected_queue_owner_state_sha256=OWNER_STATE_SHA256,
            legacy_snapshot_sha256=LEGACY_SNAPSHOT_SHA256,
        )


def test_preflight_rejects_projection_dimension_drift() -> None:
    staged = _staged_snapshot()
    staged = WorkSnapshot(
        items=(replace(staged.items[0], priority=2),),
    )

    with pytest.raises(
        ValueError,
        match="coordinator projection does not match legacy import",
    ):
        prepare_work_ownership_cutover(
            assessment=_ready_assessment(),
            import_report=preview_legacy_snapshots(
                LegacySnapshots(next_tasks=(_legacy_row(),))
            ),
            projection=project_legacy_next_tasks(staged),
            expected_queue_owner_state_sha256=OWNER_STATE_SHA256,
            legacy_snapshot_sha256=LEGACY_SNAPSHOT_SHA256,
        )


def test_preflight_revalidates_the_fixed_seven_day_evidence_contract() -> None:
    forged = replace(
        _ready_assessment(),
        observation_count=1,
        recorded_through="2026-07-16T13:00:00+00:00",
        required_window_seconds=60 * 60,
    )

    with pytest.raises(
        ValueError,
        match="shadow assessment evidence is incomplete",
    ):
        prepare_work_ownership_cutover(
            assessment=forged,
            import_report=preview_legacy_snapshots(
                LegacySnapshots(next_tasks=(_legacy_row(),))
            ),
            projection=project_legacy_next_tasks(_staged_snapshot()),
            expected_queue_owner_state_sha256=OWNER_STATE_SHA256,
            legacy_snapshot_sha256=LEGACY_SNAPSHOT_SHA256,
        )


def test_preflight_rejects_timezone_naive_assessment_timestamps() -> None:
    naive = replace(
        _ready_assessment(),
        assessed_at="2026-07-23T13:00:00",
        recorded_from="2026-07-16T12:00:00",
        recorded_through="2026-07-23T12:00:00",
    )

    with pytest.raises(
        ValueError,
        match="shadow assessment evidence is incomplete",
    ):
        prepare_work_ownership_cutover(
            assessment=naive,
            import_report=preview_legacy_snapshots(
                LegacySnapshots(next_tasks=(_legacy_row(),))
            ),
            projection=project_legacy_next_tasks(_staged_snapshot()),
            expected_queue_owner_state_sha256=OWNER_STATE_SHA256,
            legacy_snapshot_sha256=LEGACY_SNAPSHOT_SHA256,
        )
