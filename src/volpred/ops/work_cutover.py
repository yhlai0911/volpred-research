"""Fail-closed preflight for the Work Coordinator ownership cutover."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import fcntl
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
from .work_projection import (
    NEXT_TASKS_PROJECTION_SCHEMA_VERSION,
    LegacyNextTasksProjection,
)
from .work_shadow_assessment import (
    MAX_OBSERVATION_GAP,
    REQUIRED_OBSERVATION_WINDOW,
    assess_shadow_observation_directory,
)
from .work_shadow_replay import (
    freeze_legacy_snapshots,
    identify_legacy_snapshots,
)
from .task_pool_mode import (
    load_task_pool_mode_evidence,
    task_pool_mode_path,
)


_SCHEMA_VERSION = "work-owner-cutover-manifest.v3"
_MANIFEST_TTL = timedelta(minutes=15)


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
        "created_at_observed_not_after": (
            candidate.created_at_observed_not_after
        ),
        "creation_sort_time": candidate.creation_sort_time,
        "updated_at": candidate.updated_at,
        "kind": request.kind,
        "title": request.title,
        "priority": request.priority,
        "source": request.source,
        "legacy_source": candidate.legacy_source,
        "source_classification": candidate.source_classification,
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
        "dispatch_lane": candidate.dispatch_lane,
        "preferred_agent": candidate.preferred_agent,
        "target_agent": candidate.target_agent,
        "fallback_allowed": candidate.fallback_allowed,
        "ref_event_job_id": candidate.ref_event_job_id,
        "dreaming": candidate.dreaming,
        "requester_ref": request.requester_ref,
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


def _active_next_task_leases(
    report: ReconciliationReport,
) -> tuple[str, ...]:
    return tuple(
        sorted(
            candidate.legacy_id
            for candidate in report.candidates
            if candidate.source_system == "next_tasks"
            and candidate.status in {"claimed", "running"}
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


def _canonical_queue_path() -> Path:
    return Path(__file__).resolve().parents[3] / "storage" / "next_tasks.json"


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
    projection_schema_version: str
    projection_sha256: str
    prepared_at: str
    valid_until: str
    sha256: str

    def identity_dict(self) -> dict[str, str | int]:
        return {
            "schema_version": self.schema_version,
            "legacy_row_count": self.legacy_row_count,
            "coordinator_row_count": self.coordinator_row_count,
            "queue_owner_state_sha256": self.queue_owner_state_sha256,
            "legacy_snapshot_sha256": self.legacy_snapshot_sha256,
            "assessment_sha256": self.assessment_sha256,
            "import_report_sha256": self.import_report_sha256,
            "projection_schema_version": self.projection_schema_version,
            "projection_sha256": self.projection_sha256,
            "prepared_at": self.prepared_at,
            "valid_until": self.valid_until,
        }

    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.identity_dict())

    def as_dict(self) -> dict[str, str | int]:
        return {**self.identity_dict(), "sha256": self.sha256}


def prepare_work_ownership_cutover(
    *,
    observation_directory: Path,
    legacy_snapshots: LegacySnapshots,
    projection: LegacyNextTasksProjection,
) -> WorkOwnershipCutoverManifest:
    """Derive a cutover identity from raw evidence without mutating state."""

    immutable_snapshots = freeze_legacy_snapshots(legacy_snapshots)
    cutover_at = _cutover_time()
    queue_path = _canonical_queue_path().resolve()
    state_path = task_pool_mode_path(queue_path)
    with queue_path.open("rb") as queue_handle:
        fcntl.flock(queue_handle.fileno(), fcntl.LOCK_SH)
        try:
            legacy_next_tasks_bytes = queue_handle.read()
            owner = load_task_pool_mode_evidence(state_path)
            assessment = assess_shadow_observation_directory(
                observation_directory,
                assessed_at=cutover_at,
                queue_owner=owner,
                required_window=REQUIRED_OBSERVATION_WINDOW,
                max_gap=MAX_OBSERVATION_GAP,
            )
        finally:
            fcntl.flock(queue_handle.fileno(), fcntl.LOCK_UN)
    if not assessment.ready_for_cutover:
        raise ValueError("shadow assessment is not ready for cutover")
    raw_next_tasks = _decode_next_tasks(legacy_next_tasks_bytes)
    if raw_next_tasks != immutable_snapshots.next_tasks:
        raise ValueError(
            "raw legacy snapshot does not match supplied snapshots"
        )
    import_report = LegacySnapshotImporter().import_snapshot(
        immutable_snapshots
    )
    if not import_report.ready:
        raise ValueError("legacy import is not ready for cutover")
    current_snapshot = identify_legacy_snapshots(immutable_snapshots)
    if (
        assessment.latest_snapshot_sha256 != current_snapshot.sha256
        or assessment.latest_snapshot_source_counts
        != current_snapshot.source_counts
    ):
        raise ValueError(
            "shadow ledger does not end at the cutover snapshot"
        )
    if (
        projection.schema_version
        != NEXT_TASKS_PROJECTION_SCHEMA_VERSION
    ):
        raise ValueError(
            "unsupported coordinator projection schema: "
            f"{projection.schema_version}"
        )
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
    active_leases = _active_next_task_leases(import_report)
    if active_leases:
        raise ValueError(
            "cutover requires a quiescent legacy queue; active work: "
            + ", ".join(active_leases)
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
        "projection_schema_version": projection.schema_version,
        "projection_sha256": projection_sha256,
        "prepared_at": cutover_at.isoformat(),
        "valid_until": (cutover_at + _MANIFEST_TTL).isoformat(),
    }
    return WorkOwnershipCutoverManifest(
        **identity,
        sha256=_sha256(_canonical_bytes(identity)),
    )


__all__ = [
    "WorkOwnershipCutoverManifest",
    "prepare_work_ownership_cutover",
]
