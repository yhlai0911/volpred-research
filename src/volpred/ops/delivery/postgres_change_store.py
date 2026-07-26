"""PostgreSQL adapter for durable ChangeSet lifecycle state."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from . import (
    ChangeSetConflict,
    ChangeSetProposal,
    ChangeSetView,
    CheckEvidence,
    ContentHash,
    DeliveryReceipt,
    _normalize_proposal,
    _proposal_sha256,
)
from ._change_store import ChangeSetRecord
from ._change_settlement import (
    CommitSettlement,
    commit_settlement_sha256,
)
from ._git_actuator import CommitActuationReceipt


ConnectionFactory = Callable[[], Connection[Any]]
_GIT_OBJECT_ID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_DELIVERY_FIELDS = (
    "delivery_schema_version",
    "delivery_authority_request_sha256",
    "delivery_work_lease_ref",
    "delivery_primary_authority_ref",
    "delivery_repository",
    "delivery_commit_sha",
    "delivery_parent_sha",
    "delivery_exact_paths",
    "delivery_commit_worker_ref",
    "delivery_status",
    "delivery_actuation_observed_at",
    "delivery_settled_at",
    "delivery_settlement_ref",
    "delivery_settlement_sha256",
    "delivery_commit_owner_generation",
    "delivery_commit_owner_ref",
)


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
    payload: Mapping[str, Any] | None,
) -> CommitActuationReceipt | None:
    if payload is None:
        return None
    if not isinstance(payload, Mapping):
        raise ValueError("actuation_receipt must be an object")
    return CommitActuationReceipt(
        schema_version=_text(payload["schema_version"], "actuation schema"),
        proposal_sha256=_sha(
            payload["proposal_sha256"], "actuation proposal_sha256"
        ),
        work_item_id=_text(payload["work_item_id"], "actuation work_item_id"),
        work_item_version=_positive_int(
            payload["work_item_version"], "actuation work_item_version"
        ),
        commit_owner_generation=_positive_int(
            payload["commit_owner_generation"],
            "actuation commit_owner_generation",
        ),
        commit_owner_ref=_text(
            payload["commit_owner_ref"], "actuation commit_owner_ref"
        ),
        authority_request_sha256=_sha(
            payload["authority_request_sha256"],
            "actuation authority_request_sha256",
        ),
        work_lease_ref=_text(
            payload["work_lease_ref"], "actuation work_lease_ref"
        ),
        primary_authority_ref=_text(
            payload["primary_authority_ref"],
            "actuation primary_authority_ref",
        ),
        commit_sha=_git_object(payload["commit_sha"], "actuation commit_sha"),
        parent_sha=_git_object(payload["parent_sha"], "actuation parent_sha"),
        exact_paths=_text_tuple(
            payload["exact_paths"], "actuation exact_paths"
        ),
        actor=_commit_worker(payload["actor"]),
        status=_text(payload["status"], "actuation status"),
        observed_at=_isoformat(payload["observed_at"]),
    )


def _record_from_row(row: Mapping[str, Any]) -> ChangeSetRecord:
    try:
        return _decode_record(row)
    except RuntimeError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError) as error:
        raise RuntimeError(
            f"malformed ChangeSet record: {error}"
        ) from error


def _decode_record(row: Mapping[str, Any]) -> ChangeSetRecord:
    if not isinstance(row, Mapping):
        raise ValueError("record must be an object")
    raw_hashes = _object_tuple(row["content_hashes"], "content_hashes")
    raw_checks = _object_tuple(row["required_checks"], "required_checks")
    proposal = ChangeSetProposal(
        idempotency_key=_text(row["idempotency_key"], "idempotency_key"),
        work_item_id=_text(row["work_item_id"], "work_item_id"),
        work_item_version=_positive_int(
            row["work_item_version"], "work_item_version"
        ),
        base_commit=_git_object(row["base_commit"], "base_commit"),
        workspace_ref=_absolute_path(row["workspace_ref"], "workspace_ref"),
        exact_paths=_text_tuple(row["exact_paths"], "exact_paths"),
        content_hashes=tuple(
            ContentHash(
                path=_text(item["path"], "content hash path"),
                sha256=_sha(item["sha256"], "content hash"),
            )
            for item in raw_hashes
        ),
        required_checks=tuple(
            CheckEvidence(
                name=_text(item["name"], "check name"),
                status=_text(item["status"], "check status"),
                evidence_ref=_text(item["evidence_ref"], "check evidence"),
            )
            for item in raw_checks
        ),
        author_ref=_text(row["author_ref"], "author_ref"),
        author_evidence_ref=_text(
            row["author_evidence_ref"], "author_evidence_ref"
        ),
    )
    normalized = _normalize_proposal(proposal)
    if normalized != proposal:
        raise ValueError("proposal fields are not canonical")
    proposal_sha256 = _sha(row["proposal_sha256"], "proposal_sha256")
    if _proposal_sha256(normalized) != proposal_sha256:
        raise ValueError("proposal_sha256 does not match proposal fields")
    schema_version = _text(row["schema_version"], "schema_version")
    if schema_version != "changeset.v1":
        raise ValueError("unsupported schema_version")
    status = _text(row["status"], "status")
    if status not in {"proposed", "commit_unsettled", "landed"}:
        raise ValueError("unsupported ChangeSet status")
    view = ChangeSetView(
        schema_version=schema_version,
        id=_text(row["id"], "id"),
        idempotency_key=normalized.idempotency_key,
        work_item_id=normalized.work_item_id,
        work_item_version=normalized.work_item_version,
        base_commit=normalized.base_commit,
        workspace_ref=normalized.workspace_ref,
        exact_paths=normalized.exact_paths,
        content_hashes=normalized.content_hashes,
        required_checks=normalized.required_checks,
        author_ref=normalized.author_ref,
        author_evidence_ref=normalized.author_evidence_ref,
        proposal_sha256=proposal_sha256,
        status=status,
        created_at=_isoformat(row["created_at"]),
    )
    _isoformat(row["updated_at"])

    land_command_sha256 = _optional_sha(
        row["land_command_sha256"], "land_command_sha256"
    )
    actuation = _actuation_from_json(row["actuation_receipt"])
    if actuation is not None:
        _validate_actuation(view, actuation)
    delivery = _delivery_from_row(row, view=view, actuation=actuation)
    if status == "proposed" and (
        land_command_sha256 is not None
        or actuation is not None
        or delivery is not None
    ):
        raise ValueError("proposed ChangeSet contains landing state")
    if status == "commit_unsettled" and (
        land_command_sha256 is None
        or actuation is None
        or delivery is not None
    ):
        raise ValueError("commit_unsettled ChangeSet lifecycle is incomplete")
    if status == "landed" and (
        land_command_sha256 is None
        or actuation is None
        or delivery is None
    ):
        raise ValueError("landed ChangeSet lifecycle is incomplete")
    return ChangeSetRecord(
        view=view,
        land_command_sha256=land_command_sha256,
        actuation=actuation,
        delivery=delivery,
    )


def _delivery_from_row(
    row: Mapping[str, Any],
    *,
    view: ChangeSetView,
    actuation: CommitActuationReceipt | None,
) -> DeliveryReceipt | None:
    if row["delivery_schema_version"] is None:
        if any(row[field] is not None for field in _DELIVERY_FIELDS):
            raise ValueError("partial delivery receipt")
        return None
    receipt = DeliveryReceipt(
        schema_version=_text(
            row["delivery_schema_version"], "delivery schema_version"
        ),
        change_set_id=view.id,
        proposal_sha256=view.proposal_sha256,
        work_item_id=view.work_item_id,
        work_item_version=view.work_item_version,
        commit_owner_generation=_positive_int(
            row["delivery_commit_owner_generation"],
            "delivery commit_owner_generation",
        ),
        commit_owner_ref=_text(
            row["delivery_commit_owner_ref"], "delivery commit_owner_ref"
        ),
        authority_request_sha256=_sha(
            row["delivery_authority_request_sha256"],
            "delivery authority_request_sha256",
        ),
        work_lease_ref=_text(
            row["delivery_work_lease_ref"], "delivery work_lease_ref"
        ),
        primary_authority_ref=_text(
            row["delivery_primary_authority_ref"],
            "delivery primary_authority_ref",
        ),
        repository=_absolute_path(
            row["delivery_repository"], "delivery repository"
        ),
        commit_sha=_git_object(
            row["delivery_commit_sha"], "delivery commit_sha"
        ),
        parent_sha=_git_object(
            row["delivery_parent_sha"], "delivery parent_sha"
        ),
        exact_paths=_text_tuple(
            row["delivery_exact_paths"], "delivery exact_paths"
        ),
        actor=_commit_worker(row["delivery_commit_worker_ref"]),
        status=_text(row["delivery_status"], "delivery status"),
        actuation_observed_at=_isoformat(
            row["delivery_actuation_observed_at"]
        ),
        settled_at=_isoformat(row["delivery_settled_at"]),
        settlement_ref=_text(
            row["delivery_settlement_ref"], "delivery settlement_ref"
        ),
        settlement_sha256=_sha(
            row["delivery_settlement_sha256"], "delivery settlement_sha256"
        ),
    )
    if (
        actuation is None
        or receipt.schema_version != "change-delivery-receipt.v1"
        or receipt.commit_owner_generation
        != actuation.commit_owner_generation
        or receipt.commit_owner_ref != actuation.commit_owner_ref
        or receipt.authority_request_sha256
        != actuation.authority_request_sha256
        or receipt.work_lease_ref != actuation.work_lease_ref
        or receipt.primary_authority_ref != actuation.primary_authority_ref
        or receipt.commit_sha != actuation.commit_sha
        or receipt.parent_sha != actuation.parent_sha
        or receipt.exact_paths != actuation.exact_paths
        or receipt.actor != actuation.actor
        or receipt.status != "landed"
        or receipt.actuation_observed_at != actuation.observed_at
        or receipt.settlement_ref
        != f"change-delivery:{view.id}:{actuation.commit_sha}"
        or receipt.settlement_sha256
        != commit_settlement_sha256(
            CommitSettlement(
                change_set_id=view.id,
                repository=receipt.repository,
                work_lease_token="redacted-readback",
                primary_fencing_token="redacted-readback",
                actuation=actuation,
            )
        )
    ):
        raise ValueError("delivery receipt does not match actuation")
    return receipt


def _validate_actuation(
    view: ChangeSetView,
    receipt: CommitActuationReceipt,
) -> None:
    expected_owner_ref = (
        "commit-owner:git.commit:"
        f"generation-{receipt.commit_owner_generation}"
    )
    if (
        receipt.schema_version != "commit-actuation.v1"
        or receipt.proposal_sha256 != view.proposal_sha256
        or receipt.work_item_id != view.work_item_id
        or receipt.work_item_version != view.work_item_version
        or receipt.parent_sha != view.base_commit
        or receipt.exact_paths != view.exact_paths
        or receipt.status != "committed"
        or receipt.commit_owner_ref != expected_owner_ref
    ):
        raise ValueError("actuation receipt does not match ChangeSet")


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{field} must be non-empty canonical text")
    return value


def _positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _sha(value: object, field: str) -> str:
    text = _text(value, field)
    if _SHA256.fullmatch(text) is None:
        raise ValueError(f"{field} must be lowercase SHA-256")
    return text


def _optional_sha(value: object, field: str) -> str | None:
    return None if value is None else _sha(value, field)


def _git_object(value: object, field: str) -> str:
    text = _text(value, field)
    if _GIT_OBJECT_ID.fullmatch(text) is None:
        raise ValueError(f"{field} must be a lowercase Git object id")
    return text


def _commit_worker(value: object) -> str:
    actor = _text(value, "commit worker")
    if not actor.startswith("commit-worker:"):
        raise ValueError("commit worker identity is invalid")
    return actor


def _text_tuple(value: object, field: str) -> tuple[str, ...]:
    if (
        not isinstance(value, (list, tuple))
        or isinstance(value, (str, bytes))
    ):
        raise ValueError(f"{field} must be an array")
    return tuple(_text(item, field) for item in value)


def _object_tuple(
    value: object,
    field: str,
) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{field} must be an array")
    if any(not isinstance(item, Mapping) for item in value):
        raise ValueError(f"{field} entries must be objects")
    return tuple(value)


def _absolute_path(value: object, field: str) -> str:
    raw = _text(value, field)
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise ValueError(f"{field} must be an absolute path")
    return raw


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
