"""Fail-closed host workflow for a Primary Authority lease."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import RLock
from typing import Literal, Protocol

from . import (
    AuthorityReceipt,
    AuthorityRequest,
    PrimaryLease,
)


class AuthorityInactive(RuntimeError):
    """The local host must not perform a primary-authorized operation."""


class _PrimaryAuthorityClient(Protocol):
    def acquire(self, request: AuthorityRequest) -> PrimaryLease: ...

    def renew(self, lease: PrimaryLease) -> PrimaryLease: ...

    def release(self, lease: PrimaryLease) -> AuthorityReceipt: ...


@dataclass(frozen=True)
class HostAuthorityStatus:
    """Token-redacted local host state."""

    state: Literal["standby", "active", "demoted"]
    authority_key: str
    holder_ref: str
    epoch: int | None
    expires_at: str | None
    last_release_ref: str | None


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _timestamp(value: str, *, field: str) -> datetime:
    try:
        observed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be an ISO timestamp") from None
    if observed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return observed.astimezone(UTC)


class HostAuthoritySession:
    """Keep one host active only while its DB-clock lease remains usable.

    Formal commit and effect adapters still revalidate the raw fencing token
    in PostgreSQL. This workflow owns the host-side lifecycle: one successful
    activation, explicit renewal, and immediate local demotion when renewal or
    release cannot be confirmed.
    """

    def __init__(
        self,
        authority: _PrimaryAuthorityClient,
        request: AuthorityRequest,
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        if not isinstance(request, AuthorityRequest):
            raise TypeError("AuthorityRequest is required")
        authority_key = request.authority_key.strip()
        holder_ref = request.holder_ref.strip()
        if not authority_key or not holder_ref:
            raise ValueError(
                "authority_key and holder_ref are required"
            )
        if (
            isinstance(request.lease_seconds, bool)
            or not isinstance(request.lease_seconds, int)
            or request.lease_seconds <= 0
        ):
            raise ValueError("authority lease_seconds must be positive")
        self._authority = authority
        self._request = AuthorityRequest(
            authority_key=authority_key,
            holder_ref=holder_ref,
            lease_seconds=request.lease_seconds,
        )
        self._clock = clock
        self._lock = RLock()
        self._state: Literal["standby", "active", "demoted"] = "standby"
        self._lease: PrimaryLease | None = None
        # Never exposed to callers after local demotion.  It is retained only
        # long enough for demote() to attempt a fenced remote release; the
        # production store journals the token-redacted identity if that call
        # cannot be confirmed.
        self._pending_demotion_lease: PrimaryLease | None = None
        self._last_release_ref: str | None = None

    def status(self) -> HostAuthorityStatus:
        with self._lock:
            if self._state == "active" and self._lease is not None:
                try:
                    expired = self._lease_expired(self._lease)
                except Exception as error:
                    self._pending_demotion_lease = self._lease
                    self._lease = None
                    self._state = "demoted"
                    raise AuthorityInactive(
                        "Primary Authority lease validation failed; "
                        "local host demoted"
                    ) from error
                if expired:
                    self._pending_demotion_lease = self._lease
                    self._lease = None
                    self._state = "demoted"
            lease = self._lease
            return HostAuthorityStatus(
                state=self._state,
                authority_key=self._request.authority_key,
                holder_ref=self._request.holder_ref,
                epoch=lease.epoch if lease is not None else None,
                expires_at=(
                    lease.expires_at if lease is not None else None
                ),
                last_release_ref=self._last_release_ref,
            )

    def activate(self) -> PrimaryLease:
        with self._lock:
            if self._state == "active":
                return self._active_lease_locked()
            self._now()
            lease = self._authority.acquire(self._request)
            self._validate_lease(lease)
            if self._lease_expired(lease):
                raise AuthorityInactive(
                    "Primary Authority activation returned an expired lease"
                )
            self._lease = lease
            self._pending_demotion_lease = None
            self._state = "active"
            self._last_release_ref = None
            return lease

    def renew(self) -> PrimaryLease:
        with self._lock:
            lease = self._active_lease_locked()
            try:
                renewed = self._authority.renew(lease)
                self._validate_lease(renewed, prior=lease)
                if self._lease_expired(renewed):
                    raise ValueError(
                        "Primary Authority renewal returned an expired lease"
                    )
            except Exception as error:
                self._pending_demotion_lease = lease
                self._lease = None
                self._state = "demoted"
                raise AuthorityInactive(
                    "Primary Authority renewal failed; local host demoted"
                ) from error
            self._lease = renewed
            return renewed

    def current_lease(self) -> PrimaryLease:
        with self._lock:
            return self._active_lease_locked()

    def demote(self) -> AuthorityReceipt | None:
        with self._lock:
            lease = self._lease or self._pending_demotion_lease
            if lease is None:
                return None
            self._lease = None
            self._pending_demotion_lease = None
            self._state = "demoted"
            try:
                receipt = self._authority.release(lease)
                self._validate_receipt(receipt, lease=lease)
            except Exception as error:
                raise AuthorityInactive(
                    "Primary Authority release unconfirmed; "
                    "local host demoted"
                ) from error
            self._last_release_ref = receipt.primary_authority_ref
            return receipt

    def _active_lease_locked(self) -> PrimaryLease:
        if self._state != "active" or self._lease is None:
            raise AuthorityInactive(
                "Primary Authority host session is not active"
            )
        try:
            expired = self._lease_expired(self._lease)
        except Exception as error:
            self._pending_demotion_lease = self._lease
            self._lease = None
            self._state = "demoted"
            raise AuthorityInactive(
                "Primary Authority lease validation failed; "
                "local host demoted"
            ) from error
        if expired:
            self._pending_demotion_lease = self._lease
            self._lease = None
            self._state = "demoted"
            raise AuthorityInactive(
                "Primary Authority lease expired locally; host demoted"
            )
        return self._lease

    def _validate_lease(
        self,
        lease: PrimaryLease,
        *,
        prior: PrimaryLease | None = None,
    ) -> None:
        if not isinstance(lease, PrimaryLease):
            raise TypeError("Primary Authority returned no typed lease")
        if lease.schema_version != "primary-lease.v1":
            raise ValueError(
                "Primary Authority returned an unsupported lease schema"
            )
        if (
            lease.authority_key != self._request.authority_key
            or lease.holder_ref != self._request.holder_ref
            or lease.lease_seconds != self._request.lease_seconds
        ):
            raise ValueError(
                "Primary Authority lease identity drifted"
            )
        if (
            isinstance(lease.epoch, bool)
            or not isinstance(lease.epoch, int)
            or lease.epoch <= 0
        ):
            raise ValueError("Primary Authority returned an invalid epoch")
        if (
            not isinstance(lease.fencing_token, str)
            or not lease.fencing_token.strip()
        ):
            raise ValueError(
                "Primary Authority returned an invalid fencing token"
            )
        acquired_at = _timestamp(
            lease.acquired_at,
            field="PrimaryLease acquired_at",
        )
        expires_at = _timestamp(
            lease.expires_at,
            field="PrimaryLease expires_at",
        )
        if expires_at <= acquired_at:
            raise ValueError(
                "Primary Authority returned an invalid lease window"
            )
        if prior is not None and (
            lease.epoch != prior.epoch
            or lease.fencing_token != prior.fencing_token
            or lease.acquired_at != prior.acquired_at
        ):
            raise ValueError(
                "Primary Authority renewal changed lease identity"
            )

    @staticmethod
    def _validate_receipt(
        receipt: AuthorityReceipt,
        *,
        lease: PrimaryLease,
    ) -> None:
        expected_ref = (
            f"primary-authority:{lease.authority_key}:"
            f"epoch-{lease.epoch}"
        )
        if not isinstance(receipt, AuthorityReceipt):
            raise TypeError(
                "Primary Authority returned no typed release receipt"
            )
        if (
            receipt.schema_version
            != "primary-authority-receipt.v1"
            or receipt.authority_key != lease.authority_key
            or receipt.holder_ref != lease.holder_ref
            or isinstance(receipt.epoch, bool)
            or not isinstance(receipt.epoch, int)
            or receipt.epoch != lease.epoch
            or receipt.primary_authority_ref != expected_ref
        ):
            raise ValueError(
                "Primary Authority release receipt drifted"
            )
        _timestamp(
            receipt.released_at,
            field="AuthorityReceipt released_at",
        )

    def _lease_expired(self, lease: PrimaryLease) -> bool:
        return _timestamp(
            lease.expires_at,
            field="PrimaryLease expires_at",
        ) <= self._now()

    def _now(self) -> datetime:
        observed = self._clock()
        if not isinstance(observed, datetime) or observed.tzinfo is None:
            raise ValueError(
                "Primary Authority session clock must be timezone-aware"
            )
        return observed.astimezone(UTC)


__all__ = [
    "AuthorityInactive",
    "HostAuthoritySession",
    "HostAuthorityStatus",
]
