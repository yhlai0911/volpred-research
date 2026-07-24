"""Primary Authority external interface.

The module owns cross-host primary leases and fencing tokens.  Raw fencing
tokens are returned only to the holder that acquired them; durable receipts
and grants contain token-redacted authority references.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Callable, Protocol
from uuid import uuid4


_SHA256 = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class AuthorityRequest:
    authority_key: str
    holder_ref: str
    lease_seconds: int


@dataclass(frozen=True)
class PrimaryLease:
    schema_version: str
    authority_key: str
    holder_ref: str
    epoch: int
    fencing_token: str
    lease_seconds: int
    acquired_at: str
    expires_at: str


@dataclass(frozen=True)
class WriteIntent:
    authority_key: str
    holder_ref: str
    epoch: int
    fencing_token: str
    request_sha256: str
    resource_ref: str


@dataclass(frozen=True)
class FencingGrant:
    schema_version: str
    request_sha256: str
    resource_ref: str
    primary_authority_ref: str
    granted_at: str


@dataclass(frozen=True)
class AuthorityReceipt:
    schema_version: str
    authority_key: str
    holder_ref: str
    epoch: int
    primary_authority_ref: str
    released_at: str


class _AuthorityStore(Protocol):
    def acquire(
        self,
        request: AuthorityRequest,
        *,
        fencing_token: str,
    ) -> PrimaryLease: ...

    def renew(self, lease: PrimaryLease) -> PrimaryLease: ...

    def authorize(self, intent: WriteIntent) -> FencingGrant: ...

    def release(self, lease: PrimaryLease) -> AuthorityReceipt: ...


class PrimaryAuthority:
    """Own the primary-lease lifecycle behind four typed operations."""

    def __init__(
        self,
        store: _AuthorityStore,
        *,
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        self._store = store
        self._token_factory = token_factory or (
            lambda: f"primary_{uuid4().hex}"
        )

    def acquire(self, request: AuthorityRequest) -> PrimaryLease:
        normalized = _normalize_request(request)
        fencing_token = _required_text(
            self._token_factory(),
            field="Primary Authority fencing token",
        )
        return self._store.acquire(
            normalized,
            fencing_token=fencing_token,
        )

    def renew(self, lease: PrimaryLease) -> PrimaryLease:
        return self._store.renew(_normalize_lease(lease))

    def authorize(self, intent: WriteIntent) -> FencingGrant:
        return self._store.authorize(_normalize_intent(intent))

    def release(self, lease: PrimaryLease) -> AuthorityReceipt:
        return self._store.release(_normalize_lease(lease))


def _required_text(value: str, *, field: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be text")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} is required")
    return normalized


def _positive_integer(value: int, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} must be positive")
    return value


def _normalize_request(request: AuthorityRequest) -> AuthorityRequest:
    if not isinstance(request, AuthorityRequest):
        raise TypeError("AuthorityRequest is required")
    return AuthorityRequest(
        authority_key=_required_text(
            request.authority_key,
            field="authority_key",
        ),
        holder_ref=_required_text(request.holder_ref, field="holder_ref"),
        lease_seconds=_positive_integer(
            request.lease_seconds,
            field="authority lease_seconds",
        ),
    )


def _normalize_lease(lease: PrimaryLease) -> PrimaryLease:
    if not isinstance(lease, PrimaryLease):
        raise TypeError("PrimaryLease is required")
    return PrimaryLease(
        schema_version=_required_text(
            lease.schema_version,
            field="PrimaryLease schema_version",
        ),
        authority_key=_required_text(
            lease.authority_key,
            field="authority_key",
        ),
        holder_ref=_required_text(lease.holder_ref, field="holder_ref"),
        epoch=_positive_integer(lease.epoch, field="authority epoch"),
        fencing_token=_required_text(
            lease.fencing_token,
            field="Primary Authority fencing token",
        ),
        lease_seconds=_positive_integer(
            lease.lease_seconds,
            field="authority lease_seconds",
        ),
        acquired_at=_required_text(
            lease.acquired_at,
            field="authority acquired_at",
        ),
        expires_at=_required_text(
            lease.expires_at,
            field="authority expires_at",
        ),
    )


def _normalize_intent(intent: WriteIntent) -> WriteIntent:
    if not isinstance(intent, WriteIntent):
        raise TypeError("WriteIntent is required")
    request_sha256 = _required_text(
        intent.request_sha256,
        field="write intent request_sha256",
    )
    if _SHA256.fullmatch(request_sha256) is None:
        raise ValueError(
            "write intent request_sha256 must be lowercase SHA-256"
        )
    return WriteIntent(
        authority_key=_required_text(
            intent.authority_key,
            field="authority_key",
        ),
        holder_ref=_required_text(intent.holder_ref, field="holder_ref"),
        epoch=_positive_integer(intent.epoch, field="authority epoch"),
        fencing_token=_required_text(
            intent.fencing_token,
            field="Primary Authority fencing token",
        ),
        request_sha256=request_sha256,
        resource_ref=_required_text(
            intent.resource_ref,
            field="write intent resource_ref",
        ),
    )


from .keepalive import (  # noqa: E402
    HostAuthorityKeepalive,
    HostAuthorityKeepaliveStatus,
    KeepaliveState,
    build_supabase_host_authority_keepalive,
)
from .session import (  # noqa: E402
    AuthorityInactive,
    HostAuthoritySession,
    HostAuthorityStatus,
)


__all__ = [
    "AuthorityInactive",
    "AuthorityReceipt",
    "AuthorityRequest",
    "FencingGrant",
    "HostAuthorityKeepalive",
    "HostAuthorityKeepaliveStatus",
    "HostAuthoritySession",
    "HostAuthorityStatus",
    "KeepaliveState",
    "PrimaryAuthority",
    "PrimaryLease",
    "WriteIntent",
    "build_supabase_host_authority_keepalive",
]
