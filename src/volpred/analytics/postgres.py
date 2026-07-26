"""PostgreSQL adapter for the analytics privacy contract."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
import hashlib
import hmac
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from .privacy import (
    AnalyticsEvent,
    AnalyticsEventReceipt,
    AnalyticsIdentityMergeReceipt,
    AnalyticsPrivacyActionReceipt,
    AnalyticsPrivacyReadback,
)


ConnectionFactory = Callable[[], psycopg.Connection[Any]]


class PostgresAnalyticsStore:
    """Durable private-schema store with transactional identity operations."""

    def __init__(
        self,
        connection_factory: ConnectionFactory,
        *,
        tombstone_secret: bytes,
        digest_key_id: str,
    ) -> None:
        if len(tombstone_secret) < 32:
            raise ValueError(
                "analytics tombstone_secret must contain at least 32 bytes"
            )
        if not digest_key_id.strip():
            raise ValueError("analytics digest_key_id is required")
        self._connection_factory = connection_factory
        self._tombstone_secret = tombstone_secret
        self._digest_key_id = digest_key_id

    def _lock_subjects(
        self,
        connection: psycopg.Connection[Any],
        subject_refs: set[str],
    ) -> None:
        self._verify_digest_key(connection)
        connection.execute(
            """
            SELECT pg_advisory_xact_lock(
              hashtextextended('volpred-analytics:identity-graph', 0)
            )
            """
        )
        for subject_ref in sorted(subject_refs):
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"volpred-analytics:{subject_ref}",),
            )

    def _verify_digest_key(
        self,
        connection: psycopg.Connection[Any],
    ) -> None:
        verifier = self._keyed_digest(
            f"digest-key-verifier:{self._digest_key_id}".encode("utf-8")
        )
        connection.execute(
            """
            INSERT INTO volpred_analytics.digest_key_identity (
              singleton,
              key_id,
              verifier
            ) VALUES (true, %s, %s)
            ON CONFLICT (singleton) DO NOTHING
            """,
            (self._digest_key_id, verifier),
        )
        existing = connection.execute(
            """
            SELECT key_id, verifier
            FROM volpred_analytics.digest_key_identity
            WHERE singleton
            """
        ).fetchone()
        if (
            existing is None
            or existing[0] != self._digest_key_id
            or not hmac.compare_digest(bytes(existing[1]), verifier)
        ):
            raise ValueError("analytics digest key identity mismatch")

    def _subject_digest(self, subject_kind: str, subject_id: str) -> bytes:
        return self._keyed_digest(
            f"subject:{subject_kind}:{subject_id}".encode("utf-8")
        )

    def _event_key_digest(self, idempotency_key: str) -> bytes:
        return self._keyed_digest(
            f"event-key:{idempotency_key}".encode("utf-8")
        )

    def _event_payload_digest(self, event: AnalyticsEvent) -> bytes:
        return self._keyed_digest(
            b"event-payload:" + event.canonical_payload_bytes()
        )

    def _keyed_digest(self, value: bytes) -> bytes:
        return hmac.new(
            self._tombstone_secret, value, hashlib.sha256
        ).digest()

    def _aliases(
        self,
        connection: psycopg.Connection[Any],
        subject_kind: str,
        subject_id: str,
    ) -> tuple[set[str], set[str]]:
        anonymous_ids: set[str] = set()
        user_ids: set[str] = set()
        if subject_kind == "anonymous":
            anonymous_ids.add(subject_id)
            row = connection.execute(
                """
                SELECT user_id
                FROM volpred_analytics.identity_links
                WHERE anonymous_id = %s
                """,
                (subject_id,),
            ).fetchone()
            if row is not None:
                user_ids.add(row[0])
        else:
            user_ids.add(subject_id)
        if user_ids:
            rows = connection.execute(
                """
                SELECT anonymous_id
                FROM volpred_analytics.identity_links
                WHERE user_id = ANY(%s)
                """,
                (list(user_ids),),
            ).fetchall()
            anonymous_ids.update(row[0] for row in rows)
        return anonymous_ids, user_ids

    def _is_deleted(
        self,
        connection: psycopg.Connection[Any],
        identities: set[tuple[str, str]],
    ) -> bool:
        if not identities:
            return False
        digests = [
            self._subject_digest(subject_kind, subject_id)
            for subject_kind, subject_id in identities
        ]
        return (
            connection.execute(
                """
                SELECT EXISTS (
                  SELECT 1
                  FROM volpred_analytics.privacy_tombstones
                  WHERE subject_digest = ANY(%s)
                )
                """,
                (digests,),
            ).fetchone()[0]
            is True
        )

    def _store_subject_tombstones(
        self,
        connection: psycopg.Connection[Any],
        identities: set[tuple[str, str]],
        *,
        deleted_at: str,
    ) -> None:
        with connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO volpred_analytics.privacy_tombstones (
                  subject_digest,
                  deleted_at
                ) VALUES (%s, %s)
                ON CONFLICT (subject_digest)
                DO UPDATE SET deleted_at = EXCLUDED.deleted_at
                """,
                [
                    (
                        self._subject_digest(subject_kind, subject_id),
                        deleted_at,
                    )
                    for subject_kind, subject_id in identities
                ],
            )

    def _is_opted_out(
        self,
        connection: psycopg.Connection[Any],
        anonymous_ids: set[str],
        user_ids: set[str],
    ) -> bool:
        return (
            connection.execute(
                """
                SELECT EXISTS (
                  SELECT 1
                  FROM volpred_analytics.privacy_preferences
                  WHERE (
                    subject_kind = 'anonymous'
                    AND subject_id = ANY(%s)
                  ) OR (
                    subject_kind = 'user'
                    AND subject_id = ANY(%s)
                  )
                )
                """,
                (list(anonymous_ids), list(user_ids)),
            ).fetchone()[0]
            is True
        )

    def record(
        self,
        event: AnalyticsEvent,
        *,
        raw_expires_at: str,
    ) -> AnalyticsEventReceipt:
        with self._connection_factory() as connection:
            payload_digest = self._event_payload_digest(event)
            refs = {
                ref
                for ref in (
                    f"anonymous:{event.anonymous_id}"
                    if event.anonymous_id
                    else None,
                    f"user:{event.user_id}" if event.user_id else None,
                )
                if ref is not None
            }
            self._lock_subjects(connection, refs)
            existing = connection.execute(
                """
                SELECT id, idempotency_key, raw_expires_at, payload_digest
                FROM volpred_analytics.events
                WHERE idempotency_key = %s
                """,
                (event.idempotency_key,),
            ).fetchone()
            if existing is not None:
                if not hmac.compare_digest(
                    bytes(existing[3]), payload_digest
                ):
                    raise ValueError(
                        "analytics event idempotency_key was reused"
                    )
                return AnalyticsEventReceipt(
                    event_id=f"analytics-event-{existing[0]}",
                    idempotency_key=existing[1],
                    accepted=True,
                    duplicate=True,
                    raw_expires_at=existing[2].isoformat(),
                )
            direct_identities = {
                identity
                for identity in (
                    ("anonymous", event.anonymous_id)
                    if event.anonymous_id
                    else None,
                    ("user", event.user_id) if event.user_id else None,
                )
                if identity is not None
            }
            if self._is_deleted(connection, direct_identities):
                return AnalyticsEventReceipt(
                    event_id=None,
                    idempotency_key=event.idempotency_key,
                    accepted=False,
                    duplicate=False,
                    raw_expires_at=None,
                    reason="deleted",
                )
            expired_replay = connection.execute(
                """
                SELECT event_payload_digest, suppression_reason
                  FROM volpred_analytics.event_dedupe_tombstones
                  WHERE idempotency_digest = %s
                """,
                (self._event_key_digest(event.idempotency_key),),
            ).fetchone()
            if expired_replay is not None:
                if not hmac.compare_digest(
                    bytes(expired_replay[0]), payload_digest
                ):
                    raise ValueError(
                        "analytics event idempotency_key was reused"
                    )
                return AnalyticsEventReceipt(
                    event_id=None,
                    idempotency_key=event.idempotency_key,
                    accepted=False,
                    duplicate=False,
                    raw_expires_at=None,
                    reason=expired_replay[1],
                )
            anonymous_ids = (
                {event.anonymous_id} if event.anonymous_id else set()
            )
            user_ids = {event.user_id} if event.user_id else set()
            if event.anonymous_id:
                linked = connection.execute(
                    """
                    SELECT user_id
                    FROM volpred_analytics.identity_links
                    WHERE anonymous_id = %s
                    """,
                    (event.anonymous_id,),
                ).fetchone()
                if linked is not None:
                    if (
                        event.user_id is not None
                        and linked[0] != event.user_id
                    ):
                        raise ValueError("conflicting analytics identities")
                    user_ids.add(linked[0])
            identities = {
                *(("anonymous", value) for value in anonymous_ids),
                *(("user", value) for value in user_ids),
            }
            if self._is_deleted(connection, identities):
                return AnalyticsEventReceipt(
                    event_id=None,
                    idempotency_key=event.idempotency_key,
                    accepted=False,
                    duplicate=False,
                    raw_expires_at=None,
                    reason="deleted",
                )
            if self._is_opted_out(connection, anonymous_ids, user_ids):
                return AnalyticsEventReceipt(
                    event_id=None,
                    idempotency_key=event.idempotency_key,
                    accepted=False,
                    duplicate=False,
                    raw_expires_at=None,
                    reason="opted_out",
                )
            canonical_user_id = event.user_id
            if canonical_user_id is None and user_ids:
                canonical_user_id = next(iter(user_ids))
            inserted = connection.execute(
                """
                INSERT INTO volpred_analytics.events (
                  idempotency_key,
                  kind,
                  occurred_at,
                  anonymous_id,
                  submitted_user_id,
                  user_id,
                  properties,
                  payload_digest,
                  raw_expires_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, raw_expires_at
                """,
                (
                    event.idempotency_key,
                    event.kind,
                    event.occurred_at,
                    event.anonymous_id,
                    event.user_id,
                    canonical_user_id,
                    Jsonb(dict(event.properties)),
                    payload_digest,
                    raw_expires_at,
                ),
            ).fetchone()
            return AnalyticsEventReceipt(
                event_id=f"analytics-event-{inserted[0]}",
                idempotency_key=event.idempotency_key,
                accepted=True,
                duplicate=False,
                raw_expires_at=inserted[1].isoformat(),
            )

    def merge_identity(
        self,
        *,
        idempotency_key: str,
        anonymous_id: str,
        user_id: str,
        merged_at: str,
    ) -> AnalyticsIdentityMergeReceipt:
        with self._connection_factory() as connection:
            self._lock_subjects(
                connection,
                {f"anonymous:{anonymous_id}", f"user:{user_id}"},
            )
            existing_replay = connection.execute(
                """
                SELECT anonymous_id, user_id, merged_at, merged_events
                FROM volpred_analytics.identity_merge_receipts
                WHERE idempotency_key = %s
                """,
                (idempotency_key,),
            ).fetchone()
            if existing_replay is not None:
                if existing_replay[:2] != (anonymous_id, user_id):
                    raise ValueError(
                        "identity merge idempotency_key was reused"
                    )
                return AnalyticsIdentityMergeReceipt(
                    idempotency_key=idempotency_key,
                    anonymous_id=anonymous_id,
                    user_id=user_id,
                    merged_events=existing_replay[3],
                    duplicate=True,
                    merged_at=existing_replay[2].isoformat(),
                )
            if self._is_deleted(
                connection,
                {
                    ("anonymous", anonymous_id),
                    ("user", user_id),
                },
            ):
                self._store_subject_tombstones(
                    connection,
                    {
                        ("anonymous", anonymous_id),
                        ("user", user_id),
                    },
                    deleted_at=merged_at,
                )
                connection.commit()
                raise ValueError("cannot merge a deleted analytics identity")
            existing_link = connection.execute(
                """
                SELECT user_id
                FROM volpred_analytics.identity_links
                WHERE anonymous_id = %s
                """,
                (anonymous_id,),
            ).fetchone()
            if existing_link is not None and existing_link[0] != user_id:
                raise ValueError(
                    "anonymous identity already belongs to another user: "
                    f"{anonymous_id}"
                )
            updated = connection.execute(
                """
                UPDATE volpred_analytics.events
                SET user_id = %s
                WHERE anonymous_id = %s
                  AND user_id IS DISTINCT FROM %s
                """,
                (user_id, anonymous_id, user_id),
            )
            if existing_link is None:
                connection.execute(
                    """
                    INSERT INTO volpred_analytics.identity_links (
                      anonymous_id,
                      user_id,
                      merged_at
                    ) VALUES (%s, %s, %s)
                    """,
                    (
                        anonymous_id,
                        user_id,
                        merged_at,
                    ),
                )
            connection.execute(
                """
                INSERT INTO volpred_analytics.identity_merge_receipts (
                  idempotency_key,
                  anonymous_id,
                  user_id,
                  merged_at,
                  merged_events
                ) VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    idempotency_key,
                    anonymous_id,
                    user_id,
                    merged_at,
                    updated.rowcount,
                ),
            )
            return AnalyticsIdentityMergeReceipt(
                idempotency_key=idempotency_key,
                anonymous_id=anonymous_id,
                user_id=user_id,
                merged_events=updated.rowcount,
                duplicate=False,
                merged_at=merged_at,
            )

    def admin_summary(
        self,
        *,
        start_at: str,
        end_at: str,
    ) -> tuple[dict[str, int | str], ...]:
        with self._connection_factory() as connection:
            self._verify_digest_key(connection)
            rows = connection.execute(
                """
                SELECT events.kind, count(*)::integer
                FROM volpred_analytics.events AS events
                WHERE events.occurred_at >= %s
                  AND events.occurred_at < %s
                  AND NOT EXISTS (
                    SELECT 1
                    FROM volpred_analytics.privacy_preferences AS prefs
                    WHERE (
                      prefs.subject_kind = 'anonymous'
                      AND prefs.subject_id = events.anonymous_id
                    ) OR (
                      prefs.subject_kind = 'user'
                      AND prefs.subject_id = events.user_id
                    ) OR (
                      prefs.subject_kind = 'user'
                      AND prefs.subject_id = (
                        SELECT links.user_id
                        FROM volpred_analytics.identity_links AS links
                        WHERE links.anonymous_id = events.anonymous_id
                      )
                    ) OR (
                      prefs.subject_kind = 'anonymous'
                      AND EXISTS (
                        SELECT 1
                        FROM volpred_analytics.identity_links AS links
                        WHERE links.anonymous_id = prefs.subject_id
                          AND links.user_id = events.user_id
                      )
                    )
                  )
                GROUP BY events.kind
                ORDER BY events.kind
                """,
                (start_at, end_at),
            ).fetchall()
        return tuple(
            {"event_kind": row[0], "event_count": row[1]}
            for row in rows
        )

    def _privacy_action_replay(
        self,
        connection: psycopg.Connection[Any],
        idempotency_key: str,
        *,
        action: str,
        subject_digest: bytes,
    ) -> AnalyticsPrivacyActionReceipt | None:
        row = connection.execute(
            """
            SELECT action, subject_digest, acted_at, removed_raw_events,
                   removed_identity_links
            FROM volpred_analytics.privacy_action_receipts
            WHERE idempotency_key = %s
            """,
            (idempotency_key,),
        ).fetchone()
        if row is None:
            return None
        if row[0] != action or bytes(row[1]) != subject_digest:
            raise ValueError("privacy action idempotency_key was reused")
        return AnalyticsPrivacyActionReceipt(
            action=row[0],
            idempotency_key=idempotency_key,
            acted_at=row[2].isoformat(),
            removed_raw_events=row[3],
            removed_identity_links=row[4],
            duplicate=True,
        )

    def _save_privacy_action(
        self,
        connection: psycopg.Connection[Any],
        *,
        action: str,
        subject_digest: bytes,
        idempotency_key: str,
        acted_at: str,
        removed_raw_events: int = 0,
        removed_identity_links: int = 0,
    ) -> AnalyticsPrivacyActionReceipt:
        connection.execute(
            """
            INSERT INTO volpred_analytics.privacy_action_receipts (
              idempotency_key,
              action,
              subject_digest,
              acted_at,
              removed_raw_events,
              removed_identity_links
            ) VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                idempotency_key,
                action,
                subject_digest,
                acted_at,
                removed_raw_events,
                removed_identity_links,
            ),
        )
        return AnalyticsPrivacyActionReceipt(
            action=action,
            idempotency_key=idempotency_key,
            acted_at=acted_at,
            removed_raw_events=removed_raw_events,
            removed_identity_links=removed_identity_links,
            duplicate=False,
        )

    def _suppress_event_rows(
        self,
        connection: psycopg.Connection[Any],
        rows: list[tuple[Any, ...]],
        *,
        reason: str,
        acted_at: str,
    ) -> None:
        with connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO volpred_analytics.event_dedupe_tombstones (
                  idempotency_digest,
                  event_payload_digest,
                  suppression_reason,
                  suppressed_at
                ) VALUES (%s, %s, %s, %s)
                ON CONFLICT (idempotency_digest)
                DO UPDATE SET
                  suppression_reason = EXCLUDED.suppression_reason,
                  suppressed_at = EXCLUDED.suppressed_at
                WHERE event_dedupe_tombstones.event_payload_digest
                  = EXCLUDED.event_payload_digest
                """,
                [
                    (
                        self._event_key_digest(row[1]),
                        bytes(row[2]),
                        reason,
                        acted_at,
                    )
                    for row in rows
                ],
            )

    def set_opt_out(
        self,
        *,
        subject_kind: str,
        subject_id: str,
        idempotency_key: str,
        acted_at: str,
    ) -> AnalyticsPrivacyActionReceipt:
        with self._connection_factory() as connection:
            self._lock_subjects(
                connection, {f"{subject_kind}:{subject_id}"}
            )
            replay = self._privacy_action_replay(
                connection,
                idempotency_key,
                action="opt_out",
                subject_digest=self._subject_digest(
                    subject_kind, subject_id
                ),
            )
            if replay is not None:
                return replay
            if self._is_deleted(
                connection, {(subject_kind, subject_id)}
            ):
                raise ValueError("cannot mutate a deleted analytics identity")
            connection.execute(
                """
                INSERT INTO volpred_analytics.privacy_preferences (
                  subject_kind,
                  subject_id,
                  opted_out,
                  idempotency_key,
                  acted_at
                ) VALUES (%s, %s, true, %s, %s)
                ON CONFLICT (subject_kind, subject_id)
                DO UPDATE SET
                  opted_out = true,
                  idempotency_key = EXCLUDED.idempotency_key,
                  acted_at = EXCLUDED.acted_at
                """,
                (subject_kind, subject_id, idempotency_key, acted_at),
            )
            return self._save_privacy_action(
                connection,
                action="opt_out",
                subject_digest=self._subject_digest(
                    subject_kind, subject_id
                ),
                idempotency_key=idempotency_key,
                acted_at=acted_at,
            )

    def clear(
        self,
        *,
        subject_kind: str,
        subject_id: str,
        idempotency_key: str,
        acted_at: str,
    ) -> AnalyticsPrivacyActionReceipt:
        with self._connection_factory() as connection:
            self._lock_subjects(
                connection, {f"{subject_kind}:{subject_id}"}
            )
            replay = self._privacy_action_replay(
                connection,
                idempotency_key,
                action="clear",
                subject_digest=self._subject_digest(
                    subject_kind, subject_id
                ),
            )
            if replay is not None:
                return replay
            if self._is_deleted(
                connection, {(subject_kind, subject_id)}
            ):
                raise ValueError("cannot mutate a deleted analytics identity")
            anonymous_ids, user_ids = self._aliases(
                connection, subject_kind, subject_id
            )
            cleared_rows = connection.execute(
                """
                SELECT id, idempotency_key, payload_digest
                FROM volpred_analytics.events
                WHERE anonymous_id = ANY(%s)
                   OR user_id = ANY(%s)
                FOR UPDATE
                """,
                (list(anonymous_ids), list(user_ids)),
            ).fetchall()
            self._suppress_event_rows(
                connection,
                cleared_rows,
                reason="cleared",
                acted_at=acted_at,
            )
            connection.execute(
                """
                DELETE FROM volpred_analytics.events
                WHERE id = ANY(%s)
                """,
                ([row[0] for row in cleared_rows],),
            )
            return self._save_privacy_action(
                connection,
                action="clear",
                subject_digest=self._subject_digest(
                    subject_kind, subject_id
                ),
                idempotency_key=idempotency_key,
                acted_at=acted_at,
                removed_raw_events=len(cleared_rows),
            )

    def delete(
        self,
        *,
        subject_kind: str,
        subject_id: str,
        idempotency_key: str,
        acted_at: str,
    ) -> AnalyticsPrivacyActionReceipt:
        with self._connection_factory() as connection:
            self._lock_subjects(
                connection, {f"{subject_kind}:{subject_id}"}
            )
            replay = self._privacy_action_replay(
                connection,
                idempotency_key,
                action="delete",
                subject_digest=self._subject_digest(
                    subject_kind, subject_id
                ),
            )
            if replay is not None:
                return replay
            anonymous_ids, user_ids = self._aliases(
                connection, subject_kind, subject_id
            )
            self._store_subject_tombstones(
                connection,
                {
                    *(("anonymous", value) for value in anonymous_ids),
                    *(("user", value) for value in user_ids),
                },
                deleted_at=acted_at,
            )
            removed_events = connection.execute(
                """
                DELETE FROM volpred_analytics.events
                WHERE anonymous_id = ANY(%s)
                   OR user_id = ANY(%s)
                """,
                (list(anonymous_ids), list(user_ids)),
            ).rowcount
            connection.execute(
                """
                DELETE FROM volpred_analytics.privacy_preferences
                WHERE (
                  subject_kind = 'anonymous'
                  AND subject_id = ANY(%s)
                ) OR (
                  subject_kind = 'user'
                  AND subject_id = ANY(%s)
                )
                """,
                (list(anonymous_ids), list(user_ids)),
            )
            removed_links = connection.execute(
                """
                DELETE FROM volpred_analytics.identity_links
                WHERE anonymous_id = ANY(%s)
                   OR user_id = ANY(%s)
                """,
                (list(anonymous_ids), list(user_ids)),
            ).rowcount
            connection.execute(
                """
                DELETE FROM volpred_analytics.identity_merge_receipts
                WHERE anonymous_id = ANY(%s)
                   OR user_id = ANY(%s)
                """,
                (list(anonymous_ids), list(user_ids)),
            )
            action_digests = [
                *(
                    self._subject_digest("anonymous", value)
                    for value in anonymous_ids
                ),
                *(
                    self._subject_digest("user", value)
                    for value in user_ids
                ),
            ]
            connection.execute(
                """
                DELETE FROM volpred_analytics.privacy_action_receipts
                WHERE subject_digest = ANY(%s)
                """,
                (action_digests,),
            )
            return self._save_privacy_action(
                connection,
                action="delete",
                subject_digest=self._subject_digest(
                    subject_kind, subject_id
                ),
                idempotency_key=idempotency_key,
                acted_at=acted_at,
                removed_raw_events=removed_events,
                removed_identity_links=removed_links,
            )

    def inspect_privacy(
        self,
        *,
        subject_kind: str,
        subject_id: str,
    ) -> AnalyticsPrivacyReadback:
        with self._connection_factory() as connection:
            self._verify_digest_key(connection)
            anonymous_ids, user_ids = self._aliases(
                connection, subject_kind, subject_id
            )
            raw_event_count = connection.execute(
                """
                SELECT count(*)::integer
                FROM volpred_analytics.events
                WHERE anonymous_id = ANY(%s)
                   OR user_id = ANY(%s)
                """,
                (list(anonymous_ids), list(user_ids)),
            ).fetchone()[0]
            opted_out = self._is_opted_out(
                connection, anonymous_ids, user_ids
            )
            identity_link_count = connection.execute(
                """
                SELECT count(*)::integer
                FROM volpred_analytics.identity_links
                WHERE anonymous_id = ANY(%s)
                  AND user_id = ANY(%s)
                """,
                (list(anonymous_ids), list(user_ids)),
            ).fetchone()[0]
        return AnalyticsPrivacyReadback(
            opted_out=opted_out,
            raw_event_count=raw_event_count,
            projected_event_count=0 if opted_out else raw_event_count,
            identity_link_count=identity_link_count,
        )

    def purge_expired(self, *, before: str) -> int:
        with self._connection_factory() as connection:
            self._lock_subjects(connection, set())
            expired_rows = connection.execute(
                """
                SELECT id, idempotency_key, payload_digest
                FROM volpred_analytics.events
                WHERE raw_expires_at <= %s
                FOR UPDATE
                """,
                (before,),
            ).fetchall()
            self._suppress_event_rows(
                connection,
                expired_rows,
                reason="expired",
                acted_at=before,
            )
            connection.execute(
                """
                DELETE FROM volpred_analytics.events
                WHERE id = ANY(%s)
                """,
                ([row[0] for row in expired_rows],),
            )
        return len(expired_rows)
