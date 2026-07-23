from __future__ import annotations

import hashlib

import pytest

from volpred.ops.delivery import (
    AcknowledgedEffect,
    AcknowledgementExpectation,
    EffectView,
)
from volpred.ops.delivery.owned_email import (
    NotificationOwner,
    NotificationOwnershipLost,
    OwnedEmailAttempt,
    OwnedEmailCommand,
    OwnedEmailNotification,
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
        outcome: AcknowledgedEffect,
    ) -> OwnedEmailReceipt:
        self.calls.append(("settle", (attempt, outcome)))
        return OwnedEmailReceipt(
            schema_version="owned-email-receipt.v1",
            owner_generation=attempt.owner_generation,
            work_id=attempt.work_id,
            work_status="succeeded",
            effect_id=attempt.effect.id,
            effect_status="delivered",
            attempt_count=attempt.attempt_count,
            disposition="delivered",
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


def test_deliver_owns_request_begin_provider_and_settlement() -> None:
    store = _Store(_owner())
    provider = _Provider()
    tokens = iter(("work-token", "outbox-token", "primary-token"))
    delivery = OwnedEmailNotification(
        store=store,
        provider=provider,
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
        ).deliver(_command())

    assert store.calls == [("read_owner", None)]
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
