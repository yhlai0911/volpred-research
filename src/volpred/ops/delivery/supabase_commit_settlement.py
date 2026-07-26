"""Service-role PostgREST adapter for fenced Git commit settlement."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

from volpred.ops.authority import PrimaryLease

from . import DeliveryReceipt
from ._change_settlement import (
    CommitSettlement,
    CommitSettlementBlocked,
    commit_settlement_sha256,
)
from .supabase_rpc import (
    ServiceRoleRpcClient,
    SupabaseRpcError,
    runtime_environment,
)


def _utc_isoformat(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise CommitSettlementBlocked(
            f"commit settlement RPC returned an invalid {field}"
        )
    try:
        observed = datetime.fromisoformat(value)
    except ValueError:
        raise CommitSettlementBlocked(
            f"commit settlement RPC returned an invalid {field}"
        ) from None
    if observed.tzinfo is None:
        raise CommitSettlementBlocked(
            f"commit settlement RPC returned an invalid {field}"
        )
    return observed.astimezone(UTC).isoformat()


class SupabaseCommitSettlement:
    """Settle one verified commit through the canonical transaction."""

    def __init__(
        self,
        *,
        supabase_url: str,
        service_role_key: str,
        primary_lease: PrimaryLease,
        timeout_seconds: float = 45.0,
    ) -> None:
        if not isinstance(primary_lease, PrimaryLease):
            raise TypeError("primary_lease must be a PrimaryLease")
        if primary_lease.schema_version != "primary-lease.v1":
            raise ValueError("unsupported PrimaryLease schema")
        if primary_lease.epoch <= 0:
            raise ValueError("PrimaryLease epoch must be positive")
        self._client = ServiceRoleRpcClient(
            supabase_url=supabase_url,
            service_role_key=service_role_key,
            timeout_seconds=timeout_seconds,
        )
        self._primary_lease = primary_lease

    @classmethod
    def from_environment(
        cls,
        *,
        primary_lease: PrimaryLease,
    ) -> SupabaseCommitSettlement:
        values = runtime_environment()
        return cls(
            supabase_url=values.get("SUPABASE_URL", ""),
            service_role_key=values.get("SUPABASE_SERVICE_ROLE_KEY", ""),
            primary_lease=primary_lease,
            timeout_seconds=float(
                values.get("VOLPRED_OPERATIONS_RPC_TIMEOUT_SEC", "45")
            ),
        )

    def settle(self, command: CommitSettlement) -> DeliveryReceipt:
        if not isinstance(command, CommitSettlement):
            raise TypeError("CommitSettlement is required")
        actuation = command.actuation
        settlement_sha256 = commit_settlement_sha256(command)
        try:
            payload = self._client.call(
                "volpred_settle_commit_write",
                {
                    "p_authority_key": self._primary_lease.authority_key,
                    "p_authority_holder_ref": (self._primary_lease.holder_ref),
                    "p_authority_epoch": self._primary_lease.epoch,
                    "p_primary_fencing_token": (command.primary_fencing_token),
                    "p_authority_request_sha256": (actuation.authority_request_sha256),
                    "p_commit_owner_generation": (actuation.commit_owner_generation),
                    "p_commit_owner_ref": actuation.commit_owner_ref,
                    "p_settlement_sha256": settlement_sha256,
                    "p_change_set_id": command.change_set_id,
                    "p_work_lease_token": command.work_lease_token,
                    "p_work_lease_ref": actuation.work_lease_ref,
                    "p_primary_authority_ref": (actuation.primary_authority_ref),
                    "p_repository": command.repository,
                    "p_commit_sha": actuation.commit_sha,
                    "p_parent_sha": actuation.parent_sha,
                    "p_exact_paths": list(actuation.exact_paths),
                    "p_commit_worker_ref": actuation.actor,
                    "p_actuation_observed_at": actuation.observed_at,
                    "p_actuation_status": actuation.status,
                },
            )
        except SupabaseRpcError as error:
            message = str(error)
            if message.startswith(
                (
                    "commit authority",
                    "commit settlement",
                    "commit ownership",
                    "Primary Authority",
                    "WorkLease",
                    "unknown WorkItem",
                    "stale WorkItem",
                )
            ):
                raise CommitSettlementBlocked(message) from None
            raise RuntimeError(f"commit settlement RPC failed: {message}") from None

        if not isinstance(payload, Mapping):
            raise CommitSettlementBlocked(
                "commit settlement RPC returned a non-object receipt"
            )
        exact_paths = payload.get("exact_paths")
        if not isinstance(exact_paths, list) or not all(
            isinstance(path, str) for path in exact_paths
        ):
            raise CommitSettlementBlocked(
                "commit settlement RPC returned invalid exact paths"
            )
        generation = payload.get("commit_owner_generation")
        work_version = payload.get("work_item_version")
        if (
            isinstance(generation, bool)
            or not isinstance(generation, int)
            or generation <= 0
            or isinstance(work_version, bool)
            or not isinstance(work_version, int)
            or work_version <= 0
        ):
            raise CommitSettlementBlocked(
                "commit settlement RPC returned invalid versions"
            )
        observed_at = _utc_isoformat(
            payload.get("actuation_observed_at"),
            field="actuation timestamp",
        )
        settled_at = _utc_isoformat(
            payload.get("settled_at"),
            field="settlement timestamp",
        )
        receipt = DeliveryReceipt(
            schema_version=payload.get("schema_version"),
            change_set_id=payload.get("change_set_id"),
            proposal_sha256=payload.get("proposal_sha256"),
            work_item_id=payload.get("work_item_id"),
            work_item_version=work_version,
            commit_owner_generation=generation,
            commit_owner_ref=payload.get("commit_owner_ref"),
            authority_request_sha256=payload.get("authority_request_sha256"),
            work_lease_ref=payload.get("work_lease_ref"),
            primary_authority_ref=payload.get("primary_authority_ref"),
            repository=payload.get("repository"),
            commit_sha=payload.get("commit_sha"),
            parent_sha=payload.get("parent_sha"),
            exact_paths=tuple(exact_paths),
            actor=payload.get("commit_worker_ref"),
            status=payload.get("status"),
            actuation_observed_at=observed_at,
            settled_at=settled_at,
            settlement_ref=payload.get("settlement_ref"),
            settlement_sha256=payload.get("settlement_sha256"),
        )
        expected_observed_at = _utc_isoformat(
            actuation.observed_at,
            field="command actuation timestamp",
        )
        if (
            receipt.schema_version != "change-delivery-receipt.v1"
            or receipt.change_set_id != command.change_set_id
            or receipt.proposal_sha256 != actuation.proposal_sha256
            or receipt.work_item_id != actuation.work_item_id
            or receipt.work_item_version != actuation.work_item_version
            or receipt.commit_owner_generation != actuation.commit_owner_generation
            or receipt.commit_owner_ref != actuation.commit_owner_ref
            or receipt.authority_request_sha256 != actuation.authority_request_sha256
            or receipt.work_lease_ref != actuation.work_lease_ref
            or receipt.primary_authority_ref != actuation.primary_authority_ref
            or receipt.repository != command.repository
            or receipt.commit_sha != actuation.commit_sha
            or receipt.parent_sha != actuation.parent_sha
            or receipt.exact_paths != actuation.exact_paths
            or receipt.actor != actuation.actor
            or receipt.status != "landed"
            or receipt.actuation_observed_at != expected_observed_at
            or receipt.settlement_ref
            != (f"change-delivery:{command.change_set_id}:{actuation.commit_sha}")
            or receipt.settlement_sha256 != settlement_sha256
        ):
            raise CommitSettlementBlocked("durable commit settlement read-back drifted")
        return receipt


__all__ = ["SupabaseCommitSettlement"]
