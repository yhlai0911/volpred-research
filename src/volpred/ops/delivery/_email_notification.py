"""Read-back-verified adapter for one safe email notification effect.

The adapter is deliberately narrow: it accepts only
``email.notification.send`` with a single recipient and a matching
``email.sent-mail.readback`` expectation.  SMTP acceptance is not success.
The exact message must be independently readable from the configured Sent
mailbox before an ``AcknowledgedEffect`` can be returned.
"""

from __future__ import annotations

import hashlib
import imaplib
import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from email.message import Message
from email.parser import BytesParser
from email.policy import default
from email.utils import getaddresses, parseaddr
from typing import Any, Protocol

from volpred.ops.diagnostics import warn

from ._effect import (
    AcknowledgedEffect,
    AcknowledgementExpectation,
    EffectAttemptOutcome,
    EffectView,
    FailedEffect,
)

_PAYLOAD_SCHEMA = "email-notification.v1"
_EFFECT_KIND = "email.notification.send"
_ACKNOWLEDGEMENT_KIND = "email.sent-mail.readback"
_TARGET_PREFIX = "email:"
_MESSAGE_ID = re.compile(r"<[^<>\s@]+@[^<>\s@]+>")
_IMAP_LIST = re.compile(
    rb'^\((?P<flags>[^)]*)\)\s+(?:NIL|"(?:\\.|[^"])*")\s+'
    rb"(?P<mailbox>.+)$",
    re.IGNORECASE,
)
_PAYLOAD_FIELDS = frozenset(
    {"schema_version", "subject", "text_body", "html_body"}
)


class _EmailNotifier(Protocol):
    def notify(
        self,
        subject: str,
        body: str,
        *,
        level: str,
        metadata: dict[str, Any],
        html_body: str | None,
        recipients: list[str],
        provider_message_id: str,
    ) -> str: ...


class SentMailReader(Protocol):
    """True-external read port used after the SMTP write."""

    def read(self, message_id: str) -> bytes | None: ...


@dataclass(frozen=True)
class _EmailPayload:
    subject: str
    text_body: str
    html_body: str | None


class ImapSentMailReader:
    """Production adapter for exact Message-ID read-back over IMAP."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        mailbox: str | None,
        timeout_seconds: float,
    ) -> None:
        if not host.strip() or not username.strip() or not password:
            raise ValueError("IMAP sent-mail credentials are required")
        if isinstance(port, bool) or port <= 0:
            raise ValueError("IMAP port must be positive")
        if timeout_seconds <= 0:
            raise ValueError("IMAP timeout must be positive")
        self._host = host.strip()
        self._port = port
        self._username = username.strip()
        self._password = password
        self._mailbox = mailbox.strip() if mailbox else None
        self._timeout_seconds = timeout_seconds

    @classmethod
    def from_environment(cls) -> ImapSentMailReader:
        """Build the Gmail-shaped production adapter from existing ops env."""

        username = os.environ.get("SMTP_USERNAME", "")
        password = os.environ.get("SMTP_PASSWORD", "")
        return cls(
            host=os.environ.get("IMAP_HOST", "imap.gmail.com"),
            port=int(os.environ.get("IMAP_PORT", "993")),
            username=username,
            password=password,
            mailbox=os.environ.get("IMAP_SENT_MAILBOX") or None,
            timeout_seconds=float(
                os.environ.get("GMAIL_POLL_IMAP_TIMEOUT_SEC", "45")
            ),
        )

    def read(self, message_id: str) -> bytes | None:
        if _MESSAGE_ID.fullmatch(message_id) is None:
            raise ValueError("invalid provider Message-ID")
        connection = imaplib.IMAP4_SSL(
            self._host,
            self._port,
            timeout=self._timeout_seconds,
        )
        try:
            status, _ = connection.login(self._username, self._password)
            if status != "OK":
                raise RuntimeError("IMAP login failed")
            mailbox = (
                _imap_mailbox(self._mailbox)
                if self._mailbox is not None
                else _discover_sent_mailbox(connection)
            )
            status, _ = connection.select(mailbox, readonly=True)
            if status != "OK":
                raise RuntimeError("IMAP sent mailbox selection failed")
            status, search_data = connection.uid(
                "search",
                None,
                "HEADER",
                "Message-ID",
                message_id,
            )
            if status != "OK":
                raise RuntimeError("IMAP sent-mail search failed")
            identifiers = (
                search_data[0].split()
                if search_data and search_data[0]
                else []
            )
            for identifier in reversed(identifiers):
                status, fetched = connection.uid(
                    "fetch",
                    identifier,
                    "(RFC822)",
                )
                if status != "OK":
                    raise RuntimeError("IMAP sent-mail fetch failed")
                for item in fetched or ():
                    if not (
                        isinstance(item, tuple)
                        and len(item) >= 2
                        and isinstance(item[1], bytes)
                    ):
                        continue
                    raw = item[1]
                    parsed = BytesParser(policy=default).parsebytes(raw)
                    if str(parsed.get("Message-ID") or "").strip() == message_id:
                        return raw
            return None
        finally:
            try:
                connection.logout()
            except (OSError, imaplib.IMAP4.error) as error:
                warn(
                    "email_notification",
                    "IMAP logout failed after sent-mail read-back",
                    err=error,
                )


def _imap_mailbox(value: str) -> str:
    """Encode one configured mailbox as an IMAP quoted-string."""

    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _discover_sent_mailbox(connection: imaplib.IMAP4_SSL) -> str:
    """Return the server-advertised RFC 6154 ``\\Sent`` mailbox argument."""

    status, entries = connection.list()
    if status != "OK":
        raise RuntimeError("IMAP mailbox discovery failed")
    for raw in entries or ():
        if not isinstance(raw, bytes):
            continue
        matched = _IMAP_LIST.fullmatch(raw)
        if matched is None:
            continue
        flags = {flag.lower() for flag in matched.group("flags").split()}
        if b"\\sent" not in flags:
            continue
        mailbox = matched.group("mailbox").decode("ascii")
        return (
            mailbox
            if mailbox.startswith('"')
            else _imap_mailbox(mailbox)
        )
    raise RuntimeError("IMAP server did not advertise a Sent mailbox")


class EmailNotificationEffectAdapter:
    """Deliver one safe email effect and require independent Sent read-back."""

    def __init__(
        self,
        *,
        notifier: _EmailNotifier,
        sent_mail_reader: SentMailReader,
    ) -> None:
        self._notifier = notifier
        self._sent_mail_reader = sent_mail_reader

    @staticmethod
    def message_id_for(effect: EffectView) -> str:
        identity = hashlib.sha256(
            (
                f"{effect.id}\0{effect.request_sha256}\0"
                f"{effect.payload_sha256}"
            ).encode()
        ).hexdigest()
        return f"<volpred-effect.{identity}@operations.volpred.local>"

    def deliver(
        self,
        effect: EffectView,
        payload: bytes,
    ) -> EffectAttemptOutcome:
        if not isinstance(payload, bytes):
            return _failure(
                effect,
                "invalid_email_notification_payload",
                retryable=False,
            )
        payload_sha256 = hashlib.sha256(payload).hexdigest()
        if payload_sha256 != effect.payload_sha256:
            return _failure(
                effect,
                "email_payload_hash_mismatch",
                retryable=False,
            )
        recipient = _contract_recipient(effect)
        if recipient is None:
            return _failure(
                effect,
                "unsupported_email_effect_contract",
                retryable=False,
            )
        try:
            decoded = _decode_payload(payload)
        except (UnicodeError, ValueError, json.JSONDecodeError):
            return _failure(
                effect,
                "invalid_email_notification_payload",
                retryable=False,
            )

        message_id = self.message_id_for(effect)
        try:
            existing = self._sent_mail_reader.read(message_id)
        except Exception:
            return _failure(
                effect,
                "email_provider_error",
                retryable=True,
            )
        if existing is not None:
            return _readback_outcome(
                effect=effect,
                payload=decoded,
                recipient=recipient,
                message_id=message_id,
                raw_message=existing,
            )

        try:
            self._notifier.notify(
                subject=decoded.subject,
                body=decoded.text_body,
                html_body=decoded.html_body,
                level="info",
                metadata={
                    "notification_type": "effect_delivery",
                    "effect_id": effect.id,
                    "work_item_id": effect.work_item_id,
                    "payload_ref": effect.payload_ref,
                    "payload_sha256": effect.payload_sha256,
                },
                recipients=[recipient],
                provider_message_id=message_id,
            )
            readback = self._sent_mail_reader.read(message_id)
        except Exception:
            return _failure(
                effect,
                "email_provider_error",
                retryable=True,
            )
        if readback is None:
            return _failure(
                effect,
                "email_sent_mail_readback_missing",
                retryable=True,
            )
        return _readback_outcome(
            effect=effect,
            payload=decoded,
            recipient=recipient,
            message_id=message_id,
            raw_message=readback,
        )


def _contract_recipient(effect: EffectView) -> str | None:
    acknowledgement = effect.acknowledgement
    if (
        effect.schema_version != "effect-request.v1"
        or effect.effect_kind != _EFFECT_KIND
        or effect.risk != "safe"
        or not effect.target_ref.startswith(_TARGET_PREFIX)
        or acknowledgement.kind != _ACKNOWLEDGEMENT_KIND
        or acknowledgement.target_ref != effect.target_ref
    ):
        return None
    recipient = effect.target_ref.removeprefix(_TARGET_PREFIX).strip()
    display_name, parsed = parseaddr(recipient)
    if (
        display_name
        or parsed != recipient
        or recipient.count("@") != 1
        or any(character in recipient for character in "\r\n,;")
    ):
        return None
    local_part, domain = recipient.rsplit("@", 1)
    if not local_part or not domain or "." not in domain:
        return None
    return recipient


def _decode_payload(payload: bytes) -> _EmailPayload:
    decoded = json.loads(payload.decode("utf-8"))
    if not isinstance(decoded, Mapping):
        raise ValueError("email notification payload must be an object")
    if set(decoded) != _PAYLOAD_FIELDS:
        raise ValueError("email notification payload fields do not match schema")
    if decoded.get("schema_version") != _PAYLOAD_SCHEMA:
        raise ValueError("unsupported email notification payload schema")
    subject = _required_payload_text(decoded.get("subject"), field="subject")
    if "\r" in subject or "\n" in subject:
        raise ValueError("email subject cannot contain line breaks")
    text_body = _required_payload_text(
        decoded.get("text_body"),
        field="text_body",
    )
    html_value = decoded.get("html_body")
    if html_value is not None and not isinstance(html_value, str):
        raise ValueError("html_body must be text or null")
    html_body = html_value if html_value else None
    return _EmailPayload(
        subject=subject,
        text_body=text_body,
        html_body=html_body,
    )


def _required_payload_text(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    return value


def _message_body(message: Message, content_type: str) -> str | None:
    for part in message.walk():
        if (
            part.get_content_type() == content_type
            and part.get_content_disposition() != "attachment"
        ):
            content = part.get_content()
            return content if isinstance(content, str) else None
    return None


def _transport_text(value: str | None) -> str | None:
    if value is None:
        return None
    return value.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")


def _readback_outcome(
    *,
    effect: EffectView,
    payload: _EmailPayload,
    recipient: str,
    message_id: str,
    raw_message: bytes,
) -> EffectAttemptOutcome:
    try:
        message = BytesParser(policy=default).parsebytes(raw_message)
        recipients = {
            address.casefold()
            for _, address in getaddresses(message.get_all("To", []))
            if address
        }
        exact = (
            str(message.get("Message-ID") or "").strip() == message_id
            and str(message.get("Subject") or "") == payload.subject
            and recipients == {recipient.casefold()}
            and _transport_text(_message_body(message, "text/plain"))
            == _transport_text(payload.text_body)
            and _transport_text(_message_body(message, "text/html"))
            == _transport_text(payload.html_body)
        )
    except Exception:
        exact = False
    if not exact:
        return _failure(
            effect,
            "email_sent_mail_readback_mismatch",
            retryable=False,
        )
    evidence_sha256 = hashlib.sha256(raw_message).hexdigest()
    message_ref = hashlib.sha256(message_id.encode("ascii")).hexdigest()
    return AcknowledgedEffect(
        acknowledgement=AcknowledgementExpectation(
            kind=_ACKNOWLEDGEMENT_KIND,
            target_ref=effect.target_ref,
        ),
        evidence_ref=f"email:sent-mail:{message_ref}",
        evidence_sha256=evidence_sha256,
    )


def _failure(
    effect: EffectView,
    reason_code: str,
    *,
    retryable: bool,
) -> FailedEffect:
    evidence = json.dumps(
        {
            "effect_id": effect.id,
            "request_sha256": effect.request_sha256,
            "reason_code": reason_code,
            "retryable": retryable,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return FailedEffect(
        reason_code=reason_code,
        evidence_ref=f"effect-attempt:{effect.id}:{reason_code}",
        evidence_sha256=hashlib.sha256(evidence).hexdigest(),
        retryable=retryable,
    )


__all__ = [
    "EmailNotificationEffectAdapter",
    "ImapSentMailReader",
    "SentMailReader",
]
