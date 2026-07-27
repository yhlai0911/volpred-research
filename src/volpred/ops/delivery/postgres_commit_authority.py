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

from volpred.ops.authority import (
    FORMAL_PRIMARY_AUTHORITY_KEY,
    PrimaryLease,
)

from ._git_actuator import (
    CommitActuatorBlocked,
    CommitAuthorityAbandonment,
    CommitAuthorityGrant,
    CommitAuthorityRequest,
    _authority_request_sha256,
    _validate_abandonment,
    _validate_authority_grant,
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
        if primary_lease.authority_key != FORMAL_PRIMARY_AUTHORITY_KEY:
            raise ValueError(
                "commit authority requires the formal primary authority "
                "lease"
            )
        self._connection_factory = connection_factory
        self._primary_lease = primary_lease

    def authorize(
        self,
        request: CommitAuthorityRequest,
    ) -> CommitAuthorityGrant:
        self._validate_request(request)

        with self._connection_factory() as connection:
            connection.row_factory = dict_row
            try:
                row = connection.execute(
                    """
                    SELECT *
                    FROM volpred_ops.authorize_commit_write(
                      %s, %s, %s, %s, %s, %s, %s, %s, %s,
                      %s, %s, %s, %s
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
                        request.commit_owner_generation,
                        request.work_lease_token,
                        request.repository,
                        request.expected_head,
                        request.actor,
                    ),
                ).fetchone()
                if row is not None:
                    row = connection.execute(
                        """
                        SELECT *
                        FROM volpred_ops.read_active_commit_authority_grant(%s)
                        """,
                        (request.request_sha256,),
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
                        "commit ownership",
                        "Primary Authority",
                    )
                ):
                    raise CommitActuatorBlocked(message) from None
                raise
        if row is None:
            raise CommitActuatorBlocked(
                "commit authority returned no durable grant"
            )
        return self._grant(row, request=request)

    def recover(
        self,
        request: CommitAuthorityRequest,
    ) -> CommitAuthorityGrant | None:
        self._validate_request(request)
        with self._connection_factory() as connection:
            connection.row_factory = dict_row
            try:
                row = connection.execute(
                    """
                    SELECT *
                    FROM volpred_ops.read_active_commit_authority_grant(%s)
                    """,
                    (request.request_sha256,),
                ).fetchone()
            except Exception as error:
                self._translate(error)
                raise AssertionError("unreachable")
        if row is None:
            return None
        return self._grant(row, request=request)

    def abandon(
        self,
        request: CommitAuthorityRequest,
        grant: CommitAuthorityGrant,
        *,
        reason: str,
    ) -> CommitAuthorityAbandonment:
        self._validate_request(request)
        _validate_authority_grant(grant, request=request)
        with self._connection_factory() as connection:
            connection.row_factory = dict_row
            try:
                row = connection.execute(
                    """
                    SELECT *
                    FROM volpred_ops.abandon_commit_write(
                      %s, %s, %s, %s
                    )
                    """,
                    (
                        request.request_sha256,
                        grant.commit_owner_generation,
                        grant.commit_owner_ref,
                        reason,
                    ),
                ).fetchone()
            except Exception as error:
                self._translate(error)
                raise AssertionError("unreachable")
        if row is None:
            raise CommitActuatorBlocked(
                "commit authority returned no abandonment receipt"
            )
        return _validate_abandonment(
            CommitAuthorityAbandonment(
                schema_version=row["schema_version"],
                request_sha256=row["request_sha256"],
                reason=row["reason"],
                abandoned_at=row["abandoned_at"].isoformat(),
            ),
            request=request,
            reason=reason,
        )

    @staticmethod
    def _validate_request(request: CommitAuthorityRequest) -> None:
        if not isinstance(request, CommitAuthorityRequest):
            raise TypeError("CommitAuthorityRequest is required")
        if request.request_sha256 != _authority_request_sha256(request):
            raise CommitActuatorBlocked(
                "commit authority request hash does not match its write intent"
            )

    @staticmethod
    def _translate(error: Exception) -> None:
        message = getattr(
            getattr(error, "diag", None),
            "message_primary",
            "",
        )
        if message.startswith(
            (
                "commit authority",
                "commit ownership",
                "Primary Authority",
            )
        ):
            raise CommitActuatorBlocked(message) from None
        raise error

    @staticmethod
    def _grant(
        row: dict[str, Any],
        *,
        request: CommitAuthorityRequest,
    ) -> CommitAuthorityGrant:
        return _validate_authority_grant(
            CommitAuthorityGrant(
                request_sha256=row["request_sha256"],
                commit_owner_generation=row["commit_owner_generation"],
                commit_owner_ref=row["commit_owner_ref"],
                work_lease_ref=row["work_lease_ref"],
                primary_authority_ref=row["primary_authority_ref"],
            ),
            request=request,
        )


__all__ = ["PostgresCommitAuthority"]
