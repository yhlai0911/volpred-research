"""Operations Core producer for durable silent-loss retirement evidence."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from volpred.ops.delivery.supabase_rpc import (
    ServiceRoleRpcClient,
    runtime_environment,
)
from volpred.ops.legacy_retirement import LegacyRetirementInputError
from volpred.ops.legacy_retirement_events import (
    _dimension_materialization_lock,
    _previous_dimension_signal,
    _write_typed_signal,
)

_DIMENSION = "silent_loss"
_RPC_SCHEMA = "silent-loss-retirement-events.v1"
_SIGNAL_SCHEMA = "legacy-retirement-signal.v1"
_VIOLATION_KINDS = frozenset(
    {
        "submitted_event_missing",
        "deadline_missed",
        "terminal_receipt_missing",
        "terminal_receipt_mismatch",
        "receipt_without_terminal_state",
        "active_event_missing",
        "terminal_event_missing",
    }
)
_WORK_STATUSES = frozenset(
    {
        "awaiting_approval",
        "pending",
        "claimed",
        "running",
        "succeeded",
        "failed",
        "blocked",
        "cancelled",
    }
)


def _timestamp(value: object, *, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise LegacyRetirementInputError(f"{field} must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise LegacyRetirementInputError(
            f"{field} must be an ISO timestamp"
        ) from error
    if parsed.tzinfo is None:
        raise LegacyRetirementInputError(f"{field} must include a timezone")
    return parsed.astimezone(UTC)


def _client() -> ServiceRoleRpcClient:
    environment = runtime_environment()
    return ServiceRoleRpcClient(
        supabase_url=environment.get("SUPABASE_URL", ""),
        service_role_key=environment.get("SUPABASE_SERVICE_ROLE_KEY", ""),
    )


def _materialize_locked(
    root: Path,
    *,
    rpc_client: ServiceRoleRpcClient,
) -> Path:
    previous = _previous_dimension_signal(root, _DIMENSION)
    after_sequence = 0
    window_from: datetime | None = None
    if previous is not None:
        if (
            previous.get("schema_version") != _SIGNAL_SCHEMA
            or previous.get("dimension") != _DIMENSION
            or previous.get("producer") != "operations_core"
        ):
            raise LegacyRetirementInputError(
                "previous silent-loss signal identity drifted"
            )
        watermark = previous.get("high_watermark")
        if isinstance(watermark, bool) or not isinstance(watermark, int):
            raise LegacyRetirementInputError(
                "previous silent-loss watermark is invalid"
            )
        after_sequence = watermark
        window_from = _timestamp(
            previous.get("window_to"),
            field="silent-loss previous window_to",
        )

    raw = rpc_client.call(
        "volpred_reconcile_silent_loss_retirement_events",
        {"p_after_sequence": after_sequence},
    )
    if not isinstance(raw, Mapping) or set(raw) != {
        "schema_version",
        "observed_at",
        "after_sequence",
        "high_watermark",
        "events",
        "active_violations",
    }:
        raise LegacyRetirementInputError(
            "silent-loss RPC response schema is invalid"
        )
    if (
        raw.get("schema_version") != _RPC_SCHEMA
        or raw.get("after_sequence") != after_sequence
    ):
        raise LegacyRetirementInputError(
            "silent-loss RPC cursor identity drifted"
        )
    observed_at = _timestamp(
        raw.get("observed_at"),
        field="silent-loss observed_at",
    )
    high_watermark = raw.get("high_watermark")
    events = raw.get("events")
    active_violations = raw.get("active_violations")
    if (
        isinstance(high_watermark, bool)
        or not isinstance(high_watermark, int)
        or high_watermark < after_sequence
        or not isinstance(events, list)
        or not isinstance(active_violations, list)
        or len(events) != high_watermark - after_sequence
    ):
        raise LegacyRetirementInputError(
            "silent-loss RPC sequence coverage is invalid"
        )

    evidence_by_sequence: dict[int, str] = {}
    earliest_event: datetime | None = None

    def validate_event(
        event: object,
        *,
        expected_sequence: int | None,
    ) -> tuple[int, datetime, str]:
        if not isinstance(event, Mapping) or set(event) != {
            "sequence",
            "work_id",
            "work_version",
            "violation_kind",
            "work_status",
            "deadline",
            "detected_at",
        }:
            raise LegacyRetirementInputError(
                "silent-loss RPC event schema is invalid"
            )
        sequence = event.get("sequence")
        work_id = event.get("work_id")
        work_version = event.get("work_version")
        violation_kind = event.get("violation_kind")
        work_status = event.get("work_status")
        deadline_raw = event.get("deadline")
        detected_at = _timestamp(
            event.get("detected_at"),
            field="silent-loss detected_at",
        )
        deadline = (
            None
            if deadline_raw is None
            else _timestamp(deadline_raw, field="silent-loss deadline")
        )
        if (
            isinstance(sequence, bool)
            or not isinstance(sequence, int)
            or sequence <= 0
            or sequence > high_watermark
            or (
                expected_sequence is not None
                and sequence != expected_sequence
            )
            or not isinstance(work_id, str)
            or not work_id.strip()
            or isinstance(work_version, bool)
            or not isinstance(work_version, int)
            or work_version <= 0
            or violation_kind not in _VIOLATION_KINDS
            or work_status not in _WORK_STATUSES
            or detected_at > observed_at
            or (
                violation_kind == "deadline_missed"
                and (deadline is None or deadline >= detected_at)
            )
        ):
            raise LegacyRetirementInputError(
                "silent-loss RPC event identity is invalid"
            )
        identity = hashlib.sha256(work_id.encode("utf-8")).hexdigest()
        evidence_ref = (
            "operations-core-work://silent-loss/"
            f"{sequence}/{identity}/{violation_kind}"
        )
        return sequence, detected_at, evidence_ref

    expected_sequence = after_sequence + 1
    for event in events:
        sequence, detected_at, evidence_ref = validate_event(
            event,
            expected_sequence=expected_sequence,
        )
        evidence_by_sequence[sequence] = evidence_ref
        earliest_event = min(detected_at, earliest_event or detected_at)
        expected_sequence += 1

    previous_active_sequence = 0
    for event in active_violations:
        sequence, detected_at, evidence_ref = validate_event(
            event,
            expected_sequence=None,
        )
        if sequence <= previous_active_sequence:
            raise LegacyRetirementInputError(
                "silent-loss active violation order is invalid"
            )
        previous_active_sequence = sequence
        evidence_by_sequence[sequence] = evidence_ref
        earliest_event = min(detected_at, earliest_event or detected_at)

    if window_from is None:
        window_from = earliest_event or observed_at
    if window_from > observed_at:
        raise LegacyRetirementInputError(
            "silent-loss signal interval regressed"
        )
    evidence_refs = [
        evidence_by_sequence[sequence]
        for sequence in sorted(evidence_by_sequence)
    ]
    if not evidence_refs:
        evidence_refs = [
            (
                "operations-core-work://silent-loss/high-watermark/"
                f"{high_watermark}/backend/{rpc_client.backend_sha256}"
            )
        ]
    signal: dict[str, object] = {
        "schema_version": _SIGNAL_SCHEMA,
        "dimension": _DIMENSION,
        "producer": "operations_core",
        "observed_at": observed_at.isoformat(),
        "window_from": window_from.isoformat(),
        "window_to": observed_at.isoformat(),
        "count": len(evidence_by_sequence),
        "high_watermark": high_watermark,
        "evidence_refs": evidence_refs,
    }
    return _write_typed_signal(
        root,
        dimension=_DIMENSION,
        signal=signal,
    )


def materialize_silent_loss_signal(
    root: Path,
    *,
    rpc_client: ServiceRoleRpcClient | None = None,
) -> Path:
    """Reconcile the DB ledger and atomically publish its interval signal."""

    repo_root = Path(root)
    client = rpc_client or _client()
    with _dimension_materialization_lock(repo_root, _DIMENSION):
        return _materialize_locked(repo_root, rpc_client=client)


__all__ = ["materialize_silent_loss_signal"]
