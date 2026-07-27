"""Service-role PostgREST adapter for Primary Authority."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from volpred.ops.delivery.supabase_rpc import (
    ServiceRoleRpcClient,
    SupabaseRpcError,
    runtime_environment,
)

from . import (
    AuthorityLifecycleEvent,
    AuthorityReceipt,
    AuthorityRequest,
    FencingGrant,
    PrimaryLease,
    WriteIntent,
)

_EVENT_TYPES = frozenset(
    {"acquired", "renewed", "expired", "demoted", "rejected"}
)
_EVENT_OPERATIONS = frozenset(
    {"acquire", "renew", "authorize", "release"}
)


def _text(payload: Mapping[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"Primary Authority RPC returned an invalid {field}"
        )
    return value.strip()


def _positive_integer(payload: Mapping[str, Any], field: str) -> int:
    value = payload.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(
            f"Primary Authority RPC returned an invalid {field}"
        )
    return value


def _timestamp(payload: Mapping[str, Any], field: str) -> str:
    value = _text(payload, field)
    try:
        observed = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError(
            f"Primary Authority RPC returned an invalid {field}"
        ) from None
    if observed.tzinfo is None:
        raise ValueError(
            f"Primary Authority RPC returned an invalid {field}"
        )
    return observed.astimezone(UTC).isoformat()


class SupabaseAuthorityStore:
    """Persist DB-clock primary leases through narrow public RPCs."""

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
    def from_environment(cls) -> SupabaseAuthorityStore:
        values = runtime_environment()
        return cls(
            supabase_url=values.get("SUPABASE_URL", ""),
            service_role_key=values.get(
                "SUPABASE_SERVICE_ROLE_KEY", ""
            ),
            timeout_seconds=float(
                values.get("VOLPRED_OPERATIONS_RPC_TIMEOUT_SEC", "45")
            ),
        )

    def acquire(
        self,
        request: AuthorityRequest,
        *,
        fencing_token: str,
    ) -> PrimaryLease:
        payload = self._rpc(
            "volpred_acquire_primary_authority",
            {
                "p_authority_key": request.authority_key,
                "p_holder_ref": request.holder_ref,
                "p_lease_seconds": request.lease_seconds,
                "p_fencing_token": fencing_token,
            },
        )
        lease = self._lease(
            payload,
            fencing_token=fencing_token,
            lease_seconds=request.lease_seconds,
        )
        if (
            lease.authority_key != request.authority_key
            or lease.holder_ref != request.holder_ref
        ):
            raise ValueError(
                "Primary Authority acquire read-back drifted"
            )
        return lease

    def renew(self, lease: PrimaryLease) -> PrimaryLease:
        payload = self._rpc(
            "volpred_renew_primary_authority",
            {
                "p_authority_key": lease.authority_key,
                "p_holder_ref": lease.holder_ref,
                "p_epoch": lease.epoch,
                "p_lease_seconds": lease.lease_seconds,
                "p_fencing_token": lease.fencing_token,
            },
        )
        renewed = self._lease(
            payload,
            fencing_token=lease.fencing_token,
            lease_seconds=lease.lease_seconds,
        )
        if (
            renewed.authority_key != lease.authority_key
            or renewed.holder_ref != lease.holder_ref
            or renewed.epoch != lease.epoch
            or renewed.acquired_at != lease.acquired_at
        ):
            raise ValueError(
                "Primary Authority renew read-back drifted"
            )
        return renewed

    def authorize(self, intent: WriteIntent) -> FencingGrant:
        payload = self._rpc(
            "volpred_authorize_primary_write",
            {
                "p_authority_key": intent.authority_key,
                "p_holder_ref": intent.holder_ref,
                "p_epoch": intent.epoch,
                "p_fencing_token": intent.fencing_token,
                "p_request_sha256": intent.request_sha256,
                "p_resource_ref": intent.resource_ref,
            },
        )
        if (
            _text(payload, "request_sha256")
            != intent.request_sha256
            or _text(payload, "authority_key")
            != intent.authority_key
            or _positive_integer(payload, "epoch") != intent.epoch
            or _text(payload, "holder_ref") != intent.holder_ref
            or _text(payload, "resource_ref") != intent.resource_ref
        ):
            raise ValueError(
                "Primary Authority grant read-back drifted"
            )
        return FencingGrant(
            schema_version="primary-fencing-grant.v1",
            request_sha256=intent.request_sha256,
            resource_ref=intent.resource_ref,
            primary_authority_ref=_text(
                payload, "primary_authority_ref"
            ),
            granted_at=_timestamp(payload, "granted_at"),
        )

    def release(self, lease: PrimaryLease) -> AuthorityReceipt:
        payload = self._rpc(
            "volpred_release_primary_authority",
            {
                "p_authority_key": lease.authority_key,
                "p_holder_ref": lease.holder_ref,
                "p_epoch": lease.epoch,
                "p_fencing_token": lease.fencing_token,
            },
        )
        if (
            _text(payload, "authority_key") != lease.authority_key
            or _text(payload, "holder_ref") != lease.holder_ref
            or _positive_integer(payload, "epoch") != lease.epoch
        ):
            raise ValueError(
                "Primary Authority release read-back drifted"
            )
        return AuthorityReceipt(
            schema_version="primary-authority-receipt.v1",
            authority_key=lease.authority_key,
            holder_ref=lease.holder_ref,
            epoch=lease.epoch,
            primary_authority_ref=_text(
                payload, "primary_authority_ref"
            ),
            released_at=_timestamp(payload, "released_at"),
        )

    def read_events(
        self,
        authority_key: str,
        *,
        limit: int = 100,
    ) -> tuple[AuthorityLifecycleEvent, ...]:
        """Read the latest token-redacted lifecycle receipts in event order."""

        normalized_key = authority_key.strip()
        if not normalized_key:
            raise ValueError("Primary Authority key is required")
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or limit <= 0
            or limit > 500
        ):
            raise ValueError(
                "Primary Authority event limit must be between 1 and 500"
            )
        try:
            payload = self._client.call(
                "volpred_read_primary_authority_events",
                {
                    "p_authority_key": normalized_key,
                    "p_limit": limit,
                },
            )
        except SupabaseRpcError as error:
            raise RuntimeError(
                f"Primary Authority event read failed: {error}"
            ) from None
        if not isinstance(payload, list):
            raise ValueError(
                "Primary Authority event RPC returned a non-list response"
            )
        events: list[AuthorityLifecycleEvent] = []
        for item in payload:
            if not isinstance(item, Mapping):
                raise ValueError(
                    "Primary Authority event RPC returned an invalid event"
                )
            events.append(self._event(item, authority_key=normalized_key))
        return tuple(events)

    def _rpc(
        self,
        function: str,
        arguments: Mapping[str, object],
    ) -> Mapping[str, Any]:
        try:
            payload = self._client.call(function, arguments)
        except SupabaseRpcError as error:
            message = str(error)
            if message.startswith("Primary Authority"):
                raise ValueError(message) from None
            raise RuntimeError(
                f"Primary Authority RPC failed: {message}"
            ) from None
        if not isinstance(payload, Mapping):
            raise ValueError(
                "Primary Authority RPC returned a non-object response"
            )
        if payload.get("status") == "rejected":
            if (
                payload.get("schema_version")
                != "primary-authority-rejection.v1"
            ):
                raise ValueError(
                    "Primary Authority RPC returned an invalid "
                    "rejection schema"
                )
            reason = _text(payload, "reason")
            _text(payload, "operation")
            _text(payload, "authority_key")
            _text(payload, "event_ref")
            _text(payload, "reason_code")
            _timestamp(payload, "occurred_at")
            if not reason.startswith("Primary Authority"):
                raise ValueError(
                    "Primary Authority RPC returned an invalid "
                    "rejection reason"
                )
            raise ValueError(reason)
        return payload

    @staticmethod
    def _lease(
        payload: Mapping[str, Any],
        *,
        fencing_token: str,
        lease_seconds: int,
    ) -> PrimaryLease:
        acquired_at = _timestamp(payload, "acquired_at")
        expires_at = _timestamp(payload, "lease_expires_at")
        if datetime.fromisoformat(expires_at) <= datetime.fromisoformat(
            acquired_at
        ):
            raise ValueError(
                "Primary Authority RPC returned an invalid lease window"
            )
        return PrimaryLease(
            schema_version="primary-lease.v1",
            authority_key=_text(payload, "authority_key"),
            holder_ref=_text(payload, "holder_ref"),
            epoch=_positive_integer(payload, "epoch"),
            fencing_token=fencing_token,
            lease_seconds=lease_seconds,
            acquired_at=acquired_at,
            expires_at=expires_at,
        )

    @staticmethod
    def _event(
        payload: Mapping[str, Any],
        *,
        authority_key: str,
    ) -> AuthorityLifecycleEvent:
        if payload.get("schema_version") != "primary-authority-event.v1":
            raise ValueError(
                "Primary Authority event RPC returned an invalid schema"
            )
        if _text(payload, "authority_key") != authority_key:
            raise ValueError(
                "Primary Authority event RPC returned another authority key"
            )
        event_type = _text(payload, "event_type")
        operation = _text(payload, "operation")
        if event_type not in _EVENT_TYPES or operation not in _EVENT_OPERATIONS:
            raise ValueError(
                "Primary Authority event RPC returned an invalid lifecycle"
            )
        epoch = payload.get("epoch")
        if epoch is not None and (
            isinstance(epoch, bool)
            or not isinstance(epoch, int)
            or epoch <= 0
        ):
            raise ValueError(
                "Primary Authority event RPC returned an invalid epoch"
            )
        holder_ref = payload.get("holder_ref")
        if holder_ref is not None and (
            not isinstance(holder_ref, str) or not holder_ref.strip()
        ):
            raise ValueError(
                "Primary Authority event RPC returned an invalid holder"
            )
        reason_code = payload.get("reason_code")
        reason = payload.get("reason")
        if event_type == "rejected":
            if (
                not isinstance(reason_code, str)
                or not reason_code.strip()
                or not isinstance(reason, str)
                or not reason.startswith("Primary Authority")
            ):
                raise ValueError(
                    "Primary Authority event RPC returned an invalid "
                    "rejection"
                )
        elif reason_code is not None or reason is not None:
            raise ValueError(
                "Primary Authority event RPC leaked a non-rejection reason"
            )
        lease_expires_at = payload.get("lease_expires_at")
        if lease_expires_at is not None:
            lease_expires_at = _timestamp(payload, "lease_expires_at")
        return AuthorityLifecycleEvent(
            schema_version="primary-authority-event.v1",
            event_ref=_text(payload, "event_ref"),
            authority_key=authority_key,
            event_type=event_type,
            operation=operation,
            epoch=epoch,
            holder_ref=holder_ref.strip() if holder_ref is not None else None,
            reason_code=(
                reason_code.strip()
                if isinstance(reason_code, str)
                else None
            ),
            reason=reason if isinstance(reason, str) else None,
            lease_expires_at=lease_expires_at,
            occurred_at=_timestamp(payload, "occurred_at"),
        )


__all__ = ["SupabaseAuthorityStore"]
