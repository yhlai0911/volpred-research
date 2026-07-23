"""PostgreSQL adapter for durable EffectRequest and outbox settlement."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from psycopg import Connection
from psycopg.rows import dict_row

from ._effect import (
    AcknowledgedEffect,
    AcknowledgementExpectation,
    EffectAttemptOutcome,
    EffectRequest,
    EffectRequestConflict,
    EffectView,
    FailedEffect,
    _normalize_attempt_outcome,
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
    to the worker that generated it. An abandoned claim becomes eligible after
    ``expires_at``; late settlement is fenced by the attempt count and token.
    """

    sequence: int
    effect_id: str
    token: str
    claimed_by: str
    attempt_count: int
    expires_at: str


@dataclass(frozen=True)
class EffectAttemptReceipt:
    """Immutable result of settling one fenced outbox attempt."""

    schema_version: str
    effect_id: str
    outbox_sequence: int
    attempt_count: int
    worker_id: str
    reported_outcome: str
    disposition: str
    acknowledgement: AcknowledgementExpectation | None
    reason_code: str | None
    evidence_ref: str
    evidence_sha256: str
    authority_request_sha256: str | None
    outbox_claim_ref: str | None
    primary_authority_ref: str | None
    retry_at: str | None
    recorded_at: str


@dataclass(frozen=True)
class EffectSettlementAuthority:
    """Token-redacted authority evidence persisted with one attempt."""

    request_sha256: str
    outbox_claim_ref: str
    primary_authority_ref: str


def _attempt_receipt_from_row(row: dict[str, Any]) -> EffectAttemptReceipt:
    acknowledgement = None
    if row["acknowledgement_kind"] is not None:
        acknowledgement = AcknowledgementExpectation(
            kind=row["acknowledgement_kind"],
            target_ref=row["acknowledgement_target_ref"],
        )
    retry_at = _isoformat(row["retry_at"])
    recorded_at = _isoformat(row["recorded_at"])
    if recorded_at is None:
        raise RuntimeError("effect attempt receipt omitted recorded_at")
    return EffectAttemptReceipt(
        schema_version="effect-attempt-receipt.v1",
        effect_id=row["effect_id"],
        outbox_sequence=row["outbox_sequence"],
        attempt_count=row["attempt_count"],
        worker_id=row["worker_id"],
        reported_outcome=row["reported_outcome"],
        disposition=row["disposition"],
        acknowledgement=acknowledgement,
        reason_code=row["reason_code"],
        evidence_ref=row["evidence_ref"],
        evidence_sha256=row["evidence_sha256"],
        authority_request_sha256=row.get("authority_request_sha256"),
        outbox_claim_ref=row.get("outbox_claim_ref"),
        primary_authority_ref=row.get("primary_authority_ref"),
        retry_at=retry_at,
        recorded_at=recorded_at,
    )


class PostgresEffectDelivery:
    """Persist effect intent and own its fenced outbox lifecycle."""

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
                "unknown effect payload:",
                "effect payload hash does not match its durable bytes",
                "unsupported effect risk:",
                "effect outbox worker and token are required",
                "effect outbox lease_seconds must be positive",
                "effect outbox settlement fields are required",
                "effect outbox settlement authority is required",
                "effect outbox attempt_count must be positive",
                "effect outbox sequence must be positive",
                "effect outbox settlement hash must be lowercase SHA-256",
                "unsupported effect outbox outcome:",
                "effect outbox acknowledgement fields are required",
                "effect outbox failure reason_code is required",
                "unknown effect outbox attempt:",
                "effect outbox attempt is not actively claimed:",
                "effect outbox attempt worker mismatch:",
                "effect outbox attempt token mismatch:",
                "effect outbox attempt count mismatch:",
                "effect outbox attempt lease expired:",
                "effect outbox acknowledgement mismatch:",
                "effect outbox settlement conflicts with its original outcome",
                "effect authority grant is missing or does not match settlement",
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

    def settle_outbox(
        self,
        *,
        lease: EffectOutboxLease,
        outcome: EffectAttemptOutcome,
        authority: EffectSettlementAuthority,
    ) -> EffectAttemptReceipt:
        """Atomically record one attempt and transition retry/terminal state.

        Equivalent replay returns the original immutable receipt. A stale
        lease, mismatched acknowledgement, or changed outcome fails closed.
        Backoff and attempt exhaustion are database-owned policy.
        """

        if not isinstance(lease, EffectOutboxLease):
            raise TypeError("effect outbox lease is required")
        if not isinstance(authority, EffectSettlementAuthority):
            raise TypeError("effect settlement authority is required")
        authority_request_sha256 = authority.request_sha256
        if (
            not isinstance(authority_request_sha256, str)
            or len(authority_request_sha256) != 64
            or any(
                character not in "0123456789abcdef"
                for character in authority_request_sha256
            )
        ):
            raise ValueError(
                "effect settlement authority request must be lowercase SHA-256"
            )
        outbox_claim_ref = authority.outbox_claim_ref.strip()
        primary_authority_ref = authority.primary_authority_ref.strip()
        if not outbox_claim_ref or not primary_authority_ref:
            raise ValueError(
                "effect settlement authority references are required"
            )
        normalized = _normalize_attempt_outcome(outcome)
        if isinstance(normalized, AcknowledgedEffect):
            outcome_kind = "acknowledged"
            acknowledgement_kind = normalized.acknowledgement.kind
            acknowledgement_target_ref = normalized.acknowledgement.target_ref
            reason_code = None
        elif isinstance(normalized, FailedEffect):
            outcome_kind = (
                "retryable_failure"
                if normalized.retryable
                else "terminal_failure"
            )
            acknowledgement_kind = None
            acknowledgement_target_ref = None
            reason_code = normalized.reason_code
        else:  # pragma: no cover - normalization is exhaustive
            raise AssertionError("unreachable effect outcome")

        with self._connection_factory() as connection:
            connection.row_factory = dict_row
            try:
                row = connection.execute(
                    """
                    SELECT *
                    FROM volpred_ops.settle_effect_outbox(
                      %s, %s, %s, %s, %s, %s,
                      %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        lease.sequence,
                        lease.effect_id,
                        lease.attempt_count,
                        lease.claimed_by,
                        lease.token,
                        authority_request_sha256,
                        outbox_claim_ref,
                        primary_authority_ref,
                        outcome_kind,
                        acknowledgement_kind,
                        acknowledgement_target_ref,
                        reason_code,
                        normalized.evidence_ref,
                        normalized.evidence_sha256,
                    ),
                ).fetchone()
            except Exception as error:
                self._translate(error)
                raise AssertionError("unreachable")
        if row is None:
            raise RuntimeError(
                "settle_effect_outbox returned no EffectAttemptReceipt"
            )
        return _attempt_receipt_from_row(row)


__all__ = [
    "EffectAttemptReceipt",
    "EffectOutboxLease",
    "EffectSettlementAuthority",
    "PostgresEffectDelivery",
]
