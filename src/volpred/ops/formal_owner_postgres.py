"""Privileged PostgreSQL adapter for incident/provider owner cutovers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from psycopg import Connection, Error
from psycopg.rows import dict_row

from volpred.ops.formal_owner_cutover import FormalOwnerCutoverManifest
from volpred.ops.incident_ownership import SupabaseIncidentOwnerStore
from volpred.ops.owner_attestation import parse_owner_attestation
from volpred.ops.provider_ownership import SupabaseProviderOwnerStore

ConnectionFactory = Callable[[], Connection[Any]]
_CONTRACTS = {
    "incident.lifecycle": SupabaseIncidentOwnerStore.contract,
    "provider.execution": SupabaseProviderOwnerStore.contract,
}


class FormalOwnerCutoverRejected(RuntimeError):
    """The evidence gate or owner compare-and-set rejected a transfer."""


@dataclass(frozen=True)
class FormalOwner:
    schema_version: str
    capability: str
    owner: str
    generation: int
    contract_ref: str
    changed_at: str
    changed_by: str
    change_reason: str
    receipt_sequence: int


@dataclass(frozen=True)
class FormalOwnerCutoverGate:
    schema_version: str
    manifest_sha256: str
    capability: str
    source_owner: str
    source_generation: int
    target_owner: str
    parent_work_owner_generation: int
    status: str
    prepared_at: str
    valid_until: str
    staged_at: str
    staged_by: str
    consumed_at: str | None
    consumed_generation: int | None
    rolled_back_at: str | None
    rolled_back_generation: int | None


def _isoformat(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _optional_isoformat(value: datetime | None) -> str | None:
    return None if value is None else _isoformat(value)


def _owner(payload: object, *, capability: str) -> FormalOwner:
    contract = _CONTRACTS.get(capability)
    if contract is None:
        raise ValueError(f"unsupported formal owner capability: {capability}")
    parsed = parse_owner_attestation(
        payload,
        contract=contract,
        backend_sha256="direct-postgres-operator",
    )
    return FormalOwner(
        schema_version=parsed.schema_version,
        capability=parsed.capability,
        owner=parsed.owner,
        generation=parsed.generation,
        contract_ref=parsed.contract_ref,
        changed_at=parsed.changed_at,
        changed_by=parsed.changed_by,
        change_reason=parsed.change_reason,
        receipt_sequence=parsed.receipt_sequence,
    )


def _gate(row: dict[str, Any]) -> FormalOwnerCutoverGate:
    return FormalOwnerCutoverGate(
        schema_version=row["schema_version"],
        manifest_sha256=row["manifest_sha256"],
        capability=row["capability"],
        source_owner=row["source_owner"],
        source_generation=row["source_generation"],
        target_owner=row["target_owner"],
        parent_work_owner_generation=row[
            "parent_work_owner_generation"
        ],
        status=row["status"],
        prepared_at=_isoformat(row["prepared_at"]),
        valid_until=_isoformat(row["valid_until"]),
        staged_at=_isoformat(row["staged_at"]),
        staged_by=row["staged_by"],
        consumed_at=_optional_isoformat(row["consumed_at"]),
        consumed_generation=row["consumed_generation"],
        rolled_back_at=_optional_isoformat(row["rolled_back_at"]),
        rolled_back_generation=row["rolled_back_generation"],
    )


class PostgresFormalOwnerStore:
    """Stage evidence and CAS-transfer a supported formal owner.

    These private functions are deliberately unavailable to service_role and
    runtime workers.  Only the privileged cutover operator can call them.
    """

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._connection_factory = connection_factory

    @staticmethod
    def _translate(error: Exception) -> None:
        message = getattr(getattr(error, "diag", None), "message_primary", "")
        if message.startswith("formal owner"):
            raise FormalOwnerCutoverRejected(message) from None
        raise error

    def read_owner(self, capability: str) -> FormalOwner:
        function = {
            "incident.lifecycle": "public.volpred_read_incident_owner()",
            "provider.execution": "public.volpred_read_provider_owner()",
        }.get(capability)
        if function is None:
            raise ValueError(
                f"unsupported formal owner capability: {capability}"
            )
        with self._connection_factory() as connection:
            try:
                row = connection.execute(f"SELECT {function}").fetchone()
            except Error as error:
                self._translate(error)
                raise AssertionError("unreachable")
        if row is None:
            raise FormalOwnerCutoverRejected(
                "formal owner read returned no durable owner"
            )
        return _owner(row[0], capability=capability)

    def _gate_query(
        self,
        query: str,
        parameters: tuple[object, ...],
    ) -> FormalOwnerCutoverGate:
        with self._connection_factory() as connection:
            connection.row_factory = dict_row
            try:
                row = connection.execute(query, parameters).fetchone()
            except Error as error:
                self._translate(error)
                raise AssertionError("unreachable")
        if row is None:
            raise FormalOwnerCutoverRejected(
                "formal owner cutover gate returned no durable row"
            )
        return _gate(row)

    def stage_cutover_manifest(
        self,
        *,
        manifest: FormalOwnerCutoverManifest,
        actor_ref: str,
    ) -> FormalOwnerCutoverGate:
        return self._gate_query(
            """
            SELECT *
            FROM volpred_ops.stage_formal_owner_cutover(%s, %s, %s)
            """,
            (manifest.sha256, manifest.canonical_bytes(), actor_ref),
        )

    def read_cutover_gate(
        self,
        manifest_sha256: str,
    ) -> FormalOwnerCutoverGate:
        return self._gate_query(
            """
            SELECT *
            FROM volpred_ops.read_formal_owner_cutover_gate(%s)
            """,
            (manifest_sha256,),
        )

    def transfer_owner(
        self,
        *,
        capability: str,
        expected_owner: str,
        expected_generation: int,
        target_owner: str,
        actor_ref: str,
        reason: str,
        cutover_manifest_sha256: str,
        rollback_of_generation: int | None = None,
    ) -> FormalOwner:
        with self._connection_factory() as connection:
            try:
                row = connection.execute(
                    """
                    SELECT volpred_ops.transfer_formal_owner(
                      %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        capability,
                        expected_owner,
                        expected_generation,
                        target_owner,
                        actor_ref,
                        reason,
                        cutover_manifest_sha256,
                        rollback_of_generation,
                    ),
                ).fetchone()
            except Error as error:
                self._translate(error)
                raise AssertionError("unreachable")
        if row is None:
            raise FormalOwnerCutoverRejected(
                "formal owner transfer returned no durable owner"
            )
        return _owner(row[0], capability=capability)


__all__ = [
    "FormalOwner",
    "FormalOwnerCutoverGate",
    "FormalOwnerCutoverRejected",
    "PostgresFormalOwnerStore",
]
