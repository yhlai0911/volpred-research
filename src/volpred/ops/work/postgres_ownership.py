"""PostgreSQL adapter for durable Work Coordinator ownership."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from psycopg import Connection
from psycopg.rows import dict_row

from .ownership import WorkCutoverGate, WorkOwner, WorkOwnershipLost

if TYPE_CHECKING:
    from ..work_cutover import WorkOwnershipCutoverManifest


ConnectionFactory = Callable[[], Connection[Any]]


def _isoformat(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _owner_from_row(row: dict[str, Any]) -> WorkOwner:
    return WorkOwner(
        schema_version=row["schema_version"],
        capability=row["capability"],
        owner=row["owner"],
        generation=row["generation"],
        cutover_manifest_sha256=row["cutover_manifest_sha256"],
        changed_at=_isoformat(row["changed_at"]),
        changed_by=row["changed_by"],
        change_reason=row["change_reason"],
    )


def _optional_isoformat(value: datetime | None) -> str | None:
    return None if value is None else _isoformat(value)


def _gate_from_row(row: dict[str, Any]) -> WorkCutoverGate:
    return WorkCutoverGate(
        schema_version=row["schema_version"],
        manifest_sha256=row["manifest_sha256"],
        source_owner=row["source_owner"],
        source_generation=row["source_generation"],
        status=row["status"],
        prepared_at=_isoformat(row["prepared_at"]),
        valid_until=_isoformat(row["valid_until"]),
        staged_at=_isoformat(row["staged_at"]),
        staged_by=row["staged_by"],
        consumed_at=_optional_isoformat(row["consumed_at"]),
        consumed_generation=row["consumed_generation"],
        rolled_back_at=_optional_isoformat(row["rolled_back_at"]),
    )


class PostgresWorkOwnerStore:
    """Read and privileged-CAS the private Work Coordinator owner row.

    Runtime worker and approver roles can only read ownership. The durable
    gate is deployed, but stage and transfer remain ungranted to runtime
    identities until a dedicated operator identity and cutover window are
    approved; this adapter is therefore limited to privileged operator
    rehearsals.
    """

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._connection_factory = connection_factory

    @staticmethod
    def _translate(error: Exception) -> None:
        message = getattr(getattr(error, "diag", None), "message_primary", "")
        if message.startswith("work ownership"):
            raise WorkOwnershipLost(message) from None
        raise error

    def _execute(
        self,
        query: str,
        parameters: tuple[object, ...],
    ) -> WorkOwner:
        with self._connection_factory() as connection:
            connection.row_factory = dict_row
            try:
                row = connection.execute(query, parameters).fetchone()
            except Exception as error:
                self._translate(error)
                raise AssertionError("unreachable")
        if row is None:
            raise WorkOwnershipLost(
                "work ownership returned no durable owner"
            )
        return _owner_from_row(row)

    def _execute_gate(
        self,
        query: str,
        parameters: tuple[object, ...],
    ) -> WorkCutoverGate:
        with self._connection_factory() as connection:
            connection.row_factory = dict_row
            try:
                row = connection.execute(query, parameters).fetchone()
            except Exception as error:
                self._translate(error)
                raise AssertionError("unreachable")
        if row is None:
            raise WorkOwnershipLost(
                "work ownership cutover gate returned no durable row"
            )
        return _gate_from_row(row)

    def read_owner(self) -> WorkOwner:
        return self._execute(
            "SELECT * FROM volpred_ops.read_work_owner()",
            (),
        )

    def stage_cutover_manifest(
        self,
        *,
        manifest: WorkOwnershipCutoverManifest,
        expected_owner: str,
        expected_generation: int,
        actor_ref: str,
    ) -> WorkCutoverGate:
        return self._execute_gate(
            """
            SELECT *
            FROM volpred_ops.stage_work_cutover_manifest(
              %s, %s, %s, %s, %s
            )
            """,
            (
                manifest.sha256,
                manifest.canonical_bytes(),
                expected_owner,
                expected_generation,
                actor_ref,
            ),
        )

    def read_cutover_gate(
        self,
        manifest_sha256: str,
    ) -> WorkCutoverGate:
        return self._execute_gate(
            """
            SELECT *
            FROM volpred_ops.read_work_cutover_gate(%s)
            """,
            (manifest_sha256,),
        )

    def transfer_owner(
        self,
        *,
        expected_owner: str,
        expected_generation: int,
        target_owner: str,
        actor_ref: str,
        reason: str,
        cutover_manifest_sha256: str,
        rollback_of_generation: int | None = None,
    ) -> WorkOwner:
        return self._execute(
            """
            SELECT *
            FROM volpred_ops.transfer_work_owner(
              %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                expected_owner,
                expected_generation,
                target_owner,
                actor_ref,
                reason,
                cutover_manifest_sha256,
                rollback_of_generation,
            ),
        )


__all__ = ["PostgresWorkOwnerStore"]
