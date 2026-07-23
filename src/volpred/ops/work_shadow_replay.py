"""Pure shadow comparison between legacy and Work Coordinator selection.

The replay boundary accepts caller-supplied snapshots only.  It never submits a
WorkItem, reads the live queue or connects to ``ops_jobs``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any
from urllib.parse import quote

from .work import WorkerOffer
from .work.legacy import (
    LegacySnapshots,
    LegacyWorkCandidate,
    ReconciliationIssue,
)
from .work_migration import preview_legacy_snapshots


_DIMENSIONS = (
    "priority",
    "readiness",
    "capability",
    "claim_ownership",
    "parent",
    "deadline",
    "terminal_disposition",
)
_TERMINAL_STATUSES = frozenset({"succeeded", "failed", "cancelled"})
_OBSERVATION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


@dataclass(frozen=True)
class ShadowSnapshotIdentity:
    sha256: str
    byte_count: int
    source_counts: dict[str, int]


@dataclass(frozen=True)
class ShadowSelectionView:
    policy: str
    snapshot_sha256: str
    selected_candidate_ref: str | None
    eligible_candidate_refs: tuple[str, ...]


@dataclass(frozen=True)
class ShadowDimensionComparison:
    name: str
    legacy: Any
    coordinator: Any
    matches: bool
    classification: str | None = None
    evidence_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class ShadowCandidateComparison:
    candidate_ref: str
    dimensions: tuple[ShadowDimensionComparison, ...]


@dataclass(frozen=True)
class ShadowSelectionDifference:
    legacy_selected_candidate_ref: str | None
    coordinator_selected_candidate_ref: str | None
    classification: str
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True)
class ShadowReplayLedger:
    schema_version: str
    observation_id: str
    observed_at: str
    snapshot: ShadowSnapshotIdentity
    legacy_selection: ShadowSelectionView
    coordinator_selection: ShadowSelectionView
    selection_difference: ShadowSelectionDifference | None
    comparisons: tuple[ShadowCandidateComparison, ...]
    reconciliation_issues: tuple[dict[str, Any], ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "observation_id": self.observation_id,
            "observed_at": self.observed_at,
            "snapshot": {
                "sha256": self.snapshot.sha256,
                "byte_count": self.snapshot.byte_count,
                "source_counts": dict(self.snapshot.source_counts),
            },
            "legacy_selection": _selection_as_dict(self.legacy_selection),
            "coordinator_selection": _selection_as_dict(
                self.coordinator_selection
            ),
            "selection_difference": (
                None
                if self.selection_difference is None
                else {
                    "legacy_selected_candidate_ref": (
                        self.selection_difference.legacy_selected_candidate_ref
                    ),
                    "coordinator_selected_candidate_ref": (
                        self.selection_difference.coordinator_selected_candidate_ref
                    ),
                    "classification": (
                        self.selection_difference.classification
                    ),
                    "evidence_refs": list(
                        self.selection_difference.evidence_refs
                    ),
                }
            ),
            "comparisons": [
                {
                    "candidate_ref": comparison.candidate_ref,
                    "dimensions": [
                        {
                            "name": dimension.name,
                            "legacy": dimension.legacy,
                            "coordinator": dimension.coordinator,
                            "matches": dimension.matches,
                            "classification": dimension.classification,
                            "evidence_refs": list(dimension.evidence_refs),
                        }
                        for dimension in comparison.dimensions
                    ],
                }
                for comparison in self.comparisons
            ],
            "reconciliation_issues": list(self.reconciliation_issues),
        }


def replay_legacy_selection(
    snapshots: LegacySnapshots,
    *,
    offer: WorkerOffer,
    observed_at: datetime,
    observation_id: str,
) -> ShadowReplayLedger:
    """Compare both policies over one hash-bound, caller-supplied snapshot."""
    observed_at = _aware_utc(observed_at)
    snapshot_bytes = _canonical_snapshot_bytes(snapshots)
    snapshot = ShadowSnapshotIdentity(
        sha256=hashlib.sha256(snapshot_bytes).hexdigest(),
        byte_count=len(snapshot_bytes),
        source_counts={
            "next_tasks": len(snapshots.next_tasks),
            "task_records": len(snapshots.task_records),
            "ops_jobs": len(snapshots.ops_jobs),
        },
    )
    immutable_snapshots = _snapshots_from_canonical_bytes(snapshot_bytes)
    report = preview_legacy_snapshots(immutable_snapshots)
    comparisons = tuple(
        _compare_candidate(
            candidate,
            candidates=report.candidates,
            offer=offer,
            snapshot_sha256=snapshot.sha256,
            reconciliation_issues=report.issues,
        )
        for candidate in sorted(
            report.candidates, key=lambda item: _candidate_ref(item)
        )
    )
    legacy_eligible = tuple(
        candidate
        for candidate in report.candidates
        if _legacy_ready(candidate, offer=offer)
    )
    coordinator_eligible = tuple(
        candidate
        for candidate in report.candidates
        if _coordinator_ready(
            candidate,
            candidates=report.candidates,
            offer=offer,
        )
    )
    if _canonical_snapshot_bytes(snapshots) != snapshot_bytes:
        raise RuntimeError("shadow replay mutated its supplied snapshots")
    legacy_selection = _selection_view(
        "legacy",
        snapshot.sha256,
        legacy_eligible,
        key=_legacy_sort_key,
    )
    coordinator_selection = _selection_view(
        "work_coordinator",
        snapshot.sha256,
        coordinator_eligible,
        key=_coordinator_sort_key,
    )
    return ShadowReplayLedger(
        schema_version="work-shadow-replay.v1",
        observation_id=observation_id,
        observed_at=observed_at.isoformat(),
        snapshot=snapshot,
        legacy_selection=legacy_selection,
        coordinator_selection=coordinator_selection,
        selection_difference=_selection_difference(
            legacy_selection,
            coordinator_selection,
            comparisons,
        ),
        comparisons=comparisons,
        reconciliation_issues=tuple(
            {
                "classification": "legacy_corruption",
                "code": issue.code,
                "source_system": issue.source_system,
                "record_id": issue.record_id,
                "detail": issue.detail,
                "evidence_ref": _issue_evidence_ref(
                    issue.source_system,
                    issue.record_id,
                    issue.code,
                ),
            }
            for issue in report.issues
        ),
    )


def append_shadow_observation(
    ledger: ShadowReplayLedger,
    *,
    directory: Path,
) -> Path:
    """Atomically append one immutable observation receipt.

    The final link uses create-if-absent semantics.  Replaying an observation ID
    therefore fails instead of replacing its existing evidence.
    """
    if _OBSERVATION_ID.fullmatch(ledger.observation_id) is None:
        raise ValueError(
            "observation_id must be 1-128 safe filename characters"
        )
    payload = (
        json.dumps(
            ledger.as_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{ledger.observation_id}.json"
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=directory,
            prefix=".work-shadow-",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temp_path, target)
        directory_fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
    return target


def _compare_candidate(
    candidate: LegacyWorkCandidate,
    *,
    candidates: tuple[LegacyWorkCandidate, ...],
    offer: WorkerOffer,
    snapshot_sha256: str,
    reconciliation_issues: tuple[ReconciliationIssue, ...],
) -> ShadowCandidateComparison:
    candidate_ref = _candidate_ref(candidate)
    candidate_issues = _issues_for_candidate(
        candidate,
        reconciliation_issues,
    )
    legacy_capability = _legacy_capability_match(candidate, offer)
    coordinator_capability = _coordinator_capability_match(candidate, offer)
    parent = _parent_candidate(candidate, candidates)
    legacy_values: dict[str, Any] = {
        "priority": candidate.request.priority,
        "readiness": _legacy_ready(candidate, offer=offer),
        "capability": legacy_capability,
        "claim_ownership": candidate.claimed_by,
        "parent": {
            "id": candidate.request.parent_id,
            "gates_readiness": False,
            "satisfied": None,
        },
        "deadline": {
            "value": candidate.request.deadline,
            "ordering": (
                "not_applicable"
                if candidate.request.deadline is None
                else "not_used"
            ),
        },
        "terminal_disposition": {
            "terminal": candidate.legacy_status
            in {
                "succeeded",
                "succeeded_null_result",
                "failed",
                "cancelled",
                "closed_no_action",
                "expired",
                "superseded",
            },
            "outcome": candidate.legacy_status,
        },
    }
    coordinator_values: dict[str, Any] = {
        "priority": candidate.request.priority,
        "readiness": _coordinator_ready(
            candidate,
            candidates=candidates,
            offer=offer,
        ),
        "capability": coordinator_capability,
        "claim_ownership": candidate.claimed_by,
        "parent": {
            "id": candidate.request.parent_id,
            "gates_readiness": candidate.request.parent_id is not None,
            "satisfied": (
                None
                if candidate.request.parent_id is None
                else parent is not None and parent.status == "succeeded"
            ),
        },
        "deadline": {
            "value": candidate.request.deadline,
            "ordering": (
                "not_applicable"
                if candidate.request.deadline is None
                else "ascending_within_priority"
            ),
        },
        "terminal_disposition": {
            "terminal": candidate.status in _TERMINAL_STATUSES,
            "outcome": candidate.status,
        },
    }
    dimensions: list[ShadowDimensionComparison] = []
    for name in _DIMENSIONS:
        legacy_value = legacy_values[name]
        coordinator_value = coordinator_values[name]
        matches = legacy_value == coordinator_value
        dimensions.append(
            ShadowDimensionComparison(
                name=name,
                legacy=legacy_value,
                coordinator=coordinator_value,
                matches=matches,
                classification=(
                    None
                    if matches
                    else _classify_difference(
                        candidate,
                        name,
                        reconciliation_issues=candidate_issues,
                    )
                ),
                evidence_refs=(
                    ()
                    if matches
                    else (
                        f"{candidate_ref}#{name}",
                        _policy_evidence_ref(name),
                        f"snapshot://sha256/{snapshot_sha256}",
                        *(
                            _issue_evidence_ref(
                                issue.source_system,
                                issue.record_id,
                                issue.code,
                            )
                            for issue in candidate_issues
                        ),
                    )
                ),
            )
        )
    return ShadowCandidateComparison(
        candidate_ref=candidate_ref,
        dimensions=tuple(dimensions),
    )


def _legacy_ready(
    candidate: LegacyWorkCandidate,
    *,
    offer: WorkerOffer,
) -> bool:
    return (
        candidate.status == "pending"
        and candidate.legacy_status != "pending_main_thread"
        and _legacy_capability_match(candidate, offer)
    )


def _coordinator_ready(
    candidate: LegacyWorkCandidate,
    *,
    candidates: tuple[LegacyWorkCandidate, ...],
    offer: WorkerOffer,
) -> bool:
    if candidate.status != "pending":
        return False
    if not _coordinator_capability_match(candidate, offer):
        return False
    if candidate.request.parent_id is None:
        return True
    parent = _parent_candidate(candidate, candidates)
    return parent is not None and parent.status == "succeeded"


def _legacy_capability_match(
    candidate: LegacyWorkCandidate,
    offer: WorkerOffer,
) -> bool:
    if not offer.worker_id.lower().startswith("codex"):
        return True
    return candidate.request.kind in {
        "platform_ops",
        "experiment",
        "governance",
        "code_review",
        "paper_review",
        "daily_article",
        "daily_digest",
    }


def _coordinator_capability_match(
    candidate: LegacyWorkCandidate,
    offer: WorkerOffer,
) -> bool:
    return (
        candidate.request.required_capabilities <= offer.capabilities
        and candidate.request.required_attestations <= offer.attestations
    )


def _parent_candidate(
    candidate: LegacyWorkCandidate,
    candidates: tuple[LegacyWorkCandidate, ...],
) -> LegacyWorkCandidate | None:
    parent_id = candidate.request.parent_id
    if parent_id is None:
        return None
    return next(
        (item for item in candidates if item.legacy_id == parent_id),
        None,
    )


def _classify_difference(
    candidate: LegacyWorkCandidate,
    dimension: str,
    *,
    reconciliation_issues: tuple[ReconciliationIssue, ...],
) -> str:
    if reconciliation_issues:
        return "legacy_corruption"
    if (
        candidate.legacy_status == "pending_main_thread"
        and dimension == "readiness"
    ):
        return "implementation_bug"
    if dimension in {
        "readiness",
        "capability",
        "parent",
        "deadline",
        "terminal_disposition",
    }:
        return "policy_change"
    return "implementation_bug"


def _issues_for_candidate(
    candidate: LegacyWorkCandidate,
    issues: tuple[ReconciliationIssue, ...],
) -> tuple[ReconciliationIssue, ...]:
    return tuple(
        issue
        for issue in issues
        if issue.record_id is not None
        and (
            issue.record_id == candidate.legacy_id
            or candidate.legacy_id in issue.record_id.split(",")
        )
        and issue.source_system in {candidate.source_system, "cross_source"}
    )


def _selection_difference(
    legacy: ShadowSelectionView,
    coordinator: ShadowSelectionView,
    comparisons: tuple[ShadowCandidateComparison, ...],
) -> ShadowSelectionDifference | None:
    if legacy.selected_candidate_ref == coordinator.selected_candidate_ref:
        return None
    selected_refs = {
        ref
        for ref in (
            legacy.selected_candidate_ref,
            coordinator.selected_candidate_ref,
        )
        if ref is not None
    }
    selected_dimensions = tuple(
        dimension
        for comparison in comparisons
        if comparison.candidate_ref in selected_refs
        for dimension in comparison.dimensions
        if not dimension.matches
    )
    classifications = {
        dimension.classification
        for dimension in selected_dimensions
        if dimension.classification is not None
    }
    if "legacy_corruption" in classifications:
        classification = "legacy_corruption"
    elif "policy_change" in classifications:
        classification = "policy_change"
    else:
        classification = "implementation_bug"
    evidence_refs = tuple(
        dict.fromkeys(
            (
                "contract://work-selection/selection-outcome",
                *(
                    evidence_ref
                    for dimension in selected_dimensions
                    for evidence_ref in dimension.evidence_refs
                ),
            )
        )
    )
    return ShadowSelectionDifference(
        legacy_selected_candidate_ref=legacy.selected_candidate_ref,
        coordinator_selected_candidate_ref=coordinator.selected_candidate_ref,
        classification=classification,
        evidence_refs=evidence_refs,
    )


def _policy_evidence_ref(dimension: str) -> str:
    return {
        "priority": "contract://work-selection/priority",
        "readiness": "contract://work-selection/readiness",
        "capability": "contract://work-selection/capability",
        "claim_ownership": "contract://work-selection/claim-ownership",
        "parent": "contract://work-selection/parent-readiness",
        "deadline": "contract://work-selection/deadline-ordering",
        "terminal_disposition": "contract://work-selection/terminal-disposition",
    }[dimension]


def _selection_view(
    policy: str,
    snapshot_sha256: str,
    eligible: tuple[LegacyWorkCandidate, ...],
    *,
    key: Any,
) -> ShadowSelectionView:
    ordered = tuple(sorted(eligible, key=key))
    refs = tuple(_candidate_ref(candidate) for candidate in ordered)
    return ShadowSelectionView(
        policy=policy,
        snapshot_sha256=snapshot_sha256,
        selected_candidate_ref=refs[0] if refs else None,
        eligible_candidate_refs=refs,
    )


def _legacy_sort_key(candidate: LegacyWorkCandidate) -> tuple[Any, ...]:
    return (candidate.request.priority, candidate.legacy_id)


def _coordinator_sort_key(candidate: LegacyWorkCandidate) -> tuple[Any, ...]:
    return (
        candidate.request.priority,
        candidate.request.deadline is None,
        candidate.request.deadline or "",
        candidate.created_at,
        _candidate_ref(candidate),
    )


def _candidate_ref(candidate: LegacyWorkCandidate) -> str:
    return (
        f"legacy://{candidate.source_system}/"
        f"{quote(candidate.legacy_id, safe='')}"
    )


def _issue_evidence_ref(
    source_system: str,
    record_id: str | None,
    code: str,
) -> str:
    return (
        f"reconciliation://{source_system}/"
        f"{quote(record_id or '_snapshot', safe='')}/{quote(code, safe='')}"
    )


def _selection_as_dict(selection: ShadowSelectionView) -> dict[str, Any]:
    return {
        "policy": selection.policy,
        "snapshot_sha256": selection.snapshot_sha256,
        "selected_candidate_ref": selection.selected_candidate_ref,
        "eligible_candidate_refs": list(selection.eligible_candidate_refs),
    }


def _canonical_snapshot_bytes(snapshots: LegacySnapshots) -> bytes:
    return json.dumps(
        {
            "schema_version": "legacy-work-snapshot.v1",
            "next_tasks": snapshots.next_tasks,
            "task_records": snapshots.task_records,
            "ops_jobs": snapshots.ops_jobs,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _snapshots_from_canonical_bytes(payload: bytes) -> LegacySnapshots:
    """Materialize both selectors' private immutable content snapshot."""
    decoded = json.loads(payload)
    return LegacySnapshots(
        next_tasks=tuple(decoded["next_tasks"]),
        task_records=tuple(decoded["task_records"]),
        ops_jobs=tuple(decoded["ops_jobs"]),
    )


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("observed_at must include a timezone")
    return value.astimezone(timezone.utc)


__all__ = [
    "append_shadow_observation",
    "ShadowCandidateComparison",
    "ShadowDimensionComparison",
    "ShadowReplayLedger",
    "ShadowSelectionDifference",
    "ShadowSelectionView",
    "ShadowSnapshotIdentity",
    "replay_legacy_selection",
]
