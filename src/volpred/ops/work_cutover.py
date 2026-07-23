"""Fail-closed preflight for the Work Coordinator ownership cutover."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from typing import Any

from .work.legacy import (
    LegacySnapshotImporter,
    LegacySnapshots,
    LegacyWorkCandidate,
    ReconciliationReport,
)
from .work_projection import LegacyNextTasksProjection
from .work_shadow_assessment import (
    MAX_OBSERVATION_GAP,
    REQUIRED_OBSERVATION_WINDOW,
    ShadowObservationAssessment,
)


_SCHEMA_VERSION = "work-owner-cutover-manifest.v1"
_REQUIRED_DIMENSIONS = frozenset(
    {
        "priority",
        "claim_ownership",
        "parent",
        "deadline",
        "terminal_disposition",
    }
)


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _candidate_identity(
    candidate: LegacyWorkCandidate,
) -> dict[str, Any]:
    request = candidate.request
    return {
        "id": candidate.legacy_id,
        "status": candidate.status,
        "kind": request.kind,
        "title": request.title,
        "priority": request.priority,
        "source": request.source,
        "required_capabilities": sorted(request.required_capabilities),
        "required_attestations": sorted(request.required_attestations),
        "risk": request.risk,
        "approval": request.approval,
        "claimed_by": candidate.claimed_by,
        "claimed_at": candidate.claimed_at,
        "claim_expires_at": candidate.claim_expires_at,
        "parent_id": request.parent_id,
        "deadline": request.deadline,
        "finished_at": candidate.finished_at,
        "result_summary": candidate.result_summary,
        "blocked_reason": candidate.blocked_reason,
    }


def _next_tasks_identity(
    report: ReconciliationReport,
) -> tuple[dict[str, Any], ...]:
    return tuple(
        sorted(
            (
                _candidate_identity(candidate)
                for candidate in report.candidates
                if candidate.source_system == "next_tasks"
            ),
            key=lambda candidate: candidate["id"],
        )
    )


def _assessment_evidence_is_complete(
    assessment: ShadowObservationAssessment,
) -> bool:
    try:
        assessed_at = datetime.fromisoformat(assessment.assessed_at or "")
        recorded_from = datetime.fromisoformat(
            assessment.recorded_from or ""
        )
        recorded_through = datetime.fromisoformat(
            assessment.recorded_through or ""
        )
    except ValueError as error:
        raise ValueError(
            "shadow assessment evidence is incomplete"
        ) from error
    if any(
        value.tzinfo is None
        for value in (assessed_at, recorded_from, recorded_through)
    ):
        return False
    required_seconds = int(REQUIRED_OBSERVATION_WINDOW.total_seconds())
    max_gap_seconds = int(MAX_OBSERVATION_GAP.total_seconds())
    state_sha = assessment.queue_owner_state_sha256 or ""
    return (
        assessment.queue_owner_mode == "queued_execution"
        and assessment.queue_owner_gate_enabled is False
        and bool(assessment.queue_owner_state_path)
        and len(state_sha) == 64
        and all(character in "0123456789abcdef" for character in state_sha)
        and assessment.observation_count >= 2
        and frozenset(assessment.covered_dimensions)
        == _REQUIRED_DIMENSIONS
        and assessment.required_window_seconds == required_seconds
        and assessment.max_gap_seconds == max_gap_seconds
        and assessment.max_observed_gap_seconds is not None
        and assessment.max_observed_gap_seconds <= max_gap_seconds
        and recorded_through - recorded_from
        >= REQUIRED_OBSERVATION_WINDOW
        and recorded_through <= assessed_at
        and assessed_at - recorded_through <= MAX_OBSERVATION_GAP
    )


@dataclass(frozen=True)
class WorkOwnershipCutoverManifest:
    """Immutable identity binding for a later compare-and-set transaction."""

    schema_version: str
    legacy_row_count: int
    coordinator_row_count: int
    queue_owner_state_sha256: str
    legacy_snapshot_sha256: str
    assessment_sha256: str
    import_report_sha256: str
    projection_sha256: str
    sha256: str

    def as_dict(self) -> dict[str, str | int]:
        return {
            "schema_version": self.schema_version,
            "legacy_row_count": self.legacy_row_count,
            "coordinator_row_count": self.coordinator_row_count,
            "queue_owner_state_sha256": self.queue_owner_state_sha256,
            "legacy_snapshot_sha256": self.legacy_snapshot_sha256,
            "assessment_sha256": self.assessment_sha256,
            "import_report_sha256": self.import_report_sha256,
            "projection_sha256": self.projection_sha256,
            "sha256": self.sha256,
        }


def prepare_work_ownership_cutover(
    *,
    assessment: ShadowObservationAssessment,
    import_report: ReconciliationReport,
    projection: LegacyNextTasksProjection,
    expected_queue_owner_state_sha256: str,
    legacy_snapshot_sha256: str,
) -> WorkOwnershipCutoverManifest:
    """Bind the already-verified pre-cutover evidence without mutating state."""

    if not assessment.ready_for_cutover or assessment.reason_codes:
        raise ValueError("shadow assessment is not ready for cutover")
    if not _assessment_evidence_is_complete(assessment):
        raise ValueError("shadow assessment evidence is incomplete")
    if (
        assessment.queue_owner_state_sha256
        != expected_queue_owner_state_sha256
    ):
        raise ValueError(
            "queue owner state changed after shadow assessment"
        )
    if not import_report.ready:
        raise ValueError("legacy import is not ready for cutover")
    if (
        len(legacy_snapshot_sha256) != 64
        or any(
            character not in "0123456789abcdef"
            for character in legacy_snapshot_sha256
        )
    ):
        raise ValueError("legacy snapshot SHA-256 is invalid")
    projected_report = LegacySnapshotImporter().import_snapshot(
        LegacySnapshots(next_tasks=tuple(projection.read()))
    )
    if (
        not projected_report.ready
        or _next_tasks_identity(projected_report)
        != _next_tasks_identity(import_report)
    ):
        raise ValueError(
            "coordinator projection does not match legacy import"
        )
    assessment_sha256 = hashlib.sha256(
        _canonical_bytes(assessment.as_dict())
    ).hexdigest()
    import_report_sha256 = hashlib.sha256(
        _canonical_bytes(import_report.as_dict())
    ).hexdigest()
    legacy_row_count = import_report.source_counts["next_tasks"]["seen"]
    identity = {
        "schema_version": _SCHEMA_VERSION,
        "legacy_row_count": legacy_row_count,
        "coordinator_row_count": projection.row_count,
        "queue_owner_state_sha256": expected_queue_owner_state_sha256,
        "legacy_snapshot_sha256": legacy_snapshot_sha256,
        "assessment_sha256": assessment_sha256,
        "import_report_sha256": import_report_sha256,
        "projection_sha256": projection.sha256,
    }
    return WorkOwnershipCutoverManifest(
        **identity,
        sha256=hashlib.sha256(_canonical_bytes(identity)).hexdigest(),
    )


__all__ = [
    "WorkOwnershipCutoverManifest",
    "prepare_work_ownership_cutover",
]
