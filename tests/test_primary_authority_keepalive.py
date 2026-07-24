from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from threading import Event
import time

import pytest

from volpred.ops.authority import (
    AuthorityReceipt,
    AuthorityRequest,
    PrimaryAuthority,
    PrimaryLease,
)
from volpred.ops.authority import (
    AuthorityInactive,
    HostAuthorityKeepalive,
    HostAuthoritySession,
    build_supabase_host_authority_keepalive,
)
from volpred.ops.authority.supabase import SupabaseAuthorityStore


class _AuthorityStore:
    def __init__(self) -> None:
        self.now = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)
        self.current: PrimaryLease | None = None
        self.epoch = 0
        self.renewed = Event()
        self.allow_renew = Event()
        self.block_renew = False
        self.renew_error: BaseException | None = None
        self.release_error: BaseException | None = None

    def clock(self) -> datetime:
        return self.now

    def acquire(
        self,
        request: AuthorityRequest,
        *,
        fencing_token: str,
    ) -> PrimaryLease:
        self.epoch += 1
        self.current = PrimaryLease(
            schema_version="primary-lease.v1",
            authority_key=request.authority_key,
            holder_ref=request.holder_ref,
            epoch=self.epoch,
            fencing_token=fencing_token,
            lease_seconds=request.lease_seconds,
            acquired_at=self.now.isoformat(),
            expires_at=(
                self.now + timedelta(seconds=request.lease_seconds)
            ).isoformat(),
        )
        return self.current

    def renew(self, lease: PrimaryLease) -> PrimaryLease:
        self.renewed.set()
        if self.block_renew:
            self.allow_renew.wait()
        if self.renew_error is not None:
            raise self.renew_error
        if lease != self.current:
            raise ValueError("lease lost")
        self.current = replace(
            lease,
            expires_at=(
                self.now + timedelta(seconds=lease.lease_seconds)
            ).isoformat(),
        )
        return self.current

    def authorize(self, intent):
        raise AssertionError("not used by keepalive tests")

    def release(self, lease: PrimaryLease) -> AuthorityReceipt:
        if self.release_error is not None:
            raise self.release_error
        if lease != self.current:
            raise ValueError("lease lost")
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
            released_at=self.now.isoformat(),
        )


def _keepalive(
    store: _AuthorityStore,
    *,
    interval: float = 0.01,
    join_timeout: float = 1.0,
) -> HostAuthorityKeepalive:
    session = HostAuthoritySession(
        PrimaryAuthority(
            store,
            token_factory=lambda: "raw-primary-secret",
        ),
        AuthorityRequest(
            authority_key="operations-core-effects",
            holder_ref="host:primary-a",
            lease_seconds=300,
        ),
        clock=store.clock,
    )
    return HostAuthorityKeepalive(
        session,
        renew_interval_seconds=interval,
        join_timeout_seconds=join_timeout,
    )


def _wait_for_state(
    keepalive: HostAuthorityKeepalive,
    expected: str,
) -> None:
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        if keepalive.status().state == expected:
            return
        time.sleep(0.005)
    raise AssertionError(
        f"keepalive did not reach {expected}: {keepalive.status()!r}"
    )


def test_keepalive_renews_and_clean_stop_releases_authority() -> None:
    store = _AuthorityStore()
    keepalive = _keepalive(store)

    lease = keepalive.start()
    assert keepalive.start() == lease
    assert store.renewed.wait(1.0)
    status = keepalive.status()
    assert status.state == "running"
    assert status.renewal_count >= 1
    assert status.last_renewed_expires_at is not None
    assert "raw-primary-secret" not in repr(status)
    assert keepalive.current_lease().epoch == lease.epoch

    keepalive.stop()

    assert store.current is None
    assert keepalive.status().state == "stopped"
    with pytest.raises(AuthorityInactive, match="not running"):
        keepalive.current_lease()
    keepalive.stop()


def test_renew_failure_demotes_and_closes_local_enable_gate() -> None:
    store = _AuthorityStore()
    store.renew_error = RuntimeError("control plane unavailable")
    keepalive = _keepalive(store)

    keepalive.start()
    assert store.renewed.wait(1.0)
    _wait_for_state(keepalive, "demoted")
    _wait_for_worker_exit(keepalive)

    status = keepalive.status()
    assert status.failure_type == "AuthorityInactive"
    assert status.worker_alive is False
    assert store.current is not None
    with pytest.raises(AuthorityInactive, match="not running"):
        keepalive.current_lease()
    with pytest.raises(
        AuthorityInactive,
        match="stopped after failure",
    ):
        keepalive.stop()


def test_base_exception_in_renew_worker_still_demotes_locally() -> None:
    store = _AuthorityStore()
    store.renew_error = KeyboardInterrupt()
    keepalive = _keepalive(store)

    keepalive.start()
    assert store.renewed.wait(1.0)
    _wait_for_state(keepalive, "demoted")
    _wait_for_worker_exit(keepalive)

    status = keepalive.status()
    assert status.failure_type == "KeyboardInterrupt"
    assert store.current is None
    with pytest.raises(AuthorityInactive, match="not running"):
        keepalive.current_lease()


def test_stop_release_failure_never_reopens_local_authority() -> None:
    store = _AuthorityStore()
    keepalive = _keepalive(store, interval=60.0)
    keepalive.start()
    store.release_error = RuntimeError("release response lost")

    with pytest.raises(
        AuthorityInactive,
        match="stopped after failure",
    ) as caught:
        keepalive.stop()

    assert isinstance(caught.value.__cause__, AuthorityInactive)
    assert keepalive.status().state == "demoted"
    with pytest.raises(AuthorityInactive, match="not running"):
        keepalive.current_lease()


def test_stop_timeout_closes_gate_before_blocked_renew_returns() -> None:
    store = _AuthorityStore()
    store.block_renew = True
    keepalive = _keepalive(
        store,
        interval=0.01,
        join_timeout=0.01,
    )
    keepalive.start()
    assert store.renewed.wait(1.0)

    with pytest.raises(AuthorityInactive, match="stop timed out"):
        keepalive.stop()

    with pytest.raises(AuthorityInactive, match="not running"):
        keepalive.current_lease()

    store.allow_renew.set()
    _wait_for_worker_exit(keepalive)
    assert keepalive.status().state == "demoted"
    assert store.current is None


def test_invalid_renew_margin_releases_the_just_acquired_lease() -> None:
    store = _AuthorityStore()
    keepalive = _keepalive(store, interval=300.0)

    with pytest.raises(
        AuthorityInactive,
        match="failed to start",
    ) as caught:
        keepalive.start()

    assert isinstance(caught.value.__cause__, ValueError)
    assert store.current is None
    assert keepalive.status().state == "demoted"


def test_environment_builder_composes_the_canonical_keepalive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _AuthorityStore()
    store.now = datetime.now(UTC)
    monkeypatch.setattr(
        SupabaseAuthorityStore,
        "from_environment",
        staticmethod(lambda: store),
    )

    keepalive = build_supabase_host_authority_keepalive(
        authority_key="operations-core-effects",
        holder_ref="host:primary-a",
        renew_interval_seconds=60.0,
    )
    lease = keepalive.start()

    assert lease.authority_key == "operations-core-effects"
    assert lease.holder_ref == "host:primary-a"
    keepalive.stop()
    assert store.current is None


@pytest.mark.parametrize(
    "interval",
    [0, -1, float("nan"), float("inf"), True],
)
def test_invalid_keepalive_duration_is_rejected(interval: float) -> None:
    store = _AuthorityStore()
    with pytest.raises(ValueError, match="positive finite duration"):
        _keepalive(store, interval=interval)


def _wait_for_worker_exit(
    keepalive: HostAuthorityKeepalive,
) -> None:
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        if not keepalive.status().worker_alive:
            return
        time.sleep(0.005)
    raise AssertionError(
        f"keepalive worker did not exit: {keepalive.status()!r}"
    )
