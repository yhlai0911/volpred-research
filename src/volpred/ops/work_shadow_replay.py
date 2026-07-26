"""Pure shadow comparison between legacy and Work Coordinator selection.

The replay boundary accepts caller-supplied snapshots only.  It never submits a
WorkItem, reads the live queue or connects to ``ops_jobs``.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Mapping
from urllib.parse import quote

from .next_tasks import (
    is_main_thread_reserved,
    normalize_dispatch_lane,
    priority_sort_key,
)
from .task_pool_selection import (
    CODEX_ELIGIBLE_TASK_TYPES,
    LegacyClaimDecision,
    is_codex_owner,
    normalized_task_type,
    select_task_for_claim,
    task_identity,
)
from .work import WorkItemView, WorkerOffer, WorkRequest
from .work.legacy import (
    LegacySnapshots,
    LegacyWorkCandidate,
    ReconciliationIssue,
)
from .work.selection import (
    AcquisitionCandidateDecision,
    select_acquirable_work,
)
from .work_migration import preview_legacy_snapshots


@dataclass(frozen=True)
class _DimensionSpec:
    name: str
    evidence_ref: str


@dataclass(frozen=True)
class _RawNextTaskRecord:
    index: int
    task: dict[str, Any]
    task_id: str
    candidate_ref: str


_DIMENSION_SPECS = (
    _DimensionSpec("priority", "contract://work-selection/priority"),
    _DimensionSpec("readiness", "contract://work-selection/readiness"),
    _DimensionSpec("capability", "contract://work-selection/capability"),
    _DimensionSpec("attestation", "contract://work-selection/attestation"),
    _DimensionSpec(
        "claim_ownership",
        "contract://work-selection/claim-ownership",
    ),
    _DimensionSpec(
        "lease_expiry",
        "contract://work-selection/lease-expiry",
    ),
    _DimensionSpec(
        "dispatch_lane",
        "contract://work-selection/dispatch-lane",
    ),
    _DimensionSpec(
        "preferred_agent",
        "contract://work-selection/preferred-agent",
    ),
    _DimensionSpec(
        "parent",
        "contract://work-selection/parent-readiness",
    ),
    _DimensionSpec(
        "deadline",
        "contract://work-selection/deadline-ordering",
    ),
    _DimensionSpec(
        "terminal_disposition",
        "contract://work-selection/terminal-disposition",
    ),
)
_ALL_DIMENSIONS = frozenset(spec.name for spec in _DIMENSION_SPECS)
_RECONCILIATION_AFFECTED_DIMENSIONS = {
    "missing_parent": frozenset({"readiness", "parent"}),
    "unrepresentable_parent": frozenset({"readiness", "parent"}),
    "simultaneous_claim": frozenset(
        {"readiness", "claim_ownership", "lease_expiry"}
    ),
    "invalid_lifecycle": frozenset(
        {
            "readiness",
            "claim_ownership",
            "lease_expiry",
            "terminal_disposition",
        }
    ),
    # Duplicate identity means neither selector can know which record owns any
    # compared field.  This broad scope is explicit, not a classifier fallback.
    "duplicate_id": _ALL_DIMENSIONS,
    "duplicate_idempotency_key": _ALL_DIMENSIONS,
}
_CANONICAL_TERMINAL_STATUSES = frozenset(
    {"succeeded", "failed", "cancelled"}
)
_LEGACY_TERMINAL_STATUSES = frozenset(
    {
        "succeeded",
        "succeeded_null_result",
        "failed",
        "cancelled",
        "closed_no_action",
        "expired",
        "superseded",
    }
)
_LEGACY_TERMINAL_OUTCOME = {
    "succeeded": "succeeded",
    "succeeded_null_result": "succeeded",
    "failed": "failed",
    "cancelled": "cancelled",
    "closed_no_action": "cancelled",
    "expired": "cancelled",
    "superseded": "cancelled",
}
_COORDINATOR_STATUS_REASONS = frozenset(
    {
        "ready_pending",
        "ready_expired_claim",
        "live_claim",
        "claim_expiry_missing",
        "status_not_acquirable",
    }
)
_PARENT_UNREPRESENTABLE_ISSUES = frozenset(
    {
        "duplicate_id",
        "duplicate_idempotency_key",
        "invalid_record",
        "unknown_kind",
        "unknown_policy",
        "unknown_source",
        "unknown_status",
        "unrepresentable_public_effect",
    }
)
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
    classification_reason_code: str | None = None
    legacy_reason_codes: tuple[str, ...] = ()
    coordinator_reason_codes: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class ShadowCandidateComparison:
    candidate_ref: str
    legacy_eligible: bool
    coordinator_eligible: bool
    dimensions: tuple[ShadowDimensionComparison, ...]


@dataclass(frozen=True)
class ShadowSelectionDifference:
    legacy_selected_candidate_ref: str | None
    coordinator_selected_candidate_ref: str | None
    classification: str
    classification_reason_code: str
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True)
class ShadowReplayLedger:
    schema_version: str
    observation_id: str
    observed_at: str
    selection_scope: str
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
            "selection_scope": self.selection_scope,
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
                    "classification_reason_code": (
                        self.selection_difference.classification_reason_code
                    ),
                    "evidence_refs": list(
                        self.selection_difference.evidence_refs
                    ),
                }
            ),
            "comparisons": [
                {
                    "candidate_ref": comparison.candidate_ref,
                    "legacy_eligible": comparison.legacy_eligible,
                    "coordinator_eligible": comparison.coordinator_eligible,
                    "dimensions": [
                        {
                            "name": dimension.name,
                            "legacy": dimension.legacy,
                            "coordinator": dimension.coordinator,
                            "matches": dimension.matches,
                            "classification": dimension.classification,
                            "classification_reason_code": (
                                dimension.classification_reason_code
                            ),
                            "legacy_reason_codes": list(
                                dimension.legacy_reason_codes
                            ),
                            "coordinator_reason_codes": list(
                                dimension.coordinator_reason_codes
                            ),
                            "evidence_refs": list(dimension.evidence_refs),
                        }
                        for dimension in comparison.dimensions
                    ],
                }
                for comparison in self.comparisons
            ],
            "reconciliation_issues": list(self.reconciliation_issues),
        }


def identify_legacy_snapshots(
    snapshots: LegacySnapshots,
) -> ShadowSnapshotIdentity:
    """Return the canonical identity used by shadow replay receipts."""

    snapshot_bytes = _canonical_snapshot_bytes(snapshots)
    return ShadowSnapshotIdentity(
        sha256=hashlib.sha256(snapshot_bytes).hexdigest(),
        byte_count=len(snapshot_bytes),
        source_counts={
            "next_tasks": len(snapshots.next_tasks),
            "task_records": len(snapshots.task_records),
            "ops_jobs": len(snapshots.ops_jobs),
        },
    )


def freeze_legacy_snapshots(
    snapshots: LegacySnapshots,
) -> LegacySnapshots:
    """Detach mutable caller mappings behind one canonical byte snapshot."""

    return _snapshots_from_canonical_bytes(
        _canonical_snapshot_bytes(snapshots)
    )


def replay_legacy_selection(
    snapshots: LegacySnapshots,
    *,
    offer: WorkerOffer,
    observed_at: datetime,
    observation_id: str,
) -> ShadowReplayLedger:
    """Compare both policies over one hash-bound, caller-supplied snapshot."""
    observed_at = _aware_utc(observed_at)
    immutable_snapshots = freeze_legacy_snapshots(snapshots)
    snapshot = identify_legacy_snapshots(immutable_snapshots)
    report = preview_legacy_snapshots(immutable_snapshots)
    raw_next_tasks = tuple(
        dict(task) for task in immutable_snapshots.next_tasks
    )
    raw_records = _raw_next_task_records(raw_next_tasks)
    terminal_history_indexes = _terminal_history_indexes(
        raw_records,
        report.issues,
    )
    reconciliation_issues = _without_terminal_history_issues(
        report.issues,
        raw_records=raw_records,
        terminal_history_indexes=terminal_history_indexes,
    )
    mapped_candidates = tuple(
        candidate
        for candidate in report.candidates
        if candidate.source_system == "next_tasks"
        and candidate.legacy_id
        not in {
            raw_records[index].task_id
            for index in terminal_history_indexes
        }
    )
    legacy_result = select_task_for_claim(
        raw_next_tasks,
        owner=offer.worker_id,
        main_thread=False,
        observed_at=observed_at,
    )
    legacy_eligible_indexes = frozenset(
        legacy_result.eligible_indexes
    )
    coordinator_candidates = tuple(
        candidate
        for candidate in mapped_candidates
        if not _candidate_identity_is_unrepresentable(
            candidate,
            reconciliation_issues,
        )
    )
    dependency_candidates = tuple(
        candidate
        for candidate in report.candidates
        if candidate.source_system != "next_tasks"
        and not _candidate_identity_is_unrepresentable(
            candidate,
            reconciliation_issues,
        )
    )
    terminal_dependency_candidates = tuple(
        _terminal_dependency_candidate(raw_records[index])
        for index in terminal_history_indexes
        if any(
            record.task.get("parent_task_id")
            == raw_records[index].task_id
            for record in raw_records
        )
    )
    dependency_candidates = (
        *dependency_candidates,
        *terminal_dependency_candidates,
    )
    coordinator_context = (
        *coordinator_candidates,
        *dependency_candidates,
    )
    coordinator_result = select_acquirable_work(
        tuple(
            _coordinator_item(candidate)
            for candidate in coordinator_candidates
        ),
        offer=offer,
        observed_at=observed_at,
        dependency_items=tuple(
            _coordinator_item(candidate)
            for candidate in dependency_candidates
        ),
    )
    coordinator_decisions = {
        decision.work_id: decision
        for decision in coordinator_result.decisions
    }
    coordinator_candidates_by_id = {
        candidate.legacy_id: candidate
        for candidate in coordinator_candidates
    }
    comparisons_buffer: list[ShadowCandidateComparison] = []
    for raw_record, legacy_decision in zip(
        raw_records,
        legacy_result.decisions,
        strict=True,
    ):
        if raw_record.index in terminal_history_indexes:
            comparisons_buffer.append(
                _compare_terminal_history(
                    raw_record,
                    legacy_decision=legacy_decision,
                    legacy_selection_eligible=(
                        raw_record.index in legacy_eligible_indexes
                    ),
                    snapshot_sha256=snapshot.sha256,
                )
            )
            continue
        candidate = coordinator_candidates_by_id.get(raw_record.task_id)
        if candidate is None:
            comparison = _compare_unavailable_next_task(
                raw_record,
                legacy_decision=legacy_decision,
                legacy_selection_eligible=(
                    raw_record.index in legacy_eligible_indexes
                ),
                snapshot_sha256=snapshot.sha256,
                reconciliation_issues=reconciliation_issues,
            )
        else:
            comparison = _compare_candidate(
                candidate,
                candidates=coordinator_context,
                raw_task=raw_record.task,
                legacy_decision=legacy_decision,
                legacy_selection_eligible=(
                    raw_record.index in legacy_eligible_indexes
                ),
                coordinator_decision=coordinator_decisions[
                    candidate.legacy_id
                ],
                snapshot_sha256=snapshot.sha256,
                reconciliation_issues=reconciliation_issues,
            )
        comparisons_buffer.append(comparison)
    comparisons = tuple(
        sorted(
            comparisons_buffer,
            key=lambda comparison: comparison.candidate_ref,
        )
    )
    legacy_selection = ShadowSelectionView(
        policy="legacy",
        snapshot_sha256=snapshot.sha256,
        selected_candidate_ref=(
            None
            if legacy_result.selected_index is None
            else raw_records[
                legacy_result.selected_index
            ].candidate_ref
        ),
        eligible_candidate_refs=tuple(
            raw_records[index].candidate_ref
            for index in legacy_result.eligible_indexes
        ),
    )
    coordinator_selection = _selection_view(
        "work_coordinator",
        snapshot.sha256,
        selected_id=coordinator_result.selected_id,
        eligible_ids=tuple(
            decision.work_id
            for decision in coordinator_result.decisions
            if decision.eligible
        ),
    )
    return ShadowReplayLedger(
        schema_version="work-shadow-replay.v2",
        observation_id=observation_id,
        observed_at=observed_at.isoformat(),
        selection_scope="next_tasks",
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
                **(
                    {"record_index": issue.record_index}
                    if issue.record_index is not None
                    else {}
                ),
                **(
                    {
                        "affected_record_ids": list(
                            issue.affected_record_ids
                        )
                    }
                    if issue.affected_record_ids
                    else {}
                ),
                "evidence_ref": _issue_evidence_ref(issue),
            }
            for issue in reconciliation_issues
        ),
    )


def append_shadow_observation(
    ledger: ShadowReplayLedger,
    *,
    directory: Path,
    queue_owner_evidence: Mapping[str, Any] | None = None,
) -> Path:
    """Atomically append one immutable observation receipt.

    The final link uses create-if-absent semantics.  Replaying an observation ID
    therefore fails instead of replacing its existing evidence.
    """
    if _OBSERVATION_ID.fullmatch(ledger.observation_id) is None:
        raise ValueError(
            "observation_id must be 1-128 safe filename characters"
        )
    receipt = {
        **ledger.as_dict(),
        "schema_version": (
            "work-shadow-replay.v4"
            if queue_owner_evidence is not None
            else "work-shadow-replay.v3"
        ),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    if queue_owner_evidence is not None:
        receipt["queue_owner_evidence"] = dict(queue_owner_evidence)
    payload = (
        json.dumps(
            receipt,
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


@dataclass(frozen=True)
class _PolicyOracleRule:
    dimension: str
    legacy_requires: frozenset[str]
    coordinator_requires: frozenset[str]
    classification: str
    reason_code: str


_POLICY_ORACLE = (
    _PolicyOracleRule(
        "readiness",
        frozenset({"live_revalidation_required"}),
        frozenset({"ready_pending"}),
        "implementation_bug",
        "replay_missing_live_revalidation_evidence",
    ),
    _PolicyOracleRule(
        "readiness",
        frozenset({"legacy_managed_event_deadline_gate"}),
        frozenset({"ready_pending"}),
        "policy_change",
        "schedule_materializer_event_deadline_contract",
    ),
    _PolicyOracleRule(
        "readiness",
        frozenset({"eligible"}),
        frozenset({"live_claim"}),
        "policy_change",
        "coordinator_inline_lease_contract",
    ),
    _PolicyOracleRule(
        "readiness",
        frozenset({"already_claimed"}),
        frozenset({"live_claim"}),
        "policy_change",
        "coordinator_inline_lease_contract",
    ),
    _PolicyOracleRule(
        "readiness",
        frozenset({"already_claimed"}),
        frozenset({"claim_expiry_missing"}),
        "implementation_bug",
        "claim_expiry_unrepresentable",
    ),
    _PolicyOracleRule(
        "readiness",
        frozenset({"legacy_blocked_status_claimable"}),
        frozenset({"status_not_acquirable"}),
        "policy_change",
        "coordinator_blocked_status_policy",
    ),
    _PolicyOracleRule(
        "capability",
        frozenset({"legacy_capability_not_enforced"}),
        frozenset({"capability_mismatch"}),
        "policy_change",
        "coordinator_capability_contract",
    ),
    _PolicyOracleRule(
        "capability",
        frozenset({"legacy_no_capability_requirement"}),
        frozenset({"capability_mismatch"}),
        "policy_change",
        "coordinator_capability_contract",
    ),
    _PolicyOracleRule(
        "attestation",
        frozenset({"legacy_attestation_not_enforced"}),
        frozenset({"attestation_mismatch"}),
        "policy_change",
        "coordinator_attestation_contract",
    ),
    _PolicyOracleRule(
        "claim_ownership",
        frozenset({"already_claimed"}),
        frozenset({"ready_expired_claim"}),
        "policy_change",
        "coordinator_expired_lease_reclaim",
    ),
    _PolicyOracleRule(
        "claim_ownership",
        frozenset({"eligible"}),
        frozenset({"live_claim"}),
        "policy_change",
        "coordinator_inline_lease_contract",
    ),
    _PolicyOracleRule(
        "claim_ownership",
        frozenset({"already_claimed"}),
        frozenset({"claim_expiry_missing"}),
        "implementation_bug",
        "claim_expiry_unrepresentable",
    ),
    _PolicyOracleRule(
        "lease_expiry",
        frozenset({"legacy_cleanup_only_reclaim"}),
        frozenset({"ready_expired_claim"}),
        "policy_change",
        "coordinator_expired_lease_reclaim",
    ),
    _PolicyOracleRule(
        "lease_expiry",
        frozenset({"legacy_cleanup_only_reclaim"}),
        frozenset({"live_claim"}),
        "policy_change",
        "coordinator_inline_lease_contract",
    ),
    _PolicyOracleRule(
        "lease_expiry",
        frozenset({"legacy_cleanup_only_reclaim"}),
        frozenset({"claim_expiry_missing"}),
        "implementation_bug",
        "claim_expiry_unrepresentable",
    ),
    _PolicyOracleRule(
        "dispatch_lane",
        frozenset({"main_thread_lane"}),
        frozenset({"coordinator_dispatch_lane_unrepresented"}),
        "implementation_bug",
        "migration_missing_dispatch_lane_capability_mapping",
    ),
    _PolicyOracleRule(
        "preferred_agent",
        frozenset({"legacy_preferred_agent_routing"}),
        frozenset({"coordinator_preferred_agent_unrepresented"}),
        "policy_change",
        "provider_execution_capability_routing",
    ),
    _PolicyOracleRule(
        "parent",
        frozenset({"legacy_parent_not_enforced"}),
        frozenset({"parent_missing"}),
        "policy_change",
        "coordinator_parent_readiness",
    ),
    _PolicyOracleRule(
        "parent",
        frozenset({"legacy_parent_not_enforced"}),
        frozenset({"parent_not_succeeded"}),
        "policy_change",
        "coordinator_parent_readiness",
    ),
    _PolicyOracleRule(
        "parent",
        frozenset({"legacy_parent_not_enforced"}),
        frozenset({"parent_succeeded"}),
        "policy_change",
        "coordinator_parent_readiness",
    ),
    _PolicyOracleRule(
        "deadline",
        frozenset(
            {"deadline_expired", "legacy_managed_event_deadline_gate"}
        ),
        frozenset({"coordinator_deadline_ranked"}),
        "policy_change",
        "schedule_materializer_event_deadline_contract",
    ),
    _PolicyOracleRule(
        "deadline",
        frozenset({"legacy_deadline_not_ranked"}),
        frozenset({"coordinator_deadline_ranked"}),
        "policy_change",
        "coordinator_deadline_ordering",
    ),
    _PolicyOracleRule(
        "terminal_disposition",
        frozenset({"legacy_terminal_mapping"}),
        frozenset({"coordinator_terminal_mapping"}),
        "policy_change",
        "coordinator_terminal_mapping",
    ),
)


def is_registered_policy_change(
    *,
    dimension: str | None,
    reason_code: str,
    legacy_reason_codes: tuple[str, ...],
    coordinator_reason_codes: tuple[str, ...],
    evidence_refs: tuple[str, ...],
    candidate_ref: str | None,
    snapshot_sha256: str,
) -> bool:
    """Validate a policy-change label against oracle inputs and evidence."""
    evidence = frozenset(evidence_refs)
    snapshot_ref = f"snapshot://sha256/{snapshot_sha256}"
    oracle_ref = f"oracle://work-selection/{reason_code}"
    if dimension is None:
        return (
            reason_code == "coordinator_ranking_contract"
            and {
                "contract://work-selection/selection-outcome",
                "contract://work-selection/priority",
                snapshot_ref,
                oracle_ref,
            }.issubset(evidence)
        )
    spec = next(
        (item for item in _DIMENSION_SPECS if item.name == dimension),
        None,
    )
    if spec is None or candidate_ref is None:
        return False
    rule_matches = any(
        rule.classification == "policy_change"
        and rule.reason_code == reason_code
        and rule.dimension == dimension
        and rule.legacy_requires.issubset(legacy_reason_codes)
        and rule.coordinator_requires.issubset(
            coordinator_reason_codes
        )
        for rule in _POLICY_ORACLE
    )
    return rule_matches and {
        f"{candidate_ref}#{dimension}",
        spec.evidence_ref,
        snapshot_ref,
        oracle_ref,
    }.issubset(evidence)


def _compare_candidate(
    candidate: LegacyWorkCandidate,
    *,
    candidates: tuple[LegacyWorkCandidate, ...],
    raw_task: Mapping[str, Any],
    legacy_decision: LegacyClaimDecision,
    legacy_selection_eligible: bool,
    coordinator_decision: AcquisitionCandidateDecision,
    snapshot_sha256: str,
    reconciliation_issues: tuple[ReconciliationIssue, ...],
) -> ShadowCandidateComparison:
    candidate_ref = _candidate_ref(candidate)
    candidate_issues = _issues_for_candidate(
        candidate,
        reconciliation_issues,
    )
    raw_task_dict = dict(raw_task)
    parent = _parent_candidate(candidate, candidates)
    parent_topology_issues = _parent_topology_issues(
        candidate,
        reconciliation_issues,
    )
    legacy_values, legacy_reason_map = _legacy_dimension_projection(
        raw_task_dict,
        legacy_decision,
        candidate=candidate,
    )
    coordinator_status_codes = tuple(
        code
        for code in coordinator_decision.reason_codes
        if code in _COORDINATOR_STATUS_REASONS
    )
    coordinator_status_ready = any(
        code in {"ready_pending", "ready_expired_claim"}
        for code in coordinator_status_codes
    )
    coordinator_capability_match = (
        not coordinator_decision.missing_capabilities
    )
    coordinator_attestation_match = (
        not coordinator_decision.missing_attestations
    )
    preferred_agent = (
        candidate.preferred_agent or candidate.target_agent
    )
    coordinator_values: dict[str, Any] = {
        "priority": {"value": candidate.request.priority},
        "readiness": coordinator_status_ready,
        "capability": {"matched": coordinator_capability_match},
        "attestation": {"matched": coordinator_attestation_match},
        "claim_ownership": {
            "claimed_by": candidate.claimed_by,
            "blocks_claim": "live_claim" in coordinator_status_codes,
        },
        "lease_expiry": _coordinator_lease_value(
            candidate,
            coordinator_status_codes,
        ),
        "dispatch_lane": {
            "value": candidate.dispatch_lane,
            "claimable": True,
        },
        "preferred_agent": (
            {"value": None}
            if preferred_agent is None
            else {
                "value": preferred_agent,
                "routing_effect": False,
            }
        ),
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
        "terminal_disposition": (
            {
                "terminal": True,
                "outcome": candidate.status,
            }
            if candidate.status in _CANONICAL_TERMINAL_STATUSES
            else {"terminal": False}
        ),
    }
    coordinator_reason_map = _coordinator_dimension_reason_codes(
        candidate,
        coordinator_decision=coordinator_decision,
        coordinator_status_codes=coordinator_status_codes,
    )
    dimensions: list[ShadowDimensionComparison] = []
    for spec in _DIMENSION_SPECS:
        legacy_value = legacy_values[spec.name]
        coordinator_value = coordinator_values[spec.name]
        legacy_reasons = legacy_reason_map[spec.name]
        coordinator_reasons = coordinator_reason_map[spec.name]
        matches = legacy_value == coordinator_value
        classification: str | None = None
        classification_reason: str | None = None
        dimension_issues = _reconciliation_issues_for_dimension(
            spec.name,
            candidate_issues,
        )
        if spec.name == "parent":
            dimension_issues = tuple(
                dict.fromkeys(
                    (*dimension_issues, *parent_topology_issues)
                )
            )
        if not matches:
            classification, classification_reason = _classify_difference(
                spec.name,
                legacy_reason_codes=legacy_reasons,
                coordinator_reason_codes=coordinator_reasons,
                reconciliation_issues=dimension_issues,
            )
        dimensions.append(
            ShadowDimensionComparison(
                name=spec.name,
                legacy=legacy_value,
                coordinator=coordinator_value,
                matches=matches,
                classification=classification,
                classification_reason_code=classification_reason,
                legacy_reason_codes=legacy_reasons,
                coordinator_reason_codes=coordinator_reasons,
                evidence_refs=(
                    ()
                    if matches
                    else tuple(
                        dict.fromkeys(
                            (
                                f"{candidate_ref}#{spec.name}",
                                spec.evidence_ref,
                                f"snapshot://sha256/{snapshot_sha256}",
                                *(
                                    "selector://legacy/"
                                    f"{quote(candidate.legacy_id, safe='')}/"
                                    f"{quote(code, safe='')}"
                                    for code in legacy_reasons
                                ),
                                *(
                                    "selector://work-coordinator/"
                                    f"{quote(candidate.legacy_id, safe='')}/"
                                    f"{quote(code, safe='')}"
                                    for code in coordinator_reasons
                                ),
                                (
                                    "oracle://work-selection/"
                                    f"{classification_reason}"
                                ),
                                *(
                                    _issue_evidence_ref(issue)
                                    for issue in dimension_issues
                                ),
                            )
                        )
                    )
                ),
            )
        )
    return ShadowCandidateComparison(
        candidate_ref=candidate_ref,
        legacy_eligible=legacy_selection_eligible,
        coordinator_eligible=coordinator_decision.eligible,
        dimensions=tuple(dimensions),
    )


def _compare_unavailable_next_task(
    raw_record: _RawNextTaskRecord,
    *,
    legacy_decision: LegacyClaimDecision,
    legacy_selection_eligible: bool,
    snapshot_sha256: str,
    reconciliation_issues: tuple[ReconciliationIssue, ...],
) -> ShadowCandidateComparison:
    """Record a production-visible task that migration cannot represent."""

    raw_task = raw_record.task
    task_id = raw_record.task_id
    candidate_ref = raw_record.candidate_ref
    candidate_issues = _issues_for_raw_next_task(
        raw_record,
        reconciliation_issues,
    )
    issue_codes = tuple(
        sorted({issue.code for issue in candidate_issues})
    )
    classification_reason = (
        f"reconciliation:{','.join(issue_codes)}"
        if issue_codes
        else "migration_candidate_missing_without_reconciliation_issue"
    )
    legacy_values, legacy_reasons = _legacy_dimension_projection(
        raw_task,
        legacy_decision,
        candidate=None,
    )
    unavailable = {
        "unavailable": True,
        "availability": "not_evaluated",
        "reconciliation_codes": issue_codes,
    }
    dimensions: list[ShadowDimensionComparison] = []
    for spec in _DIMENSION_SPECS:
        classification, reason_code = (
            _classify_difference(
                spec.name,
                legacy_reason_codes=legacy_reasons[spec.name],
                coordinator_reason_codes=(),
                reconciliation_issues=candidate_issues,
            )
            if candidate_issues
            else (
                "implementation_bug",
                classification_reason,
            )
        )
        dimensions.append(
            ShadowDimensionComparison(
                name=spec.name,
                legacy=legacy_values[spec.name],
                coordinator=unavailable,
                matches=False,
                classification=classification,
                classification_reason_code=reason_code,
                legacy_reason_codes=legacy_reasons[spec.name],
                coordinator_reason_codes=(),
                evidence_refs=tuple(
                    dict.fromkeys(
                        (
                            f"{candidate_ref}#{spec.name}",
                            spec.evidence_ref,
                            f"snapshot://sha256/{snapshot_sha256}",
                            *(
                                "selector://legacy/"
                                f"{quote(task_id, safe='')}/"
                                f"{quote(code, safe='')}"
                                for code in legacy_reasons[spec.name]
                            ),
                            _migration_unavailable_evidence_ref(
                                raw_record
                            ),
                            (
                                "oracle://work-selection/"
                                f"{reason_code}"
                            ),
                            *(
                                _issue_evidence_ref(issue)
                                for issue in candidate_issues
                            ),
                        )
                    )
                ),
            )
        )
    return ShadowCandidateComparison(
        candidate_ref=candidate_ref,
        legacy_eligible=legacy_selection_eligible,
        coordinator_eligible=False,
        dimensions=tuple(dimensions),
    )


def _compare_terminal_history(
    raw_record: _RawNextTaskRecord,
    *,
    legacy_decision: LegacyClaimDecision,
    legacy_selection_eligible: bool,
    snapshot_sha256: str,
) -> ShadowCandidateComparison:
    """Compare a final disposition without rematerialising it as work."""

    candidate_ref = raw_record.candidate_ref
    legacy_values, legacy_reasons = _legacy_dimension_projection(
        raw_record.task,
        legacy_decision,
        candidate=None,
    )
    coordinator_values = dict(legacy_values)
    raw_status = str(raw_record.task["status"]).strip().lower()
    coordinator_values["terminal_disposition"] = {
        "terminal": True,
        "outcome": _LEGACY_TERMINAL_OUTCOME[raw_status],
    }
    dimensions: list[ShadowDimensionComparison] = []
    for spec in _DIMENSION_SPECS:
        legacy_value = legacy_values[spec.name]
        coordinator_value = coordinator_values[spec.name]
        matches = legacy_value == coordinator_value
        coordinator_reasons = (
            ("coordinator_terminal_mapping",)
            if spec.name == "terminal_disposition"
            else legacy_reasons[spec.name]
        )
        classification: str | None = None
        reason_code: str | None = None
        evidence_refs: tuple[str, ...] = ()
        if not matches:
            classification, reason_code = _classify_difference(
                spec.name,
                legacy_reason_codes=legacy_reasons[spec.name],
                coordinator_reason_codes=coordinator_reasons,
                reconciliation_issues=(),
            )
            evidence_refs = (
                f"{candidate_ref}#{spec.name}",
                spec.evidence_ref,
                f"snapshot://sha256/{snapshot_sha256}",
                f"oracle://work-selection/{reason_code}",
            )
        dimensions.append(
            ShadowDimensionComparison(
                name=spec.name,
                legacy=legacy_value,
                coordinator=coordinator_value,
                matches=matches,
                classification=classification,
                classification_reason_code=reason_code,
                legacy_reason_codes=legacy_reasons[spec.name],
                coordinator_reason_codes=coordinator_reasons,
                evidence_refs=evidence_refs,
            )
        )
    return ShadowCandidateComparison(
        candidate_ref=candidate_ref,
        legacy_eligible=legacy_selection_eligible,
        coordinator_eligible=False,
        dimensions=tuple(dimensions),
    )


def _legacy_dimension_projection(
    raw_task: Mapping[str, Any],
    legacy_decision: LegacyClaimDecision,
    *,
    candidate: LegacyWorkCandidate | None,
) -> tuple[
    dict[str, Any],
    dict[str, tuple[str, ...]],
]:
    """Project legacy values and reasons once for every comparison path."""

    raw_status = str(raw_task.get("status") or "").strip().lower()
    legacy_status = (
        candidate.legacy_status if candidate is not None else raw_status
    )
    active_claim = legacy_status in {"claimed", "in_progress"} or (
        candidate is not None and candidate.status in {"claimed", "running"}
    )
    claimed_by = (
        candidate.claimed_by
        if candidate is not None
        else raw_task.get("claimed_by")
    )
    claim_expires_at = (
        candidate.claim_expires_at
        if candidate is not None
        else raw_task.get("claim_expires_at")
    )
    dispatch_lane = (
        candidate.dispatch_lane
        if candidate is not None
        else normalize_dispatch_lane(dict(raw_task))
    )
    preferred_agent = (
        candidate.preferred_agent or candidate.target_agent
        if candidate is not None
        else raw_task.get("preferred_agent")
        or raw_task.get("target_agent")
    )
    parent_id = (
        candidate.request.parent_id
        if candidate is not None
        else raw_task.get("parent_task_id") or raw_task.get("parent_id")
    )
    deadline = (
        candidate.request.deadline
        if candidate is not None
        else raw_task.get("deadline")
    )
    priority = (
        candidate.request.priority
        if candidate is not None
        else priority_sort_key(raw_task.get("priority"), default=999)
    )
    lane_reserved = is_main_thread_reserved(dict(raw_task))
    legacy_status_ready = legacy_decision.primary_reason not in {
        "wrong_status",
        "missing_deadline",
        "invalid_deadline",
        "deadline_expired",
        "live_revalidation_required",
        "duplicate_task_id",
        "missing_task_id",
    }
    preferred_agent_effect = (
        preferred_agent is not None
        and is_codex_owner(legacy_decision.owner)
        and normalized_task_type(raw_task) not in CODEX_ELIGIBLE_TASK_TYPES
        and str(preferred_agent).strip().lower() == "codex"
    )
    values: dict[str, Any] = {
        "priority": {"value": priority},
        "readiness": legacy_status_ready,
        "capability": {
            "matched": legacy_decision.primary_reason
            != "not_codex_eligible"
        },
        "attestation": {"matched": True},
        "claim_ownership": {
            "claimed_by": claimed_by,
            "blocks_claim": (
                legacy_decision.primary_reason == "already_claimed"
            ),
        },
        "lease_expiry": (
            {
                "claim_expires_at": claim_expires_at,
                "reclaim": "cleanup_pass_only",
            }
            if active_claim
            else {"state": "none"}
        ),
        "dispatch_lane": {
            "value": dispatch_lane,
            "claimable": not lane_reserved,
        },
        "preferred_agent": (
            {"value": None}
            if preferred_agent is None
            else {
                "value": preferred_agent,
                "routing_effect": preferred_agent_effect,
            }
        ),
        "parent": {
            "id": parent_id,
            "gates_readiness": False,
            "satisfied": None,
        },
        "deadline": {
            "value": deadline,
            "ordering": (
                "not_applicable" if deadline is None else "not_used"
            ),
        },
        "terminal_disposition": (
            {"terminal": True, "outcome": legacy_status}
            if legacy_status in _LEGACY_TERMINAL_STATUSES
            else {"terminal": False}
        ),
    }
    readiness_reasons = (
        ("legacy_blocked_status_claimable", legacy_decision.primary_reason)
        if legacy_status == "blocked"
        else (
            legacy_decision.primary_reason,
            *(
                ("legacy_managed_event_deadline_gate",)
                if "legacy_managed_event_deadline_gate"
                in legacy_decision.policy_codes
                else ()
            ),
        )
    )
    reasons: dict[str, tuple[str, ...]] = {
        "priority": ("legacy_priority_then_id_rank",),
        "readiness": readiness_reasons,
        "capability": (
            ("legacy_capability_not_enforced",)
            if "legacy_capability_not_enforced"
            in legacy_decision.policy_codes
            else ("legacy_no_capability_requirement",)
        ),
        "attestation": (
            ("legacy_attestation_not_enforced",)
            if "legacy_attestation_not_enforced"
            in legacy_decision.policy_codes
            else ("legacy_no_attestation_requirement",)
        ),
        "claim_ownership": (legacy_decision.primary_reason,),
        "lease_expiry": (
            ("legacy_cleanup_only_reclaim", legacy_decision.primary_reason)
            if active_claim
            else ("legacy_no_active_claim",)
        ),
        "dispatch_lane": (
            ("main_thread_lane",)
            if lane_reserved
            else ("legacy_dispatch_lane_allowed",)
        ),
        "preferred_agent": (
            ("legacy_no_preferred_agent",)
            if preferred_agent is None
            else ("legacy_preferred_agent_routing",)
        ),
        "parent": (
            ("legacy_no_parent",)
            if parent_id is None
            else ("legacy_parent_not_enforced",)
        ),
        "deadline": (
            ("legacy_no_deadline",)
            if deadline is None
            else (
                "legacy_deadline_not_ranked",
                *(
                    (legacy_decision.primary_reason,)
                    if legacy_decision.primary_reason
                    in {
                        "missing_deadline",
                        "invalid_deadline",
                        "deadline_expired",
                    }
                    else ()
                ),
                *(
                    ("legacy_managed_event_deadline_gate",)
                    if "legacy_managed_event_deadline_gate"
                    in legacy_decision.policy_codes
                    else ()
                ),
            )
        ),
        "terminal_disposition": (
            ("legacy_terminal_mapping",)
            if legacy_status in _LEGACY_TERMINAL_STATUSES
            else ("legacy_non_terminal",)
        ),
    }
    return values, reasons


def _classify_difference(
    dimension: str,
    *,
    legacy_reason_codes: tuple[str, ...],
    coordinator_reason_codes: tuple[str, ...],
    reconciliation_issues: tuple[ReconciliationIssue, ...],
) -> tuple[str, str]:
    if reconciliation_issues:
        issue_codes = ",".join(
            sorted({issue.code for issue in reconciliation_issues})
        )
        return "legacy_corruption", f"reconciliation:{issue_codes}"
    legacy = frozenset(legacy_reason_codes)
    coordinator = frozenset(coordinator_reason_codes)
    for rule in _POLICY_ORACLE:
        if (
            rule.dimension == dimension
            and rule.legacy_requires <= legacy
            and rule.coordinator_requires <= coordinator
        ):
            return rule.classification, rule.reason_code
    return "implementation_bug", "unregistered_selector_reason_pair"


def _coordinator_item(candidate: LegacyWorkCandidate) -> WorkItemView:
    return WorkItemView(
        id=candidate.legacy_id,
        idempotency_key=candidate.request.idempotency_key,
        source=candidate.request.source,
        kind=candidate.request.kind,
        title=candidate.request.title,
        priority=candidate.request.priority,
        required_capabilities=candidate.request.required_capabilities,
        required_attestations=candidate.request.required_attestations,
        risk=candidate.request.risk,
        approval=candidate.request.approval,
        payload_ref=candidate.request.payload_ref,
        status=candidate.status,
        version=1,
        created_at=candidate.creation_sort_time,
        parent_id=candidate.request.parent_id,
        deadline=candidate.request.deadline,
        requester_ref=candidate.request.requester_ref,
        updated_at=candidate.updated_at,
        blocked_reason=candidate.blocked_reason,
        claimed_by=candidate.claimed_by,
        claim_expires_at=candidate.claim_expires_at,
        result_summary=candidate.result_summary,
        finished_at=candidate.finished_at,
    )


def _coordinator_lease_value(
    candidate: LegacyWorkCandidate,
    coordinator_status_codes: tuple[str, ...],
) -> dict[str, Any]:
    if candidate.status not in {"claimed", "running"}:
        return {"state": "none"}
    state = next(
        (
            code
            for code in coordinator_status_codes
            if code
            in {
                "ready_expired_claim",
                "live_claim",
                "claim_expiry_missing",
            }
        ),
        "claim_expiry_missing",
    )
    return {
        "claim_expires_at": candidate.claim_expires_at,
        "state": state,
        "reclaim_inline": state == "ready_expired_claim",
    }


def _coordinator_dimension_reason_codes(
    candidate: LegacyWorkCandidate,
    *,
    coordinator_decision: AcquisitionCandidateDecision,
    coordinator_status_codes: tuple[str, ...],
) -> dict[str, tuple[str, ...]]:
    preferred_agent = (
        candidate.preferred_agent or candidate.target_agent
    )
    return {
        "priority": ("coordinator_priority_deadline_created_id_rank",),
        "readiness": coordinator_status_codes,
        "capability": (
            ("coordinator_capability_enforced", "capability_mismatch")
            if coordinator_decision.missing_capabilities
            else ("coordinator_capability_enforced", "capability_match")
        ),
        "attestation": (
            ("coordinator_attestation_enforced", "attestation_mismatch")
            if coordinator_decision.missing_attestations
            else ("coordinator_attestation_enforced", "attestation_match")
        ),
        "claim_ownership": coordinator_status_codes,
        "lease_expiry": coordinator_status_codes,
        "dispatch_lane": (
            "coordinator_dispatch_lane_unrepresented",
            *coordinator_status_codes,
        ),
        "preferred_agent": (
            ("coordinator_no_preferred_agent",)
            if preferred_agent is None
            else ("coordinator_preferred_agent_unrepresented",)
        ),
        "parent": (
            ("coordinator_no_parent",)
            if candidate.request.parent_id is None
            else tuple(
                code
                for code in coordinator_decision.reason_codes
                if code
                in {
                    "parent_missing",
                    "parent_not_succeeded",
                    "parent_succeeded",
                }
            )
        ),
        "deadline": (
            ("coordinator_no_deadline",)
            if candidate.request.deadline is None
            else ("coordinator_deadline_ranked",)
        ),
        "terminal_disposition": (
            ("coordinator_non_terminal",)
            if candidate.status not in _CANONICAL_TERMINAL_STATUSES
            else ("coordinator_terminal_mapping",)
        ),
    }


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


def _issues_for_candidate(
    candidate: LegacyWorkCandidate,
    issues: tuple[ReconciliationIssue, ...],
) -> tuple[ReconciliationIssue, ...]:
    return tuple(
        issue
        for issue in issues
        if _issue_affects_record(issue, candidate.legacy_id)
        and issue.source_system in {candidate.source_system, "cross_source"}
    )


def _issues_for_raw_next_task(
    record: _RawNextTaskRecord,
    issues: tuple[ReconciliationIssue, ...],
) -> tuple[ReconciliationIssue, ...]:
    return tuple(
        issue
        for issue in issues
        if issue.source_system in {"next_tasks", "cross_source"}
        and (
            (
                issue.source_system == "next_tasks"
                and issue.record_index is not None
                and issue.record_index == record.index
            )
            or (
                (
                    issue.source_system != "next_tasks"
                    or issue.record_index is None
                )
                and bool(record.task_id)
                and _issue_affects_record(issue, record.task_id)
            )
        )
    )


def _parent_topology_issues(
    candidate: LegacyWorkCandidate,
    issues: tuple[ReconciliationIssue, ...],
) -> tuple[ReconciliationIssue, ...]:
    parent_id = candidate.request.parent_id
    if parent_id is None:
        return ()
    return tuple(
        issue
        for issue in issues
        if issue.code in _PARENT_UNREPRESENTABLE_ISSUES
        and _issue_affects_record(issue, parent_id)
    )


def _issue_affects_record(
    issue: ReconciliationIssue,
    record_id: str,
) -> bool:
    if issue.affected_record_ids:
        return record_id in issue.affected_record_ids
    return issue.record_id == record_id


def _candidate_identity_is_unrepresentable(
    candidate: LegacyWorkCandidate,
    issues: tuple[ReconciliationIssue, ...],
) -> bool:
    return any(
        issue.code in {"duplicate_id", "duplicate_idempotency_key"}
        for issue in _issues_for_candidate(candidate, issues)
    )


def _reconciliation_issues_for_dimension(
    dimension: str,
    issues: tuple[ReconciliationIssue, ...],
) -> tuple[ReconciliationIssue, ...]:
    return tuple(
        issue
        for issue in issues
        if dimension
        in _RECONCILIATION_AFFECTED_DIMENSIONS.get(
            issue.code,
            frozenset(),
        )
    )


def _selection_difference(
    legacy: ShadowSelectionView,
    coordinator: ShadowSelectionView,
    comparisons: tuple[ShadowCandidateComparison, ...],
) -> ShadowSelectionDifference | None:
    if legacy.selected_candidate_ref == coordinator.selected_candidate_ref:
        return None
    selected_refs = tuple(
        dict.fromkeys(
            ref
            for ref in (
                legacy.selected_candidate_ref,
                coordinator.selected_candidate_ref,
            )
            if ref is not None
        )
    )
    selected_comparisons = tuple(
        comparison
        for selected_ref in selected_refs
        for comparison in comparisons
        if comparison.candidate_ref == selected_ref
    )
    eligibility_dimensions = tuple(
        dimension
        for comparison in selected_comparisons
        if comparison.legacy_eligible != comparison.coordinator_eligible
        for dimension in comparison.dimensions
        if not dimension.matches
        and dimension.name
        in {
            "readiness",
            "capability",
            "attestation",
            "claim_ownership",
            "lease_expiry",
            "dispatch_lane",
            "preferred_agent",
            "parent",
            "deadline",
            "terminal_disposition",
        }
    )
    deadline_dimensions = tuple(
        dimension
        for comparison in selected_comparisons
        for dimension in comparison.dimensions
        if not dimension.matches
        if dimension.name == "deadline"
    )
    # Winner changes are caused first by admission, then by ordering.  Other
    # per-candidate semantic differences remain in the ledger but must not
    # accidentally mask the selector decision that actually changed the winner.
    selected_dimensions = eligibility_dimensions or deadline_dimensions
    if not selected_dimensions:
        return ShadowSelectionDifference(
            legacy_selected_candidate_ref=legacy.selected_candidate_ref,
            coordinator_selected_candidate_ref=coordinator.selected_candidate_ref,
            classification="policy_change",
            classification_reason_code="coordinator_ranking_contract",
            evidence_refs=(
                "contract://work-selection/selection-outcome",
                "contract://work-selection/priority",
                f"snapshot://sha256/{legacy.snapshot_sha256}",
                (
                    "oracle://work-selection/"
                    "coordinator_ranking_contract"
                ),
                "selector://legacy/legacy_priority_then_id_rank",
                (
                    "selector://work-coordinator/"
                    "coordinator_priority_deadline_created_id_rank"
                ),
            ),
        )
    classifications = {
        dimension.classification
        for dimension in selected_dimensions
        if dimension.classification is not None
    }
    if "legacy_corruption" in classifications:
        classification = "legacy_corruption"
    elif "implementation_bug" in classifications:
        classification = "implementation_bug"
    elif "policy_change" in classifications:
        classification = "policy_change"
    else:
        classification = "implementation_bug"
    classification_reason_code = next(
        (
            dimension.classification_reason_code
            for dimension in selected_dimensions
            if dimension.classification == classification
            and dimension.classification_reason_code is not None
        ),
        "unexplained_selection_difference",
    )
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
        classification_reason_code=classification_reason_code,
        evidence_refs=evidence_refs,
    )


def _selection_view(
    policy: str,
    snapshot_sha256: str,
    *,
    selected_id: str | None,
    eligible_ids: tuple[str, ...],
) -> ShadowSelectionView:
    refs = tuple(
        _next_task_candidate_ref(task_id)
        for task_id in eligible_ids
    )
    return ShadowSelectionView(
        policy=policy,
        snapshot_sha256=snapshot_sha256,
        selected_candidate_ref=(
            None
            if selected_id is None
            else _next_task_candidate_ref(selected_id)
        ),
        eligible_candidate_refs=refs,
    )


def _next_task_candidate_ref(task_id: str) -> str:
    return f"legacy://next_tasks/{quote(task_id, safe='')}"


_ARCHIVED_TOMBSTONE_NOTICE_CODES = frozenset(
    {"invalid_lifecycle", "invalid_record", "unknown_kind", "unknown_source"}
)


def _terminal_history_indexes(
    records: tuple[_RawNextTaskRecord, ...],
    issues: tuple[ReconciliationIssue, ...],
) -> frozenset[int]:
    """Return exact terminal rows that cannot own executable work."""

    indexes: set[int] = set()
    for record in records:
        task = record.task
        if (
            not record.task_id
            or str(task.get("status") or "").strip().lower()
            not in _LEGACY_TERMINAL_OUTCOME
        ):
            continue
        row_issues = _issues_for_raw_next_task(record, issues)
        if any(
            issue.code not in _ARCHIVED_TOMBSTONE_NOTICE_CODES
            for issue in row_issues
        ):
            continue
        indexes.add(record.index)
    return frozenset(indexes)


def _without_terminal_history_issues(
    issues: tuple[ReconciliationIssue, ...],
    *,
    raw_records: tuple[_RawNextTaskRecord, ...],
    terminal_history_indexes: frozenset[int],
) -> tuple[ReconciliationIssue, ...]:
    archived_issues = {
        issue
        for index in terminal_history_indexes
        for issue in _issues_for_raw_next_task(raw_records[index], issues)
        if issue.code in _ARCHIVED_TOMBSTONE_NOTICE_CODES
    }
    archived_ids = {
        raw_records[index].task_id for index in terminal_history_indexes
    }
    terminal_parent_issues = {
        issue
        for issue in issues
        if issue.code == "unrepresentable_parent"
        and any(
            raw_record.task_id == issue.record_id
            and raw_record.task.get("parent_task_id") in archived_ids
            for raw_record in raw_records
        )
    }
    return tuple(
        issue
        for issue in issues
        if issue not in archived_issues
        and issue not in terminal_parent_issues
    )


def _terminal_dependency_candidate(
    record: _RawNextTaskRecord,
) -> LegacyWorkCandidate:
    """Project an archived terminal row only as dependency disposition."""

    task = record.task
    raw_status = str(task["status"]).strip().lower()
    outcome = _LEGACY_TERMINAL_OUTCOME[raw_status]
    finished_at = next(
        (
            str(task[field])
            for field in ("completed_at", "finished_at", "updated_at")
            if task.get(field)
        ),
        None,
    )
    created_at = next(
        (
            str(task[field])
            for field in ("created_at", "completed_at", "finished_at", "updated_at")
            if task.get(field)
        ),
        "1970-01-01T00:00:00+00:00",
    )
    return LegacyWorkCandidate(
        source_system="next_tasks_terminal_dependency",
        legacy_id=record.task_id,
        request=WorkRequest(
            idempotency_key=f"legacy-terminal:{record.task_id}",
            source="agent",
            kind="dependency_receipt",
            title=str(task.get("title") or record.task_id),
            priority=4,
            required_capabilities=frozenset(),
            required_attestations=frozenset(),
            risk="safe",
            approval="auto",
            payload_ref=f"legacy://next_tasks/{quote(record.task_id, safe='')}",
        ),
        status=outcome,
        legacy_status=raw_status,
        legacy_source=str(task.get("source") or ""),
        source_classification="archived_terminal_dependency",
        created_at=created_at,
        created_at_observed_not_after=None,
        creation_sort_time=created_at,
        finished_at=finished_at,
    )


def _raw_next_task_records(
    tasks: tuple[dict[str, Any], ...],
) -> tuple[_RawNextTaskRecord, ...]:
    identities = tuple(task_identity(task) for task in tasks)
    counts = Counter(identities)
    records: list[_RawNextTaskRecord] = []
    for index, (task, task_id) in enumerate(
        zip(tasks, identities, strict=True)
    ):
        if task_id and counts[task_id] == 1:
            candidate_ref = _next_task_candidate_ref(task_id)
        else:
            digest = hashlib.sha256(
                json.dumps(
                    task,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            identity_segment = quote(task_id or "_missing-id", safe="")
            candidate_ref = (
                f"legacy://next_tasks/{identity_segment}"
                f"?record_index={index}&sha256={digest}"
            )
        records.append(
            _RawNextTaskRecord(
                index=index,
                task=task,
                task_id=task_id,
                candidate_ref=candidate_ref,
            )
        )
    return tuple(records)


def _migration_unavailable_evidence_ref(
    record: _RawNextTaskRecord,
) -> str:
    identity_segment = quote(record.task_id or "_missing-id", safe="")
    return (
        f"migration://next_tasks/{identity_segment}/"
        f"record-{record.index}/candidate-not-emitted"
    )


def _candidate_ref(candidate: LegacyWorkCandidate) -> str:
    return (
        f"legacy://{candidate.source_system}/"
        f"{quote(candidate.legacy_id, safe='')}"
    )


def _issue_evidence_ref(issue: ReconciliationIssue) -> str:
    if issue.affected_record_ids:
        query = "&".join(
            f"record_id={quote(record_id, safe='')}"
            for record_id in issue.affected_record_ids
        )
        return (
            f"reconciliation://{issue.source_system}/_records/"
            f"{quote(issue.code, safe='')}?{query}"
        )
    if issue.record_index is not None and issue.record_id is not None:
        record_path = (
            f"{quote(issue.record_id, safe='')}/record-{issue.record_index}"
        )
    elif issue.record_index is not None:
        record_path = f"_record_{issue.record_index}"
    else:
        record_path = quote(issue.record_id or "_snapshot", safe="")
    return (
        f"reconciliation://{issue.source_system}/"
        f"{record_path}/{quote(issue.code, safe='')}"
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
    "is_registered_policy_change",
    "ShadowCandidateComparison",
    "ShadowDimensionComparison",
    "ShadowReplayLedger",
    "ShadowSelectionDifference",
    "ShadowSelectionView",
    "ShadowSnapshotIdentity",
    "freeze_legacy_snapshots",
    "identify_legacy_snapshots",
    "replay_legacy_selection",
]
