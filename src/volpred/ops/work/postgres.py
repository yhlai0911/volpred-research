"""PostgreSQL coordination adapter for the shadow Work Coordinator."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row

from . import (
    ApprovalGranted,
    Checkpointed,
    ClaimLost,
    Completed,
    Released,
    VerifiedCheckpointView,
    WorkEventView,
    WorkItemView,
    WorkLease,
    WorkQuery,
    WorkReceiptView,
    WorkerOffer,
)


ConnectionFactory = Callable[[], Connection[Any]]


def _isoformat(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat() if value is not None else None


def _item_from_row(row: dict[str, Any]) -> WorkItemView:
    return WorkItemView(
        id=row["id"],
        idempotency_key=row["idempotency_key"],
        source=row["source"],
        kind=row["kind"],
        title=row["title"],
        priority=row["priority"],
        required_capabilities=frozenset(row["required_capabilities"]),
        required_attestations=frozenset(row["required_attestations"]),
        risk=row["risk"],
        approval=row["approval"],
        payload_ref=row["payload_ref"],
        parent_id=row["parent_id"],
        deadline=_isoformat(row["deadline"]),
        requester_ref=row["requester_ref"],
        status=row["status"],
        version=row["version"],
        created_at=_isoformat(row["created_at"]),
        updated_at=_isoformat(row["updated_at"]),
        blocked_reason=row["blocked_reason"],
        claimed_by=row["claimed_by"],
        claim_expires_at=_isoformat(row["claim_expires_at"]),
        latest_verified_checkpoint_id=row["latest_verified_checkpoint_id"],
        last_release_reason=row["last_release_reason"],
        result_ref=row["result_ref"],
        result_summary=row["result_summary"],
        finished_at=_isoformat(row["finished_at"]),
    )


class PostgresCoordinationStore:
    """Persist coordination state in one PostgreSQL transaction per mutation."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._connection_factory = connection_factory

    @staticmethod
    def _execute_mutation(
        connection: Connection[Any],
        query: str,
        params: tuple[Any, ...],
    ) -> dict[str, Any] | None:
        try:
            return connection.execute(query, params).fetchone()
        except Exception as error:
            message = getattr(getattr(error, "diag", None), "message_primary", "")
            if message.startswith("claim lost: "):
                raise ClaimLost(message.removeprefix("claim lost: ")) from None
            if message.startswith(
                (
                    "unknown work item:",
                    "stale work item version:",
                    "cannot approve work item",
                    "cannot mutate work item",
                    "claim token is required",
                    "approval requires",
                    "checkpoint report",
                    "completion report",
                    "lease_seconds must be positive",
                )
            ):
                raise ValueError(message) from None
            raise

    def create_if_absent(
        self,
        idempotency_key: str,
        candidate: WorkItemView,
    ) -> WorkItemView:
        with self._connection_factory() as connection:
            connection.row_factory = dict_row
            item = self._execute_mutation(
                connection,
                """
                SELECT *
                FROM volpred_ops.submit_work(
                  %s, %s, %s, %s, %s, %s, %s, %s, %s,
                  %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    candidate.id,
                    idempotency_key,
                    candidate.source,
                    candidate.kind,
                    candidate.title,
                    candidate.priority,
                    list(candidate.required_capabilities),
                    list(candidate.required_attestations),
                    candidate.risk,
                    candidate.approval,
                    candidate.payload_ref,
                    candidate.parent_id,
                    candidate.deadline,
                    candidate.requester_ref,
                    candidate.status,
                    candidate.version,
                    candidate.created_at,
                    candidate.updated_at,
                ),
            )
            if item is None:
                raise RuntimeError("submit_work returned no work item")
            return _item_from_row(item)

    def inspect(self, query: WorkQuery) -> tuple[WorkItemView, ...]:
        with self._connection_factory() as connection:
            connection.row_factory = dict_row
            if query.work_id is None:
                rows = connection.execute(
                    "SELECT * FROM volpred_ops.work_item_reads ORDER BY id"
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM volpred_ops.work_item_reads WHERE id = %s",
                    (query.work_id,),
                ).fetchall()
            return tuple(_item_from_row(row) for row in rows)

    def inspect_events(self, query: WorkQuery) -> tuple[WorkEventView, ...]:
        with self._connection_factory() as connection:
            connection.row_factory = dict_row
            if query.work_id is None:
                rows = connection.execute(
                    """
                    SELECT work_id, kind, version, created_at,
                           actor_ref, evidence_ref
                    FROM volpred_ops.work_events
                    ORDER BY sequence
                    """
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT work_id, kind, version, created_at,
                           actor_ref, evidence_ref
                    FROM volpred_ops.work_events
                    WHERE work_id = %s
                    ORDER BY sequence
                    """,
                    (query.work_id,),
                ).fetchall()
            return tuple(
                WorkEventView(
                    work_id=row["work_id"],
                    kind=row["kind"],
                    version=row["version"],
                    created_at=_isoformat(row["created_at"]),
                    actor_ref=row["actor_ref"],
                    evidence_ref=row["evidence_ref"],
                )
                for row in rows
            )

    def inspect_checkpoints(
        self,
        query: WorkQuery,
    ) -> tuple[VerifiedCheckpointView, ...]:
        with self._connection_factory() as connection:
            connection.row_factory = dict_row
            if query.work_id is None:
                rows = connection.execute(
                    """
                    SELECT id, work_id, artifact_ref, artifact_sha256,
                           verification_ref, created_at
                    FROM volpred_ops.work_checkpoints
                    ORDER BY created_at, id
                    """
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT id, work_id, artifact_ref, artifact_sha256,
                           verification_ref, created_at
                    FROM volpred_ops.work_checkpoints
                    WHERE work_id = %s
                    ORDER BY created_at, id
                    """,
                    (query.work_id,),
                ).fetchall()
            return tuple(
                VerifiedCheckpointView(
                    id=row["id"],
                    work_id=row["work_id"],
                    artifact_ref=row["artifact_ref"],
                    artifact_sha256=row["artifact_sha256"],
                    verification_ref=row["verification_ref"],
                    created_at=_isoformat(row["created_at"]),
                )
                for row in rows
            )

    def inspect_receipts(
        self,
        query: WorkQuery,
    ) -> tuple[WorkReceiptView, ...]:
        with self._connection_factory() as connection:
            connection.row_factory = dict_row
            if query.work_id is None:
                rows = connection.execute(
                    """
                    SELECT id, work_id, outcome, result_ref, summary, created_at
                    FROM volpred_ops.work_receipts
                    ORDER BY created_at, id
                    """
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT id, work_id, outcome, result_ref, summary, created_at
                    FROM volpred_ops.work_receipts
                    WHERE work_id = %s
                    ORDER BY created_at, id
                    """,
                    (query.work_id,),
                ).fetchall()
            return tuple(
                WorkReceiptView(
                    id=row["id"],
                    work_id=row["work_id"],
                    outcome=row["outcome"],
                    result_ref=row["result_ref"],
                    summary=row["summary"],
                    created_at=_isoformat(row["created_at"]),
                )
                for row in rows
            )

    def acquire(
        self,
        offer: WorkerOffer,
        *,
        token: str,
        claimed_at: str,
        expires_at: str,
    ) -> WorkLease | None:
        # PostgreSQL is authoritative for lease time across hosts.
        del claimed_at, expires_at
        with self._connection_factory() as connection:
            connection.row_factory = dict_row
            claimed = self._execute_mutation(
                connection,
                """
                SELECT *
                FROM volpred_ops.acquire_work(%s, %s, %s, %s, %s)
                """,
                (
                    offer.worker_id,
                    list(offer.capabilities),
                    list(offer.attestations),
                    offer.lease_seconds,
                    token,
                ),
            )
            if claimed is None:
                return None
            item = _item_from_row(claimed)
            return WorkLease(
                token=token,
                work_item=item,
                expires_at=item.claim_expires_at,
                resume_checkpoint_id=item.latest_verified_checkpoint_id,
            )

    def approve(
        self,
        report: ApprovalGranted,
        *,
        created_at: str,
    ) -> WorkItemView:
        del created_at
        with self._connection_factory() as connection:
            connection.row_factory = dict_row
            approved = self._execute_mutation(
                connection,
                """
                SELECT *
                FROM volpred_ops.approve_work(%s, %s, %s, %s)
                """,
                (
                    report.work_id,
                    report.expected_version,
                    report.approved_by,
                    report.evidence_ref,
                ),
            )
            if approved is None:
                raise RuntimeError("approve_work returned no work item")
            return _item_from_row(approved)

    def start(
        self,
        work_id: str,
        *,
        lease_token: str,
        expected_version: int,
        observed_at: str,
    ) -> WorkItemView:
        del observed_at
        with self._connection_factory() as connection:
            connection.row_factory = dict_row
            running = self._execute_mutation(
                connection,
                """
                SELECT *
                FROM volpred_ops.start_work(%s, %s, %s)
                """,
                (work_id, lease_token, expected_version),
            )
            if running is None:
                raise RuntimeError("start_work returned no work item")
            return _item_from_row(running)

    def checkpoint(
        self,
        report: Checkpointed,
        *,
        checkpoint_id: str,
        created_at: str,
    ) -> WorkItemView:
        del created_at
        with self._connection_factory() as connection:
            connection.row_factory = dict_row
            checkpointed = self._execute_mutation(
                connection,
                """
                SELECT *
                FROM volpred_ops.checkpoint_work(
                  %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    report.work_id,
                    report.lease_token,
                    report.expected_version,
                    report.report_id,
                    report.artifact_ref,
                    report.artifact_sha256,
                    report.verification_ref,
                ),
            )
            if checkpointed is None:
                raise RuntimeError("checkpoint_work returned no work item")
            return _item_from_row(checkpointed)

    def release(self, report: Released, *, observed_at: str) -> WorkItemView:
        del observed_at
        with self._connection_factory() as connection:
            connection.row_factory = dict_row
            released = self._execute_mutation(
                connection,
                """
                SELECT *
                FROM volpred_ops.release_work(%s, %s, %s, %s)
                """,
                (
                    report.work_id,
                    report.lease_token,
                    report.expected_version,
                    report.reason,
                ),
            )
            if released is None:
                raise RuntimeError("release_work returned no work item")
            return _item_from_row(released)

    def complete(
        self,
        report: Completed,
        *,
        created_at: str,
    ) -> WorkItemView:
        del created_at
        with self._connection_factory() as connection:
            connection.row_factory = dict_row
            completed = self._execute_mutation(
                connection,
                """
                SELECT *
                FROM volpred_ops.complete_work(%s, %s, %s, %s, %s, %s)
                """,
                (
                    report.report_id,
                    report.work_id,
                    report.lease_token,
                    report.expected_version,
                    report.result_ref,
                    report.summary,
                ),
            )
            if completed is None:
                raise RuntimeError("complete_work returned no work item")
            return _item_from_row(completed)
