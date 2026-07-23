"""Fail-closed assessment of append-only Work Coordinator shadow receipts.

The assessor is deliberately separate from replay and cutover.  It reads only
caller-supplied receipt files and returns evidence about whether the required
observation window is complete; it never reads or mutates the live queue.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .work_shadow_replay import is_registered_policy_change

_REQUIRED_SCHEMA = "work-shadow-replay.v3"
REQUIRED_OBSERVATION_WINDOW = timedelta(days=7)
MAX_OBSERVATION_GAP = timedelta(hours=26)
MAX_REPLAY_CLOCK_SKEW = timedelta(minutes=5)
_REQUIRED_SOURCE_COUNTS = frozenset(
    {"next_tasks", "task_records", "ops_jobs"}
)
_REQUIRED_DIMENSIONS = (
    "priority",
    "claim_ownership",
    "parent",
    "deadline",
    "terminal_disposition",
)
_REQUIRED_DIMENSION_SET = frozenset(_REQUIRED_DIMENSIONS)


@dataclass(frozen=True)
class ShadowObservationAssessment:
    ready_for_cutover: bool
    reason_codes: tuple[str, ...]
    observation_count: int
    covered_dimensions: tuple[str, ...]
    assessed_at: str | None = None
    queue_owner_mode: str | None = None
    queue_owner_gate_enabled: bool | None = None
    queue_owner_state_path: str | None = None
    queue_owner_state_sha256: str | None = None
    observed_from: str | None = None
    observed_through: str | None = None
    recorded_from: str | None = None
    recorded_through: str | None = None
    required_window_seconds: int = 0
    max_gap_seconds: int = 0
    max_observed_gap_seconds: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "work-shadow-assessment.v1",
            "ready_for_cutover": self.ready_for_cutover,
            "reason_codes": list(self.reason_codes),
            "observation_count": self.observation_count,
            "covered_dimensions": list(self.covered_dimensions),
            "assessed_at": self.assessed_at,
            "queue_owner_mode": self.queue_owner_mode,
            "queue_owner_gate_enabled": self.queue_owner_gate_enabled,
            "queue_owner_state_path": self.queue_owner_state_path,
            "queue_owner_state_sha256": self.queue_owner_state_sha256,
            "observed_from": self.observed_from,
            "observed_through": self.observed_through,
            "recorded_from": self.recorded_from,
            "recorded_through": self.recorded_through,
            "required_window_seconds": self.required_window_seconds,
            "max_gap_seconds": self.max_gap_seconds,
            "max_observed_gap_seconds": self.max_observed_gap_seconds,
        }


@dataclass(frozen=True)
class _AssessmentContext:
    assessed_at: datetime
    queue_owner_mode: str
    queue_owner_gate_enabled: bool | None
    queue_owner_state_path: str | None
    queue_owner_state_sha256: str | None
    required_window: timedelta
    max_gap: timedelta


def _failed_assessment(
    context: _AssessmentContext,
    *,
    reason_code: str,
    observation_count: int,
) -> ShadowObservationAssessment:
    return ShadowObservationAssessment(
        ready_for_cutover=False,
        reason_codes=(reason_code,),
        observation_count=observation_count,
        covered_dimensions=(),
        assessed_at=context.assessed_at.isoformat(),
        queue_owner_mode=context.queue_owner_mode,
        queue_owner_gate_enabled=context.queue_owner_gate_enabled,
        queue_owner_state_path=context.queue_owner_state_path,
        queue_owner_state_sha256=context.queue_owner_state_sha256,
        required_window_seconds=int(
            context.required_window.total_seconds()
        ),
        max_gap_seconds=int(context.max_gap.total_seconds()),
    )


def assess_shadow_observation_directory(
    directory: Path,
    *,
    assessed_at: datetime,
    queue_owner_mode: str,
    queue_owner_gate_enabled: bool | None = None,
    queue_owner_state_path: str | None = None,
    queue_owner_state_sha256: str | None = None,
    required_window: timedelta,
    max_gap: timedelta,
) -> ShadowObservationAssessment:
    """Assess explicit replay receipts without consulting live state."""
    context = _AssessmentContext(
        assessed_at=_aware_utc(assessed_at),
        queue_owner_mode=queue_owner_mode,
        queue_owner_gate_enabled=queue_owner_gate_enabled,
        queue_owner_state_path=queue_owner_state_path,
        queue_owner_state_sha256=queue_owner_state_sha256,
        required_window=required_window,
        max_gap=max_gap,
    )
    receipt_paths = tuple(sorted(directory.glob("*.json")))
    receipts: list[dict[str, Any]] = []
    try:
        for path in receipt_paths:
            receipt = json.loads(path.read_text(encoding="utf-8"))
            if (
                not isinstance(receipt, dict)
                or receipt.get("schema_version") != _REQUIRED_SCHEMA
                or not _receipt_shape_is_valid(receipt)
            ):
                raise ValueError("unsupported shadow receipt")
            receipts.append(receipt)
    except (OSError, ValueError, json.JSONDecodeError, TypeError):
        return _failed_assessment(
            context,
            reason_code="invalid_receipt",
            observation_count=len(receipt_paths),
        )
    snapshot_identity_mismatch = any(
        receipt["legacy_selection"]["snapshot_sha256"]
        != receipt["snapshot"]["sha256"]
        or receipt["coordinator_selection"]["snapshot_sha256"]
        != receipt["snapshot"]["sha256"]
        for receipt in receipts
    )
    if snapshot_identity_mismatch:
        return _failed_assessment(
            context,
            reason_code="snapshot_identity_mismatch",
            observation_count=len(receipt_paths),
        )
    observation_ids = tuple(
        receipt["observation_id"] for receipt in receipts
    )
    if len(set(observation_ids)) != len(observation_ids):
        return _failed_assessment(
            context,
            reason_code="duplicate_observation_id",
            observation_count=len(receipt_paths),
        )
    try:
        parsed_observed_at = tuple(
            _parse_observed_at(receipt["observed_at"])
            for receipt in receipts
        )
        parsed_recorded_at = tuple(
            _parse_observed_at(receipt["recorded_at"])
            for receipt in receipts
        )
    except (KeyError, TypeError, ValueError):
        return _failed_assessment(
            context,
            reason_code="invalid_receipt",
            observation_count=len(receipt_paths),
        )
    if len(set(parsed_observed_at)) != len(parsed_observed_at):
        return _failed_assessment(
            context,
            reason_code="duplicate_observed_at",
            observation_count=len(receipt_paths),
        )
    if len(set(parsed_recorded_at)) != len(parsed_recorded_at):
        return _failed_assessment(
            context,
            reason_code="duplicate_recorded_at",
            observation_count=len(receipt_paths),
        )
    timed_receipts = tuple(
        sorted(
            zip(
                parsed_recorded_at,
                parsed_observed_at,
                receipts,
                strict=True,
            ),
            key=lambda item: item[0],
        )
    )
    recorded_at = tuple(item[0] for item in timed_receipts)
    observed_at = tuple(item[1] for item in timed_receipts)
    receipts = [item[2] for item in timed_receipts]
    covered = {
        dimension["name"]
        for receipt in receipts
        for comparison in receipt["comparisons"]
        for dimension in comparison["dimensions"]
    }
    reasons: list[str] = []
    if queue_owner_mode != "queued_execution" or (
        queue_owner_gate_enabled is not None
        and queue_owner_gate_enabled is not False
    ):
        reasons.append("queue_owner_mode_not_queued_execution")
    if not receipts:
        reasons.append("no_observations")
    elif recorded_at[-1] - recorded_at[0] < required_window:
        reasons.append("observation_window_too_short")
    gaps = tuple(
        later - earlier
        for earlier, later in zip(recorded_at, recorded_at[1:])
    )
    if recorded_at:
        if recorded_at[-1] > context.assessed_at:
            reasons.append("observation_in_future")
        if any(gap > max_gap for gap in gaps):
            reasons.append("observation_gap_exceeded")
        if context.assessed_at - recorded_at[-1] > max_gap:
            reasons.append("observation_stale")
    if any(
        recorded < observed
        or recorded - observed > MAX_REPLAY_CLOCK_SKEW
        for recorded, observed in zip(
            recorded_at,
            observed_at,
            strict=True,
        )
    ):
        reasons.append("replay_clock_not_live")
    missing_dimensions = tuple(
        name for name in _REQUIRED_DIMENSIONS if name not in covered
    )
    if missing_dimensions:
        reasons.append("missing_reconciliation_dimension")
    if any(
        len(receipt["comparisons"])
        != receipt["snapshot"]["source_counts"]["next_tasks"]
        for receipt in receipts
    ):
        reasons.append("receipt_row_count_mismatch")
    if any(
        len(
            [
                comparison["candidate_ref"]
                for comparison in receipt["comparisons"]
            ]
        )
        != len(
            {
                comparison["candidate_ref"]
                for comparison in receipt["comparisons"]
            }
        )
        for receipt in receipts
    ):
        reasons.append("duplicate_candidate_identity")
    if any(
        not _REQUIRED_DIMENSION_SET.issubset(
            {
                dimension["name"]
                for dimension in comparison["dimensions"]
            }
        )
        for receipt in receipts
        for comparison in receipt["comparisons"]
    ):
        reasons.append("candidate_dimension_incomplete")
    if any(
        not _selection_evidence_is_consistent(receipt)
        for receipt in receipts
    ):
        reasons.append("selection_evidence_mismatch")
    if any(
        isinstance(receipt.get("selection_difference"), dict)
        and receipt["selection_difference"].get("classification")
        != "policy_change"
        for receipt in receipts
    ):
        reasons.append("blocking_selection_difference")
    if any(
        receipt.get("reconciliation_issues")
        for receipt in receipts
    ):
        reasons.append("reconciliation_issue_present")
    if _has_unregistered_policy_change(receipts):
        reasons.append("unregistered_policy_change")
    if any(
        dimension.get("matches") is False
        and dimension.get("classification") != "policy_change"
        for receipt in receipts
        for comparison in receipt["comparisons"]
        for dimension in comparison["dimensions"]
    ):
        reasons.append("blocking_dimension_difference")
    return ShadowObservationAssessment(
        ready_for_cutover=not reasons,
        reason_codes=tuple(reasons),
        observation_count=len(receipts),
        covered_dimensions=tuple(
            name for name in _REQUIRED_DIMENSIONS if name in covered
        ),
        assessed_at=context.assessed_at.isoformat(),
        queue_owner_mode=queue_owner_mode,
        queue_owner_gate_enabled=queue_owner_gate_enabled,
        queue_owner_state_path=queue_owner_state_path,
        queue_owner_state_sha256=queue_owner_state_sha256,
        observed_from=(
            observed_at[0].isoformat() if observed_at else None
        ),
        observed_through=(
            observed_at[-1].isoformat() if observed_at else None
        ),
        recorded_from=(
            recorded_at[0].isoformat() if recorded_at else None
        ),
        recorded_through=(
            recorded_at[-1].isoformat() if recorded_at else None
        ),
        required_window_seconds=int(required_window.total_seconds()),
        max_gap_seconds=int(max_gap.total_seconds()),
        max_observed_gap_seconds=(
            int(max(gaps).total_seconds()) if gaps else None
        ),
    )


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("assessed_at must be timezone-aware")
    return value.astimezone(timezone.utc)


def _parse_observed_at(raw: Any) -> datetime:
    if not isinstance(raw, str):
        raise ValueError("observed_at must be an ISO-8601 string")
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    return _aware_utc(parsed)


def _receipt_shape_is_valid(receipt: dict[str, Any]) -> bool:
    if (
        not isinstance(receipt.get("observation_id"), str)
        or not receipt["observation_id"]
        or not isinstance(receipt.get("observed_at"), str)
        or not receipt["observed_at"]
        or not isinstance(receipt.get("recorded_at"), str)
        or not receipt["recorded_at"]
    ):
        return False
    if receipt.get("selection_scope") != "next_tasks":
        return False
    snapshot = receipt.get("snapshot")
    if not isinstance(snapshot, dict):
        return False
    sha256 = snapshot.get("sha256")
    if (
        not isinstance(sha256, str)
        or len(sha256) != 64
        or any(character not in "0123456789abcdef" for character in sha256)
    ):
        return False
    byte_count = snapshot.get("byte_count")
    if (
        isinstance(byte_count, bool)
        or not isinstance(byte_count, int)
        or byte_count < 0
    ):
        return False
    source_counts = snapshot.get("source_counts")
    if (
        not isinstance(source_counts, dict)
        or set(source_counts) != _REQUIRED_SOURCE_COUNTS
        or any(
            isinstance(count, bool)
            or not isinstance(count, int)
            or count < 0
            for count in source_counts.values()
        )
    ):
        return False
    for selection_name in ("legacy_selection", "coordinator_selection"):
        selection = receipt.get(selection_name)
        if (
            not isinstance(selection, dict)
            or not isinstance(selection.get("snapshot_sha256"), str)
            or (
                selection.get("selected_candidate_ref") is not None
                and not isinstance(
                    selection.get("selected_candidate_ref"),
                    str,
                )
            )
            or not isinstance(
                selection.get("eligible_candidate_refs"),
                list,
            )
            or not all(
                isinstance(reference, str) and reference
                for reference in selection.get(
                    "eligible_candidate_refs",
                    [],
                )
            )
        ):
            return False
    comparisons = receipt.get("comparisons")
    if not isinstance(comparisons, list):
        return False
    for comparison in comparisons:
        if (
            not isinstance(comparison, dict)
            or not isinstance(comparison.get("candidate_ref"), str)
            or not comparison["candidate_ref"]
            or not isinstance(comparison.get("legacy_eligible"), bool)
            or not isinstance(
                comparison.get("coordinator_eligible"),
                bool,
            )
        ):
            return False
        dimensions = comparison.get("dimensions")
        if not isinstance(dimensions, list):
            return False
        for dimension in dimensions:
            if (
                not isinstance(dimension, dict)
                or not isinstance(dimension.get("name"), str)
                or not isinstance(dimension.get("matches"), bool)
            ):
                return False
    if not isinstance(receipt.get("reconciliation_issues"), list):
        return False
    selection_difference = receipt.get("selection_difference")
    return selection_difference is None or isinstance(
        selection_difference,
        dict,
    )


def _dimension_policy_change_is_registered(
    payload: dict[str, Any],
    *,
    candidate_ref: str,
    snapshot_sha256: str,
) -> bool:
    reason_code = payload.get("classification_reason_code")
    evidence_refs = payload.get("evidence_refs")
    legacy_reason_codes = payload.get("legacy_reason_codes")
    coordinator_reason_codes = payload.get(
        "coordinator_reason_codes"
    )
    return (
        isinstance(reason_code, str)
        and bool(reason_code)
        and isinstance(evidence_refs, list)
        and bool(evidence_refs)
        and isinstance(legacy_reason_codes, list)
        and isinstance(coordinator_reason_codes, list)
        and all(
            isinstance(reference, str) and bool(reference)
            for reference in evidence_refs
        )
        and all(
            isinstance(code, str) and bool(code)
            for code in (
                *legacy_reason_codes,
                *coordinator_reason_codes,
            )
        )
        and is_registered_policy_change(
            dimension=payload["name"],
            reason_code=reason_code,
            legacy_reason_codes=tuple(legacy_reason_codes),
            coordinator_reason_codes=tuple(
                coordinator_reason_codes
            ),
            evidence_refs=tuple(evidence_refs),
            candidate_ref=candidate_ref,
            snapshot_sha256=snapshot_sha256,
        )
    )


def _has_unregistered_policy_change(
    receipts: list[dict[str, Any]],
) -> bool:
    for receipt in receipts:
        snapshot_sha256 = receipt["snapshot"]["sha256"]
        valid_dimension_reasons: dict[str, set[str]] = {}
        for comparison in receipt["comparisons"]:
            for dimension in comparison["dimensions"]:
                if (
                    dimension.get("matches") is not False
                    or dimension.get("classification") != "policy_change"
                ):
                    continue
                if not _dimension_policy_change_is_registered(
                    dimension,
                    candidate_ref=comparison["candidate_ref"],
                    snapshot_sha256=snapshot_sha256,
                ):
                    return True
                valid_dimension_reasons.setdefault(
                    comparison["candidate_ref"],
                    set(),
                ).add(
                    dimension["classification_reason_code"]
                )
        selection = receipt.get("selection_difference")
        if (
            not isinstance(selection, dict)
            or selection.get("classification") != "policy_change"
        ):
            continue
        reason_code = selection.get("classification_reason_code")
        evidence_refs = selection.get("evidence_refs")
        if (
            selection.get("legacy_selected_candidate_ref")
            == selection.get("coordinator_selected_candidate_ref")
            or not isinstance(reason_code, str)
            or not isinstance(evidence_refs, list)
            or not all(
                isinstance(reference, str) and reference
                for reference in evidence_refs
            )
        ):
            return True
        if reason_code == "coordinator_ranking_contract":
            if not is_registered_policy_change(
                dimension=None,
                reason_code=reason_code,
                legacy_reason_codes=(),
                coordinator_reason_codes=(),
                evidence_refs=tuple(evidence_refs),
                candidate_ref=None,
                snapshot_sha256=snapshot_sha256,
            ):
                return True
            continue
        selected_refs = {
            reference
            for reference in (
                selection.get("legacy_selected_candidate_ref"),
                selection.get("coordinator_selected_candidate_ref"),
            )
            if isinstance(reference, str)
        }
        if not any(
            reason_code
            in valid_dimension_reasons.get(reference, set())
            for reference in selected_refs
        ):
            return True
        if {
            "contract://work-selection/selection-outcome",
            f"snapshot://sha256/{snapshot_sha256}",
            f"oracle://work-selection/{reason_code}",
        } - set(evidence_refs):
            return True
    return False


def _selection_evidence_is_consistent(
    receipt: dict[str, Any],
) -> bool:
    candidate_refs = {
        comparison["candidate_ref"]
        for comparison in receipt["comparisons"]
    }
    legacy = receipt["legacy_selection"]
    coordinator = receipt["coordinator_selection"]
    expected_eligible = (
        {
            comparison["candidate_ref"]
            for comparison in receipt["comparisons"]
            if comparison["legacy_eligible"]
        },
        {
            comparison["candidate_ref"]
            for comparison in receipt["comparisons"]
            if comparison["coordinator_eligible"]
        },
    )
    for selection, expected in zip(
        (legacy, coordinator),
        expected_eligible,
        strict=True,
    ):
        eligible_refs = selection["eligible_candidate_refs"]
        eligible = set(eligible_refs)
        selected = selection["selected_candidate_ref"]
        if (
            len(eligible_refs) != len(eligible)
            or eligible != expected
            or not eligible.issubset(candidate_refs)
        ):
            return False
        if (selected is None) != (not eligible):
            return False
        if selected is not None and (
            selected not in candidate_refs
            or selected not in eligible
        ):
            return False
    legacy_selected = legacy["selected_candidate_ref"]
    coordinator_selected = coordinator["selected_candidate_ref"]
    difference = receipt.get("selection_difference")
    if legacy_selected == coordinator_selected:
        return difference is None
    return (
        isinstance(difference, dict)
        and difference.get("legacy_selected_candidate_ref")
        == legacy_selected
        and difference.get("coordinator_selected_candidate_ref")
        == coordinator_selected
    )


__all__ = [
    "MAX_OBSERVATION_GAP",
    "MAX_REPLAY_CLOCK_SKEW",
    "REQUIRED_OBSERVATION_WINDOW",
    "ShadowObservationAssessment",
    "assess_shadow_observation_directory",
]
