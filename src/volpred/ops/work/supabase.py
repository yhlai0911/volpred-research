"""Service-role PostgREST read model for one Operations Core WorkItem."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
import re
from typing import Any

from volpred.ops.delivery.supabase_rpc import (
    ServiceRoleRpcClient,
    SupabaseRpcError,
    runtime_environment,
)

from . import (
    VerifiedCheckpointView,
    WorkEventView,
    WorkItemView,
    WorkQuery,
    WorkReceiptView,
    WorkSnapshot,
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


class WorkReadModelError(RuntimeError):
    """The remote Work read model returned untrusted or inconsistent data."""


def _text(
    payload: Mapping[str, Any],
    field: str,
    *,
    optional: bool = False,
) -> str | None:
    value = payload.get(field)
    if optional and value is None:
        return None
    if not isinstance(value, str) or not value:
        raise WorkReadModelError(
            f"work snapshot returned an invalid {field}"
        )
    return value


def _positive_integer(payload: Mapping[str, Any], field: str) -> int:
    value = payload.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise WorkReadModelError(
            f"work snapshot returned an invalid {field}"
        )
    return value


def _timestamp(
    payload: Mapping[str, Any],
    field: str,
    *,
    optional: bool = False,
) -> str | None:
    value = _text(payload, field, optional=optional)
    if value is None:
        return None
    try:
        observed = datetime.fromisoformat(value)
    except ValueError:
        raise WorkReadModelError(
            f"work snapshot returned an invalid {field}"
        ) from None
    if observed.tzinfo is None:
        raise WorkReadModelError(
            f"work snapshot returned an invalid {field}"
        )
    return observed.astimezone(UTC).isoformat()


def _string_set(payload: Mapping[str, Any], field: str) -> frozenset[str]:
    value = payload.get(field)
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item for item in value
    ):
        raise WorkReadModelError(
            f"work snapshot returned an invalid {field}"
        )
    return frozenset(value)


def _mapping(value: object, *, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise WorkReadModelError(
            f"work snapshot returned an invalid {field}"
        )
    return value


def _records(
    payload: Mapping[str, Any],
    field: str,
) -> tuple[Mapping[str, Any], ...]:
    value = payload.get(field)
    if not isinstance(value, list):
        raise WorkReadModelError(
            f"work snapshot returned an invalid {field}"
        )
    return tuple(
        _mapping(record, field=f"{field} record") for record in value
    )


def _item(payload: Mapping[str, Any]) -> WorkItemView:
    status = _text(payload, "status")
    if status not in _WORK_STATUSES:
        raise WorkReadModelError(
            "work snapshot returned an unsupported WorkItem lifecycle"
        )
    return WorkItemView(
        id=_text(payload, "id"),
        idempotency_key=_text(payload, "idempotency_key"),
        source=_text(payload, "source"),
        kind=_text(payload, "kind"),
        title=_text(payload, "title"),
        priority=_positive_integer(payload, "priority"),
        required_capabilities=_string_set(
            payload, "required_capabilities"
        ),
        required_attestations=_string_set(
            payload, "required_attestations"
        ),
        risk=_text(payload, "risk"),
        approval=_text(payload, "approval"),
        payload_ref=_text(payload, "payload_ref"),
        parent_id=_text(payload, "parent_id", optional=True),
        deadline=_timestamp(payload, "deadline", optional=True),
        requester_ref=_text(payload, "requester_ref"),
        status=status,
        version=_positive_integer(payload, "version"),
        created_at=_timestamp(payload, "created_at"),
        updated_at=_timestamp(payload, "updated_at", optional=True),
        blocked_reason=_text(
            payload, "blocked_reason", optional=True
        ),
        claimed_by=_text(payload, "claimed_by", optional=True),
        claim_expires_at=_timestamp(
            payload, "claim_expires_at", optional=True
        ),
        latest_verified_checkpoint_id=_text(
            payload,
            "latest_verified_checkpoint_id",
            optional=True,
        ),
        last_release_reason=_text(
            payload, "last_release_reason", optional=True
        ),
        result_ref=_text(payload, "result_ref", optional=True),
        result_summary=_text(
            payload, "result_summary", optional=True
        ),
        finished_at=_timestamp(
            payload, "finished_at", optional=True
        ),
    )


def _event(payload: Mapping[str, Any]) -> WorkEventView:
    return WorkEventView(
        work_id=_text(payload, "work_id"),
        kind=_text(payload, "kind"),
        version=_positive_integer(payload, "version"),
        created_at=_timestamp(payload, "created_at"),
        actor_ref=_text(payload, "actor_ref", optional=True),
        evidence_ref=_text(payload, "evidence_ref", optional=True),
    )


def _checkpoint(
    payload: Mapping[str, Any],
) -> VerifiedCheckpointView:
    artifact_sha256 = _text(payload, "artifact_sha256")
    if re.fullmatch(r"[0-9a-f]{64}", artifact_sha256 or "") is None:
        raise WorkReadModelError(
            "work snapshot returned an invalid checkpoint artifact SHA-256"
        )
    return VerifiedCheckpointView(
        id=_text(payload, "id"),
        work_id=_text(payload, "work_id"),
        artifact_ref=_text(payload, "artifact_ref"),
        artifact_sha256=artifact_sha256,
        verification_ref=_text(payload, "verification_ref"),
        created_at=_timestamp(payload, "created_at"),
    )


def _receipt(payload: Mapping[str, Any]) -> WorkReceiptView:
    return WorkReceiptView(
        id=_text(payload, "id"),
        work_id=_text(payload, "work_id"),
        outcome=_text(payload, "outcome"),
        result_ref=_text(payload, "result_ref"),
        summary=_text(payload, "summary"),
        created_at=_timestamp(payload, "created_at"),
    )


class SupabaseWorkReadModel:
    """Read one WorkItem snapshot through a service-role-only RPC."""

    def __init__(
        self,
        *,
        supabase_url: str,
        service_role_key: str,
        timeout_seconds: float = 45.0,
    ) -> None:
        self._client = ServiceRoleRpcClient(
            supabase_url=supabase_url,
            service_role_key=service_role_key,
            timeout_seconds=timeout_seconds,
        )

    @classmethod
    def from_environment(cls) -> SupabaseWorkReadModel:
        values = runtime_environment()
        return cls(
            supabase_url=values.get("SUPABASE_URL", ""),
            service_role_key=values.get(
                "SUPABASE_SERVICE_ROLE_KEY", ""
            ),
            timeout_seconds=float(
                values.get("VOLPRED_OPERATIONS_RPC_TIMEOUT_SEC", "45")
            ),
        )

    def inspect(self, query: WorkQuery) -> WorkSnapshot:
        if not isinstance(query, WorkQuery):
            raise TypeError("WorkQuery is required")
        if not isinstance(query.work_id, str) or not query.work_id.strip():
            raise ValueError("exact WorkItem id is required")
        work_id = query.work_id.strip()
        try:
            decoded = self._client.call(
                "volpred_read_work_snapshot",
                {"p_work_id": work_id},
            )
        except SupabaseRpcError as error:
            raise WorkReadModelError(
                f"work snapshot RPC failed: {error}"
            ) from None
        payload = _mapping(decoded, field="response")
        if payload.get("schema_version") != "work-snapshot.v1":
            raise WorkReadModelError(
                "work snapshot returned an unsupported schema"
            )
        snapshot = WorkSnapshot(
            items=tuple(_item(row) for row in _records(payload, "items")),
            events=tuple(
                _event(row) for row in _records(payload, "events")
            ),
            checkpoints=tuple(
                _checkpoint(row)
                for row in _records(payload, "checkpoints")
            ),
            receipts=tuple(
                _receipt(row)
                for row in _records(payload, "receipts")
            ),
        )
        identities = {
            item.id for item in snapshot.items
        } | {
            event.work_id for event in snapshot.events
        } | {
            checkpoint.work_id for checkpoint in snapshot.checkpoints
        } | {
            receipt.work_id for receipt in snapshot.receipts
        }
        if identities - {work_id}:
            raise WorkReadModelError(
                "work snapshot read-back drifted from requested WorkItem"
            )
        return snapshot


__all__ = ["SupabaseWorkReadModel", "WorkReadModelError"]
