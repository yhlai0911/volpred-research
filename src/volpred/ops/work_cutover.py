"""Fail-closed preflight for the Work Coordinator ownership cutover."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
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
    assess_shadow_observation_directory,
)
from .task_pool_mode import load_task_pool_mode_evidence


_SCHEMA_VERSION = "work-owner-cutover-manifest.v1"


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _candidate_identity(
    candidate: LegacyWorkCandidate,
) -> dict[str, Any]:
    request = candidate.request
    return {
        "id": candidate.legacy_id,
        "status": candidate.status,
        "created_at": candidate.created_at,
        "updated_at": candidate.updated_at,
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
        "started_at": candidate.started_at,
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


def _decode_next_tasks(payload: bytes) -> tuple[dict[str, Any], ...]:
    try:
        decoded = json.loads(payload)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("raw legacy snapshot is not valid JSON") from error
    if not isinstance(decoded, list) or not all(
        isinstance(row, dict) for row in decoded
    ):
        raise ValueError(
            "raw legacy snapshot must be an array of objects"
        )
    return tuple(decoded)


def _cutover_time() -> datetime:
    return datetime.now(timezone.utc)


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
    observation_directory: Path,
    queue_owner_state_path: Path,
    legacy_next_tasks_bytes: bytes,
    legacy_snapshots: LegacySnapshots,
    projection: LegacyNextTasksProjection,
) -> WorkOwnershipCutoverManifest:
    """Derive a cutover identity from raw evidence without mutating state."""

    owner = load_task_pool_mode_evidence(queue_owner_state_path)
    assessment = assess_shadow_observation_directory(
        observation_directory,
        assessed_at=_cutover_time(),
        queue_owner_mode=owner.mode.mode,
        queue_owner_gate_enabled=owner.mode.enabled,
        queue_owner_state_path=owner.state_path,
        queue_owner_state_sha256=owner.sha256,
        required_window=REQUIRED_OBSERVATION_WINDOW,
        max_gap=MAX_OBSERVATION_GAP,
    )
    if not assessment.ready_for_cutover:
        raise ValueError("shadow assessment is not ready for cutover")
    raw_next_tasks = _decode_next_tasks(legacy_next_tasks_bytes)
    if raw_next_tasks != legacy_snapshots.next_tasks:
        raise ValueError(
            "raw legacy snapshot does not match supplied snapshots"
        )
    import_report = LegacySnapshotImporter().import_snapshot(
        legacy_snapshots
    )
    if not import_report.ready:
        raise ValueError("legacy import is not ready for cutover")
    projection_rows = projection.read()
    projection_payload = _canonical_bytes(projection_rows)
    projection_sha256 = _sha256(projection_payload)
    if (
        projection.row_count != len(projection_rows)
        or projection.sha256 != projection_sha256
    ):
        raise ValueError(
            "coordinator projection metadata does not match payload"
        )
    projected_report = LegacySnapshotImporter().import_snapshot(
        LegacySnapshots(next_tasks=tuple(projection_rows))
    )
    if (
        not projected_report.ready
        or _next_tasks_identity(projected_report)
        != _next_tasks_identity(import_report)
    ):
        raise ValueError(
            "coordinator projection does not match legacy import"
        )
    assessment_sha256 = _sha256(_canonical_bytes(assessment.as_dict()))
    import_report_sha256 = _sha256(
        _canonical_bytes(import_report.as_dict())
    )
    legacy_row_count = import_report.source_counts["next_tasks"]["seen"]
    identity = {
        "schema_version": _SCHEMA_VERSION,
        "legacy_row_count": legacy_row_count,
        "coordinator_row_count": projection.row_count,
        "queue_owner_state_sha256": owner.sha256,
        "legacy_snapshot_sha256": _sha256(legacy_next_tasks_bytes),
        "assessment_sha256": assessment_sha256,
        "import_report_sha256": import_report_sha256,
        "projection_sha256": projection_sha256,
    }
    return WorkOwnershipCutoverManifest(
        **identity,
        sha256=_sha256(_canonical_bytes(identity)),
    )


__all__ = [
    "WorkOwnershipCutoverManifest",
    "prepare_work_ownership_cutover",
]
