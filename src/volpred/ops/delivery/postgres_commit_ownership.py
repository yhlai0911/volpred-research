"""PostgreSQL adapter for the durable Git commit owner generation."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row

from .owned_change import CommitOwner, CommitOwnershipLost


ConnectionFactory = Callable[[], Connection[Any]]


def _isoformat(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _owner_from_row(row: dict[str, Any]) -> CommitOwner:
    return CommitOwner(
        schema_version=row["schema_version"],
        capability=row["capability"],
        owner=row["owner"],
        generation=row["generation"],
        changed_at=_isoformat(row["changed_at"]),
        changed_by=row["changed_by"],
        change_reason=row["change_reason"],
    )


class PostgresCommitOwnerStore:
    """Read and CAS-transfer the private Git owner row."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._connection_factory = connection_factory

    @staticmethod
    def _translate(error: Exception) -> None:
        message = getattr(getattr(error, "diag", None), "message_primary", "")
        if message.startswith(
            (
                "commit ownership",
                "operations core does not own git.commit",
            )
        ):
            raise CommitOwnershipLost(message) from None
        raise error

    def _execute(
        self,
        query: str,
        parameters: tuple[object, ...],
    ) -> CommitOwner:
        with self._connection_factory() as connection:
            connection.row_factory = dict_row
            try:
                row = connection.execute(query, parameters).fetchone()
            except Exception as error:
                self._translate(error)
                raise AssertionError("unreachable")
        if row is None:
            raise CommitOwnershipLost(
                "commit ownership returned no durable owner"
            )
        return _owner_from_row(row)

    def read_owner(self) -> CommitOwner:
        return self._execute(
            "SELECT * FROM volpred_ops.read_commit_owner()",
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
        rollback_of_generation: int | None = None,
    ) -> CommitOwner:
        return self._execute(
            """
            SELECT *
            FROM volpred_ops.transfer_commit_owner(
              %s, %s, %s, %s, %s, %s
            )
            """,
            (
                expected_owner,
                expected_generation,
                target_owner,
                actor_ref,
                reason,
                rollback_of_generation,
            ),
        )


__all__ = ["PostgresCommitOwnerStore"]
