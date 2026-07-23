"""PostgreSQL adapter for durable EffectRequest and outbox claiming."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from psycopg import Connection
from psycopg.rows import dict_row

from ._effect import (
    AcknowledgementExpectation,
    EffectRequest,
    EffectRequestConflict,
    EffectView,
    _normalize_request,
    _request_sha256,
)


ConnectionFactory = Callable[[], Connection[Any]]


def _isoformat(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat() if value is not None else None


def _effect_from_row(row: dict[str, Any]) -> EffectView:
    return EffectView(
        schema_version="effect-request.v1",
        id=row["id"],
        idempotency_key=row["idempotency_key"],
        work_item_id=row["work_item_id"],
        work_item_version=row["work_item_version"],
        effect_kind=row["effect_kind"],
        target_ref=row["target_ref"],
        payload_ref=row["payload_ref"],
        payload_sha256=row["payload_sha256"],
        risk=row["risk"],
        acknowledgement=AcknowledgementExpectation(
            kind=row["acknowledgement_kind"],
            target_ref=row["acknowledgement_target_ref"],
        ),
        requester_ref=row["requester_ref"],
        request_sha256=row["request_sha256"],
        status=row["status"],
        created_at=_isoformat(row["created_at"]),
    )


@dataclass(frozen=True)
class EffectOutboxLease:
    """A fenced claim on one pending effect intent.

    The token is deliberately absent from the read projection and only returned
    to the worker that generated it. Delivery acknowledgement arrives in a
    later slice; an abandoned claim becomes eligible after ``expires_at``.
    """

    sequence: int
    effect_id: str
    token: str
    claimed_by: str
    attempt_count: int
    expires_at: str


class PostgresEffectDelivery:
    """Persist effect intent and its outbox row in one database transaction."""

    def __init__(
        self,
        connection_factory: ConnectionFactory,
        *,
        id_factory: Callable[[], str] | None = None,
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        self._connection_factory = connection_factory
        self._id_factory = id_factory or (lambda: f"effect_{uuid4().hex}")
        self._token_factory = token_factory or (
            lambda: f"effect_claim_{uuid4().hex}"
        )

    @staticmethod
    def _translate(error: Exception) -> None:
        message = getattr(getattr(error, "diag", None), "message_primary", "")
        if message.startswith(
            "effect request idempotency key conflicts with its original payload"
        ):
            raise EffectRequestConflict(message) from None
        if message.startswith(
            (
                "unknown effect work item:",
                "stale effect work item version:",
                "effect request fields are required",
                "effect work item version must be positive",
                "effect request hashes must be lowercase SHA-256",
                "unsupported effect risk:",
                "effect outbox worker and token are required",
                "effect outbox lease_seconds must be positive",
            )
        ):
            raise ValueError(message) from None
        raise error

    def request(self, request: EffectRequest) -> EffectView:
        normalized = _normalize_request(request)
        request_sha256 = _request_sha256(normalized)
        effect_id = self._id_factory().strip()
        if not effect_id:
            raise ValueError("EffectRequest id is required")

        with self._connection_factory() as connection:
            connection.row_factory = dict_row
            try:
                row = connection.execute(
                    """
                    SELECT *
                    FROM volpred_ops.request_effect(
                      %s, %s, %s, %s, %s, %s, %s,
                      %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        effect_id,
                        normalized.idempotency_key,
                        normalized.work_item_id,
                        normalized.work_item_version,
                        normalized.effect_kind,
                        normalized.target_ref,
                        normalized.payload_ref,
                        normalized.payload_sha256,
                        normalized.risk,
                        normalized.acknowledgement.kind,
                        normalized.acknowledgement.target_ref,
                        normalized.requester_ref,
                        request_sha256,
                    ),
                ).fetchone()
            except Exception as error:
                self._translate(error)
                raise AssertionError("unreachable")
        if row is None:
            raise RuntimeError("request_effect returned no EffectRequest")
        return _effect_from_row(row)

    def inspect(self, effect_id: str) -> EffectView:
        if not isinstance(effect_id, str) or not effect_id.strip():
            raise ValueError("EffectRequest id is required")
        with self._connection_factory() as connection:
            connection.row_factory = dict_row
            row = connection.execute(
                """
                SELECT *
                FROM volpred_ops.effect_request_reads
                WHERE id = %s
                """,
                (effect_id.strip(),),
            ).fetchone()
        if row is None:
            raise ValueError(f"unknown EffectRequest: {effect_id.strip()}")
        return _effect_from_row(row)

    def claim_outbox(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
    ) -> EffectOutboxLease | None:
        if not isinstance(worker_id, str) or not worker_id.strip():
            raise ValueError("effect outbox worker is required")
        if (
            isinstance(lease_seconds, bool)
            or not isinstance(lease_seconds, int)
            or lease_seconds <= 0
        ):
            raise ValueError("effect outbox lease_seconds must be positive")
        token = self._token_factory().strip()
        if not token:
            raise ValueError("effect outbox token is required")

        with self._connection_factory() as connection:
            connection.row_factory = dict_row
            try:
                row = connection.execute(
                    """
                    SELECT *
                    FROM volpred_ops.claim_effect_outbox(%s, %s, %s)
                    """,
                    (worker_id.strip(), lease_seconds, token),
                ).fetchone()
            except Exception as error:
                self._translate(error)
                raise AssertionError("unreachable")
        if row is None:
            return None
        expires_at = _isoformat(row["claim_expires_at"])
        if expires_at is None:
            raise RuntimeError("claimed effect outbox row omitted expiry")
        return EffectOutboxLease(
            sequence=row["sequence"],
            effect_id=row["effect_id"],
            token=token,
            claimed_by=row["claimed_by"],
            attempt_count=row["attempt_count"],
            expires_at=expires_at,
        )


__all__ = ["EffectOutboxLease", "PostgresEffectDelivery"]
