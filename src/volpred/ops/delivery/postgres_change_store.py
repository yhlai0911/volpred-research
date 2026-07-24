"""PostgreSQL adapter for durable ChangeSet lifecycle state."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from . import (
    ChangeSetConflict,
    ChangeSetView,
    CheckEvidence,
    ContentHash,
    DeliveryReceipt,
)
from ._change_store import ChangeSetRecord
from ._git_actuator import CommitActuationReceipt


ConnectionFactory = Callable[[], Connection[Any]]


def _isoformat(value: datetime | str) -> str:
    observed = (
        datetime.fromisoformat(value)
        if isinstance(value, str)
        else value
    )
    if observed.tzinfo is None:
        raise ValueError("ChangeSet timestamp must include UTC offset")
    return observed.astimezone(timezone.utc).isoformat()


def _actuation_json(receipt: CommitActuationReceipt) -> dict[str, Any]:
    return {
        "schema_version": receipt.schema_version,
        "proposal_sha256": receipt.proposal_sha256,
        "work_item_id": receipt.work_item_id,
        "work_item_version": receipt.work_item_version,
        "commit_owner_generation": receipt.commit_owner_generation,
        "commit_owner_ref": receipt.commit_owner_ref,
        "authority_request_sha256": receipt.authority_request_sha256,
        "work_lease_ref": receipt.work_lease_ref,
        "primary_authority_ref": receipt.primary_authority_ref,
        "commit_sha": receipt.commit_sha,
        "parent_sha": receipt.parent_sha,
        "exact_paths": list(receipt.exact_paths),
        "actor": receipt.actor,
        "status": receipt.status,
        "observed_at": receipt.observed_at,
    }


def _actuation_from_json(
    payload: dict[str, Any] | None,
) -> CommitActuationReceipt | None:
    if payload is None:
        return None
    return CommitActuationReceipt(
        schema_version=payload["schema_version"],
        proposal_sha256=payload["proposal_sha256"],
        work_item_id=payload["work_item_id"],
        work_item_version=int(payload["work_item_version"]),
        commit_owner_generation=int(payload["commit_owner_generation"]),
        commit_owner_ref=payload["commit_owner_ref"],
        authority_request_sha256=payload["authority_request_sha256"],
        work_lease_ref=payload["work_lease_ref"],
        primary_authority_ref=payload["primary_authority_ref"],
        commit_sha=payload["commit_sha"],
        parent_sha=payload["parent_sha"],
        exact_paths=tuple(payload["exact_paths"]),
        actor=payload["actor"],
        status=payload["status"],
        observed_at=payload["observed_at"],
    )


def _record_from_row(row: Mapping[str, Any]) -> ChangeSetRecord:
    view = ChangeSetView(
        schema_version=row["schema_version"],
        id=row["id"],
        idempotency_key=row["idempotency_key"],
        work_item_id=row["work_item_id"],
        work_item_version=row["work_item_version"],
        base_commit=row["base_commit"],
        workspace_ref=row["workspace_ref"],
        exact_paths=tuple(row["exact_paths"]),
        content_hashes=tuple(
            ContentHash(path=item["path"], sha256=item["sha256"])
            for item in row["content_hashes"]
        ),
        required_checks=tuple(
            CheckEvidence(
                name=item["name"],
                status=item["status"],
                evidence_ref=item["evidence_ref"],
            )
            for item in row["required_checks"]
        ),
        author_ref=row["author_ref"],
        author_evidence_ref=row["author_evidence_ref"],
        proposal_sha256=row["proposal_sha256"],
        status=row["status"],
        created_at=_isoformat(row["created_at"]),
    )
    delivery = None
    if row["delivery_schema_version"] is not None:
        delivery = DeliveryReceipt(
            schema_version=row["delivery_schema_version"],
            change_set_id=row["id"],
            proposal_sha256=row["proposal_sha256"],
            work_item_id=row["work_item_id"],
            work_item_version=row["work_item_version"],
            commit_owner_generation=row["delivery_commit_owner_generation"],
            commit_owner_ref=row["delivery_commit_owner_ref"],
            authority_request_sha256=row[
                "delivery_authority_request_sha256"
            ],
            work_lease_ref=row["delivery_work_lease_ref"],
            primary_authority_ref=row["delivery_primary_authority_ref"],
            repository=row["delivery_repository"],
            commit_sha=row["delivery_commit_sha"],
            parent_sha=row["delivery_parent_sha"],
            exact_paths=tuple(row["delivery_exact_paths"]),
            actor=row["delivery_commit_worker_ref"],
            status=row["delivery_status"],
            actuation_observed_at=_isoformat(
                row["delivery_actuation_observed_at"]
            ),
            settled_at=_isoformat(row["delivery_settled_at"]),
            settlement_ref=row["delivery_settlement_ref"],
            settlement_sha256=row["delivery_settlement_sha256"],
        )
    return ChangeSetRecord(
        view=view,
        land_command_sha256=row["land_command_sha256"],
        actuation=_actuation_from_json(row["actuation_receipt"]),
        delivery=delivery,
    )


class PostgresChangeSetStore:
    """Persist proposals and crash-recovery checkpoints behind one seam."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._connection_factory = connection_factory

    @staticmethod
    def _translate(error: Exception) -> None:
        message = getattr(getattr(error, "diag", None), "message_primary", "")
        if "conflicts with" in message and message.startswith("ChangeSet"):
            raise ChangeSetConflict(message) from None
        if message.startswith(
            (
                "ChangeSet fields are required",
                "ChangeSet hashes must be lowercase SHA-256",
                "ChangeSet work item is unknown:",
                "ChangeSet work item version is stale:",
                "ChangeSet JSON evidence is invalid",
                "ChangeSet status cannot",
                "ChangeSet actuation receipt is invalid",
                "ChangeSet delivery receipt is unknown",
                "ChangeSet delivery receipt does not match",
                "duplicate ChangeSet id:",
                "unknown ChangeSet:",
            )
        ):
            raise ValueError(message) from None
        raise error

    def _execute_one(
        self,
        query: str,
        parameters: tuple[Any, ...],
        *,
        missing: str,
        missing_error: type[Exception] = RuntimeError,
    ) -> ChangeSetRecord:
        with self._connection_factory() as connection:
            connection.row_factory = dict_row
            try:
                row = connection.execute(query, parameters).fetchone()
            except Exception as error:
                self._translate(error)
                raise AssertionError("unreachable")
        if row is None:
            raise missing_error(missing)
        return _record_from_row(row)

    def create(self, view: ChangeSetView) -> ChangeSetRecord:
        return self._execute_one(
            """
            SELECT *
            FROM volpred_ops.create_change_set(
              %s, %s, %s, %s, %s, %s, %s, %s, %s,
              %s, %s, %s, %s, %s
            )
            """,
            (
                view.id,
                view.idempotency_key,
                view.work_item_id,
                view.work_item_version,
                view.base_commit,
                view.workspace_ref,
                Jsonb(list(view.exact_paths)),
                Jsonb(
                    [
                        {"path": item.path, "sha256": item.sha256}
                        for item in view.content_hashes
                    ]
                ),
                Jsonb(
                    [
                        {
                            "name": item.name,
                            "status": item.status,
                            "evidence_ref": item.evidence_ref,
                        }
                        for item in view.required_checks
                    ]
                ),
                view.author_ref,
                view.author_evidence_ref,
                view.proposal_sha256,
                view.schema_version,
                view.created_at,
            ),
            missing="create_change_set returned no ChangeSet",
        )

    def load(self, change_set_id: str) -> ChangeSetRecord:
        normalized = change_set_id.strip()
        if not normalized:
            raise ValueError("ChangeSet id is required")
        return self._execute_one(
            """
            SELECT *
            FROM volpred_ops.change_set_reads
            WHERE id = %s
            """,
            (normalized,),
            missing=f"unknown ChangeSet: {normalized}",
            missing_error=ValueError,
        )

    def load_by_idempotency_key(
        self,
        idempotency_key: str,
    ) -> ChangeSetRecord | None:
        normalized = idempotency_key.strip()
        if not normalized:
            raise ValueError("ChangeSet idempotency key is required")
        with self._connection_factory() as connection:
            connection.row_factory = dict_row
            row = connection.execute(
                """
                SELECT *
                FROM volpred_ops.change_set_reads
                WHERE idempotency_key = %s
                """,
                (normalized,),
            ).fetchone()
        return _record_from_row(row) if row is not None else None

    def checkpoint_actuation(
        self,
        *,
        change_set_id: str,
        proposal_sha256: str,
        land_command_sha256: str,
        actuation: CommitActuationReceipt,
    ) -> ChangeSetRecord:
        return self._execute_one(
            """
            SELECT *
            FROM volpred_ops.checkpoint_change_set_actuation(
              %s, %s, %s, %s
            )
            """,
            (
                change_set_id,
                proposal_sha256,
                land_command_sha256,
                Jsonb(_actuation_json(actuation)),
            ),
            missing="checkpoint_change_set_actuation returned no ChangeSet",
        )

    def mark_landed(
        self,
        *,
        change_set_id: str,
        proposal_sha256: str,
        land_command_sha256: str,
        delivery: DeliveryReceipt,
    ) -> ChangeSetRecord:
        record = self._execute_one(
            """
            SELECT *
            FROM volpred_ops.mark_change_set_landed(
              %s, %s, %s, %s
            )
            """,
            (
                change_set_id,
                proposal_sha256,
                land_command_sha256,
                delivery.authority_request_sha256,
            ),
            missing="mark_change_set_landed returned no ChangeSet",
        )
        if record.delivery != delivery:
            raise ChangeSetConflict(
                "ChangeSet delivery conflicts with its durable receipt"
            )
        return record


__all__ = ["PostgresChangeSetStore"]
