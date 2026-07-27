"""Service-role PostgREST adapter for fenced Git commit authority."""

from __future__ import annotations

from collections.abc import Mapping

from volpred.ops.authority import (
    FORMAL_PRIMARY_AUTHORITY_KEY,
    PrimaryLease,
)

from ._git_actuator import (
    CommitActuatorBlocked,
    CommitAuthorityAbandonment,
    CommitAuthorityGrant,
    CommitAuthorityRequest,
    _authority_request_sha256,
    _validate_abandonment,
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
        if primary_lease.authority_key != FORMAL_PRIMARY_AUTHORITY_KEY:
            raise ValueError(
                "commit authority requires the formal primary authority "
                "lease"
            )
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

    def recover(
        self,
        request: CommitAuthorityRequest,
    ) -> CommitAuthorityGrant | None:
        self._validate_request(request)
        payload = self._call(
            "volpred_read_commit_authority_grant",
            {"p_request_sha256": request.request_sha256},
        )
        if payload is None:
            return None
        return self._grant(payload, request=request)

    def abandon(
        self,
        request: CommitAuthorityRequest,
        grant: CommitAuthorityGrant,
        *,
        reason: str,
    ) -> CommitAuthorityAbandonment:
        self._validate_request(request)
        _validate_authority_grant(grant, request=request)
        payload = self._call(
            "volpred_abandon_commit_write",
            {
                "p_request_sha256": request.request_sha256,
                "p_commit_owner_generation": (
                    grant.commit_owner_generation
                ),
                "p_commit_owner_ref": grant.commit_owner_ref,
                "p_reason": reason,
            },
        )
        if not isinstance(payload, Mapping):
            raise CommitActuatorBlocked(
                "commit authority RPC returned a non-object abandonment"
            )
        return _validate_abandonment(
            CommitAuthorityAbandonment(
                schema_version=payload.get("schema_version"),
                request_sha256=payload.get("request_sha256"),
                reason=payload.get("reason"),
                abandoned_at=payload.get("abandoned_at"),
            ),
            request=request,
            reason=reason,
        )

    def _call(
        self,
        function: str,
        payload: Mapping[str, object],
    ) -> object:
        try:
            return self._client.call(function, payload)
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

    @staticmethod
    def _validate_request(request: CommitAuthorityRequest) -> None:
        if not isinstance(request, CommitAuthorityRequest):
            raise TypeError("CommitAuthorityRequest is required")
        if request.request_sha256 != _authority_request_sha256(request):
            raise CommitActuatorBlocked(
                "commit authority request hash does not match its write intent"
            )

    @staticmethod
    def _grant(
        payload: object,
        *,
        request: CommitAuthorityRequest,
    ) -> CommitAuthorityGrant:
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
