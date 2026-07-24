"""PostgreSQL adapter for commit write authority.

The database transaction verifies the current running WorkLease and Primary
Authority lease before issuing one durable, token-redacted grant. Git mutation
remains behind :class:`GitCommitActuator`.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row

from volpred.ops.authority import PrimaryLease

from ._git_actuator import (
    CommitAuthorityGrant,
    CommitAuthorityRequest,
    CommitActuatorBlocked,
    _authority_request_sha256,
)


ConnectionFactory = Callable[[], Connection[Any]]


class PostgresCommitAuthority:
    """Atomically verify both commit fences against durable coordination state."""

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

    def authorize(
        self,
        request: CommitAuthorityRequest,
    ) -> CommitAuthorityGrant:
        if not isinstance(request, CommitAuthorityRequest):
            raise TypeError("CommitAuthorityRequest is required")
        if request.request_sha256 != _authority_request_sha256(request):
            raise CommitActuatorBlocked(
                "commit authority request hash does not match its write intent"
            )

        with self._connection_factory() as connection:
            connection.row_factory = dict_row
            try:
                row = connection.execute(
                    """
                    SELECT *
                    FROM volpred_ops.authorize_commit_write(
                      %s, %s, %s, %s, %s, %s, %s, %s, %s,
                      %s, %s, %s
                    )
                    """,
                    (
                        self._primary_lease.authority_key,
                        self._primary_lease.holder_ref,
                        self._primary_lease.epoch,
                        request.primary_fencing_token,
                        request.request_sha256,
                        request.proposal_sha256,
                        request.work_item_id,
                        request.work_item_version,
                        request.work_lease_token,
                        request.repository,
                        request.expected_head,
                        request.actor,
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
                        "commit authority",
                        "Primary Authority",
                    )
                ):
                    raise CommitActuatorBlocked(message) from None
                raise
        if row is None:
            raise CommitActuatorBlocked(
                "commit authority returned no durable grant"
            )
        return CommitAuthorityGrant(
            request_sha256=row["request_sha256"],
            work_lease_ref=row["work_lease_ref"],
            primary_authority_ref=row["primary_authority_ref"],
        )


__all__ = ["PostgresCommitAuthority"]
