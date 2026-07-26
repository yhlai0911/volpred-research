"""PostgreSQL adapter for durable Work Coordinator ownership."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row

from .ownership import WorkOwner, WorkOwnershipLost


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


class PostgresWorkOwnerStore:
    """Read and privileged-CAS the private Work Coordinator owner row.

    Runtime worker and approver roles can only read ownership. The transfer
    function remains ungranted until a durable cutover-gate transaction is
    available, so this adapter is limited to migration-owner rehearsals.
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

    def read_owner(self) -> WorkOwner:
        return self._execute(
            "SELECT * FROM volpred_ops.read_work_owner()",
            (),
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
