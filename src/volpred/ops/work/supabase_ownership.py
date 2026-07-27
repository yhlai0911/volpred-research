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


def _text(payload: Mapping[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Work owner RPC returned an invalid {field}")
    return value.strip()


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
        generation = decoded.get("generation")
        if (
            isinstance(generation, bool)
            or not isinstance(generation, int)
            or generation <= 0
        ):
            raise ValueError(
                "Work owner RPC returned an invalid generation"
            )
        return WorkOwnerAttestation(
            schema_version="work-owner-attestation.v1",
            capability=capability,
            owner=owner,
            generation=generation,
            cutover_manifest_sha256=_manifest(decoded, owner=owner),
            changed_at=_timestamp(decoded, "changed_at"),
            changed_by=_text(decoded, "changed_by"),
            change_reason=_text(decoded, "change_reason"),
            attested_at=_timestamp(decoded, "attested_at"),
            backend_sha256=self._client.backend_sha256,
        )


__all__ = ["SupabaseWorkOwnerStore", "WorkOwnerAttestation"]
