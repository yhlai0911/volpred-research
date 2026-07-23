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

from .next_tasks import is_main_thread_reserved
from .task_pool_selection import (
    CODEX_ELIGIBLE_TASK_TYPES,
    LegacyClaimDecision,
    is_codex_owner,
    normalized_task_type,
    select_task_for_claim,
)
from .work import WorkItemView, WorkerOffer
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
_COORDINATOR_STATUS_REASONS = frozenset(
    {
        "ready_pending",
        "ready_expired_claim",
        "live_claim",
        "claim_expiry_missing",
        "status_not_acquirable",
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
    selection_candidates = tuple(
        candidate
        for candidate in report.candidates
        if candidate.source_system == "next_tasks"
    )
    legacy_inputs = tuple(
        _legacy_task_record(candidate)
        for candidate in selection_candidates
    )
    legacy_result = select_task_for_claim(
        legacy_inputs,
        owner=offer.worker_id,
        main_thread=False,
        observed_at=observed_at,
    )
    legacy_decisions = {
        decision.task_id: decision
        for decision in legacy_result.decisions
    }
    legacy_eligible_ids = frozenset(legacy_result.eligible_task_ids)
    coordinator_result = select_acquirable_work(
        tuple(
            _coordinator_item(candidate)
            for candidate in selection_candidates
        ),
        offer=offer,
        observed_at=observed_at,
    )
    coordinator_decisions = {
        decision.work_id: decision
        for decision in coordinator_result.decisions
    }
    comparisons = tuple(
        _compare_candidate(
            candidate,
            candidates=selection_candidates,
            legacy_decision=legacy_decisions[candidate.legacy_id],
            legacy_selection_eligible=(
                candidate.legacy_id in legacy_eligible_ids
            ),
            coordinator_decision=coordinator_decisions[
                candidate.legacy_id
            ],
            snapshot_sha256=snapshot.sha256,
            reconciliation_issues=report.issues,
        )
        for candidate in sorted(
            selection_candidates, key=lambda item: _candidate_ref(item)
        )
    )
    if _canonical_snapshot_bytes(snapshots) != snapshot_bytes:
        raise RuntimeError("shadow replay mutated its supplied snapshots")
    legacy_selection = _selection_view(
        "legacy",
        snapshot.sha256,
        selected_id=legacy_result.selected_task_id,
        eligible_ids=legacy_result.eligible_task_ids,
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


def _compare_candidate(
    candidate: LegacyWorkCandidate,
    *,
    candidates: tuple[LegacyWorkCandidate, ...],
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
    raw_task = _legacy_task_record(candidate)
    parent = _parent_candidate(candidate, candidates)
    coordinator_status_codes = tuple(
        code
        for code in coordinator_decision.reason_codes
        if code in _COORDINATOR_STATUS_REASONS
    )
    legacy_status_ready = legacy_decision.primary_reason not in {
        "wrong_status",
        "missing_deadline",
        "invalid_deadline",
        "deadline_expired",
        "live_revalidation_required",
    }
    coordinator_status_ready = any(
        code in {"ready_pending", "ready_expired_claim"}
        for code in coordinator_status_codes
    )
    # ``task_pool_claim`` has a task-family routing allowlist for Codex, but it
    # does not enforce Work Coordinator's declared capability set.
    legacy_capability_match = (
        legacy_decision.primary_reason != "not_codex_eligible"
    )
    coordinator_capability_match = (
        not coordinator_decision.missing_capabilities
    )
    coordinator_attestation_match = (
        not coordinator_decision.missing_attestations
    )
    lane_reserved = is_main_thread_reserved(raw_task)
    preferred_agent = (
        candidate.preferred_agent or candidate.target_agent
    )
    legacy_preferred_agent_effect = (
        preferred_agent is not None
        and is_codex_owner(legacy_decision.owner)
        and normalized_task_type(raw_task) not in CODEX_ELIGIBLE_TASK_TYPES
        and str(preferred_agent).strip().lower() == "codex"
    )

    legacy_values: dict[str, Any] = {
        "priority": {"value": candidate.request.priority},
        "readiness": legacy_status_ready,
        "capability": {"matched": legacy_capability_match},
        "attestation": {"matched": True},
        "claim_ownership": {
            "claimed_by": candidate.claimed_by,
            "blocks_claim": (
                legacy_decision.primary_reason == "already_claimed"
            ),
        },
        "lease_expiry": _legacy_lease_value(candidate),
        "dispatch_lane": {
            "value": candidate.dispatch_lane,
            "claimable": not lane_reserved,
        },
        "preferred_agent": (
            {"value": None}
            if preferred_agent is None
            else {
                "value": preferred_agent,
                "routing_effect": legacy_preferred_agent_effect,
            }
        ),
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
        "terminal_disposition": (
            {
                "terminal": True,
                "outcome": candidate.legacy_status,
            }
            if candidate.legacy_status in _LEGACY_TERMINAL_STATUSES
            else {"terminal": False}
        ),
    }
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
    reasons = _dimension_reason_codes(
        candidate,
        raw_task=raw_task,
        legacy_decision=legacy_decision,
        coordinator_decision=coordinator_decision,
        coordinator_status_codes=coordinator_status_codes,
    )
    dimensions: list[ShadowDimensionComparison] = []
    for spec in _DIMENSION_SPECS:
        legacy_value = legacy_values[spec.name]
        coordinator_value = coordinator_values[spec.name]
        legacy_reasons, coordinator_reasons = reasons[spec.name]
        matches = legacy_value == coordinator_value
        classification: str | None = None
        classification_reason: str | None = None
        dimension_issues = _reconciliation_issues_for_dimension(
            spec.name,
            candidate_issues,
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
                                    _issue_evidence_ref(
                                        issue.source_system,
                                        issue.record_id,
                                        issue.code,
                                    )
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


def _legacy_task_record(
    candidate: LegacyWorkCandidate,
) -> dict[str, Any]:
    return {
        "id": candidate.legacy_id,
        "status": candidate.legacy_status,
        "task_type": candidate.request.kind,
        "title": candidate.request.title,
        "priority": candidate.request.priority,
        "source": candidate.legacy_source,
        "created_at": candidate.created_at,
        "claimed_by": candidate.claimed_by,
        "claimed_at": candidate.claimed_at,
        "claim_expires_at": candidate.claim_expires_at,
        "dispatch_lane": candidate.dispatch_lane,
        "preferred_agent": candidate.preferred_agent,
        "target_agent": candidate.target_agent,
        "fallback_allowed": candidate.fallback_allowed,
        "ref_event_job_id": candidate.ref_event_job_id,
        "dreaming": candidate.dreaming,
        "parent_task_id": candidate.request.parent_id,
        "deadline": candidate.request.deadline,
        "required_capabilities": sorted(
            candidate.request.required_capabilities
        ),
        "required_attestations": sorted(
            candidate.request.required_attestations
        ),
    }


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
        created_at=candidate.created_at,
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


def _legacy_lease_value(
    candidate: LegacyWorkCandidate,
) -> dict[str, Any]:
    if candidate.status not in {"claimed", "running"}:
        return {"state": "none"}
    return {
        "claim_expires_at": candidate.claim_expires_at,
        "reclaim": "cleanup_pass_only",
    }


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


def _dimension_reason_codes(
    candidate: LegacyWorkCandidate,
    *,
    raw_task: dict[str, Any],
    legacy_decision: LegacyClaimDecision,
    coordinator_decision: AcquisitionCandidateDecision,
    coordinator_status_codes: tuple[str, ...],
) -> dict[str, tuple[tuple[str, ...], tuple[str, ...]]]:
    legacy_capability_reasons = (
        ("legacy_capability_not_enforced",)
        if "legacy_capability_not_enforced" in legacy_decision.policy_codes
        else ("legacy_no_capability_requirement",)
    )
    preferred_agent = (
        candidate.preferred_agent or candidate.target_agent
    )
    legacy_readiness_reasons = (
        ("legacy_blocked_status_claimable", legacy_decision.primary_reason)
        if candidate.legacy_status == "blocked"
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
    lease_legacy_reasons = (
        ("legacy_cleanup_only_reclaim", legacy_decision.primary_reason)
        if candidate.status in {"claimed", "running"}
        else ("legacy_no_active_claim",)
    )
    return {
        "priority": (
            ("legacy_priority_then_id_rank",),
            ("coordinator_priority_deadline_created_id_rank",),
        ),
        "readiness": (
            legacy_readiness_reasons,
            coordinator_status_codes,
        ),
        "capability": (
            legacy_capability_reasons,
            (
                ("coordinator_capability_enforced", "capability_mismatch")
                if coordinator_decision.missing_capabilities
                else ("coordinator_capability_enforced", "capability_match")
            ),
        ),
        "attestation": (
            (
                ("legacy_attestation_not_enforced",)
                if "legacy_attestation_not_enforced"
                in legacy_decision.policy_codes
                else ("legacy_no_attestation_requirement",)
            ),
            (
                ("coordinator_attestation_enforced", "attestation_mismatch")
                if coordinator_decision.missing_attestations
                else ("coordinator_attestation_enforced", "attestation_match")
            ),
        ),
        "claim_ownership": (
            (legacy_decision.primary_reason,),
            coordinator_status_codes,
        ),
        "lease_expiry": (
            lease_legacy_reasons,
            coordinator_status_codes,
        ),
        "dispatch_lane": (
            (
                ("main_thread_lane",)
                if is_main_thread_reserved(raw_task)
                else ("legacy_dispatch_lane_allowed",)
            ),
            (
                "coordinator_dispatch_lane_unrepresented",
                *coordinator_status_codes,
            ),
        ),
        "preferred_agent": (
            (
                ("legacy_no_preferred_agent",)
                if preferred_agent is None
                else ("legacy_preferred_agent_routing",)
            ),
            (
                ("coordinator_no_preferred_agent",)
                if preferred_agent is None
                else ("coordinator_preferred_agent_unrepresented",)
            ),
        ),
        "parent": (
            (
                ("legacy_no_parent",)
                if candidate.request.parent_id is None
                else ("legacy_parent_not_enforced",)
            ),
            (
                ("coordinator_no_parent",)
                if candidate.request.parent_id is None
                else tuple(
                    code
                    for code in coordinator_decision.reason_codes
                    if code in {"parent_missing", "parent_not_succeeded"}
                )
                or ("parent_succeeded",)
            ),
        ),
        "deadline": (
            (
                ("legacy_no_deadline",)
                if candidate.request.deadline is None
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
            (
                ("coordinator_no_deadline",)
                if candidate.request.deadline is None
                else ("coordinator_deadline_ranked",)
            ),
        ),
        "terminal_disposition": (
            (
                ("legacy_non_terminal",)
                if candidate.legacy_status
                not in _LEGACY_TERMINAL_STATUSES
                else ("legacy_terminal_mapping",)
            ),
            (
                ("coordinator_non_terminal",)
                if candidate.status not in _CANONICAL_TERMINAL_STATUSES
                else ("coordinator_terminal_mapping",)
            ),
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
        if issue.record_id is not None
        and (
            issue.record_id == candidate.legacy_id
            or candidate.legacy_id in issue.record_id.split(",")
        )
        and issue.source_system in {candidate.source_system, "cross_source"}
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
