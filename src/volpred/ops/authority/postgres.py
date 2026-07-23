"""PostgreSQL adapter for Primary Authority leases and fencing grants."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row

from . import (
    AuthorityReceipt,
    AuthorityRequest,
    FencingGrant,
    PrimaryLease,
    WriteIntent,
)


ConnectionFactory = Callable[[], Connection[Any]]


def _isoformat(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


class PostgresAuthorityStore:
    """Persist one DB-clock lease per authority key."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._connection_factory = connection_factory

    @staticmethod
    def _translate(error: Exception) -> None:
        message = getattr(getattr(error, "diag", None), "message_primary", "")
        if message.startswith(
            (
                "Primary Authority fields are required",
                "Primary Authority lease_seconds must be positive",
                "Primary Authority is already held:",
                "Primary Authority lease lost:",
                "Primary Authority epoch mismatch:",
                "Primary Authority lease expired:",
                "Primary Authority request hash must be lowercase SHA-256",
                "Primary Authority grant conflicts with its original intent",
            )
        ):
            raise ValueError(message) from None
        raise error

    def acquire(
        self,
        request: AuthorityRequest,
        *,
        fencing_token: str,
    ) -> PrimaryLease:
        with self._connection_factory() as connection:
            connection.row_factory = dict_row
            try:
                row = connection.execute(
                    """
                    SELECT *
                    FROM volpred_ops.acquire_primary_authority(
                      %s, %s, %s, %s
                    )
                    """,
                    (
                        request.authority_key,
                        request.holder_ref,
                        request.lease_seconds,
                        fencing_token,
                    ),
                ).fetchone()
            except Exception as error:
                self._translate(error)
                raise AssertionError("unreachable")
        if row is None:
            raise RuntimeError("acquire_primary_authority returned no lease")
        return PrimaryLease(
            schema_version="primary-lease.v1",
            authority_key=row["authority_key"],
            holder_ref=row["holder_ref"],
            epoch=row["epoch"],
            fencing_token=fencing_token,
            lease_seconds=request.lease_seconds,
            acquired_at=_isoformat(row["acquired_at"]),
            expires_at=_isoformat(row["lease_expires_at"]),
        )

    def renew(self, lease: PrimaryLease) -> PrimaryLease:
        with self._connection_factory() as connection:
            connection.row_factory = dict_row
            try:
                row = connection.execute(
                    """
                    SELECT *
                    FROM volpred_ops.renew_primary_authority(
                      %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        lease.authority_key,
                        lease.holder_ref,
                        lease.epoch,
                        lease.lease_seconds,
                        lease.fencing_token,
                    ),
                ).fetchone()
            except Exception as error:
                self._translate(error)
                raise AssertionError("unreachable")
        if row is None:
            raise RuntimeError("renew_primary_authority returned no lease")
        return PrimaryLease(
            schema_version="primary-lease.v1",
            authority_key=row["authority_key"],
            holder_ref=row["holder_ref"],
            epoch=row["epoch"],
            fencing_token=lease.fencing_token,
            lease_seconds=lease.lease_seconds,
            acquired_at=_isoformat(row["acquired_at"]),
            expires_at=_isoformat(row["lease_expires_at"]),
        )

    def authorize(self, intent: WriteIntent) -> FencingGrant:
        with self._connection_factory() as connection:
            connection.row_factory = dict_row
            try:
                row = connection.execute(
                    """
                    SELECT *
                    FROM volpred_ops.authorize_primary_write(
                      %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        intent.authority_key,
                        intent.holder_ref,
                        intent.epoch,
                        intent.fencing_token,
                        intent.request_sha256,
                        intent.resource_ref,
                    ),
                ).fetchone()
            except Exception as error:
                self._translate(error)
                raise AssertionError("unreachable")
        if row is None:
            raise RuntimeError("authorize_primary_write returned no grant")
        return FencingGrant(
            schema_version="primary-fencing-grant.v1",
            request_sha256=row["request_sha256"],
            resource_ref=row["resource_ref"],
            primary_authority_ref=row["primary_authority_ref"],
            granted_at=_isoformat(row["granted_at"]),
        )

    def release(self, lease: PrimaryLease) -> AuthorityReceipt:
        with self._connection_factory() as connection:
            connection.row_factory = dict_row
            try:
                row = connection.execute(
                    """
                    SELECT *
                    FROM volpred_ops.release_primary_authority(
                      %s, %s, %s, %s
                    )
                    """,
                    (
                        lease.authority_key,
                        lease.holder_ref,
                        lease.epoch,
                        lease.fencing_token,
                    ),
                ).fetchone()
            except Exception as error:
                self._translate(error)
                raise AssertionError("unreachable")
        if row is None:
            raise RuntimeError("release_primary_authority returned no receipt")
        return AuthorityReceipt(
            schema_version="primary-authority-receipt.v1",
            authority_key=row["authority_key"],
            holder_ref=row["holder_ref"],
            epoch=row["epoch"],
            primary_authority_ref=row["primary_authority_ref"],
            released_at=_isoformat(row["released_at"]),
        )


__all__ = ["PostgresAuthorityStore"]
