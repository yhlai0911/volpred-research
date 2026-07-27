"""Service-role PostgREST adapter for Work Coordinator owner attestation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from volpred.ops.delivery.supabase_rpc import (
    ServiceRoleRpcClient,
    SupabaseRpcError,
    runtime_environment,
)

_EXPECTED_FIELDS = frozenset(
    {
        "schema_version",
        "capability",
        "owner",
        "generation",
        "cutover_manifest_sha256",
        "changed_at",
        "changed_by",
        "change_reason",
        "attested_at",
        "ownership_receipt_sequence",
        "ownership_receipt_capability",
        "ownership_receipt_owner",
        "ownership_receipt_generation",
        "ownership_receipt_manifest_sha256",
        "ownership_receipt_changed_at",
        "ownership_receipt_actor_ref",
        "ownership_receipt_reason",
        "ownership_receipt_rollback_of_generation",
        "cutover_gate_manifest_sha256",
        "cutover_gate_status",
        "cutover_gate_consumed_generation",
        "cutover_gate_consumed_at",
        "cutover_gate_rolled_back_at",
    }
)


@dataclass(frozen=True)
class WorkOwnerAttestation:
    schema_version: str
    capability: str
    owner: str
    generation: int
    cutover_manifest_sha256: str | None
    changed_at: str
    changed_by: str
    change_reason: str
    attested_at: str
    backend_sha256: str
    ownership_receipt_sequence: int
    ownership_receipt_generation: int
    cutover_gate_status: str | None


def _text(payload: Mapping[str, Any], field: str) -> str:
    value = payload.get(field)
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
    ):
        raise ValueError(f"Work owner RPC returned an invalid {field}")
    return value


def _positive_integer(payload: Mapping[str, Any], field: str) -> int:
    value = payload.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        readable_field = field.replace("_", " ")
        raise ValueError(
            f"Work owner RPC returned an invalid {readable_field}"
        )
    return value


def _optional_positive_integer(
    payload: Mapping[str, Any],
    field: str,
) -> int | None:
    if payload.get(field) is None:
        return None
    return _positive_integer(payload, field)


def _timestamp(payload: Mapping[str, Any], field: str) -> str:
    value = _text(payload, field)
    try:
        observed = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError(
            f"Work owner RPC returned an invalid {field}"
        ) from None
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise ValueError(f"Work owner RPC returned an invalid {field}")
    return observed.astimezone(UTC).isoformat()


def _manifest(payload: Mapping[str, Any], *, owner: str) -> str | None:
    value = payload.get("cutover_manifest_sha256")
    if value is None:
        if owner == "operations_core":
            raise ValueError(
                "Work owner RPC returned an invalid cutover manifest"
            )
        return None
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(
            "Work owner RPC returned an invalid cutover manifest"
        )
    return value


def _optional_manifest(
    payload: Mapping[str, Any],
    field: str,
) -> str | None:
    value = payload.get(field)
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"Work owner RPC returned an invalid {field}")
    return value


def _optional_timestamp(
    payload: Mapping[str, Any],
    field: str,
) -> str | None:
    if payload.get(field) is None:
        return None
    return _timestamp(payload, field)


def _instant(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)


class SupabaseWorkOwnerStore:
    """Read the durable Work Coordinator owner without mutation authority."""

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
    def from_environment(cls) -> SupabaseWorkOwnerStore:
        values = runtime_environment()
        return cls(
            supabase_url=values.get("SUPABASE_URL", ""),
            service_role_key=values.get("SUPABASE_SERVICE_ROLE_KEY", ""),
            timeout_seconds=float(
                values.get("VOLPRED_OPERATIONS_RPC_TIMEOUT_SEC", "45")
            ),
        )

    def read_owner(self) -> WorkOwnerAttestation:
        try:
            decoded = self._client.call("volpred_read_work_owner", {})
        except SupabaseRpcError as exc:
            raise RuntimeError(
                f"work ownership RPC failed: {exc}"
            ) from None
        if not isinstance(decoded, Mapping):
            raise TypeError(
                "work ownership RPC returned a non-object response"
            )
        if set(decoded) != _EXPECTED_FIELDS:
            raise ValueError("Work owner RPC returned invalid fields")
        if decoded.get("schema_version") != "work-owner-attestation.v1":
            raise ValueError("Work owner RPC returned an invalid schema")
        capability = _text(decoded, "capability")
        if capability != "work.coordinate":
            raise ValueError("Work owner RPC returned another capability")
        owner = _text(decoded, "owner")
        if owner not in {"legacy", "operations_core"}:
            raise ValueError("Work owner RPC returned an invalid owner")
        generation = _positive_integer(decoded, "generation")
        manifest = _manifest(decoded, owner=owner)
        changed_at = _timestamp(decoded, "changed_at")
        changed_by = _text(decoded, "changed_by")
        change_reason = _text(decoded, "change_reason")
        attested_at = _timestamp(decoded, "attested_at")
        receipt_sequence = _positive_integer(
            decoded,
            "ownership_receipt_sequence",
        )
        receipt_capability = _text(
            decoded,
            "ownership_receipt_capability",
        )
        receipt_owner = _text(decoded, "ownership_receipt_owner")
        receipt_generation = _positive_integer(
            decoded,
            "ownership_receipt_generation",
        )
        receipt_manifest = _optional_manifest(
            decoded,
            "ownership_receipt_manifest_sha256",
        )
        receipt_changed_at = _timestamp(
            decoded,
            "ownership_receipt_changed_at",
        )
        receipt_actor = _text(
            decoded,
            "ownership_receipt_actor_ref",
        )
        receipt_reason = _text(decoded, "ownership_receipt_reason")
        receipt_rollback_generation = _optional_positive_integer(
            decoded,
            "ownership_receipt_rollback_of_generation",
        )
        gate_manifest = _optional_manifest(
            decoded,
            "cutover_gate_manifest_sha256",
        )
        gate_status_raw = decoded.get("cutover_gate_status")
        if gate_status_raw is not None and gate_status_raw not in {
            "consumed",
            "rolled_back",
        }:
            raise ValueError(
                "Work owner RPC returned an invalid consumed cutover gate"
            )
        gate_status = gate_status_raw
        gate_generation = _optional_positive_integer(
            decoded,
            "cutover_gate_consumed_generation",
        )
        gate_consumed_at = _optional_timestamp(
            decoded,
            "cutover_gate_consumed_at",
        )
        gate_rolled_back_at = _optional_timestamp(
            decoded,
            "cutover_gate_rolled_back_at",
        )

        if receipt_capability != capability:
            raise ValueError(
                "Work owner RPC receipt capability drifted"
            )
        if receipt_owner != owner:
            raise ValueError("Work owner RPC receipt owner drifted")
        if receipt_generation != generation:
            raise ValueError(
                "Work owner RPC receipt generation drifted"
            )
        if receipt_manifest != manifest:
            raise ValueError("Work owner RPC receipt manifest drifted")
        if receipt_changed_at != changed_at:
            raise ValueError(
                "Work owner RPC receipt changed_at drifted"
            )
        if receipt_actor != changed_by:
            raise ValueError("Work owner RPC receipt actor drifted")
        if receipt_reason != change_reason:
            raise ValueError("Work owner RPC receipt reason drifted")
        if _instant(changed_at) > _instant(attested_at):
            raise ValueError("Work owner RPC chronology drifted")

        if owner == "operations_core":
            if gate_manifest != manifest:
                raise ValueError(
                    "Work owner RPC cutover manifest drifted"
                )
            if gate_generation != generation:
                raise ValueError(
                    "Work owner RPC consumed generation drifted"
                )
            if (
                gate_status != "consumed"
                or gate_consumed_at is None
                or gate_rolled_back_at is not None
                or receipt_rollback_generation is not None
            ):
                raise ValueError(
                    "Work owner RPC lacks a consumed cutover gate"
                )
            if not (
                _instant(changed_at)
                <= _instant(gate_consumed_at)
                <= _instant(attested_at)
            ):
                raise ValueError("Work owner RPC chronology drifted")
        elif manifest is None:
            if (
                generation != 1
                or receipt_rollback_generation is not None
                or gate_manifest is not None
                or gate_status is not None
                or gate_generation is not None
                or gate_consumed_at is not None
                or gate_rolled_back_at is not None
            ):
                raise ValueError(
                    "Work owner RPC initial legacy evidence drifted"
                )
        else:
            if (
                gate_manifest != manifest
                or gate_status != "rolled_back"
                or gate_generation is None
                or receipt_rollback_generation != gate_generation
                or generation != gate_generation + 1
                or gate_consumed_at is None
                or gate_rolled_back_at is None
            ):
                raise ValueError(
                    "Work owner RPC rollback evidence drifted"
                )
            if not (
                _instant(gate_consumed_at)
                <= _instant(changed_at)
                <= _instant(gate_rolled_back_at)
                <= _instant(attested_at)
            ):
                raise ValueError("Work owner RPC chronology drifted")

        return WorkOwnerAttestation(
            schema_version="work-owner-attestation.v1",
            capability=capability,
            owner=owner,
            generation=generation,
            cutover_manifest_sha256=manifest,
            changed_at=changed_at,
            changed_by=changed_by,
            change_reason=change_reason,
            attested_at=attested_at,
            backend_sha256=self._client.backend_sha256,
            ownership_receipt_sequence=receipt_sequence,
            ownership_receipt_generation=receipt_generation,
            cutover_gate_status=gate_status,
        )


__all__ = ["SupabaseWorkOwnerStore", "WorkOwnerAttestation"]
