"""PostgreSQL adapter for durable Change Delivery commit settlement."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from volpred.ops.authority import PrimaryLease

from . import DeliveryReceipt
from ._change_settlement import (
    CommitSettlement,
    CommitSettlementBlocked,
    commit_settlement_sha256,
)


ConnectionFactory = Callable[[], Connection[Any]]


def _isoformat(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


class PostgresCommitSettlement:
    """Revalidate both fences after Git mutation and persist one exact receipt."""

    def __init__(
        self,
        connection_factory: ConnectionFactory,
        *,
        primary_lease: PrimaryLease,
    ) -> None:
        if not isinstance(primary_lease, PrimaryLease):
            raise TypeError("primary_lease must be a PrimaryLease")
        if primary_lease.schema_version != "primary-lease.v1":
            raise ValueError("unsupported PrimaryLease schema")
        if primary_lease.epoch <= 0:
            raise ValueError("PrimaryLease epoch must be positive")
        self._connection_factory = connection_factory
        self._primary_lease = primary_lease

    def settle(self, command: CommitSettlement) -> DeliveryReceipt:
        if not isinstance(command, CommitSettlement):
            raise TypeError("CommitSettlement is required")
        actuation = command.actuation
        settlement_sha256 = commit_settlement_sha256(command)

        with self._connection_factory() as connection:
            connection.row_factory = dict_row
            try:
                row = connection.execute(
                    """
                    SELECT *
                    FROM volpred_ops.settle_commit_write(
                      %s, %s, %s, %s, %s, %s, %s, %s, %s,
                      %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        self._primary_lease.authority_key,
                        self._primary_lease.holder_ref,
                        self._primary_lease.epoch,
                        command.primary_fencing_token,
                        actuation.authority_request_sha256,
                        settlement_sha256,
                        command.change_set_id,
                        command.work_lease_token,
                        actuation.work_lease_ref,
                        actuation.primary_authority_ref,
                        command.repository,
                        actuation.commit_sha,
                        actuation.parent_sha,
                        Jsonb(list(actuation.exact_paths)),
                        actuation.actor,
                        actuation.observed_at,
                        actuation.status,
                    ),
                ).fetchone()
            except Exception as error:
                message = getattr(
                    getattr(error, "diag", None),
                    "message_primary",
                    "",
                )
                if message.startswith(
                    (
                        "commit settlement",
                        "Primary Authority",
                    )
                ):
                    raise CommitSettlementBlocked(message) from None
                raise
        if row is None:
            raise CommitSettlementBlocked(
                "commit settlement returned no durable receipt"
            )

        receipt = DeliveryReceipt(
            schema_version=row["schema_version"],
            change_set_id=row["change_set_id"],
            proposal_sha256=row["proposal_sha256"],
            work_item_id=row["work_item_id"],
            work_item_version=row["work_item_version"],
            authority_request_sha256=row["authority_request_sha256"],
            work_lease_ref=row["work_lease_ref"],
            primary_authority_ref=row["primary_authority_ref"],
            repository=row["repository"],
            commit_sha=row["commit_sha"],
            parent_sha=row["parent_sha"],
            exact_paths=tuple(row["exact_paths"]),
            actor=row["commit_worker_ref"],
            status=row["status"],
            actuation_observed_at=_isoformat(row["actuation_observed_at"]),
            settled_at=_isoformat(row["settled_at"]),
            settlement_ref=row["settlement_ref"],
            settlement_sha256=row["settlement_sha256"],
        )
        if (
            receipt.settlement_sha256 != settlement_sha256
            or receipt.authority_request_sha256
            != actuation.authority_request_sha256
            or receipt.change_set_id != command.change_set_id
            or receipt.repository != command.repository
            or receipt.commit_sha != actuation.commit_sha
            or receipt.parent_sha != actuation.parent_sha
            or receipt.exact_paths != actuation.exact_paths
            or receipt.actor != actuation.actor
            or receipt.actuation_observed_at
            != datetime.fromisoformat(actuation.observed_at).astimezone(
                timezone.utc
            ).isoformat()
        ):
            raise CommitSettlementBlocked(
                "durable commit settlement read-back drifted"
            )
        return receipt


__all__ = ["PostgresCommitSettlement"]
