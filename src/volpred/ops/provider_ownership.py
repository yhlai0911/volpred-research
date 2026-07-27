"""Service-role PostgREST adapter for provider-execution owner attestation."""

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

_CAPABILITY = "provider.execution"
_CONTRACT_REF = "contract://issue-12/zero-paid-provider-registry"
_EXPECTED_FIELDS = frozenset(
    {
        "schema_version",
        "capability",
        "owner",
        "generation",
        "contract_ref",
        "changed_at",
        "changed_by",
        "change_reason",
        "receipt_sequence",
        "receipt_capability",
        "receipt_owner",
        "receipt_generation",
        "receipt_contract_ref",
        "receipt_changed_at",
        "receipt_actor_ref",
        "receipt_reason",
        "attested_at",
    }
)


@dataclass(frozen=True)
class ProviderOwnerAttestation:
    schema_version: str
    capability: str
    owner: str
    generation: int
    contract_ref: str
    changed_at: str
    changed_by: str
    change_reason: str
    receipt_sequence: int
    attested_at: str
    backend_sha256: str


def _text(payload: Mapping[str, Any], field: str) -> str:
    value = payload.get(field)
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
    ):
        raise ValueError(f"Provider owner RPC returned an invalid {field}")
    return value


def _positive_integer(payload: Mapping[str, Any], field: str) -> int:
    value = payload.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        readable_field = field.replace("_", " ")
        raise ValueError(
            f"Provider owner RPC returned an invalid {readable_field}"
        )
    return value


def _timestamp(payload: Mapping[str, Any], field: str) -> str:
    value = _text(payload, field)
    try:
        observed = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError(
            f"Provider owner RPC returned an invalid {field}"
        ) from None
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise ValueError(
            f"Provider owner RPC returned an invalid {field}"
        )
    return observed.astimezone(UTC).isoformat()


class SupabaseProviderOwnerStore:
    """Read the durable provider-execution owner without mutation authority."""

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
    def from_environment(cls) -> SupabaseProviderOwnerStore:
        values = runtime_environment()
        return cls(
            supabase_url=values.get("SUPABASE_URL", ""),
            service_role_key=values.get(
                "SUPABASE_SERVICE_ROLE_KEY",
                "",
            ),
            timeout_seconds=float(
                values.get("VOLPRED_OPERATIONS_RPC_TIMEOUT_SEC", "45")
            ),
        )

    def read_owner(self) -> ProviderOwnerAttestation:
        try:
            decoded = self._client.call(
                "volpred_read_provider_owner",
                {},
            )
        except SupabaseRpcError as exc:
            raise RuntimeError(
                f"provider ownership RPC failed: {exc}"
            ) from None
        if not isinstance(decoded, Mapping):
            raise TypeError(
                "provider ownership RPC returned a non-object response"
            )
        if set(decoded) != _EXPECTED_FIELDS:
            raise ValueError("Provider owner RPC returned invalid fields")
        if decoded.get("schema_version") != "provider-owner-attestation.v1":
            raise ValueError("Provider owner RPC returned an invalid schema")

        capability = _text(decoded, "capability")
        if capability != _CAPABILITY:
            raise ValueError(
                "Provider owner RPC returned another capability"
            )
        owner = _text(decoded, "owner")
        if owner != "legacy":
            raise ValueError("Provider owner RPC returned an invalid owner")
        generation = _positive_integer(decoded, "generation")
        if generation != 1:
            raise ValueError(
                "Provider owner RPC returned an invalid generation"
            )
        contract_ref = _text(decoded, "contract_ref")
        if contract_ref != _CONTRACT_REF:
            raise ValueError(
                "Provider owner RPC returned an invalid contract"
            )
        changed_at = _timestamp(decoded, "changed_at")
        changed_by = _text(decoded, "changed_by")
        change_reason = _text(decoded, "change_reason")
        receipt_sequence = _positive_integer(
            decoded,
            "receipt_sequence",
        )
        receipt_capability = _text(decoded, "receipt_capability")
        receipt_owner = _text(decoded, "receipt_owner")
        receipt_generation = _positive_integer(
            decoded,
            "receipt_generation",
        )
        receipt_contract_ref = _text(decoded, "receipt_contract_ref")
        receipt_changed_at = _timestamp(
            decoded,
            "receipt_changed_at",
        )
        receipt_actor_ref = _text(decoded, "receipt_actor_ref")
        receipt_reason = _text(decoded, "receipt_reason")
        attested_at = _timestamp(decoded, "attested_at")

        if receipt_capability != capability:
            raise ValueError(
                "Provider owner RPC receipt capability drifted"
            )
        if receipt_owner != owner:
            raise ValueError("Provider owner RPC receipt owner drifted")
        if receipt_generation != generation:
            raise ValueError(
                "Provider owner RPC receipt generation drifted"
            )
        if receipt_contract_ref != contract_ref:
            raise ValueError(
                "Provider owner RPC receipt contract drifted"
            )
        if receipt_changed_at != changed_at:
            raise ValueError(
                "Provider owner RPC receipt changed_at drifted"
            )
        if receipt_actor_ref != changed_by:
            raise ValueError("Provider owner RPC receipt actor drifted")
        if receipt_reason != change_reason:
            raise ValueError("Provider owner RPC receipt reason drifted")
        if datetime.fromisoformat(changed_at) > datetime.fromisoformat(
            attested_at
        ):
            raise ValueError("Provider owner RPC chronology drifted")

        return ProviderOwnerAttestation(
            schema_version="provider-owner-attestation.v1",
            capability=capability,
            owner=owner,
            generation=generation,
            contract_ref=contract_ref,
            changed_at=changed_at,
            changed_by=changed_by,
            change_reason=change_reason,
            receipt_sequence=receipt_sequence,
            attested_at=attested_at,
            backend_sha256=self._client.backend_sha256,
        )


__all__ = [
    "ProviderOwnerAttestation",
    "SupabaseProviderOwnerStore",
]
