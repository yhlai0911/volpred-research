"""Shared fail-closed reader for pre-cutover formal owner attestations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, ClassVar, Self

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
class OwnerAttestation:
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


@dataclass(frozen=True)
class OwnerAttestationContract:
    schema_version: str
    capability: str
    allowed_owners: frozenset[str]
    minimum_generation: int
    contract_ref: str
    rpc_name: str
    label: str


def _text(
    payload: Mapping[str, Any],
    field: str,
    *,
    label: str,
) -> str:
    value = payload.get(field)
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
    ):
        raise ValueError(f"{label} RPC returned an invalid {field}")
    return value


def _positive_integer(
    payload: Mapping[str, Any],
    field: str,
    *,
    label: str,
) -> int:
    value = payload.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        readable_field = field.replace("_", " ")
        raise ValueError(
            f"{label} RPC returned an invalid {readable_field}"
        )
    return value


def _timestamp(
    payload: Mapping[str, Any],
    field: str,
    *,
    label: str,
) -> str:
    value = _text(payload, field, label=label)
    try:
        observed = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError(
            f"{label} RPC returned an invalid {field}"
        ) from None
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise ValueError(f"{label} RPC returned an invalid {field}")
    return observed.astimezone(UTC).isoformat()


def parse_owner_attestation(
    payload: object,
    *,
    contract: OwnerAttestationContract,
    backend_sha256: str,
) -> OwnerAttestation:
    if not isinstance(payload, Mapping):
        raise TypeError(
            f"{contract.label.lower()} RPC returned a non-object response"
        )
    if set(payload) != _EXPECTED_FIELDS:
        raise ValueError(f"{contract.label} RPC returned invalid fields")
    if payload.get("schema_version") != contract.schema_version:
        raise ValueError(
            f"{contract.label} RPC returned an invalid schema"
        )

    capability = _text(payload, "capability", label=contract.label)
    if capability != contract.capability:
        raise ValueError(
            f"{contract.label} RPC returned another capability"
        )
    owner = _text(payload, "owner", label=contract.label)
    if owner not in contract.allowed_owners:
        raise ValueError(f"{contract.label} RPC returned an invalid owner")
    generation = _positive_integer(
        payload,
        "generation",
        label=contract.label,
    )
    if generation < contract.minimum_generation:
        raise ValueError(
            f"{contract.label} RPC returned an invalid generation"
        )
    contract_ref = _text(
        payload,
        "contract_ref",
        label=contract.label,
    )
    if contract_ref != contract.contract_ref:
        raise ValueError(
            f"{contract.label} RPC returned an invalid contract"
        )

    changed_at = _timestamp(
        payload,
        "changed_at",
        label=contract.label,
    )
    changed_by = _text(payload, "changed_by", label=contract.label)
    change_reason = _text(
        payload,
        "change_reason",
        label=contract.label,
    )
    receipt_sequence = _positive_integer(
        payload,
        "receipt_sequence",
        label=contract.label,
    )
    receipt_capability = _text(
        payload,
        "receipt_capability",
        label=contract.label,
    )
    receipt_owner = _text(
        payload,
        "receipt_owner",
        label=contract.label,
    )
    receipt_generation = _positive_integer(
        payload,
        "receipt_generation",
        label=contract.label,
    )
    receipt_contract_ref = _text(
        payload,
        "receipt_contract_ref",
        label=contract.label,
    )
    receipt_changed_at = _timestamp(
        payload,
        "receipt_changed_at",
        label=contract.label,
    )
    receipt_actor_ref = _text(
        payload,
        "receipt_actor_ref",
        label=contract.label,
    )
    receipt_reason = _text(
        payload,
        "receipt_reason",
        label=contract.label,
    )
    attested_at = _timestamp(
        payload,
        "attested_at",
        label=contract.label,
    )

    bound_fields = (
        (
            receipt_capability,
            capability,
            "receipt capability",
        ),
        (receipt_owner, owner, "receipt owner"),
        (
            receipt_generation,
            generation,
            "receipt generation",
        ),
        (
            receipt_contract_ref,
            contract_ref,
            "receipt contract",
        ),
        (
            receipt_changed_at,
            changed_at,
            "receipt changed_at",
        ),
        (
            receipt_actor_ref,
            changed_by,
            "receipt actor",
        ),
        (
            receipt_reason,
            change_reason,
            "receipt reason",
        ),
    )
    for actual, expected, field in bound_fields:
        if actual != expected:
            raise ValueError(f"{contract.label} RPC {field} drifted")
    if datetime.fromisoformat(changed_at) > datetime.fromisoformat(
        attested_at
    ):
        raise ValueError(f"{contract.label} RPC chronology drifted")

    return OwnerAttestation(
        schema_version=contract.schema_version,
        capability=capability,
        owner=owner,
        generation=generation,
        contract_ref=contract_ref,
        changed_at=changed_at,
        changed_by=changed_by,
        change_reason=change_reason,
        receipt_sequence=receipt_sequence,
        attested_at=attested_at,
        backend_sha256=backend_sha256,
    )


class SupabaseOwnerAttestationStore:
    """Read one exact formal owner attestation without mutation authority."""

    contract: ClassVar[OwnerAttestationContract]

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
    def from_environment(cls) -> Self:
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

    def read_owner(self) -> OwnerAttestation:
        try:
            decoded = self._client.call(
                self.contract.rpc_name,
                {},
            )
        except SupabaseRpcError as exc:
            raise RuntimeError(
                f"{self.contract.label.lower()} RPC failed: {exc}"
            ) from None
        return parse_owner_attestation(
            decoded,
            contract=self.contract,
            backend_sha256=self._client.backend_sha256,
        )


__all__ = [
    "OwnerAttestation",
    "OwnerAttestationContract",
    "SupabaseOwnerAttestationStore",
    "parse_owner_attestation",
]
