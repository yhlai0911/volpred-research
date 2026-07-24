"""Service-role PostgREST adapter for durable Git commit ownership."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from .owned_change import CommitOwner, CommitOwnershipLost
from .supabase_rpc import (
    ServiceRoleRpcClient,
    SupabaseRpcError,
    runtime_environment,
)


def _required_text(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    return value.strip()


def _owner_from_payload(payload: Mapping[str, Any]) -> CommitOwner:
    schema_version = _required_text(
        payload.get("schema_version"),
        field="commit owner schema_version",
    )
    capability = _required_text(
        payload.get("capability"),
        field="commit owner capability",
    )
    owner = _required_text(
        payload.get("owner"),
        field="commit owner",
    )
    generation = payload.get("generation")
    changed_at = _required_text(
        payload.get("changed_at"),
        field="commit owner changed_at",
    )
    if schema_version != "commit-owner.v1":
        raise ValueError("unsupported commit owner schema")
    if capability != "git.commit":
        raise ValueError("unsupported commit owner capability")
    if owner not in {"legacy", "operations_core"}:
        raise ValueError("unsupported commit owner")
    if (
        isinstance(generation, bool)
        or not isinstance(generation, int)
        or generation <= 0
    ):
        raise ValueError("commit owner generation must be positive")
    try:
        observed_at = datetime.fromisoformat(changed_at)
    except ValueError as exc:
        raise ValueError(
            "commit owner changed_at must be ISO-8601"
        ) from exc
    if observed_at.tzinfo is None:
        raise ValueError("commit owner changed_at must include UTC offset")
    return CommitOwner(
        schema_version=schema_version,
        capability=capability,
        owner=owner,
        generation=generation,
        changed_at=changed_at,
        changed_by=_required_text(
            payload.get("changed_by"),
            field="commit owner changed_by",
        ),
        change_reason=_required_text(
            payload.get("change_reason"),
            field="commit owner change_reason",
        ),
    )


class SupabaseCommitOwnerStore:
    """Read and CAS-transfer Git ownership through service-role-only RPCs."""

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
    def from_environment(cls) -> SupabaseCommitOwnerStore:
        values = runtime_environment()
        return cls(
            supabase_url=values.get("SUPABASE_URL", ""),
            service_role_key=values.get("SUPABASE_SERVICE_ROLE_KEY", ""),
            timeout_seconds=float(
                values.get("VOLPRED_OPERATIONS_RPC_TIMEOUT_SEC", "45")
            ),
        )

    def read_owner(self) -> CommitOwner:
        return _owner_from_payload(
            self._rpc("volpred_read_commit_owner", {})
        )

    def transfer_owner(
        self,
        *,
        expected_owner: str,
        expected_generation: int,
        target_owner: str,
        actor_ref: str,
        reason: str,
        rollback_of_generation: int | None = None,
    ) -> CommitOwner:
        return _owner_from_payload(
            self._rpc(
                "volpred_transfer_commit_owner",
                {
                    "p_expected_owner": expected_owner,
                    "p_expected_generation": expected_generation,
                    "p_target_owner": target_owner,
                    "p_actor_ref": actor_ref,
                    "p_reason": reason,
                    "p_rollback_of_generation": rollback_of_generation,
                },
            )
        )

    def _rpc(
        self,
        function: str,
        payload: Mapping[str, object],
    ) -> Mapping[str, Any]:
        try:
            decoded = self._client.call(function, payload)
        except SupabaseRpcError as exc:
            message = str(exc)
            if message.startswith(
                (
                    "commit ownership",
                    "operations core does not own git.commit",
                )
            ):
                raise CommitOwnershipLost(message) from None
            raise RuntimeError(f"commit ownership RPC failed: {message}")
        if not isinstance(decoded, Mapping):
            raise RuntimeError(
                "commit ownership RPC returned a non-object response"
            )
        return decoded


__all__ = ["SupabaseCommitOwnerStore"]
