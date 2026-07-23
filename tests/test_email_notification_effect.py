from __future__ import annotations

from dataclasses import replace
from email.message import EmailMessage
from email.policy import default
from email.parser import BytesParser
import hashlib
import json

import pytest

from volpred.ops.delivery import (
    AcknowledgedEffect,
    AcknowledgementExpectation,
    EffectView,
    FailedEffect,
)
from volpred.ops.delivery import _email_notification
from volpred.ops.delivery._email_notification import (
    EmailNotificationEffectAdapter,
    ImapSentMailReader,
)
from volpred.publisher.email_notifier import EmailNotifier


def _payload(**overrides: object) -> bytes:
    value: dict[str, object] = {
        "schema_version": "email-notification.v1",
        "subject": "Work completed",
        "text_body": "The operation finished and passed verification.",
        "html_body": "<p>The operation finished and passed verification.</p>",
    }
    value.update(overrides)
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _effect(payload: bytes, **overrides: object) -> EffectView:
    effect = EffectView(
        schema_version="effect-request.v1",
        id="effect-email-1",
        idempotency_key="effect:work-1:email:completion",
        work_item_id="work-1",
        work_item_version=7,
        effect_kind="email.notification.send",
        target_ref="email:owner@example.com",
        payload_ref="artifact:completion-email-v1",
        payload_sha256=hashlib.sha256(payload).hexdigest(),
        risk="safe",
        acknowledgement=AcknowledgementExpectation(
            kind="email.sent-mail.readback",
            target_ref="email:owner@example.com",
        ),
        requester_ref="agent:effect-worker",
        request_sha256="a" * 64,
        status="requested",
        created_at="2026-07-24T02:00:00+00:00",
    )
    return replace(effect, **overrides)


class _SentMailbox:
    def __init__(self) -> None:
        self.messages: dict[str, bytes] = {}
        self.reads: list[str] = []

    def read(self, message_id: str) -> bytes | None:
        self.reads.append(message_id)
        return self.messages.get(message_id)


class _Notifier:
    def __init__(self, mailbox: _SentMailbox) -> None:
        self.mailbox = mailbox
        self.calls: list[dict[str, object]] = []
        self.raise_error: Exception | None = None
        self.persist_sent_copy = True

    def notify(self, **kwargs: object) -> str:
        if self.raise_error is not None:
            raise self.raise_error
        self.calls.append(kwargs)
        message_id = str(kwargs["provider_message_id"])
        if self.persist_sent_copy:
            message = EmailMessage()
            message["Message-ID"] = message_id
            message["Subject"] = str(kwargs["subject"])
            message["From"] = "VolPred <ops@example.com>"
            recipients = kwargs["recipients"]
            assert isinstance(recipients, list)
            message["To"] = ", ".join(str(item) for item in recipients)
            message.set_content(str(kwargs["body"]))
            html_body = kwargs.get("html_body")
            if html_body is not None:
                message.add_alternative(str(html_body), subtype="html")
            self.mailbox.messages[message_id] = message.as_bytes()
        return "notification-1"


def _adapter() -> tuple[
    EmailNotificationEffectAdapter,
    _Notifier,
    _SentMailbox,
]:
    mailbox = _SentMailbox()
    notifier = _Notifier(mailbox)
    return (
        EmailNotificationEffectAdapter(
            notifier=notifier,
            sent_mail_reader=mailbox,
        ),
        notifier,
        mailbox,
    )


def test_deliver_requires_sent_mail_readback_before_acknowledging() -> None:
    payload = _payload()
    adapter, notifier, mailbox = _adapter()

    outcome = adapter.deliver(_effect(payload), payload)

    assert isinstance(outcome, AcknowledgedEffect)
    assert outcome.acknowledgement == AcknowledgementExpectation(
        kind="email.sent-mail.readback",
        target_ref="email:owner@example.com",
    )
    assert outcome.evidence_ref.startswith("email:sent-mail:")
    assert len(outcome.evidence_sha256) == 64
    assert len(notifier.calls) == 1
    assert len(mailbox.reads) == 2
    assert notifier.calls[0]["recipients"] == ["owner@example.com"]
    assert notifier.calls[0]["metadata"] == {
        "notification_type": "effect_delivery",
        "effect_id": "effect-email-1",
        "work_item_id": "work-1",
        "payload_ref": "artifact:completion-email-v1",
        "payload_sha256": _effect(payload).payload_sha256,
    }


def test_existing_verified_sent_copy_makes_retry_idempotent() -> None:
    payload = _payload()
    adapter, notifier, mailbox = _adapter()
    first = adapter.deliver(_effect(payload), payload)
    assert isinstance(first, AcknowledgedEffect)

    replay = adapter.deliver(_effect(payload), payload)

    assert replay == first
    assert len(notifier.calls) == 1
    assert len(mailbox.reads) == 3


def test_smtp_acceptance_without_sent_mail_copy_is_retryable_failure() -> None:
    payload = _payload()
    adapter, notifier, _mailbox = _adapter()
    notifier.persist_sent_copy = False

    outcome = adapter.deliver(_effect(payload), payload)

    assert isinstance(outcome, FailedEffect)
    assert outcome.reason_code == "email_sent_mail_readback_missing"
    assert outcome.retryable is True
    assert len(notifier.calls) == 1


def test_transport_error_is_retryable_and_never_acknowledged() -> None:
    payload = _payload()
    adapter, notifier, _mailbox = _adapter()
    notifier.raise_error = TimeoutError("smtp timed out")

    outcome = adapter.deliver(_effect(payload), payload)

    assert isinstance(outcome, FailedEffect)
    assert outcome.reason_code == "email_provider_error"
    assert outcome.retryable is True


def test_readback_payload_drift_fails_closed_without_resending() -> None:
    payload = _payload()
    adapter, notifier, mailbox = _adapter()
    message_id = adapter.message_id_for(_effect(payload))
    drifted = EmailMessage()
    drifted["Message-ID"] = message_id
    drifted["Subject"] = "Wrong subject"
    drifted["From"] = "VolPred <ops@example.com>"
    drifted["To"] = "owner@example.com"
    drifted.set_content("Wrong body")
    mailbox.messages[message_id] = drifted.as_bytes()

    outcome = adapter.deliver(_effect(payload), payload)

    assert isinstance(outcome, FailedEffect)
    assert outcome.reason_code == "email_sent_mail_readback_mismatch"
    assert outcome.retryable is False
    assert notifier.calls == []


def test_raw_payload_hash_is_verified_before_provider_execution() -> None:
    payload = _payload()
    adapter, notifier, mailbox = _adapter()

    outcome = adapter.deliver(
        _effect(payload, payload_sha256="b" * 64),
        payload,
    )

    assert isinstance(outcome, FailedEffect)
    assert outcome.reason_code == "email_payload_hash_mismatch"
    assert outcome.retryable is False
    assert notifier.calls == []
    assert mailbox.reads == []


def test_only_safe_email_notification_contract_is_supported() -> None:
    payload = _payload()
    adapter, notifier, _mailbox = _adapter()
    cases = (
        _effect(payload, effect_kind="telegram.message.send"),
        _effect(payload, target_ref="telegram:owner-chat"),
        _effect(payload, risk="sensitive"),
        _effect(
            payload,
            acknowledgement=AcknowledgementExpectation(
                kind="email.sent-mail.readback",
                target_ref="email:other@example.com",
            ),
        ),
    )

    for effect in cases:
        outcome = adapter.deliver(effect, payload)
        assert isinstance(outcome, FailedEffect)
        assert outcome.reason_code == "unsupported_email_effect_contract"
        assert outcome.retryable is False
    assert notifier.calls == []


def test_payload_schema_and_header_injection_fail_closed() -> None:
    adapter, notifier, _mailbox = _adapter()
    malformed = (
        b"not-json",
        _payload(schema_version="email-notification.v2"),
        _payload(subject="bad\r\nBcc: victim@example.com"),
        _payload(text_body=""),
        _payload(extra="not-allowed"),
    )

    for payload in malformed:
        outcome = adapter.deliver(_effect(payload), payload)
        assert isinstance(outcome, FailedEffect)
        assert outcome.reason_code == "invalid_email_notification_payload"
        assert outcome.retryable is False
    assert notifier.calls == []


def test_readback_verifies_recipient_subject_plain_and_html_body() -> None:
    payload = _payload()
    adapter, notifier, mailbox = _adapter()
    effect = _effect(payload)
    message_id = adapter.message_id_for(effect)
    notifier.persist_sent_copy = False

    variants = (
        (
            "owner@example.com",
            "Wrong",
            "The operation finished and passed verification.",
            "<p>The operation finished and passed verification.</p>",
        ),
        (
            "other@example.com",
            "Work completed",
            "The operation finished and passed verification.",
            "<p>The operation finished and passed verification.</p>",
        ),
        (
            "owner@example.com",
            "Work completed",
            "Wrong",
            "<p>The operation finished and passed verification.</p>",
        ),
        (
            "owner@example.com",
            "Work completed",
            "The operation finished and passed verification.",
            "<p>Wrong</p>",
        ),
    )
    for recipient, subject, text_body, html_body in variants:
        message = EmailMessage()
        message["Message-ID"] = message_id
        message["Subject"] = subject
        message["From"] = "VolPred <ops@example.com>"
        message["To"] = recipient
        message.set_content(text_body)
        message.add_alternative(html_body, subtype="html")
        mailbox.messages[message_id] = message.as_bytes()

        outcome = adapter.deliver(effect, payload)
        assert isinstance(outcome, FailedEffect)
        assert outcome.reason_code == "email_sent_mail_readback_mismatch"
        assert outcome.retryable is False


def test_evidence_hash_is_the_exact_readback_message_bytes() -> None:
    payload = _payload()
    adapter, _notifier, mailbox = _adapter()

    outcome = adapter.deliver(_effect(payload), payload)

    assert isinstance(outcome, AcknowledgedEffect)
    raw = mailbox.messages[adapter.message_id_for(_effect(payload))]
    assert outcome.evidence_sha256 == hashlib.sha256(raw).hexdigest()
    parsed = BytesParser(policy=default).parsebytes(raw)
    assert parsed["Message-ID"] is not None


def test_email_notifier_threads_stable_message_id_into_transport_and_log(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ADMIN_NOTIFICATION_EMAILS", "owner@example.com")
    monkeypatch.setenv("EMAIL_FROM", "ops@example.com")
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    notifier = EmailNotifier(storage_dir=str(tmp_path))
    observed: dict[str, object] = {}

    def capture_send(**kwargs: object) -> None:
        observed.update(kwargs)

    monkeypatch.setattr(notifier, "_send_email", capture_send)
    message_id = "<volpred-effect.test@operations.volpred.local>"

    notification_id = notifier.notify(
        subject="Work completed",
        body="Verified",
        recipients=["owner@example.com"],
        provider_message_id=message_id,
    )

    assert observed["provider_message_id"] == message_id
    notification = json.loads(
        (
            tmp_path
            / "notifications"
            / f"{notification_id}.json"
        ).read_text(encoding="utf-8")
    )
    assert notification["metadata"]["provider_message_id"] == message_id


def test_email_notifier_rejects_invalid_or_conflicting_message_identity(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ADMIN_NOTIFICATION_EMAILS", "owner@example.com")
    monkeypatch.setenv("EMAIL_FROM", "ops@example.com")
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    notifier = EmailNotifier(storage_dir=str(tmp_path))

    with pytest.raises(ValueError, match="must be one Message-ID"):
        notifier.notify(
            subject="Work completed",
            body="Verified",
            provider_message_id="<one@example.com> <two@example.com>",
        )
    with pytest.raises(ValueError, match="conflicts"):
        notifier.notify(
            subject="Work completed",
            body="Verified",
            metadata={"provider_message_id": "<other@example.com>"},
            provider_message_id="<effect@example.com>",
        )
    assert list((tmp_path / "notifications").iterdir()) == []


def test_imap_reader_fetches_exact_message_id_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = EmailMessage()
    message_id = "<volpred-effect.test@operations.volpred.local>"
    raw["Message-ID"] = message_id
    raw["Subject"] = "Work completed"
    raw["To"] = "owner@example.com"
    raw.set_content("Verified")
    raw_bytes = raw.as_bytes()
    instances = []

    class FakeImap:
        def __init__(
            self,
            host: str,
            port: int,
            *,
            timeout: float,
        ) -> None:
            self.calls: list[tuple[object, ...]] = []
            self.calls.append(("connect", host, port, timeout))
            instances.append(self)

        def login(self, username: str, password: str):
            self.calls.append(("login", username, password))
            return "OK", [b""]

        def select(self, mailbox: str, readonly: bool):
            self.calls.append(("select", mailbox, readonly))
            return "OK", [b"1"]

        def uid(self, command: str, *args: object):
            self.calls.append(("uid", command, *args))
            if command == "search":
                return "OK", [b"42"]
            return "OK", [(b"42 (RFC822 {123})", raw_bytes), b")"]

        def logout(self):
            self.calls.append(("logout",))
            return "BYE", [b""]

    monkeypatch.setattr(_email_notification.imaplib, "IMAP4_SSL", FakeImap)
    reader = ImapSentMailReader(
        host="imap.example.com",
        port=993,
        username="ops@example.com",
        password="secret",
        mailbox="Sent",
        timeout_seconds=12,
    )

    assert reader.read(message_id) == raw_bytes
    assert instances
    calls = instances[0].calls
    assert (
        "uid",
        "search",
        None,
        "HEADER",
        "Message-ID",
        message_id,
    ) in calls
    assert ("uid", "fetch", b"42", "(RFC822)") in calls
    assert calls[-1] == ("logout",)
