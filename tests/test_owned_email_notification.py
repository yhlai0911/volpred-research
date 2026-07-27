from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from volpred.ops.delivery import owned_email as owned_email_module
from volpred.ops.delivery import (
    AcknowledgedEffect,
    AcknowledgementExpectation,
    EffectView,
    FailedEffect,
)
from volpred.ops.authority import PrimaryLease
from volpred.ops.delivery._email_notification import (
    EmailNotificationEffectAdapter,
)
from volpred.ops.delivery.owned_email import (
    NotificationOwner,
    NotificationOwnershipLost,
    OwnedEmailAttempt,
    OwnedEmailCommand,
    OwnedEmailExistingRequest,
    OwnedEmailNotification,
    OwnedEmailRecovery,
    OwnedEmailReceipt,
    OwnedEmailRequest,
    SupabaseOwnedEmailStore,
    dispatch_email_by_current_owner,
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
        self.existing_request: OwnedEmailExistingRequest | None = None
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
            primary_authority_key="operations-core-primary",
            primary_authority_holder_ref="effect-worker:ops-alert-email",
            primary_authority_epoch=1,
            primary_fencing_token="",
            authority_request_sha256="c" * 64,
            outbox_claim_ref="outbox:1:attempt:1",
            primary_authority_ref=(
                "primary-authority:operations-core-primary:"
                "effect-worker:ops-alert-email:epoch:1"
            ),
            lease_expires_at="2026-07-24T07:05:00+00:00",
        )

    def read_owner(self) -> NotificationOwner:
        self.calls.append(("read_owner", None))
        return self.owner

    def read_request(
        self,
        idempotency_key: str,
    ) -> OwnedEmailExistingRequest | None:
        return self.existing_request

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
        *,
        authorize_mutation: Callable[[], object],
    ) -> AcknowledgedEffect:
        authorize_mutation()
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
            authority_key="operations-core-primary",
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
    assert primary_authority.calls == 4


def test_deliver_returns_terminal_receipt_without_second_provider_call() -> None:
    store = _Store(_owner())
    provider = _Provider()
    terminal = OwnedEmailReceipt(
        schema_version="owned-email-receipt.v1",
        owner_generation=store.owner.generation,
        work_id=store.request_view.work_id,
        work_status="succeeded",
        effect_id=store.request_view.effect_id,
        effect_status="delivered",
        attempt_count=1,
        disposition="delivered",
        evidence_ref="imap-sent:terminal-replay",
        evidence_sha256="e" * 64,
        primary_authority_ref="primary-authority:terminal-replay",
        recorded_at="2026-07-24T07:00:02+00:00",
    )
    store.request_view = OwnedEmailRequest(
        **{
            **store.request_view.__dict__,
            "terminal_receipt": terminal,
        }
    )

    receipt = OwnedEmailNotification(
        store=store,
        provider=provider,
        primary_authority=_LeaseGate(),
    ).deliver(_command())

    assert receipt == terminal
    assert [name for name, _ in store.calls] == [
        "read_owner",
        "request",
    ]
    assert provider.calls == []


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


def test_environment_dispatch_routes_operations_core_through_owned_delivery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _Store(_owner())
    captured: dict[str, object] = {}

    class FakeNotifier:
        def __init__(self, *, storage_dir: str) -> None:
            captured["storage_dir"] = storage_dir

        def notify(self, **kwargs: object) -> str:
            raise AssertionError("operations_core route used direct SMTP")

    class FakeKeepalive:
        def start(self) -> None:
            captured["keepalive_started"] = True

        def stop(self) -> None:
            captured["keepalive_stopped"] = True

    class FakeOwnedDelivery:
        def __init__(self, **kwargs: object) -> None:
            captured["owned_init"] = kwargs

        def deliver(self, command: OwnedEmailCommand) -> object:
                captured["command"] = command
                return SimpleNamespace(
                    owner_generation=2,
                    effect_id="effect-boss-report",
                delivered=True,
                disposition="delivered",
                work_id="work-boss-report",
                effect_status="delivered",
                attempt_count=1,
                evidence_ref="imap-sent:boss-report",
                evidence_sha256="a" * 64,
            )

    monkeypatch.setattr(
        "volpred.ops.delivery.owned_email."
        "SupabaseOwnedEmailStore.from_environment",
        classmethod(lambda cls: store),
    )
    monkeypatch.setattr(
        "volpred.publisher.email_notifier.EmailNotifier",
        FakeNotifier,
    )
    monkeypatch.setattr(
        "volpred.ops.delivery.owned_email.OwnedEmailNotification",
        FakeOwnedDelivery,
    )
    monkeypatch.setattr(
        "volpred.ops.delivery._email_notification."
        "ImapSentMailReader.from_environment",
        classmethod(lambda cls: object()),
    )
    monkeypatch.setattr(
        "volpred.ops.authority."
        "build_supabase_host_authority_keepalive",
        lambda **kwargs: (
            captured.update({"keepalive_kwargs": kwargs})
            or FakeKeepalive()
        ),
    )

    result = dispatch_email_by_current_owner(
        _command(),
        storage_dir=str(tmp_path / "storage"),
    )

    assert captured["command"] == _command()
    assert captured["keepalive_started"] is True
    assert captured["keepalive_stopped"] is True
    assert captured["keepalive_kwargs"] == {
        "holder_ref": "effect-worker:ops-alert-email",
    }
    assert result["delivery_owner"] == "operations_core"
    assert result["effect_status"] == "delivered"
    assert result["sent"] is True


def test_environment_dispatch_fences_and_verifies_explicit_legacy_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    store = _Store(_owner(owner="legacy"))

    class FakeNotifier:
        def __init__(self, *, storage_dir: str) -> None:
            captured["storage_dir"] = storage_dir

    class FakeAdapter:
        def __init__(self, **kwargs: object) -> None:
            captured["adapter"] = kwargs

        def deliver(
            self,
            effect: EffectView,
            payload: bytes,
            *,
            authorize_mutation: Callable[[], object],
        ) -> AcknowledgedEffect:
            authorize_mutation()
            captured["effect"] = effect
            captured["payload"] = payload
            return AcknowledgedEffect(
                acknowledgement=effect.acknowledgement,
                evidence_ref="imap-sent:legacy",
                evidence_sha256="f" * 64,
            )

    class FakeKeepalive:
        def start(self) -> None:
            captured["keepalive_started"] = True

        def stop(self) -> None:
            captured["keepalive_stopped"] = True

        def current_lease(self) -> PrimaryLease:
            return PrimaryLease(
                schema_version="primary-lease.v1",
                authority_key="operations-core-primary",
                holder_ref="effect-worker:ops-alert-email-legacy",
                epoch=1,
                fencing_token="legacy-primary-token",
                lease_seconds=300,
                acquired_at="2026-07-26T12:00:00+00:00",
                expires_at="2026-07-26T12:05:00+00:00",
            )

    monkeypatch.setattr(
        "volpred.ops.delivery.owned_email."
        "SupabaseOwnedEmailStore.from_environment",
        classmethod(lambda cls: store),
    )
    monkeypatch.setattr(
        "volpred.publisher.email_notifier.EmailNotifier",
        FakeNotifier,
    )
    monkeypatch.setattr(
        "volpred.ops.delivery._email_notification."
        "EmailNotificationEffectAdapter",
        FakeAdapter,
    )
    monkeypatch.setattr(
        "volpred.ops.delivery._email_notification."
        "ImapSentMailReader.from_environment",
        classmethod(lambda cls: object()),
    )
    monkeypatch.setattr(
        "volpred.ops.authority."
        "build_supabase_host_authority_keepalive",
        lambda **kwargs: (
            captured.update({"keepalive_kwargs": kwargs})
            or FakeKeepalive()
        ),
    )

    result = dispatch_email_by_current_owner(
        _command(),
        storage_dir=str(tmp_path / "storage"),
    )

    effect = captured["effect"]
    assert effect.idempotency_key == _command().idempotency_key
    assert effect.effect_kind == "email.notification.send"
    assert captured["keepalive_kwargs"] == {
        "holder_ref": "effect-worker:ops-alert-email-legacy",
    }
    assert captured["keepalive_started"] is True
    assert captured["keepalive_stopped"] is True
    assert result["delivery_owner"] == "legacy"
    assert result["effect_status"] == "legacy_sent_verified"
    assert result["evidence_ref"] == "imap-sent:legacy"
    assert result["sent"] is True


def test_environment_dispatch_uses_stable_legacy_effect_identity_across_hosts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _Store(_owner(owner="legacy"))
    effect_ids: list[str] = []

    class FakeNotifier:
        def __init__(self, *, storage_dir: str) -> None:
            pass

    class FakeAdapter:
        def __init__(self, **kwargs: object) -> None:
            pass

        def deliver(
            self,
            effect: EffectView,
            payload: bytes,
            *,
            authorize_mutation: Callable[[], object],
        ) -> AcknowledgedEffect:
            authorize_mutation()
            effect_ids.append(effect.id)
            return AcknowledgedEffect(
                acknowledgement=effect.acknowledgement,
                evidence_ref="imap-sent:already-there",
                evidence_sha256="e" * 64,
            )

    class FakeKeepalive:
        def start(self) -> None:
            pass

        def stop(self) -> None:
            pass

        def current_lease(self) -> PrimaryLease:
            return PrimaryLease(
                schema_version="primary-lease.v1",
                authority_key="operations-core-primary",
                holder_ref="effect-worker:ops-alert-email-legacy",
                epoch=1,
                fencing_token="legacy-primary-token",
                lease_seconds=300,
                acquired_at="2026-07-26T12:00:00+00:00",
                expires_at="2026-07-26T12:05:00+00:00",
            )

    monkeypatch.setattr(
        "volpred.ops.delivery.owned_email."
        "SupabaseOwnedEmailStore.from_environment",
        classmethod(lambda cls: store),
    )
    monkeypatch.setattr(
        "volpred.publisher.email_notifier.EmailNotifier",
        FakeNotifier,
    )
    monkeypatch.setattr(
        "volpred.ops.delivery._email_notification."
        "EmailNotificationEffectAdapter",
        FakeAdapter,
    )
    monkeypatch.setattr(
        "volpred.ops.delivery._email_notification."
        "ImapSentMailReader.from_environment",
        classmethod(lambda cls: object()),
    )
    monkeypatch.setattr(
        "volpred.ops.authority."
        "build_supabase_host_authority_keepalive",
        lambda **kwargs: FakeKeepalive(),
    )

    first = dispatch_email_by_current_owner(
        _command(),
        storage_dir=str(tmp_path / "storage"),
    )
    second = dispatch_email_by_current_owner(
        _command(),
        storage_dir=str(tmp_path / "other-storage"),
    )

    assert first["sent"] is second["sent"] is True
    assert effect_ids[0] == effect_ids[1]
    assert first["evidence_ref"] == "imap-sent:already-there"


def test_environment_dispatch_fails_before_provider_when_owner_read_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notifier_constructed = False

    class FailingStore:
        def read_request(
            self,
            idempotency_key: str,
        ) -> OwnedEmailExistingRequest | None:
            return None

        def read_owner(self) -> NotificationOwner:
            raise RuntimeError("owner read unavailable")

    class FakeNotifier:
        def __init__(self, *, storage_dir: str) -> None:
            nonlocal notifier_constructed
            notifier_constructed = True

    monkeypatch.setattr(
        "volpred.ops.delivery.owned_email."
        "SupabaseOwnedEmailStore.from_environment",
        classmethod(lambda cls: FailingStore()),
    )
    monkeypatch.setattr(
        "volpred.publisher.email_notifier.EmailNotifier",
        FakeNotifier,
    )

    with pytest.raises(RuntimeError, match="owner read unavailable"):
        dispatch_email_by_current_owner(
            _command(),
            storage_dir=str(tmp_path / "storage"),
        )

    assert notifier_constructed is False


def test_environment_dispatch_returns_cross_host_terminal_before_legacy_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _Store(_owner(owner="legacy"))
    terminal = OwnedEmailReceipt(
        schema_version="owned-email-receipt.v1",
        owner_generation=2,
        work_id="work-owned-email-1",
        work_status="succeeded",
        effect_id="effect-owned-email-1",
        effect_status="delivered",
        attempt_count=1,
        disposition="delivered",
        evidence_ref="imap-sent:cross-host",
        evidence_sha256="d" * 64,
        primary_authority_ref="primary-authority:cross-host",
        recorded_at="2026-07-26T12:50:00+00:00",
    )
    store.existing_request = OwnedEmailExistingRequest(
        command=_command(),
        request=OwnedEmailRequest(
            owner_generation=2,
            work_id="work-owned-email-1",
            effect_id="effect-owned-email-1",
            request_sha256="a" * 64,
            terminal_receipt=terminal,
        ),
    )

    class ForbiddenNotifier:
        def __init__(self, **kwargs: object) -> None:
            raise AssertionError("terminal replay constructed a provider")

    monkeypatch.setattr(
        "volpred.ops.delivery.owned_email."
        "SupabaseOwnedEmailStore.from_environment",
        classmethod(lambda cls: store),
    )
    monkeypatch.setattr(
        "volpred.publisher.email_notifier.EmailNotifier",
        ForbiddenNotifier,
    )

    result = dispatch_email_by_current_owner(
        _command(),
        storage_dir=str(tmp_path / "storage"),
    )

    assert result["sent"] is True
    assert result["delivery_owner"] == "operations_core"
    assert result["evidence_ref"] == "imap-sent:cross-host"


def test_environment_dispatch_refuses_legacy_over_nonterminal_core_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _Store(_owner(owner="legacy"))
    store.existing_request = OwnedEmailExistingRequest(
        command=_command(),
        request=store.request_view,
    )
    monkeypatch.setattr(
        "volpred.ops.delivery.owned_email."
        "SupabaseOwnedEmailStore.from_environment",
        classmethod(lambda cls: store),
    )

    with pytest.raises(
        RuntimeError,
        match="cannot supersede",
    ):
        dispatch_email_by_current_owner(
            _command(),
            storage_dir=str(tmp_path / "storage"),
        )


def test_legacy_fence_rechecks_and_refuses_new_pending_core_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _Store(_owner(owner="legacy"))
    pending = OwnedEmailExistingRequest(
        command=_command(),
        request=store.request_view,
    )
    request_reads = iter((None, pending))
    store.read_request = lambda idempotency_key: next(  # type: ignore[method-assign]
        request_reads
    )
    provider_constructed = False

    class FakeKeepalive:
        def start(self) -> None:
            pass

        def stop(self) -> None:
            pass

        def current_lease(self) -> PrimaryLease:
            return PrimaryLease(
                schema_version="primary-lease.v1",
                authority_key="operations-core-primary",
                holder_ref="effect-worker:ops-alert-email-legacy",
                epoch=1,
                fencing_token="legacy-primary-token",
                lease_seconds=300,
                acquired_at="2026-07-26T12:00:00+00:00",
                expires_at="2026-07-26T12:05:00+00:00",
            )

    class ForbiddenNotifier:
        def __init__(self, **kwargs: object) -> None:
            nonlocal provider_constructed
            provider_constructed = True

    monkeypatch.setattr(
        "volpred.ops.delivery.owned_email."
        "SupabaseOwnedEmailStore.from_environment",
        classmethod(lambda cls: store),
    )
    monkeypatch.setattr(
        "volpred.publisher.email_notifier.EmailNotifier",
        ForbiddenNotifier,
    )
    monkeypatch.setattr(
        "volpred.ops.authority."
        "build_supabase_host_authority_keepalive",
        lambda **kwargs: FakeKeepalive(),
    )

    with pytest.raises(RuntimeError, match="pending Operations Core"):
        dispatch_email_by_current_owner(
            _command(),
            storage_dir=str(tmp_path / "storage"),
        )

    assert provider_constructed is False


def test_legacy_fence_rechecks_and_replays_new_terminal_core_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _Store(_owner(owner="legacy"))
    terminal = OwnedEmailReceipt(
        schema_version="owned-email-receipt.v1",
        owner_generation=2,
        work_id="work-owned-email-1",
        work_status="succeeded",
        effect_id="effect-owned-email-1",
        effect_status="delivered",
        attempt_count=1,
        disposition="delivered",
        evidence_ref="imap-sent:interleaved-terminal",
        evidence_sha256="c" * 64,
        primary_authority_ref="primary-authority:interleaved",
        recorded_at="2026-07-26T12:50:00+00:00",
    )
    completed = OwnedEmailExistingRequest(
        command=_command(),
        request=OwnedEmailRequest(
            owner_generation=2,
            work_id="work-owned-email-1",
            effect_id="effect-owned-email-1",
            request_sha256="a" * 64,
            terminal_receipt=terminal,
        ),
    )
    request_reads = iter((None, completed))
    store.read_request = lambda idempotency_key: next(  # type: ignore[method-assign]
        request_reads
    )

    class FakeKeepalive:
        def start(self) -> None:
            pass

        def stop(self) -> None:
            pass

        def current_lease(self) -> PrimaryLease:
            return PrimaryLease(
                schema_version="primary-lease.v1",
                authority_key="operations-core-primary",
                holder_ref="effect-worker:ops-alert-email-legacy",
                epoch=1,
                fencing_token="legacy-primary-token",
                lease_seconds=300,
                acquired_at="2026-07-26T12:00:00+00:00",
                expires_at="2026-07-26T12:05:00+00:00",
            )

    class ForbiddenNotifier:
        def __init__(self, **kwargs: object) -> None:
            raise AssertionError("terminal interleaving reached provider")

    monkeypatch.setattr(
        "volpred.ops.delivery.owned_email."
        "SupabaseOwnedEmailStore.from_environment",
        classmethod(lambda cls: store),
    )
    monkeypatch.setattr(
        "volpred.publisher.email_notifier.EmailNotifier",
        ForbiddenNotifier,
    )
    monkeypatch.setattr(
        "volpred.ops.authority."
        "build_supabase_host_authority_keepalive",
        lambda **kwargs: FakeKeepalive(),
    )

    result = dispatch_email_by_current_owner(
        _command(),
        storage_dir=str(tmp_path / "storage"),
    )

    assert result["sent"] is True
    assert result["delivery_owner"] == "operations_core"
    assert result["evidence_ref"] == "imap-sent:interleaved-terminal"


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


def test_deliver_revalidates_primary_authority_at_smtp_mutation_boundary() -> None:
    store = _Store(_owner())
    primary_authority = _LeaseGate()
    payload = json.dumps(
        {
            "schema_version": "email-notification.v1",
            "subject": "Authority boundary canary",
            "text_body": "This message must not be sent.",
            "html_body": "<p>This message must not be sent.</p>",
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    store.attempt = OwnedEmailAttempt(
        **{
            **store.attempt.__dict__,
            "effect": replace(
                store.attempt.effect,
                payload_sha256=hashlib.sha256(payload).hexdigest(),
            ),
            "payload": payload,
        }
    )

    class ReplacingSentMailbox:
        def __init__(self) -> None:
            self.reads = 0

        def read(self, _message_id: str) -> bytes | None:
            self.reads += 1
            original = primary_authority.lease
            primary_authority.lease = PrimaryLease(
                **{
                    **original.__dict__,
                    "epoch": original.epoch + 1,
                    "fencing_token": "replacement-token",
                }
            )
            return None

    class ForbiddenNotifier:
        def __init__(self) -> None:
            self.calls = 0

        def notify(self, **_kwargs: object) -> str:
            self.calls += 1
            raise AssertionError("stale authority reached SMTP mutation")

    mailbox = ReplacingSentMailbox()
    notifier = ForbiddenNotifier()
    provider = EmailNotificationEffectAdapter(
        notifier=notifier,
        sent_mail_reader=mailbox,
    )

    with pytest.raises(
        NotificationOwnershipLost,
        match="lease was replaced",
    ):
        OwnedEmailNotification(
            store=store,
            provider=provider,
            primary_authority=primary_authority,
        ).deliver(_command())

    assert mailbox.reads == 1
    assert notifier.calls == 0
    assert "settle" not in [name for name, _ in store.calls]


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


def test_supabase_store_parses_terminal_receipt_from_request_replay() -> None:
    store = SupabaseOwnedEmailStore(
        supabase_url="https://project.supabase.co",
        service_role_key="fake-service-role-key",
    )
    store._rpc = lambda function, payload: {  # type: ignore[method-assign]
        "schema_version": "owned-email-request.v1",
        "owner_generation": 2,
        "work_id": "work-owned-email-1",
        "effect_id": "effect-owned-email-1",
        "request_sha256": "a" * 64,
        "receipt": {
            "schema_version": "owned-email-receipt.v1",
            "owner_generation": 2,
            "work_id": "work-owned-email-1",
            "work_status": "succeeded",
            "effect_id": "effect-owned-email-1",
            "effect_status": "delivered",
            "attempt_count": 1,
            "disposition": "delivered",
            "evidence_ref": "imap-sent:terminal-replay",
            "evidence_sha256": "b" * 64,
            "primary_authority_ref": "primary-authority:terminal-replay",
            "recorded_at": "2026-07-26T12:50:00+00:00",
        },
    }

    request_view = store.request(_command(), owner_generation=2)

    assert request_view.terminal_receipt is not None
    assert request_view.terminal_receipt.delivered is True
    assert request_view.terminal_receipt.evidence_sha256 == "b" * 64


def test_supabase_store_rejects_wrong_request_and_receipt_schemas() -> None:
    store = SupabaseOwnedEmailStore(
        supabase_url="https://project.supabase.co",
        service_role_key="fake-service-role-key",
    )
    store._rpc = lambda function, payload: {  # type: ignore[method-assign]
        "schema_version": "owned-email-request.v0",
    }
    with pytest.raises(RuntimeError, match="request schema"):
        store.request(_command(), owner_generation=2)

    store._rpc = lambda function, payload: {  # type: ignore[method-assign]
        "schema_version": "owned-email-request.v1",
        "owner_generation": 2,
        "work_id": "work-owned-email-1",
        "effect_id": "effect-owned-email-1",
        "request_sha256": "a" * 64,
        "receipt": {
            "schema_version": "owned-email-receipt.v0",
        },
    }
    with pytest.raises(RuntimeError, match="receipt schema"):
        store.request(_command(), owner_generation=2)


def test_owned_email_terminal_replay_migration_returns_receipt() -> None:
    migration = (
        Path(__file__).resolve().parents[1]
        / "supabase"
        / "migrations"
        / "20260726125016_boss_report_owned_email_terminal_replay.sql"
    ).read_text(encoding="utf-8")

    assert "terminal_attempt volpred_ops.owned_notification_attempts" in migration
    assert "'receipt', terminal_receipt" in migration
    assert "'receipt', NULL" in migration
    assert "attempt.status IN ('delivered', 'dead_lettered')" in migration
    assert "public.volpred_read_owned_email_request" in migration
    assert "'schema_version', 'owned-email-request-read.v1'" in migration
    assert "TO service_role" in migration


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
