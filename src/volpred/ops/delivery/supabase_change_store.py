"""Service-role PostgREST adapter for durable ChangeSet lifecycle state."""

from __future__ import annotations

from collections.abc import Mapping

from . import ChangeSetConflict, ChangeSetView, DeliveryReceipt
from ._change_store import ChangeSetRecord
from ._git_actuator import CommitActuationReceipt
from .postgres_change_store import (
    _actuation_json,
    _record_from_row,
)
from .supabase_rpc import (
    ServiceRoleRpcClient,
    SupabaseRpcError,
    runtime_environment,
)


class SupabaseChangeSetStore:
    """Persist ChangeSets through narrow service-role-only public RPCs."""

    def __init__(
        self,
        *,
        supabase_url: str,
        service_role_key: str,
        timeout_seconds: float = 45.0,
    ) -> None:
        self._client = ServiceRoleRpcClient(
            supabase_url=supabase_url,
            service_role_key=service_role_key,
            timeout_seconds=timeout_seconds,
        )

    @classmethod
    def from_environment(cls) -> SupabaseChangeSetStore:
        values = runtime_environment()
        return cls(
            supabase_url=values.get("SUPABASE_URL", ""),
            service_role_key=values.get("SUPABASE_SERVICE_ROLE_KEY", ""),
            timeout_seconds=float(
                values.get("VOLPRED_OPERATIONS_RPC_TIMEOUT_SEC", "45")
            ),
        )

    @staticmethod
    def _translate(error: SupabaseRpcError) -> None:
        message = str(error)
        if message.startswith("ChangeSet") and "conflicts with" in message:
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
        raise RuntimeError(f"ChangeSet RPC failed: {message}") from None

    def _call(
        self,
        function: str,
        payload: Mapping[str, object],
    ) -> object:
        try:
            return self._client.call(function, payload)
        except SupabaseRpcError as error:
            self._translate(error)
            raise AssertionError("unreachable")

    @staticmethod
    def _record(
        payload: object,
        *,
        missing: str,
    ) -> ChangeSetRecord:
        if payload is None:
            raise ValueError(missing)
        if not isinstance(payload, Mapping):
            raise RuntimeError(
                "ChangeSet RPC returned a non-object response"
            )
        return _record_from_row(payload)

    def create(self, view: ChangeSetView) -> ChangeSetRecord:
        payload = self._call(
            "volpred_create_change_set",
            {
                "p_id": view.id,
                "p_idempotency_key": view.idempotency_key,
                "p_work_item_id": view.work_item_id,
                "p_work_item_version": view.work_item_version,
                "p_base_commit": view.base_commit,
                "p_workspace_ref": view.workspace_ref,
                "p_exact_paths": list(view.exact_paths),
                "p_content_hashes": [
                    {"path": item.path, "sha256": item.sha256}
                    for item in view.content_hashes
                ],
                "p_required_checks": [
                    {
                        "name": item.name,
                        "status": item.status,
                        "evidence_ref": item.evidence_ref,
                    }
                    for item in view.required_checks
                ],
                "p_author_ref": view.author_ref,
                "p_author_evidence_ref": view.author_evidence_ref,
                "p_proposal_sha256": view.proposal_sha256,
                "p_schema_version": view.schema_version,
                "p_created_at": view.created_at,
            },
        )
        return self._record(
            payload,
            missing="create_change_set returned no ChangeSet",
        )

    def load(self, change_set_id: str) -> ChangeSetRecord:
        normalized = change_set_id.strip()
        if not normalized:
            raise ValueError("ChangeSet id is required")
        return self._record(
            self._call(
                "volpred_read_change_set",
                {"p_change_set_id": normalized},
            ),
            missing=f"unknown ChangeSet: {normalized}",
        )

    def load_by_idempotency_key(
        self,
        idempotency_key: str,
    ) -> ChangeSetRecord | None:
        normalized = idempotency_key.strip()
        if not normalized:
            raise ValueError("ChangeSet idempotency key is required")
        payload = self._call(
            "volpred_read_change_set_by_idempotency_key",
            {"p_idempotency_key": normalized},
        )
        if payload is None:
            return None
        return self._record(
            payload,
            missing="unreachable ChangeSet idempotency lookup",
        )

    def checkpoint_actuation(
        self,
        *,
        change_set_id: str,
        proposal_sha256: str,
        land_command_sha256: str,
        actuation: CommitActuationReceipt,
    ) -> ChangeSetRecord:
        return self._record(
            self._call(
                "volpred_checkpoint_change_set_actuation",
                {
                    "p_change_set_id": change_set_id,
                    "p_proposal_sha256": proposal_sha256,
                    "p_land_command_sha256": land_command_sha256,
                    "p_actuation_receipt": _actuation_json(actuation),
                },
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
        record = self._record(
            self._call(
                "volpred_mark_change_set_landed",
                {
                    "p_change_set_id": change_set_id,
                    "p_proposal_sha256": proposal_sha256,
                    "p_land_command_sha256": land_command_sha256,
                    "p_delivery_authority_request_sha256": (
                        delivery.authority_request_sha256
                    ),
                },
            ),
            missing="mark_change_set_landed returned no ChangeSet",
        )
        if record.delivery != delivery:
            raise ChangeSetConflict(
                "ChangeSet delivery conflicts with its durable receipt"
            )
        return record


__all__ = ["SupabaseChangeSetStore"]
