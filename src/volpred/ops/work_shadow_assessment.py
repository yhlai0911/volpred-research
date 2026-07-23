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

_REQUIRED_SCHEMA = "work-shadow-replay.v2"
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


@dataclass(frozen=True)
class ShadowObservationAssessment:
    ready_for_cutover: bool
    reason_codes: tuple[str, ...]
    observation_count: int
    covered_dimensions: tuple[str, ...]
    assessed_at: str | None = None
    queue_owner_mode: str | None = None
    observed_from: str | None = None
    observed_through: str | None = None
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
            "observed_from": self.observed_from,
            "observed_through": self.observed_through,
            "required_window_seconds": self.required_window_seconds,
            "max_gap_seconds": self.max_gap_seconds,
            "max_observed_gap_seconds": self.max_observed_gap_seconds,
        }


def assess_shadow_observation_directory(
    directory: Path,
    *,
    assessed_at: datetime,
    queue_owner_mode: str,
    required_window: timedelta,
    max_gap: timedelta,
) -> ShadowObservationAssessment:
    """Assess explicit replay receipts without consulting live state."""
    assessed_at = _aware_utc(assessed_at)
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
        return ShadowObservationAssessment(
            ready_for_cutover=False,
            reason_codes=("invalid_receipt",),
            observation_count=len(receipt_paths),
            covered_dimensions=(),
            assessed_at=assessed_at.isoformat(),
            queue_owner_mode=queue_owner_mode,
            required_window_seconds=int(required_window.total_seconds()),
            max_gap_seconds=int(max_gap.total_seconds()),
        )
    try:
        snapshot_identity_mismatch = any(
            receipt["legacy_selection"]["snapshot_sha256"]
            != receipt["snapshot"]["sha256"]
            or receipt["coordinator_selection"]["snapshot_sha256"]
            != receipt["snapshot"]["sha256"]
            for receipt in receipts
        )
    except (KeyError, TypeError):
        return ShadowObservationAssessment(
            ready_for_cutover=False,
            reason_codes=("invalid_receipt",),
            observation_count=len(receipt_paths),
            covered_dimensions=(),
            assessed_at=assessed_at.isoformat(),
            queue_owner_mode=queue_owner_mode,
            required_window_seconds=int(required_window.total_seconds()),
            max_gap_seconds=int(max_gap.total_seconds()),
        )
    if snapshot_identity_mismatch:
        return ShadowObservationAssessment(
            ready_for_cutover=False,
            reason_codes=("snapshot_identity_mismatch",),
            observation_count=len(receipt_paths),
            covered_dimensions=(),
            assessed_at=assessed_at.isoformat(),
            queue_owner_mode=queue_owner_mode,
            required_window_seconds=int(required_window.total_seconds()),
            max_gap_seconds=int(max_gap.total_seconds()),
        )
    observation_ids = tuple(
        receipt.get("observation_id") for receipt in receipts
    )
    if (
        any(
            not isinstance(observation_id, str) or not observation_id
            for observation_id in observation_ids
        )
        or len(set(observation_ids)) != len(observation_ids)
    ):
        return ShadowObservationAssessment(
            ready_for_cutover=False,
            reason_codes=("duplicate_observation_id",),
            observation_count=len(receipt_paths),
            covered_dimensions=(),
            assessed_at=assessed_at.isoformat(),
            queue_owner_mode=queue_owner_mode,
            required_window_seconds=int(required_window.total_seconds()),
            max_gap_seconds=int(max_gap.total_seconds()),
        )
    try:
        parsed_observed_at = tuple(
            _parse_observed_at(receipt["observed_at"])
            for receipt in receipts
        )
    except (KeyError, TypeError, ValueError):
        return ShadowObservationAssessment(
            ready_for_cutover=False,
            reason_codes=("invalid_receipt",),
            observation_count=len(receipt_paths),
            covered_dimensions=(),
            assessed_at=assessed_at.isoformat(),
            queue_owner_mode=queue_owner_mode,
            required_window_seconds=int(required_window.total_seconds()),
            max_gap_seconds=int(max_gap.total_seconds()),
        )
    if len(set(parsed_observed_at)) != len(parsed_observed_at):
        return ShadowObservationAssessment(
            ready_for_cutover=False,
            reason_codes=("duplicate_observed_at",),
            observation_count=len(receipt_paths),
            covered_dimensions=(),
            assessed_at=assessed_at.isoformat(),
            queue_owner_mode=queue_owner_mode,
            required_window_seconds=int(required_window.total_seconds()),
            max_gap_seconds=int(max_gap.total_seconds()),
        )
    timed_receipts = tuple(
        sorted(
            zip(parsed_observed_at, receipts, strict=True),
            key=lambda item: item[0],
        )
    )
    observed_at = tuple(item[0] for item in timed_receipts)
    receipts = [item[1] for item in timed_receipts]
    covered = {
        dimension["name"]
        for receipt in receipts
        for comparison in receipt["comparisons"]
        for dimension in comparison["dimensions"]
    }
    reasons: list[str] = []
    if queue_owner_mode != "legacy_queue_shadow":
        reasons.append("queue_owner_mode_not_legacy_shadow")
    if not receipts:
        reasons.append("no_observations")
    elif observed_at[-1] - observed_at[0] < required_window:
        reasons.append("observation_window_too_short")
    gaps = tuple(
        later - earlier
        for earlier, later in zip(observed_at, observed_at[1:])
    )
    if observed_at:
        if any(gap > max_gap for gap in gaps):
            reasons.append("observation_gap_exceeded")
        if assessed_at - observed_at[-1] > max_gap:
            reasons.append("observation_stale")
    missing_dimensions = tuple(
        name for name in _REQUIRED_DIMENSIONS if name not in covered
    )
    if missing_dimensions:
        reasons.append("missing_reconciliation_dimension")
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
        assessed_at=assessed_at.isoformat(),
        queue_owner_mode=queue_owner_mode,
        observed_from=(
            observed_at[0].isoformat() if observed_at else None
        ),
        observed_through=(
            observed_at[-1].isoformat() if observed_at else None
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
        ):
            return False
    comparisons = receipt.get("comparisons")
    if not isinstance(comparisons, list):
        return False
    for comparison in comparisons:
        if not isinstance(comparison, dict):
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


__all__ = [
    "ShadowObservationAssessment",
    "assess_shadow_observation_directory",
]
