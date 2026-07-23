"""PostgreSQL adapter for immutable durable effect payloads."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timezone
import hashlib
from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row


ConnectionFactory = Callable[[], Connection[Any]]


@dataclass(frozen=True)
class EffectPayloadView:
    schema_version: str
    payload_ref: str
    payload_sha256: str
    byte_size: int
    writer_ref: str
    created_at: str


class EffectPayloadConflict(ValueError):
    """A durable payload ref was replayed with different bytes."""


class PostgresEffectPayloadStore:
    """Write and read immutable payload bytes through named DB functions."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._connection_factory = connection_factory

    @staticmethod
    def _translate(error: Exception) -> None:
        message = getattr(getattr(error, "diag", None), "message_primary", "")
        if message.startswith(
            "effect payload ref conflicts with its original bytes"
        ):
            raise EffectPayloadConflict(message) from None
        if message.startswith(
            (
                "effect payload fields are required",
                "effect payload hash must be lowercase SHA-256",
                "effect payload hash does not match its bytes",
                "unknown effect payload:",
            )
        ):
            raise ValueError(message) from None
        raise error

    def write(
        self,
        *,
        payload_ref: str,
        payload: bytes,
        writer_ref: str,
    ) -> EffectPayloadView:
        if not isinstance(payload, bytes):
            raise TypeError("effect payload must be bytes")
        payload_sha256 = hashlib.sha256(payload).hexdigest()
        with self._connection_factory() as connection:
            connection.row_factory = dict_row
            try:
                row = connection.execute(
                    """
                    SELECT *
                    FROM volpred_ops.put_effect_payload(%s, %s, %s, %s)
                    """,
                    (
                        payload_ref,
                        payload,
                        payload_sha256,
                        writer_ref,
                    ),
                ).fetchone()
            except Exception as error:
                self._translate(error)
                raise AssertionError("unreachable")
        if row is None:
            raise RuntimeError("put_effect_payload returned no payload")
        return EffectPayloadView(
            schema_version="effect-payload.v1",
            payload_ref=row["payload_ref"],
            payload_sha256=row["payload_sha256"],
            byte_size=row["byte_size"],
            writer_ref=row["writer_ref"],
            created_at=row["created_at"].astimezone(timezone.utc).isoformat(),
        )

    def read(self, payload_ref: str) -> bytes:
        with self._connection_factory() as connection:
            try:
                row = connection.execute(
                    "SELECT volpred_ops.read_effect_payload(%s)",
                    (payload_ref,),
                ).fetchone()
            except Exception as error:
                self._translate(error)
                raise AssertionError("unreachable")
        if row is None or not isinstance(row[0], bytes):
            raise RuntimeError("read_effect_payload returned invalid bytes")
        return row[0]


__all__ = [
    "EffectPayloadConflict",
    "EffectPayloadView",
    "PostgresEffectPayloadStore",
]
