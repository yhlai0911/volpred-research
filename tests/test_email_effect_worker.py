from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from email.message import EmailMessage
from pathlib import Path

import pytest

from volpred.ops.delivery import (
    AcknowledgedEffect,
    AcknowledgementExpectation,
    EffectView,
    FailedEffect,
)
from volpred.ops.delivery._effect_worker import (
    EffectAuthorityGrant,
    EffectAuthorityRequest,
    EffectOutboxWorker,
    EffectWorkerBlocked,
    EffectWorkerCommand,
    FileEffectPayloadReader,
)
from volpred.ops.delivery._email_notification import (
    EmailNotificationEffectAdapter,
)
from volpred.ops.delivery.postgres import (
    EffectAttemptReceipt,
    EffectOutboxLease,
    EffectSettlementAuthority,
)


def _payload() -> bytes:
    return json.dumps(
        {
            "schema_version": "email-notification.v1",
            "subject": "Shadow delivery verified",
            "text_body": "The fenced outbox worker completed.",
            "html_body": "<p>The fenced outbox worker completed.</p>",
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _effect(payload: bytes) -> EffectView:
    return EffectView(
        schema_version="effect-request.v1",
        id="effect-email-worker-1",
        idempotency_key="effect:work-1:email:shadow",
        work_item_id="work-1",
        work_item_version=7,
        effect_kind="email.notification.send",
        target_ref="email:owner@example.com",
        payload_ref="file:effects/shadow-email.json",
        payload_sha256=hashlib.sha256(payload).hexdigest(),
        risk="safe",
        acknowledgement=AcknowledgementExpectation(
            kind="email.sent-mail.readback",
            target_ref="email:owner@example.com",
        ),
        requester_ref="agent:effect-worker",
        request_sha256="a" * 64,
        status="requested",
        created_at="2026-07-24T03:00:00+00:00",
    )


class _PayloadReader:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.error: Exception | None = None
        self.refs: list[str] = []

    def read(self, payload_ref: str) -> bytes:
        self.refs.append(payload_ref)
        if self.error is not None:
            raise self.error
        return self.payload


class _Mailbox:
    def __init__(self) -> None:
        self.messages: dict[str, bytes] = {}

    def read(self, message_id: str) -> bytes | None:
        return self.messages.get(message_id)


class _Notifier:
    def __init__(self, mailbox: _Mailbox) -> None:
        self.mailbox = mailbox
        self.calls: list[dict[str, object]] = []

    def notify(self, **kwargs: object) -> str:
        self.calls.append(kwargs)
        message = EmailMessage()
        message["Message-ID"] = str(kwargs["provider_message_id"])
        message["Subject"] = str(kwargs["subject"])
        message["From"] = "VolPred <ops@example.com>"
        recipients = kwargs["recipients"]
        assert isinstance(recipients, list)
        message["To"] = ", ".join(str(item) for item in recipients)
        message.set_content(str(kwargs["body"]))
        html_body = kwargs.get("html_body")
        if html_body is not None:
            message.add_alternative(str(html_body), subtype="html")
        self.mailbox.messages[str(kwargs["provider_message_id"])] = (
            message.as_bytes()
        )
        return "notification-shadow-1"


class _ProviderError:
    def deliver(self, effect: EffectView, payload: bytes):
        raise TimeoutError("provider timed out")


class _Authority:
    def __init__(
        self,
        *,
        primary_fencing_token: str = "primary-fence-current",
    ) -> None:
        self.primary_fencing_token = primary_fencing_token
        self.requests: list[EffectAuthorityRequest] = []

    def authorize(
        self,
        request: EffectAuthorityRequest,
    ) -> EffectAuthorityGrant:
        self.requests.append(request)
        if request.primary_fencing_token != self.primary_fencing_token:
            raise EffectWorkerBlocked("stale Primary Authority fencing token")
        if request.outbox_claim_token != "outbox-claim-secret":
            raise EffectWorkerBlocked("stale effect outbox claim")
        return EffectAuthorityGrant(
            request_sha256=request.request_sha256,
            outbox_claim_ref="effect-outbox:1:attempt-1",
            primary_authority_ref="primary-authority:epoch-42",
        )


class _MismatchedAuthority(_Authority):
    def authorize(
        self,
        request: EffectAuthorityRequest,
    ) -> EffectAuthorityGrant:
        return replace(
            super().authorize(request),
            request_sha256="0" * 64,
        )


class _Store:
    def __init__(self, effect: EffectView) -> None:
        self.effect = effect
        self.available = True
        self.outcomes: list[object] = []
        self.authorities: list[EffectSettlementAuthority] = []
        self.receipt_drift = False

    def claim_outbox(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
    ) -> EffectOutboxLease | None:
        if not self.available:
            return None
        self.available = False
        return EffectOutboxLease(
            sequence=1,
            effect_id=self.effect.id,
            token="outbox-claim-secret",
            claimed_by=worker_id,
            attempt_count=1,
            expires_at="2026-07-24T03:05:00+00:00",
        )

    def inspect(self, effect_id: str) -> EffectView:
        assert effect_id == self.effect.id
        return self.effect

    def settle_outbox(
        self,
        *,
        lease: EffectOutboxLease,
        outcome: AcknowledgedEffect | FailedEffect,
        authority: EffectSettlementAuthority,
    ) -> EffectAttemptReceipt:
        self.outcomes.append(outcome)
        self.authorities.append(authority)
        if isinstance(outcome, AcknowledgedEffect):
            reported_outcome = "acknowledged"
            disposition = "delivered"
            acknowledgement = outcome.acknowledgement
            reason_code = None
            retry_at = None
        else:
            reported_outcome = (
                "retryable_failure"
                if outcome.retryable
                else "terminal_failure"
            )
            disposition = (
                "retry_scheduled"
                if outcome.retryable
                else "dead_lettered"
            )
            acknowledgement = None
            reason_code = outcome.reason_code
            retry_at = (
                "2026-07-24T03:00:30+00:00"
                if outcome.retryable
                else None
            )
        receipt = EffectAttemptReceipt(
            schema_version="effect-attempt-receipt.v1",
            effect_id=lease.effect_id,
            outbox_sequence=lease.sequence,
            attempt_count=lease.attempt_count,
            worker_id=lease.claimed_by,
            reported_outcome=reported_outcome,
            disposition=disposition,
            acknowledgement=acknowledgement,
            reason_code=reason_code,
            evidence_ref=outcome.evidence_ref,
            evidence_sha256=outcome.evidence_sha256,
            authority_request_sha256=authority.request_sha256,
            outbox_claim_ref=authority.outbox_claim_ref,
            primary_authority_ref=authority.primary_authority_ref,
            retry_at=retry_at,
            recorded_at="2026-07-24T03:00:01+00:00",
        )
        if self.receipt_drift:
            return replace(receipt, primary_authority_ref="primary-authority:wrong")
        return receipt


def _worker(
    *,
    authority: _Authority | None = None,
    provider: object | None = None,
    payload_reader: _PayloadReader | None = None,
) -> tuple[EffectOutboxWorker, _Store, _Notifier, _PayloadReader]:
    payload = _payload()
    store = _Store(_effect(payload))
    mailbox = _Mailbox()
    notifier = _Notifier(mailbox)
    reader = payload_reader or _PayloadReader(payload)
    selected_provider = provider or EmailNotificationEffectAdapter(
        notifier=notifier,
        sent_mail_reader=mailbox,
    )
    worker = EffectOutboxWorker(
        delivery=store,
        authority=authority or _Authority(),
        payload_reader=reader,
        provider=selected_provider,
    )
    return worker, store, notifier, reader


def _command(**overrides: object) -> EffectWorkerCommand:
    command = EffectWorkerCommand(
        worker_id="effect-worker:shadow-email",
        primary_fencing_token="primary-fence-current",
        lease_seconds=300,
    )
    return replace(command, **overrides)


def test_worker_claims_authorizes_reads_back_and_durably_settles() -> None:
    authority = _Authority()
    worker, store, notifier, reader = _worker(authority=authority)

    receipt = worker.run_once(_command())

    assert receipt is not None
    assert receipt.schema_version == "effect-worker-receipt.v1"
    assert receipt.disposition == "delivered"
    assert receipt.reported_outcome == "acknowledged"
    assert receipt.outbox_claim_ref == "effect-outbox:1:attempt-1"
    assert receipt.primary_authority_ref == "primary-authority:epoch-42"
    assert receipt.authority_request_sha256 == (
        authority.requests[0].request_sha256
    )
    assert len(notifier.calls) == 1
    assert reader.refs == ["file:effects/shadow-email.json"]
    assert isinstance(store.outcomes[0], AcknowledgedEffect)
    assert store.authorities[0].request_sha256 == (
        receipt.authority_request_sha256
    )
    assert "outbox-claim-secret" not in repr(receipt)
    assert "primary-fence-current" not in repr(receipt)


def test_worker_returns_none_without_claiming_or_authorizing() -> None:
    authority = _Authority()
    worker, store, notifier, reader = _worker(authority=authority)
    store.available = False

    assert worker.run_once(_command()) is None
    assert authority.requests == []
    assert notifier.calls == []
    assert reader.refs == []


@pytest.mark.parametrize(
    ("authority", "command", "message"),
    [
        (
            _Authority(),
            _command(primary_fencing_token="primary-fence-stale"),
            "stale Primary Authority",
        ),
        (
            _MismatchedAuthority(),
            _command(),
            "does not match",
        ),
    ],
)
def test_worker_refuses_provider_before_valid_authority(
    authority: _Authority,
    command: EffectWorkerCommand,
    message: str,
) -> None:
    worker, store, notifier, reader = _worker(authority=authority)

    with pytest.raises(EffectWorkerBlocked, match=message):
        worker.run_once(command)

    assert notifier.calls == []
    assert reader.refs == []
    assert store.outcomes == []


def test_payload_failure_is_authorized_and_settled_as_retryable() -> None:
    reader = _PayloadReader(_payload())
    reader.error = OSError("artifact store unavailable")
    worker, store, notifier, _reader = _worker(payload_reader=reader)

    receipt = worker.run_once(_command())

    assert receipt is not None
    assert receipt.disposition == "retry_scheduled"
    assert isinstance(store.outcomes[0], FailedEffect)
    assert store.outcomes[0].reason_code == "effect_payload_unavailable"
    assert store.outcomes[0].retryable is True
    assert notifier.calls == []


def test_unexpected_provider_error_is_settled_as_retryable() -> None:
    worker, store, _notifier, _reader = _worker(provider=_ProviderError())

    receipt = worker.run_once(_command())

    assert receipt is not None
    assert receipt.disposition == "retry_scheduled"
    assert isinstance(store.outcomes[0], FailedEffect)
    assert store.outcomes[0].reason_code == "effect_provider_error"


def test_worker_fails_closed_when_settlement_readback_drifts() -> None:
    worker, store, notifier, _reader = _worker()
    store.receipt_drift = True

    with pytest.raises(EffectWorkerBlocked, match="settlement read-back"):
        worker.run_once(_command())

    assert len(notifier.calls) == 1
    assert len(store.outcomes) == 1


def test_file_payload_reader_confines_refs_to_configured_root(
    tmp_path: Path,
) -> None:
    root = tmp_path / "payloads"
    payload_path = root / "effects" / "shadow-email.json"
    payload_path.parent.mkdir(parents=True)
    payload_path.write_bytes(_payload())
    outside = tmp_path / "outside.json"
    outside.write_bytes(b"outside")
    reader = FileEffectPayloadReader(root)

    assert reader.read("file:effects/shadow-email.json") == _payload()
    with pytest.raises(ValueError, match="normalized relative file"):
        reader.read("file:../outside.json")
    with pytest.raises(ValueError, match="file:"):
        reader.read("artifact:shadow-email")
