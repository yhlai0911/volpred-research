"""Service-role PostgREST adapter for fenced Git commit authority."""

from __future__ import annotations

from collections.abc import Mapping

from volpred.ops.authority import PrimaryLease

from ._git_actuator import (
    CommitActuatorBlocked,
    CommitAuthorityGrant,
    CommitAuthorityRequest,
    _authority_request_sha256,
    _validate_authority_grant,
)
from .supabase_rpc import (
    ServiceRoleRpcClient,
    SupabaseRpcError,
    runtime_environment,
)


class SupabaseCommitAuthority:
    """Authorize one commit through the canonical database transaction."""

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
    ) -> SupabaseCommitAuthority:
        values = runtime_environment()
        return cls(
            supabase_url=values.get("SUPABASE_URL", ""),
            service_role_key=values.get("SUPABASE_SERVICE_ROLE_KEY", ""),
            primary_lease=primary_lease,
            timeout_seconds=float(
                values.get("VOLPRED_OPERATIONS_RPC_TIMEOUT_SEC", "45")
            ),
        )

    def authorize(
        self,
        request: CommitAuthorityRequest,
    ) -> CommitAuthorityGrant:
        if not isinstance(request, CommitAuthorityRequest):
            raise TypeError("CommitAuthorityRequest is required")
        if request.request_sha256 != _authority_request_sha256(request):
            raise CommitActuatorBlocked(
                "commit authority request hash does not match its write intent"
            )
        try:
            payload = self._client.call(
                "volpred_authorize_commit_write",
                {
                    "p_authority_key": self._primary_lease.authority_key,
                    "p_authority_holder_ref": (
                        self._primary_lease.holder_ref
                    ),
                    "p_authority_epoch": self._primary_lease.epoch,
                    "p_primary_fencing_token": (
                        request.primary_fencing_token
                    ),
                    "p_request_sha256": request.request_sha256,
                    "p_proposal_sha256": request.proposal_sha256,
                    "p_work_item_id": request.work_item_id,
                    "p_work_item_version": request.work_item_version,
                    "p_commit_owner_generation": (
                        request.commit_owner_generation
                    ),
                    "p_work_lease_token": request.work_lease_token,
                    "p_repository": request.repository,
                    "p_expected_head": request.expected_head,
                    "p_commit_worker_ref": request.actor,
                },
            )
        except SupabaseRpcError as error:
            message = str(error)
            if message.startswith(
                (
                    "commit authority",
                    "commit ownership",
                    "Primary Authority",
                )
            ):
                raise CommitActuatorBlocked(message) from None
            raise RuntimeError(
                f"commit authority RPC failed: {message}"
            ) from None

        if not isinstance(payload, Mapping):
            raise CommitActuatorBlocked(
                "commit authority RPC returned a non-object grant"
            )
        generation = payload.get("commit_owner_generation")
        if (
            isinstance(generation, bool)
            or not isinstance(generation, int)
            or generation <= 0
        ):
            raise CommitActuatorBlocked(
                "commit authority RPC returned an invalid owner generation"
            )
        return _validate_authority_grant(
            CommitAuthorityGrant(
                request_sha256=payload.get("request_sha256"),
                commit_owner_generation=generation,
                commit_owner_ref=payload.get("commit_owner_ref"),
                work_lease_ref=payload.get("work_lease_ref"),
                primary_authority_ref=payload.get(
                    "primary_authority_ref"
                ),
            ),
            request=request,
        )


__all__ = ["SupabaseCommitAuthority"]
