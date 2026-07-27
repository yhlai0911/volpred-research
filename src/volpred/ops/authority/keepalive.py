"""Canonical keepalive owner for a host Primary Authority session."""

from __future__ import annotations

import math
from dataclasses import dataclass
from threading import Event, RLock, Thread, current_thread
from typing import Literal

from volpred.ops.diagnostics import warn

from . import (
    FORMAL_PRIMARY_AUTHORITY_KEY,
    AuthorityRequest,
    PrimaryAuthority,
    PrimaryLease,
)
from .session import (
    AuthorityInactive,
    HostAuthoritySession,
    HostAuthorityStatus,
)

KeepaliveState = Literal[
    "standby",
    "running",
    "stopping",
    "demoted",
    "stopped",
]


@dataclass(frozen=True)
class HostAuthorityKeepaliveStatus:
    """Token-redacted state of the host keepalive owner."""

    state: KeepaliveState
    authority: HostAuthorityStatus
    renew_interval_seconds: float
    renewal_count: int
    worker_alive: bool
    last_renewed_expires_at: str | None
    failure_type: str | None


class HostAuthorityKeepalive:
    """Activate, renew, and demote one host authority session.

    Callers that can produce a formal commit or external effect must obtain
    their lease through :meth:`current_lease`, never from the wrapped session.
    The keepalive marks itself non-running before any blocking release call, so
    stop and failure paths immediately close the local enable gate. PostgreSQL
    remains the final fencing owner for every individual write.
    """

    def __init__(
        self,
        session: HostAuthoritySession,
        *,
        renew_interval_seconds: float,
        join_timeout_seconds: float = 60.0,
    ) -> None:
        if not isinstance(session, HostAuthoritySession):
            raise TypeError("HostAuthoritySession is required")
        self._renew_interval_seconds = _positive_duration(
            renew_interval_seconds,
            field="renew_interval_seconds",
        )
        self._join_timeout_seconds = _positive_duration(
            join_timeout_seconds,
            field="join_timeout_seconds",
        )
        self._session = session
        self._lock = RLock()
        self._stop_requested = Event()
        self._state: KeepaliveState = "standby"
        self._worker: Thread | None = None
        self._renewal_count = 0
        self._last_renewed_expires_at: str | None = None
        self._failure: BaseException | None = None

    def start(self) -> PrimaryLease:
        """Acquire authority and start its single renewal owner."""
        with self._lock:
            if self._state == "running":
                return self._current_lease_locked()
            if self._state != "standby":
                raise AuthorityInactive(
                    "Primary Authority keepalive cannot be restarted"
                )
            # Activation and publication of the renewal worker are one local
            # transition.  Releasing this lock around the remote acquire lets
            # concurrent starters create multiple workers, or lets stop()
            # return while this call can still publish a running gate.
            lease = self._session.activate()
            try:
                self._validate_renew_margin(lease)
                worker = Thread(
                    target=self._run,
                    name=(
                        "volpred-primary-authority-"
                        f"{lease.authority_key}"
                    ),
                    daemon=True,
                )
                self._worker = worker
                self._state = "running"
                worker.start()
            except BaseException as error:
                self._fail_closed(error)
                raise AuthorityInactive(
                    "Primary Authority keepalive failed to start; "
                    "local host demoted"
                ) from error
            return lease

    def current_lease(self) -> PrimaryLease:
        """Return a lease only while the canonical renew owner is live."""
        with self._lock:
            return self._current_lease_locked()

    def status(self) -> HostAuthorityKeepaliveStatus:
        """Return token-redacted local state and renewal evidence."""
        with self._lock:
            worker = self._worker
            worker_alive = worker is not None and worker.is_alive()
            if self._state == "running" and not worker_alive:
                self._record_failure_locked(
                    RuntimeError(
                        "Primary Authority keepalive worker exited"
                    )
                )
            try:
                authority = self._session.status()
            except BaseException as error:
                self._record_failure_locked(error)
                raise AuthorityInactive(
                    "Primary Authority keepalive status failed; "
                    "local host demoted"
                ) from error
            if (
                self._state == "running"
                and authority.state != "active"
            ):
                self._record_failure_locked(
                    AuthorityInactive(
                        "Primary Authority session became inactive"
                    )
                )
            return HostAuthorityKeepaliveStatus(
                state=self._state,
                authority=authority,
                renew_interval_seconds=self._renew_interval_seconds,
                renewal_count=self._renewal_count,
                worker_alive=(
                    self._worker is not None
                    and self._worker.is_alive()
                ),
                last_renewed_expires_at=(
                    self._last_renewed_expires_at
                ),
                failure_type=(
                    type(self._failure).__name__
                    if self._failure is not None
                    else None
                ),
            )

    def stop(self) -> None:
        """Close the local gate, stop renewal, and release authority."""
        with self._lock:
            if self._state == "stopped":
                return
            if self._state == "standby":
                self._state = "stopped"
                return
            if self._state == "running":
                self._state = "stopping"
            self._stop_requested.set()
            worker = self._worker

        if worker is not None and worker is not current_thread():
            worker.join(self._join_timeout_seconds)

        with self._lock:
            if worker is not None and worker.is_alive():
                self._record_failure_locked(
                    TimeoutError(
                        "Primary Authority keepalive did not stop"
                    )
                )
                raise AuthorityInactive(
                    "Primary Authority keepalive stop timed out; "
                    "local host demoted"
                ) from self._failure
            failure = self._failure
            state = self._state
        if state == "demoted" and failure is not None:
            raise AuthorityInactive(
                "Primary Authority keepalive stopped after failure; "
                "local host demoted"
            ) from failure

    def _run(self) -> None:
        try:
            while not self._stop_requested.wait(
                self._renew_interval_seconds
            ):
                renewed = self._session.renew()
                with self._lock:
                    if self._state != "running":
                        continue
                    self._renewal_count += 1
                    self._last_renewed_expires_at = renewed.expires_at
        except BaseException as error:
            warn(
                "primary_authority_keepalive",
                "renew worker failed; local host demoted",
                phase="renew",
                failure_type=type(error).__name__,
            )
            self._fail_closed(error)
            return

        try:
            self._session.demote()
        except BaseException as error:
            warn(
                "primary_authority_keepalive",
                "release failed after stop; local host remains demoted",
                phase="stop_release",
                failure_type=type(error).__name__,
            )
            self._fail_closed(error)
            return
        with self._lock:
            if self._state == "stopping":
                self._state = "stopped"

    def _current_lease_locked(self) -> PrimaryLease:
        if self._state != "running":
            raise AuthorityInactive(
                "Primary Authority keepalive is not running"
            )
        worker = self._worker
        if worker is None or not worker.is_alive():
            self._record_failure_locked(
                RuntimeError(
                    "Primary Authority keepalive worker is not alive"
                )
            )
            raise AuthorityInactive(
                "Primary Authority keepalive worker is not alive; "
                "local host demoted"
            ) from self._failure
        try:
            return self._session.current_lease()
        except BaseException as error:
            self._record_failure_locked(error)
            raise AuthorityInactive(
                "Primary Authority session is inactive; "
                "local host demoted"
            ) from error

    def _fail_closed(self, error: BaseException) -> None:
        with self._lock:
            self._record_failure_locked(error)
        try:
            self._session.demote()
        except BaseException as cleanup_error:
            # HostAuthoritySession clears its raw lease before remote release.
            # The original failure remains the canonical keepalive cause.
            warn(
                "primary_authority_keepalive",
                "best-effort remote release failed after demotion",
                phase="failure_cleanup",
                failure_type=type(cleanup_error).__name__,
            )
            pass

    def _record_failure_locked(self, error: BaseException) -> None:
        if self._failure is None:
            self._failure = error
        self._state = "demoted"
        self._stop_requested.set()

    def _validate_renew_margin(self, lease: PrimaryLease) -> None:
        if self._renew_interval_seconds >= lease.lease_seconds:
            raise ValueError(
                "renew_interval_seconds must be shorter than the "
                "Primary Authority lease"
            )


def build_supabase_host_authority_keepalive(
    *,
    holder_ref: str,
    lease_seconds: int = 300,
    renew_interval_seconds: float = 60.0,
    join_timeout_seconds: float = 60.0,
) -> HostAuthorityKeepalive:
    """Wire the service-role authority adapter to its host renew owner."""
    from .supabase import SupabaseAuthorityStore

    session = HostAuthoritySession(
        PrimaryAuthority(SupabaseAuthorityStore.from_environment()),
        AuthorityRequest(
            authority_key=FORMAL_PRIMARY_AUTHORITY_KEY,
            holder_ref=holder_ref,
            lease_seconds=lease_seconds,
        ),
    )
    return HostAuthorityKeepalive(
        session,
        renew_interval_seconds=renew_interval_seconds,
        join_timeout_seconds=join_timeout_seconds,
    )


def _positive_duration(value: float, *, field: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ValueError(f"{field} must be a positive finite duration")
    return float(value)


__all__ = [
    "HostAuthorityKeepalive",
    "HostAuthorityKeepaliveStatus",
    "KeepaliveState",
    "build_supabase_host_authority_keepalive",
]
