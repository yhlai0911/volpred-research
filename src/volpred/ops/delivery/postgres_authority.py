"""Primary Authority adapter for durable effect attempts."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row

from ._effect_worker import (
    EffectAuthorityGrant,
    EffectAuthorityRequest,
    EffectWorkerBlocked,
)


ConnectionFactory = Callable[[], Connection[Any]]


class PostgresEffectAuthority:
    """Atomically verify Primary Authority and the current outbox claim."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._connection_factory = connection_factory

    def authorize(
        self,
        request: EffectAuthorityRequest,
    ) -> EffectAuthorityGrant:
        with self._connection_factory() as connection:
            connection.row_factory = dict_row
            try:
                row = connection.execute(
                    """
                    SELECT *
                    FROM volpred_ops.authorize_effect_write(
                      %s, %s, %s, %s, %s, %s, %s, %s, %s,
                      %s, %s, %s, %s, %s, %s, %s, %s, %s,
                      %s, %s
                    )
                    """,
                    (
                        request.primary_authority_key,
                        request.primary_authority_holder_ref,
                        request.primary_authority_epoch,
                        request.primary_fencing_token,
                        request.request_sha256,
                        request.effect_id,
                        request.effect_request_sha256,
                        request.work_item_id,
                        request.work_item_version,
                        request.outbox_sequence,
                        request.outbox_attempt_count,
                        request.outbox_claim_token,
                        request.outbox_claim_expires_at,
                        request.worker_id,
                        request.effect_kind,
                        request.target_ref,
                        request.payload_ref,
                        request.payload_sha256,
                        request.acknowledgement_kind,
                        request.acknowledgement_target_ref,
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
                        "Primary Authority",
                        "effect authority",
                    )
                ):
                    raise EffectWorkerBlocked(message) from None
                raise
        if row is None:
            raise EffectWorkerBlocked(
                "Primary Authority returned no durable effect grant"
            )
        return EffectAuthorityGrant(
            request_sha256=row["request_sha256"],
            outbox_claim_ref=row["outbox_claim_ref"],
            primary_authority_ref=row["primary_authority_ref"],
        )


__all__ = ["PostgresEffectAuthority"]
