from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import pytest

from volpred.ops.delivery import owned_email as owned_email_module
from volpred.ops.delivery import (
    AcknowledgedEffect,
    AcknowledgementExpectation,
    EffectView,
    FailedEffect,
)
from volpred.ops.authority import PrimaryLease
from volpred.ops.delivery.owned_email import (
    NotificationOwner,
    NotificationOwnershipLost,
    OwnedEmailAttempt,
    OwnedEmailCommand,
    OwnedEmailNotification,
    OwnedEmailRecovery,
    OwnedEmailReceipt,
    OwnedEmailRequest,
    SupabaseOwnedEmailStore,
)


def _owner(*, owner: str = "operations_core") -> NotificationOwner:
    return NotificationOwner(
        schema_version="notification-owner.v1",
        effect_family="email.ops_alert",
        owner=owner,
        generation=2,
        changed_at="2026-07-24T07:00:00+00:00",
        changed_by="test",
        change_reason="test ownership",
    )


def _command() -> OwnedEmailCommand:
    return OwnedEmailCommand(
        idempotency_key="ops-alert:test:2026-07-24",
        level="warn",
        title="[VolPred Alert][WARN] Test",
        recipient="owner@example.com",
        text_body="Alert level: warn\nTitle: Test\n\nBody",
        html_body="<p>Body</p>",
        actor_ref="ops-alert:test",
    )


class _Store:
    def __init__(self, owner: NotificationOwner) -> None:
        self.owner = owner
        self.calls: list[tuple[str, object]] = []
        self.request_view = OwnedEmailRequest(
            owner_generation=owner.generation,
            work_id="work-owned-email-1",
            effect_id="effect-owned-email-1",
            request_sha256="a" * 64,
        )
        payload = b'{"schema_version":"email-notification.v1"}'
        effect = EffectView(
            schema_version="effect-request.v1",
            id=self.request_view.effect_id,
            idempotency_key="owned-email-effect:test",
            work_item_id=self.request_view.work_id,
            work_item_version=1,
            effect_kind="email.notification.send",
            target_ref="email:owner@example.com",
            payload_ref="effect-payload:owned-email-1",
            payload_sha256=hashlib.sha256(payload).hexdigest(),
            risk="safe",
            acknowledgement=AcknowledgementExpectation(
                kind="email.sent-mail.readback",
                target_ref="email:owner@example.com",
            ),
            requester_ref="ops-alert:test",
            request_sha256="b" * 64,
            status="requested",
            created_at="2026-07-24T07:00:01+00:00",
        )
        self.attempt = OwnedEmailAttempt(
            owner_generation=owner.generation,
            work_id=self.request_view.work_id,
            work_version=3,
            work_lease_token="",
            effect=effect,
            payload=payload,
            outbox_sequence=1,
            attempt_count=1,
            outbox_claim_token="",
            worker_id="effect-worker:ops-alert-email",
            primary_authority_key="notification:email.ops_alert",
            primary_authority_holder_ref="effect-worker:ops-alert-email",
            primary_authority_epoch=1,
            primary_fencing_token="",
            authority_request_sha256="c" * 64,
            outbox_claim_ref="outbox:1:attempt:1",
            primary_authority_ref=(
                "primary-authority:notification:email.ops_alert:"
                "effect-worker:ops-alert-email:epoch:1"
            ),
            lease_expires_at="2026-07-24T07:05:00+00:00",
        )

    def read_owner(self) -> NotificationOwner:
        self.calls.append(("read_owner", None))
        return self.owner

    def request(
        self,
        command: OwnedEmailCommand,
        *,
        owner_generation: int,
    ) -> OwnedEmailRequest:
        self.calls.append(("request", (command, owner_generation)))
        return self.request_view

    def begin(
        self,
        request_view: OwnedEmailRequest,
        *,
        worker_id: str,
        lease_seconds: int,
        work_lease_token: str,
        outbox_claim_token: str,
        primary_fencing_token: str,
    ) -> OwnedEmailAttempt:
        self.calls.append(
            (
                "begin",
                (
                    request_view,
                    worker_id,
                    lease_seconds,
                    work_lease_token,
                    outbox_claim_token,
                    primary_fencing_token,
                ),
            )
        )
        return OwnedEmailAttempt(
            **{
                **self.attempt.__dict__,
                "work_lease_token": work_lease_token,
                "outbox_claim_token": outbox_claim_token,
                "primary_fencing_token": primary_fencing_token,
            }
        )

    def settle(
        self,
        attempt: OwnedEmailAttempt,
        outcome: AcknowledgedEffect | FailedEffect,
    ) -> OwnedEmailReceipt:
        self.calls.append(("settle", (attempt, outcome)))
        delivered = isinstance(outcome, AcknowledgedEffect)
        disposition = (
            "delivered"
            if delivered
            else (
                "retry_scheduled"
                if outcome.retryable
                else "dead_lettered"
            )
        )
        return OwnedEmailReceipt(
            schema_version="owned-email-receipt.v1",
            owner_generation=attempt.owner_generation,
            work_id=attempt.work_id,
            work_status="succeeded" if delivered else "failed",
            effect_id=attempt.effect.id,
            effect_status="delivered" if delivered else disposition,
            attempt_count=attempt.attempt_count,
            disposition=disposition,
            evidence_ref=outcome.evidence_ref,
            evidence_sha256=outcome.evidence_sha256,
            primary_authority_ref=attempt.primary_authority_ref,
            recorded_at="2026-07-24T07:00:02+00:00",
        )


class _Provider:
    def __init__(self) -> None:
        self.calls: list[tuple[EffectView, bytes]] = []

    def deliver(
        self,
        effect: EffectView,
        payload: bytes,
    ) -> AcknowledgedEffect:
        self.calls.append((effect, payload))
        return AcknowledgedEffect(
            acknowledgement=effect.acknowledgement,
            evidence_ref="imap-sent:message-id:test",
            evidence_sha256="d" * 64,
        )


class _RecoveryStore(_Store):
    def __init__(self, owner: NotificationOwner) -> None:
        super().__init__(owner)
        self.recoveries: list[OwnedEmailAttempt] = [self.attempt]

    def recover_expired(
        self,
        *,
        owner_generation: int,
        worker_id: str,
        lease_seconds: int,
        work_lease_token: str,
        outbox_claim_token: str,
        primary_fencing_token: str,
    ) -> OwnedEmailAttempt | None:
        self.calls.append(
            (
                "recover_expired",
                (
                    owner_generation,
                    worker_id,
                    lease_seconds,
                    work_lease_token,
                    outbox_claim_token,
                    primary_fencing_token,
                ),
            )
        )
        if not self.recoveries:
            return None
        attempt = self.recoveries.pop(0)
        return OwnedEmailAttempt(
            **{
                **attempt.__dict__,
                "attempt_count": attempt.attempt_count + 1,
                "work_lease_token": work_lease_token,
                "outbox_claim_token": outbox_claim_token,
                "primary_fencing_token": primary_fencing_token,
            }
        )


class _LeaseGate:
    def __init__(self) -> None:
        self.calls = 0
        self.lease = PrimaryLease(
            schema_version="primary-lease.v1",
            authority_key="notification:email.ops_alert",
            holder_ref="effect-worker:ops-alert-email",
            epoch=1,
            fencing_token="primary-token",
            lease_seconds=300,
            acquired_at="2026-07-24T07:00:00+00:00",
            expires_at="2026-07-24T07:05:00+00:00",
        )

    def current_lease(self) -> PrimaryLease:
        self.calls += 1
        return self.lease


def test_deliver_owns_request_begin_provider_and_settlement() -> None:
    store = _Store(_owner())
    provider = _Provider()
    primary_authority = _LeaseGate()
    tokens = iter(("work-token", "outbox-token"))
    delivery = OwnedEmailNotification(
        store=store,
        provider=provider,
        primary_authority=primary_authority,
        token_factory=lambda: next(tokens),
    )

    receipt = delivery.deliver(_command())

    assert receipt.delivered is True
    assert [name for name, _ in store.calls] == [
        "read_owner",
        "request",
        "begin",
        "settle",
    ]
    assert provider.calls == [(store.attempt.effect, store.attempt.payload)]
    begin_args = store.calls[2][1]
    assert isinstance(begin_args, tuple)
    assert begin_args[-3:] == (
        "work-token",
        "outbox-token",
        "primary-token",
    )
    assert primary_authority.calls == 3


def test_recover_owns_claim_provider_and_settlement() -> None:
    store = _RecoveryStore(_owner())
    provider = _Provider()
    tokens = iter(
        (
            "work-recovery-token",
            "outbox-recovery-token",
            "work-unused-token",
            "outbox-unused-token",
        )
    )
    recovery = OwnedEmailRecovery(
        store=store,
        provider=provider,
        primary_authority=_LeaseGate(),
        token_factory=lambda: next(tokens),
        now_factory=lambda: datetime(
            2026, 7, 24, 7, 30, tzinfo=timezone.utc
        ),
        max_age_seconds=3600,
    )

    summary = recovery.recover(limit=2)

    assert summary.recovered_count == 1
    assert summary.delivered_count == 1
    assert summary.stale_count == 0
    assert provider.calls == [(store.attempt.effect, store.attempt.payload)]
    assert [name for name, _ in store.calls] == [
        "read_owner",
        "recover_expired",
        "settle",
        "recover_expired",
    ]


def test_recover_dead_letters_stale_alert_without_provider_send() -> None:
    store = _RecoveryStore(_owner())
    provider = _Provider()
    settled_outcomes: list[object] = []
    original_settle = store.settle

    def capture_settle(
        attempt: OwnedEmailAttempt,
        outcome: object,
    ) -> OwnedEmailReceipt:
        settled_outcomes.append(outcome)
        return original_settle(attempt, outcome)  # type: ignore[arg-type]

    store.settle = capture_settle  # type: ignore[method-assign]
    recovery = OwnedEmailRecovery(
        store=store,
        provider=provider,
        primary_authority=_LeaseGate(),
        token_factory=iter(
            ("work-recovery-token", "outbox-recovery-token")
        ).__next__,
        now_factory=lambda: datetime(
            2026, 7, 24, 9, 0, tzinfo=timezone.utc
        ),
        max_age_seconds=3600,
    )

    summary = recovery.recover(limit=1)

    assert summary.recovered_count == 1
    assert summary.delivered_count == 0
    assert summary.stale_count == 1
    assert provider.calls == []
    assert len(settled_outcomes) == 1
    assert isinstance(settled_outcomes[0], FailedEffect)
    assert settled_outcomes[0].reason_code == "owned_email_recovery_stale"
    assert settled_outcomes[0].retryable is False


def test_deliver_fails_closed_before_request_when_owner_is_legacy() -> None:
    store = _Store(_owner(owner="legacy"))
    provider = _Provider()

    with pytest.raises(
        NotificationOwnershipLost,
        match="does not own email.ops_alert",
    ):
        OwnedEmailNotification(
            store=store,
            provider=provider,
            primary_authority=_LeaseGate(),
        ).deliver(_command())

    assert store.calls == [("read_owner", None)]
    assert provider.calls == []


def test_deliver_fails_closed_before_request_when_keepalive_is_closed() -> None:
    store = _Store(_owner())
    provider = _Provider()

    class ClosedGate:
        def current_lease(self) -> PrimaryLease:
            raise RuntimeError("host keepalive is demoted")

    with pytest.raises(RuntimeError, match="keepalive is demoted"):
        OwnedEmailNotification(
            store=store,
            provider=provider,
            primary_authority=ClosedGate(),
        ).deliver(_command())

    assert store.calls == []
    assert provider.calls == []


def test_deliver_fails_closed_before_provider_when_keepalive_is_replaced() -> None:
    store = _Store(_owner())
    provider = _Provider()
    primary_authority = _LeaseGate()
    original = primary_authority.lease

    def begin_with_replaced_lease(*args, **kwargs):
        attempt = _Store.begin(store, *args, **kwargs)
        primary_authority.lease = PrimaryLease(
            **{
                **original.__dict__,
                "epoch": original.epoch + 1,
                "fencing_token": "replacement-token",
            }
        )
        return attempt

    store.begin = begin_with_replaced_lease  # type: ignore[method-assign]

    with pytest.raises(
        NotificationOwnershipLost,
        match="lease was replaced",
    ):
        OwnedEmailNotification(
            store=store,
            provider=provider,
            primary_authority=primary_authority,
        ).deliver(_command())

    assert provider.calls == []


def test_environment_adapter_never_falls_back_to_publishable_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "volpred.ops.delivery.owned_email._runtime_environment",
        lambda: {
            "SUPABASE_URL": "https://project.supabase.co",
            "SUPABASE_KEY": "publishable-or-anon-key",
        },
    )

    with pytest.raises(
        ValueError,
        match="service-role key",
    ):
        SupabaseOwnedEmailStore.from_environment()


def test_supabase_store_blocks_remote_mutation_when_remote_writes_are_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    network_calls = 0

    def fail_if_called(*args: object, **kwargs: object) -> object:
        nonlocal network_calls
        network_calls += 1
        raise AssertionError("network attempted")

    monkeypatch.setenv("VOLPRED_NO_REMOTE_WRITE", "1")
    monkeypatch.setattr(owned_email_module.request, "urlopen", fail_if_called)
    store = SupabaseOwnedEmailStore(
        supabase_url="https://project.supabase.co",
        service_role_key="fake-service-role-key",
    )

    with pytest.raises(RuntimeError, match="remote writes are disabled"):
        store.request(_command(), owner_generation=2)

    assert network_calls == 0


def test_supabase_store_blocks_remote_mutation_under_pytest_when_guard_is_removed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    network_calls = 0

    def fail_if_called(*args: object, **kwargs: object) -> object:
        nonlocal network_calls
        network_calls += 1
        raise AssertionError("network attempted")

    monkeypatch.delenv("VOLPRED_NO_REMOTE_WRITE", raising=False)
    monkeypatch.setattr(owned_email_module.request, "urlopen", fail_if_called)
    store = SupabaseOwnedEmailStore(
        supabase_url="https://project.supabase.co",
        service_role_key="fake-service-role-key",
    )

    with pytest.raises(RuntimeError, match="remote writes are disabled"):
        store.request(_command(), owner_generation=2)

    assert network_calls == 0


def test_supabase_store_allows_owner_read_when_remote_writes_are_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Response:
        def __enter__(self) -> Response:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return (
                b'{"schema_version":"notification-owner.v1",'
                b'"effect_family":"email.ops_alert",'
                b'"owner":"legacy","generation":1,'
                b'"changed_at":"2026-07-24T07:00:00+00:00",'
                b'"changed_by":"migration","change_reason":"initial"}'
            )

    requested_urls: list[str] = []

    def respond(call: object, **kwargs: object) -> Response:
        requested_urls.append(call.full_url)  # type: ignore[attr-defined]
        return Response()

    monkeypatch.setenv("VOLPRED_NO_REMOTE_WRITE", "1")
    monkeypatch.setattr(owned_email_module.request, "urlopen", respond)
    store = SupabaseOwnedEmailStore(
        supabase_url="https://project.supabase.co",
        service_role_key="fake-service-role-key",
    )

    owner = store.read_owner()

    assert owner.owner == "legacy"
    assert requested_urls == [
        "https://project.supabase.co/rest/v1/rpc/"
        "volpred_read_notification_owner"
    ]
