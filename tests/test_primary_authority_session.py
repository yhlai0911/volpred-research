from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from volpred.ops.authority import (
    AuthorityReceipt,
    AuthorityRequest,
    PrimaryAuthority,
    PrimaryLease,
)
from volpred.ops.authority.session import (
    AuthorityInactive,
    HostAuthoritySession,
)


class _SharedAuthorityStore:
    def __init__(self, *, clock) -> None:
        self.clock = clock
        self.epoch = 0
        self.current: PrimaryLease | None = None
        self.renew_error: Exception | None = None
        self.release_error: Exception | None = None

    def acquire(
        self,
        request: AuthorityRequest,
        *,
        fencing_token: str,
    ) -> PrimaryLease:
        now = self.clock()
        if self.current is not None:
            expires_at = datetime.fromisoformat(self.current.expires_at)
            if expires_at > now:
                if (
                    self.current.holder_ref == request.holder_ref
                    and self.current.fencing_token == fencing_token
                ):
                    return self.current
                raise ValueError(
                    f"Primary Authority is already held: "
                    f"{request.authority_key}"
                )
        self.epoch += 1
        self.current = PrimaryLease(
            schema_version="primary-lease.v1",
            authority_key=request.authority_key,
            holder_ref=request.holder_ref,
            epoch=self.epoch,
            fencing_token=fencing_token,
            lease_seconds=request.lease_seconds,
            acquired_at=now.isoformat(),
            expires_at=(
                now + timedelta(seconds=request.lease_seconds)
            ).isoformat(),
        )
        return self.current

    def renew(self, lease: PrimaryLease) -> PrimaryLease:
        if self.renew_error is not None:
            raise self.renew_error
        if self.current != lease:
            raise ValueError(
                f"Primary Authority lease lost: {lease.authority_key}"
            )
        self.current = replace(
            lease,
            expires_at=(
                self.clock() + timedelta(seconds=lease.lease_seconds)
            ).isoformat(),
        )
        return self.current

    def authorize(self, intent):
        raise AssertionError("not used by host-session tests")

    def release(self, lease: PrimaryLease) -> AuthorityReceipt:
        if self.release_error is not None:
            raise self.release_error
        if self.current != lease:
            raise ValueError(
                f"Primary Authority lease lost: {lease.authority_key}"
            )
        self.current = None
        return AuthorityReceipt(
            schema_version="primary-authority-receipt.v1",
            authority_key=lease.authority_key,
            holder_ref=lease.holder_ref,
            epoch=lease.epoch,
            primary_authority_ref=(
                f"primary-authority:{lease.authority_key}:"
                f"epoch-{lease.epoch}"
            ),
            released_at=self.clock().isoformat(),
        )


def _session(
    store: _SharedAuthorityStore,
    *,
    holder_ref: str,
    token: str,
) -> HostAuthoritySession:
    return HostAuthoritySession(
        PrimaryAuthority(store, token_factory=lambda: token),
        AuthorityRequest(
            authority_key="operations-core-effects",
            holder_ref=holder_ref,
            lease_seconds=300,
        ),
        clock=store.clock,
    )


def test_only_one_host_session_can_be_active_and_failover_increments_epoch(
) -> None:
    now = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)
    store = _SharedAuthorityStore(clock=lambda: now)
    primary = _session(
        store,
        holder_ref="host:primary-a",
        token="primary-a-secret",
    )
    standby = _session(
        store,
        holder_ref="host:standby-b",
        token="standby-b-secret",
    )

    first = primary.activate()
    assert primary.activate() is first
    assert primary.status().state == "active"
    assert "primary-a-secret" not in repr(primary.status())

    with pytest.raises(ValueError, match="already held"):
        standby.activate()
    assert standby.status().state == "standby"

    receipt = primary.demote()
    assert receipt is not None
    assert primary.status().state == "demoted"
    with pytest.raises(AuthorityInactive, match="not active"):
        primary.current_lease()

    replacement = standby.activate()
    assert replacement.epoch == first.epoch + 1
    assert standby.status().state == "active"


def test_renewal_failure_demotes_locally_before_error_escapes() -> None:
    now = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)
    store = _SharedAuthorityStore(clock=lambda: now)
    session = _session(
        store,
        holder_ref="host:primary",
        token="primary-secret",
    )
    session.activate()
    store.renew_error = RuntimeError("control plane unavailable")

    with pytest.raises(
        AuthorityInactive,
        match="renewal failed; local host demoted",
    ) as caught:
        session.renew()

    assert isinstance(caught.value.__cause__, RuntimeError)
    assert session.status().state == "demoted"
    with pytest.raises(AuthorityInactive, match="not active"):
        session.current_lease()


def test_release_failure_still_disables_local_authority() -> None:
    now = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)
    store = _SharedAuthorityStore(clock=lambda: now)
    session = _session(
        store,
        holder_ref="host:primary",
        token="primary-secret",
    )
    session.activate()
    store.release_error = RuntimeError("control plane unavailable")

    with pytest.raises(
        AuthorityInactive,
        match="release unconfirmed; local host demoted",
    ):
        session.demote()

    assert session.status().state == "demoted"
    with pytest.raises(AuthorityInactive, match="not active"):
        session.current_lease()


def test_local_expiry_fails_closed_without_returning_a_stale_token() -> None:
    now = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)
    current = [now]
    store = _SharedAuthorityStore(clock=lambda: current[0])
    session = _session(
        store,
        holder_ref="host:primary",
        token="primary-secret",
    )
    lease = session.activate()
    current[0] = datetime.fromisoformat(lease.expires_at)

    with pytest.raises(AuthorityInactive, match="expired locally"):
        session.current_lease()

    assert session.status().state == "demoted"
