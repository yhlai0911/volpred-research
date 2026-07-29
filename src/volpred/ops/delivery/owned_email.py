"""Production ownership transaction for one safe ops-alert email.

The external interface is deliberately small: one call owns durable WorkItem
creation, immutable payload storage, EffectRequest/outbox creation, the
fenced provider attempt, settlement, and WorkItem completion.  PostgreSQL
keeps the cross-host owner generation; the caller never assembles those
mutations itself.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol
from urllib import error, request
from uuid import uuid4

from volpred.ops.authority import (
    FORMAL_PRIMARY_AUTHORITY_KEY,
    PrimaryLease,
)

from ._effect import (
    AcknowledgedEffect,
    AcknowledgementExpectation,
    EffectAttemptOutcome,
    EffectView,
    FailedEffect,
)

_OWNER_FAMILY = "email.ops_alert"
_PRIMARY_AUTHORITY_KEY = FORMAL_PRIMARY_AUTHORITY_KEY
_OPERATIONS_CORE_OWNER = "operations_core"
_LEGACY_OWNER = "legacy"
_READ_ONLY_RPCS = frozenset(
    {
        "volpred_read_notification_owner",
        "volpred_read_owned_email_request",
    }
)


def _remote_mutations_disabled() -> bool:
    return (
        os.environ.get("VOLPRED_NO_REMOTE_WRITE") == "1"
        or "PYTEST_CURRENT_TEST" in os.environ
        or "PYTEST_VERSION" in os.environ
    )


class NotificationOwnershipLost(RuntimeError):
    """The caller no longer owns the notification family generation."""


class OwnedEmailCommandConflict(RuntimeError):
    """The same idempotency key was reused for a different immutable command."""


@dataclass(frozen=True)
class NotificationOwner:
    schema_version: str
    effect_family: str
    owner: str
    generation: int
    changed_at: str
    changed_by: str
    change_reason: str


@dataclass(frozen=True)
class OwnedEmailCommand:
    idempotency_key: str
    level: str
    title: str
    recipient: str
    text_body: str
    html_body: str | None
    actor_ref: str


@dataclass(frozen=True)
class OwnedEmailRequest:
    owner_generation: int
    work_id: str
    effect_id: str
    request_sha256: str
    terminal_receipt: OwnedEmailReceipt | None = None


@dataclass(frozen=True)
class OwnedEmailExistingRequest:
    command: OwnedEmailCommand
    request: OwnedEmailRequest


@dataclass(frozen=True)
class OwnedEmailAttempt:
    owner_generation: int
    work_id: str
    work_version: int
    work_lease_token: str
    effect: EffectView
    payload: bytes
    outbox_sequence: int
    attempt_count: int
    outbox_claim_token: str
    worker_id: str
    primary_authority_key: str
    primary_authority_holder_ref: str
    primary_authority_epoch: int
    primary_fencing_token: str
    authority_request_sha256: str
    outbox_claim_ref: str
    primary_authority_ref: str
    lease_expires_at: str


@dataclass(frozen=True)
class OwnedEmailReceipt:
    schema_version: str
    owner_generation: int
    work_id: str
    work_status: str
    effect_id: str
    effect_status: str
    attempt_count: int
    disposition: str
    evidence_ref: str
    evidence_sha256: str
    primary_authority_ref: str
    recorded_at: str

    @property
    def delivered(self) -> bool:
        return (
            self.work_status == "succeeded"
            and self.effect_status == "delivered"
            and self.disposition == "delivered"
        )


@dataclass(frozen=True)
class OwnedEmailRecoverySummary:
    recovered_count: int
    delivered_count: int
    stale_count: int
    retry_scheduled_count: int
    receipts: tuple[OwnedEmailReceipt, ...]


class _OwnedEmailStore(Protocol):
    def read_owner(self) -> NotificationOwner: ...

    def read_request(
        self,
        idempotency_key: str,
    ) -> OwnedEmailExistingRequest | None: ...

    def request(
        self,
        command: OwnedEmailCommand,
        *,
        owner_generation: int,
    ) -> OwnedEmailRequest: ...

    def begin(
        self,
        request_view: OwnedEmailRequest,
        *,
        worker_id: str,
        lease_seconds: int,
        work_lease_token: str,
        outbox_claim_token: str,
        primary_fencing_token: str,
    ) -> OwnedEmailAttempt: ...

    def recover_expired(
        self,
        *,
        owner_generation: int,
        worker_id: str,
        lease_seconds: int,
        work_lease_token: str,
        outbox_claim_token: str,
        primary_fencing_token: str,
    ) -> OwnedEmailAttempt | None: ...

    def settle(
        self,
        attempt: OwnedEmailAttempt,
        outcome: EffectAttemptOutcome,
    ) -> OwnedEmailReceipt: ...


class _OwnedEmailProvider(Protocol):
    def deliver(
        self,
        effect: EffectView,
        payload: bytes,
        *,
        authorize_mutation: Callable[[], object],
    ) -> EffectAttemptOutcome: ...


class _PrimaryLeaseGate(Protocol):
    """Expose the host lease only while its keepalive is healthy."""

    def current_lease(self) -> PrimaryLease: ...


class _OwnedEmailExecutionContext:
    """Share the owner, token, and Primary Authority fence contract."""

    def __init__(
        self,
        *,
        store: _OwnedEmailStore,
        primary_authority: _PrimaryLeaseGate,
        worker_id: str,
        lease_seconds: int,
        token_factory: Callable[[], str] | None,
        token_prefix: str,
        operation_label: str,
    ) -> None:
        if not worker_id.strip():
            raise ValueError(
                f"owned email {operation_label} worker_id is required"
            )
        if isinstance(lease_seconds, bool) or lease_seconds <= 0:
            raise ValueError(
                f"owned email {operation_label} lease_seconds must be positive"
            )
        self._store = store
        self._primary_authority = primary_authority
        self.worker_id = worker_id.strip()
        self.lease_seconds = lease_seconds
        self._token_factory = token_factory or (
            lambda: f"{token_prefix}_{uuid4().hex}"
        )
        self._operation_label = operation_label

    def begin_owner_session(
        self,
    ) -> tuple[NotificationOwner, PrimaryLease]:
        primary_lease = self.current_lease()
        owner = self._store.read_owner()
        if (
            owner.effect_family != _OWNER_FAMILY
            or owner.owner != _OPERATIONS_CORE_OWNER
        ):
            raise NotificationOwnershipLost(
                "operations core does not own email.ops_alert"
            )
        return owner, primary_lease

    def token(self, kind: str) -> str:
        token = self._token_factory()
        if not isinstance(token, str) or not token.strip():
            raise ValueError(
                f"owned email {self._operation_label} {kind} token is required"
            )
        return token.strip()

    def current_lease(
        self,
        *,
        expected: PrimaryLease | None = None,
    ) -> PrimaryLease:
        lease = self._primary_authority.current_lease()
        if not isinstance(lease, PrimaryLease):
            raise TypeError(
                f"owned email {self._operation_label} keepalive returned no "
                "typed PrimaryLease"
            )
        if (
            lease.authority_key != _PRIMARY_AUTHORITY_KEY
            or lease.holder_ref != self.worker_id
        ):
            raise NotificationOwnershipLost(
                f"owned email {self._operation_label} keepalive lease "
                "identity mismatch"
            )
        if expected is not None and (
            lease.authority_key != expected.authority_key
            or lease.holder_ref != expected.holder_ref
            or lease.epoch != expected.epoch
            or lease.fencing_token != expected.fencing_token
            or lease.acquired_at != expected.acquired_at
        ):
            raise NotificationOwnershipLost(
                f"owned email {self._operation_label} keepalive lease was "
                "replaced"
            )
        return lease

    @staticmethod
    def validate_attempt(
        attempt: OwnedEmailAttempt,
        *,
        primary_lease: PrimaryLease,
    ) -> None:
        if (
            attempt.primary_authority_key
            != primary_lease.authority_key
            or attempt.primary_authority_holder_ref
            != primary_lease.holder_ref
            or attempt.primary_authority_epoch != primary_lease.epoch
            or attempt.primary_fencing_token
            != primary_lease.fencing_token
        ):
            raise NotificationOwnershipLost(
                "owned email begin used a different Primary Authority lease"
            )


class OwnedEmailNotification:
    """Deliver one ops-alert email through the current durable owner."""

    def __init__(
        self,
        *,
        store: _OwnedEmailStore,
        provider: _OwnedEmailProvider,
        primary_authority: _PrimaryLeaseGate,
        worker_id: str = "effect-worker:ops-alert-email",
        lease_seconds: int = 300,
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        self._store = store
        self._provider = provider
        self._execution = _OwnedEmailExecutionContext(
            store=store,
            primary_authority=primary_authority,
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            token_factory=token_factory,
            token_prefix="owned_email",
            operation_label="delivery",
        )

    def deliver(self, command: OwnedEmailCommand) -> OwnedEmailReceipt:
        normalized = _normalize_command(command)
        owner, primary_lease = self._execution.begin_owner_session()
        request_view = self._store.request(
            normalized,
            owner_generation=owner.generation,
        )
        if request_view.terminal_receipt is not None:
            self._validate_terminal_receipt(request_view)
            return request_view.terminal_receipt
        primary_lease = self._execution.current_lease(
            expected=primary_lease,
        )
        attempt = self._store.begin(
            request_view,
            worker_id=self._execution.worker_id,
            lease_seconds=self._execution.lease_seconds,
            work_lease_token=self._execution.token("work"),
            outbox_claim_token=self._execution.token("outbox"),
            primary_fencing_token=primary_lease.fencing_token,
        )
        self._execution.validate_attempt(
            attempt,
            primary_lease=primary_lease,
        )
        self._execution.current_lease(expected=primary_lease)
        outcome = self._provider.deliver(
            attempt.effect,
            attempt.payload,
            authorize_mutation=lambda: self._execution.current_lease(
                expected=primary_lease,
            ),
        )
        return self._store.settle(attempt, outcome)

    @staticmethod
    def _validate_terminal_receipt(
        request_view: OwnedEmailRequest,
    ) -> None:
        receipt = request_view.terminal_receipt
        if receipt is None:
            raise AssertionError("terminal receipt is required")
        if (
            receipt.owner_generation != request_view.owner_generation
            or receipt.work_id != request_view.work_id
            or receipt.effect_id != request_view.effect_id
        ):
            raise RuntimeError(
                "owned email terminal receipt identity drifted"
            )
        valid_terminal = (
            receipt.work_status == "succeeded"
            and receipt.effect_status == "delivered"
            and receipt.disposition == "delivered"
        ) or (
            receipt.work_status == "failed"
            and receipt.effect_status == "dead_lettered"
            and receipt.disposition == "dead_lettered"
        )
        if not valid_terminal:
            raise RuntimeError(
                "owned email request returned a non-terminal receipt"
            )


class OwnedEmailRecovery:
    """Recover process-interrupted ops-alert deliveries through one fence."""

    def __init__(
        self,
        *,
        store: _OwnedEmailStore,
        provider: _OwnedEmailProvider,
        primary_authority: _PrimaryLeaseGate,
        worker_id: str = "effect-worker:ops-alert-email",
        lease_seconds: int = 300,
        max_age_seconds: int = 3600,
        token_factory: Callable[[], str] | None = None,
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        if isinstance(max_age_seconds, bool) or max_age_seconds <= 0:
            raise ValueError(
                "owned email recovery max_age_seconds must be positive"
            )
        self._store = store
        self._provider = provider
        self._max_age_seconds = max_age_seconds
        self._execution = _OwnedEmailExecutionContext(
            store=store,
            primary_authority=primary_authority,
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            token_factory=token_factory,
            token_prefix="owned_email_recovery",
            operation_label="recovery",
        )
        self._now_factory = now_factory or (
            lambda: datetime.now(timezone.utc)
        )

    def recover(self, *, limit: int = 10) -> OwnedEmailRecoverySummary:
        if isinstance(limit, bool) or limit <= 0:
            raise ValueError("owned email recovery limit must be positive")
        owner, primary_lease = self._execution.begin_owner_session()

        receipts: list[OwnedEmailReceipt] = []
        stale_count = 0
        for _ in range(limit):
            primary_lease = self._execution.current_lease(
                expected=primary_lease,
            )
            attempt = self._store.recover_expired(
                owner_generation=owner.generation,
                worker_id=self._execution.worker_id,
                lease_seconds=self._execution.lease_seconds,
                work_lease_token=self._execution.token("work"),
                outbox_claim_token=self._execution.token("outbox"),
                primary_fencing_token=primary_lease.fencing_token,
            )
            if attempt is None:
                break
            self._execution.validate_attempt(
                attempt,
                primary_lease=primary_lease,
            )
            self._execution.current_lease(expected=primary_lease)
            if self._is_stale(attempt):
                outcome = _stale_recovery_outcome(attempt.effect)
                stale_count += 1
            else:
                outcome = self._provider.deliver(
                    attempt.effect,
                    attempt.payload,
                    authorize_mutation=lambda: self._execution.current_lease(
                        expected=primary_lease,
                    ),
                )
            receipts.append(self._store.settle(attempt, outcome))

        return OwnedEmailRecoverySummary(
            recovered_count=len(receipts),
            delivered_count=sum(
                receipt.delivered for receipt in receipts
            ),
            stale_count=stale_count,
            retry_scheduled_count=sum(
                receipt.disposition == "retry_scheduled"
                for receipt in receipts
            ),
            receipts=tuple(receipts),
        )

    def _is_stale(self, attempt: OwnedEmailAttempt) -> bool:
        created_at = _utc_datetime(
            attempt.effect.created_at,
            field="effect created_at",
        )
        now = self._now_factory()
        if not isinstance(now, datetime) or now.tzinfo is None:
            raise ValueError(
                "owned email recovery now_factory must return aware datetime"
            )
        return (
            now.astimezone(timezone.utc) - created_at
        ).total_seconds() > self._max_age_seconds


def dispatch_email_by_current_owner(
    command: OwnedEmailCommand,
    *,
    storage_dir: str,
) -> dict[str, Any]:
    """Route one ops email through the durable owner generation.

    Operations Core owns the normal production path and therefore requires
    WorkItem/EffectRequest/outbox creation, Primary Authority fencing, exact
    Sent-mail read-back, and typed settlement. The direct notifier is retained
    solely as the database-controlled ``legacy`` rollback path; an unavailable
    or invalid owner read fails before either provider is constructed.
    """

    normalized = _normalize_command(command)
    store = SupabaseOwnedEmailStore.from_environment()
    existing = store.read_request(normalized.idempotency_key)
    if existing is not None and existing.command != normalized:
        raise OwnedEmailCommandConflict(
            "owned email idempotency key conflicts with durable command"
        )
    owner = store.read_owner()
    if owner.effect_family != _OWNER_FAMILY:
        raise RuntimeError(
            "notification owner read returned the wrong effect family"
        )
    if (
        existing is not None
        and existing.request.terminal_receipt is not None
    ):
        OwnedEmailNotification._validate_terminal_receipt(
            existing.request
        )
        return _receipt_result(
            existing.request.terminal_receipt,
            subject=normalized.title,
            delivery_owner=_OPERATIONS_CORE_OWNER,
        )
    if existing is not None and owner.owner == _LEGACY_OWNER:
        raise RuntimeError(
            "legacy delivery cannot supersede an existing Operations Core "
            "owned-email request"
        )

    if owner.owner == _OPERATIONS_CORE_OWNER:
        from volpred.ops.authority import (
            build_supabase_host_authority_keepalive,
        )
        from volpred.publisher.email_notifier import EmailNotifier

        from ._email_notification import (
            EmailNotificationEffectAdapter,
            ImapSentMailReader,
        )

        # Intake is durable before this short-lived caller contends for the
        # host-wide Primary Authority. A concurrent effect holder is normal;
        # losing the notification before it reaches WorkItem/outbox is not.
        request_view = (
            existing.request
            if existing is not None
            else store.request(
                normalized,
                owner_generation=owner.generation,
            )
        )
        if request_view.terminal_receipt is not None:
            OwnedEmailNotification._validate_terminal_receipt(request_view)
            return _receipt_result(
                request_view.terminal_receipt,
                subject=normalized.title,
                delivery_owner=owner.owner,
            )

        worker_id = "effect-worker:ops-alert-email"
        keepalive = build_supabase_host_authority_keepalive(
            holder_ref=worker_id,
        )
        try:
            keepalive.start()
        except ValueError as exc:
            if not str(exc).startswith(
                "Primary Authority is already held:"
            ):
                raise
            return _pending_request_result(
                request_view,
                subject=normalized.title,
                delivery_owner=owner.owner,
                reason="primary_authority_busy",
            )
        try:
            notifier = EmailNotifier(storage_dir=storage_dir)
            receipt = OwnedEmailNotification(
                store=store,
                provider=EmailNotificationEffectAdapter(
                    notifier=notifier,
                    sent_mail_reader=ImapSentMailReader.from_environment(),
                ),
                primary_authority=keepalive,
                worker_id=worker_id,
            ).deliver(normalized)
        finally:
            keepalive.stop()
        return _receipt_result(
            receipt,
            subject=normalized.title,
            delivery_owner=owner.owner,
        )

    if owner.owner != _LEGACY_OWNER:
        raise RuntimeError(
            f"unsupported notification owner: {owner.owner}"
        )
    from volpred.ops.authority import (
        build_supabase_host_authority_keepalive,
    )
    from volpred.publisher.email_notifier import EmailNotifier

    from ._email_notification import (
        EmailNotificationEffectAdapter,
        ImapSentMailReader,
    )

    effect, payload_bytes = _legacy_effect_contract(normalized)
    worker_id = "effect-worker:ops-alert-email-legacy"
    keepalive = build_supabase_host_authority_keepalive(
        holder_ref=worker_id,
    )
    execution = _OwnedEmailExecutionContext(
        store=store,
        primary_authority=keepalive,
        worker_id=worker_id,
        lease_seconds=300,
        token_factory=None,
        token_prefix="legacy_owned_email",
        operation_label="legacy delivery",
    )
    keepalive.start()
    try:
        primary_lease = execution.current_lease()
        fenced_existing = store.read_request(
            normalized.idempotency_key
        )
        if (
            fenced_existing is not None
            and fenced_existing.command != normalized
        ):
            raise OwnedEmailCommandConflict(
                "owned email idempotency key conflicts with durable command"
            )
        fenced_owner = store.read_owner()
        if (
            fenced_owner.effect_family != _OWNER_FAMILY
            or fenced_owner.owner != _LEGACY_OWNER
            or fenced_owner.generation != owner.generation
        ):
            raise NotificationOwnershipLost(
                "legacy email ownership changed after Primary Authority fence"
            )
        if fenced_existing is not None:
            terminal = fenced_existing.request.terminal_receipt
            if terminal is None:
                raise RuntimeError(
                    "legacy delivery cannot supersede a pending "
                    "Operations Core owned-email request"
                )
            OwnedEmailNotification._validate_terminal_receipt(
                fenced_existing.request
            )
            return _receipt_result(
                terminal,
                subject=normalized.title,
                delivery_owner=_OPERATIONS_CORE_OWNER,
            )
        outcome = EmailNotificationEffectAdapter(
            notifier=EmailNotifier(storage_dir=storage_dir),
            sent_mail_reader=ImapSentMailReader.from_environment(),
        ).deliver(
            effect,
            payload_bytes,
            authorize_mutation=lambda: execution.current_lease(
                expected=primary_lease,
            ),
        )
        execution.current_lease(expected=primary_lease)
    finally:
        keepalive.stop()
    sent = isinstance(outcome, AcknowledgedEffect)
    return {
        "notification_id": effect.id,
        "subject": normalized.title,
        "sent": sent,
        "configured": True,
        "send_error": (
            None if sent else outcome.reason_code
        ),
        "delivery_owner": owner.owner,
        "owner_generation": owner.generation,
        "work_id": None,
        "effect_status": (
            "legacy_sent_verified" if sent else "legacy_failed"
        ),
        "attempt_count": 1,
        "evidence_ref": outcome.evidence_ref,
        "evidence_sha256": outcome.evidence_sha256,
    }


def read_existing_owned_email_request(
    idempotency_key: str,
) -> OwnedEmailExistingRequest | None:
    """Read the immutable cross-host command/receipt for one delivery key."""

    return SupabaseOwnedEmailStore.from_environment().read_request(
        _required_text(
            idempotency_key,
            field="owned email idempotency_key",
        )
    )


def _receipt_result(
    receipt: OwnedEmailReceipt,
    *,
    subject: str,
    delivery_owner: str,
) -> dict[str, Any]:
    return {
        "notification_id": receipt.effect_id,
        "subject": subject,
        "sent": receipt.delivered,
        "configured": True,
        "send_error": (
            None if receipt.delivered else receipt.disposition
        ),
        "delivery_owner": delivery_owner,
        "owner_generation": receipt.owner_generation,
        "work_id": receipt.work_id,
        "effect_status": receipt.effect_status,
        "attempt_count": receipt.attempt_count,
        "evidence_ref": receipt.evidence_ref,
        "evidence_sha256": receipt.evidence_sha256,
    }


def _pending_request_result(
    request_view: OwnedEmailRequest,
    *,
    subject: str,
    delivery_owner: str,
    reason: str,
) -> dict[str, Any]:
    """Return durable queue acceptance without claiming provider delivery."""
    return {
        "notification_id": request_view.effect_id,
        "subject": subject,
        "sent": False,
        "configured": True,
        "send_error": reason,
        "delivery_owner": delivery_owner,
        "owner_generation": request_view.owner_generation,
        "work_id": request_view.work_id,
        "effect_status": "pending",
        "attempt_count": 0,
        "evidence_ref": (
            f"owned-email-request:{request_view.request_sha256}"
        ),
        "evidence_sha256": request_view.request_sha256,
    }


def _legacy_effect_contract(
    command: OwnedEmailCommand,
) -> tuple[EffectView, bytes]:
    payload = json.dumps(
        {
            "schema_version": "email-notification.v1",
            "subject": command.title,
            "text_body": command.text_body,
            "html_body": command.html_body,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    request_identity = json.dumps(
        {
            "schema_version": "legacy-owned-email.v1",
            "idempotency_key": command.idempotency_key,
            "level": command.level,
            "title": command.title,
            "recipient": command.recipient,
            "text_body": command.text_body,
            "html_body": command.html_body,
            "actor_ref": command.actor_ref,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    request_sha256 = hashlib.sha256(request_identity).hexdigest()
    identity = request_sha256[:32]
    target_ref = f"email:{command.recipient}"
    return (
        EffectView(
            schema_version="effect-request.v1",
            id=f"effect_legacy_owned_email_{identity}",
            idempotency_key=command.idempotency_key,
            work_item_id=f"work_legacy_owned_email_{identity}",
            work_item_version=1,
            effect_kind="email.notification.send",
            target_ref=target_ref,
            payload_ref=f"legacy-owned-email:{identity}",
            payload_sha256=hashlib.sha256(payload).hexdigest(),
            risk="safe",
            acknowledgement=AcknowledgementExpectation(
                kind="email.sent-mail.readback",
                target_ref=target_ref,
            ),
            requester_ref=command.actor_ref,
            request_sha256=request_sha256,
            status="requested",
            created_at=datetime.now(timezone.utc).isoformat(),
        ),
        payload,
    )


class SupabaseOwnedEmailStore:
    """Service-role-only PostgREST adapter for the ownership RPCs."""

    def __init__(
        self,
        *,
        supabase_url: str,
        service_role_key: str,
        timeout_seconds: float = 45.0,
    ) -> None:
        self._url = supabase_url.strip().rstrip("/")
        self._key = service_role_key.strip()
        if not self._url or not self._key:
            raise ValueError(
                "Supabase URL and service-role key are required for "
                "notification ownership"
            )
        if timeout_seconds <= 0:
            raise ValueError("Supabase RPC timeout must be positive")
        self._timeout_seconds = timeout_seconds

    @classmethod
    def from_environment(cls) -> SupabaseOwnedEmailStore:
        values = _runtime_environment()
        return cls(
            supabase_url=values.get("SUPABASE_URL", ""),
            service_role_key=values.get("SUPABASE_SERVICE_ROLE_KEY", ""),
            timeout_seconds=float(
                values.get("VOLPRED_OPERATIONS_RPC_TIMEOUT_SEC", "45")
            ),
        )

    def read_owner(self) -> NotificationOwner:
        return _owner_from_payload(
            self._rpc("volpred_read_notification_owner", {})
        )

    def read_request(
        self,
        idempotency_key: str,
    ) -> OwnedEmailExistingRequest | None:
        payload = self._rpc_optional(
            "volpred_read_owned_email_request",
            {
                "p_idempotency_key": _required_text(
                    idempotency_key,
                    field="owned email idempotency_key",
                )
            },
        )
        if payload is None:
            return None
        if payload.get("schema_version") != "owned-email-request-read.v1":
            raise RuntimeError(
                "owned email request read schema is unsupported"
            )
        command_payload = _mapping(
            payload.get("command"),
            field="owned email request command",
        )
        if command_payload.get("schema_version") != "owned-email-command.v1":
            raise RuntimeError(
                "owned email command schema is unsupported"
            )
        request_payload = _mapping(
            payload.get("request"),
            field="owned email request view",
        )
        html_body = command_payload.get("html_body")
        if html_body is not None and not isinstance(html_body, str):
            raise RuntimeError(
                "owned email command html_body must be text or null"
            )
        return OwnedEmailExistingRequest(
            command=_normalize_command(
                OwnedEmailCommand(
                    idempotency_key=_required_text(
                        command_payload.get("idempotency_key"),
                        field="owned email idempotency_key",
                    ),
                    level=_required_text(
                        command_payload.get("level"),
                        field="owned email level",
                    ),
                    title=_required_text(
                        command_payload.get("title"),
                        field="owned email title",
                    ),
                    recipient=_required_text(
                        command_payload.get("recipient"),
                        field="owned email recipient",
                    ),
                    text_body=_required_text(
                        command_payload.get("text_body"),
                        field="owned email text_body",
                    ),
                    html_body=html_body,
                    actor_ref=_required_text(
                        command_payload.get("actor_ref"),
                        field="owned email actor_ref",
                    ),
                )
            ),
            request=_request_from_payload(request_payload),
        )

    def transfer_owner(
        self,
        *,
        expected_owner: str,
        expected_generation: int,
        target_owner: str,
        actor_ref: str,
        reason: str,
        rollback_of_generation: int | None = None,
    ) -> NotificationOwner:
        payload = self._rpc(
            "volpred_transfer_notification_owner",
            {
                "p_expected_owner": expected_owner,
                "p_expected_generation": expected_generation,
                "p_target_owner": target_owner,
                "p_actor_ref": actor_ref,
                "p_reason": reason,
                "p_rollback_of_generation": rollback_of_generation,
            },
        )
        return _owner_from_payload(payload)

    def request(
        self,
        command: OwnedEmailCommand,
        *,
        owner_generation: int,
    ) -> OwnedEmailRequest:
        payload = self._rpc(
            "volpred_request_owned_email_notification",
            {
                "p_owner_generation": owner_generation,
                "p_idempotency_key": command.idempotency_key,
                "p_level": command.level,
                "p_title": command.title,
                "p_recipient": command.recipient,
                "p_payload": {
                    "schema_version": "email-notification.v1",
                    "subject": command.title,
                    "text_body": command.text_body,
                    "html_body": command.html_body,
                },
                "p_actor_ref": command.actor_ref,
            },
        )
        return _request_from_payload(payload)

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
        payload = self._rpc(
            "volpred_begin_owned_email_notification",
            {
                "p_owner_generation": request_view.owner_generation,
                "p_effect_id": request_view.effect_id,
                "p_worker_id": worker_id,
                "p_lease_seconds": lease_seconds,
                "p_work_lease_token": work_lease_token,
                "p_outbox_claim_token": outbox_claim_token,
                "p_primary_fencing_token": primary_fencing_token,
            },
        )
        return _attempt_from_payload(
            payload,
            work_lease_token=work_lease_token,
            outbox_claim_token=outbox_claim_token,
            primary_fencing_token=primary_fencing_token,
        )

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
        payload = self._rpc(
            "volpred_recover_expired_owned_email_notification",
            {
                "p_owner_generation": owner_generation,
                "p_worker_id": worker_id,
                "p_lease_seconds": lease_seconds,
                "p_work_lease_token": work_lease_token,
                "p_outbox_claim_token": outbox_claim_token,
                "p_primary_fencing_token": primary_fencing_token,
            },
        )
        if payload.get("recovered") is False:
            return None
        if payload.get("recovered") is not True:
            raise RuntimeError(
                "owned email recovery returned invalid recovery state"
            )
        return _attempt_from_payload(
            payload,
            work_lease_token=work_lease_token,
            outbox_claim_token=outbox_claim_token,
            primary_fencing_token=primary_fencing_token,
        )

    def settle(
        self,
        attempt: OwnedEmailAttempt,
        outcome: EffectAttemptOutcome,
    ) -> OwnedEmailReceipt:
        if isinstance(outcome, AcknowledgedEffect):
            outcome_kind = "acknowledged"
            acknowledgement_kind = outcome.acknowledgement.kind
            acknowledgement_target_ref = (
                outcome.acknowledgement.target_ref
            )
            reason_code = None
        elif isinstance(outcome, FailedEffect):
            outcome_kind = (
                "retryable_failure"
                if outcome.retryable
                else "terminal_failure"
            )
            acknowledgement_kind = None
            acknowledgement_target_ref = None
            reason_code = outcome.reason_code
        else:
            raise TypeError("owned email provider returned invalid outcome")
        payload = self._rpc(
            "volpred_settle_owned_email_notification",
            {
                "p_owner_generation": attempt.owner_generation,
                "p_work_id": attempt.work_id,
                "p_work_version": attempt.work_version,
                "p_work_lease_token": attempt.work_lease_token,
                "p_effect_id": attempt.effect.id,
                "p_outbox_sequence": attempt.outbox_sequence,
                "p_attempt_count": attempt.attempt_count,
                "p_worker_id": attempt.worker_id,
                "p_outbox_claim_token": attempt.outbox_claim_token,
                "p_primary_authority_key": (
                    attempt.primary_authority_key
                ),
                "p_primary_authority_holder_ref": (
                    attempt.primary_authority_holder_ref
                ),
                "p_primary_authority_epoch": (
                    attempt.primary_authority_epoch
                ),
                "p_primary_fencing_token": attempt.primary_fencing_token,
                "p_authority_request_sha256": (
                    attempt.authority_request_sha256
                ),
                "p_outbox_claim_ref": attempt.outbox_claim_ref,
                "p_primary_authority_ref": (
                    attempt.primary_authority_ref
                ),
                "p_outcome": outcome_kind,
                "p_acknowledgement_kind": acknowledgement_kind,
                "p_acknowledgement_target_ref": (
                    acknowledgement_target_ref
                ),
                "p_reason_code": reason_code,
                "p_evidence_ref": outcome.evidence_ref,
                "p_evidence_sha256": outcome.evidence_sha256,
            },
        )
        return _receipt_from_payload(payload)

    def _rpc(self, function: str, payload: Mapping[str, object]) -> Mapping[str, Any]:
        decoded = self._rpc_value(function, payload)
        return _mapping(decoded, field=f"{function} response")

    def _rpc_optional(
        self,
        function: str,
        payload: Mapping[str, object],
    ) -> Mapping[str, Any] | None:
        decoded = self._rpc_value(function, payload)
        if decoded is None:
            return None
        return _mapping(decoded, field=f"{function} response")

    def _rpc_value(
        self,
        function: str,
        payload: Mapping[str, object],
    ) -> Any:
        if (
            function not in _READ_ONLY_RPCS
            and _remote_mutations_disabled()
        ):
            raise RuntimeError(
                "notification ownership remote writes are disabled"
            )
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        call = request.Request(
            f"{self._url}/rest/v1/rpc/{function}",
            data=encoded,
            method="POST",
            headers={
                "apikey": self._key,
                "Authorization": f"Bearer {self._key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with request.urlopen(
                call,
                timeout=self._timeout_seconds,
            ) as response:
                raw = response.read()
        except error.HTTPError as exc:
            raw = exc.read()
            message = _rpc_error_message(raw) or f"HTTP {exc.code}"
            if message.startswith(
                (
                    "notification ownership",
                    "operations core does not own",
                )
            ):
                raise NotificationOwnershipLost(message) from None
            raise RuntimeError(f"notification ownership RPC failed: {message}")
        except (OSError, error.URLError) as exc:
            raise RuntimeError(
                f"notification ownership RPC unavailable: {exc}"
            ) from exc
        try:
            decoded = json.loads(raw)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                "notification ownership RPC returned invalid JSON"
            ) from exc
        return decoded


def _runtime_environment() -> dict[str, str]:
    values = dict(os.environ)
    env_path = Path(__file__).resolve().parents[4] / ".env.local"
    if not env_path.exists():
        return values
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values.setdefault(key.strip(), value.strip().strip("\"'"))
    return values


def _normalize_command(command: OwnedEmailCommand) -> OwnedEmailCommand:
    if not isinstance(command, OwnedEmailCommand):
        raise TypeError("OwnedEmailCommand is required")
    level = _required_text(command.level, field="owned email level").lower()
    if level not in {"info", "warn", "critical"}:
        raise ValueError(f"unsupported owned email level: {level}")
    recipient = _required_text(
        command.recipient,
        field="owned email recipient",
    )
    if recipient.count("@") != 1 or any(
        character in recipient for character in "\r\n,;"
    ):
        raise ValueError("owned email recipient must be one address")
    html_body = command.html_body
    if html_body is not None and not isinstance(html_body, str):
        raise TypeError("owned email html_body must be text or None")
    return OwnedEmailCommand(
        idempotency_key=_required_text(
            command.idempotency_key,
            field="owned email idempotency_key",
        ),
        level=level,
        title=_required_text(command.title, field="owned email title"),
        recipient=recipient,
        text_body=_required_text(
            command.text_body,
            field="owned email text_body",
        ),
        html_body=html_body or None,
        actor_ref=_required_text(
            command.actor_ref,
            field="owned email actor_ref",
        ),
    )


def _owner_from_payload(payload: Mapping[str, Any]) -> NotificationOwner:
    if payload.get("schema_version") != "notification-owner.v1":
        raise RuntimeError(
            "notification owner schema is unsupported"
        )
    owner = _required_text(payload.get("owner"), field="notification owner")
    if owner not in {_LEGACY_OWNER, _OPERATIONS_CORE_OWNER}:
        raise RuntimeError(f"unsupported notification owner: {owner}")
    return NotificationOwner(
        schema_version=_required_text(
            payload.get("schema_version"),
            field="notification owner schema_version",
        ),
        effect_family=_required_text(
            payload.get("effect_family"),
            field="notification effect_family",
        ),
        owner=owner,
        generation=_positive_integer(
            payload.get("generation"),
            field="notification owner generation",
        ),
        changed_at=_required_text(
            payload.get("changed_at"),
            field="notification owner changed_at",
        ),
        changed_by=_required_text(
            payload.get("changed_by"),
            field="notification owner changed_by",
        ),
        change_reason=_required_text(
            payload.get("change_reason"),
            field="notification owner change_reason",
        ),
    )


def _receipt_from_payload(
    payload: Mapping[str, Any],
) -> OwnedEmailReceipt:
    if payload.get("schema_version") != "owned-email-receipt.v1":
        raise RuntimeError("owned email receipt schema is unsupported")
    return OwnedEmailReceipt(
        schema_version=_required_text(
            payload.get("schema_version"),
            field="owned receipt schema_version",
        ),
        owner_generation=_positive_integer(
            payload.get("owner_generation"),
            field="owned receipt owner_generation",
        ),
        work_id=_required_text(payload.get("work_id"), field="work_id"),
        work_status=_required_text(
            payload.get("work_status"),
            field="work_status",
        ),
        effect_id=_required_text(
            payload.get("effect_id"),
            field="effect_id",
        ),
        effect_status=_required_text(
            payload.get("effect_status"),
            field="effect_status",
        ),
        attempt_count=_positive_integer(
            payload.get("attempt_count"),
            field="attempt_count",
        ),
        disposition=_required_text(
            payload.get("disposition"),
            field="disposition",
        ),
        evidence_ref=_required_text(
            payload.get("evidence_ref"),
            field="evidence_ref",
        ),
        evidence_sha256=_sha256(
            payload.get("evidence_sha256"),
            field="evidence_sha256",
        ),
        primary_authority_ref=_required_text(
            payload.get("primary_authority_ref"),
            field="primary_authority_ref",
        ),
        recorded_at=_required_text(
            payload.get("recorded_at"),
            field="recorded_at",
        ),
    )


def _request_from_payload(
    payload: Mapping[str, Any],
) -> OwnedEmailRequest:
    if payload.get("schema_version") != "owned-email-request.v1":
        raise RuntimeError("owned email request schema is unsupported")
    receipt_payload = payload.get("receipt")
    return OwnedEmailRequest(
        owner_generation=_positive_integer(
            payload.get("owner_generation"),
            field="owned request owner_generation",
        ),
        work_id=_required_text(payload.get("work_id"), field="work_id"),
        effect_id=_required_text(
            payload.get("effect_id"),
            field="effect_id",
        ),
        request_sha256=_sha256(
            payload.get("request_sha256"),
            field="owned request hash",
        ),
        terminal_receipt=(
            _receipt_from_payload(
                _mapping(
                    receipt_payload,
                    field="owned request terminal receipt",
                )
            )
            if receipt_payload is not None
            else None
        ),
    )


def _attempt_from_payload(
    payload: Mapping[str, Any],
    *,
    work_lease_token: str,
    outbox_claim_token: str,
    primary_fencing_token: str,
) -> OwnedEmailAttempt:
    effect_payload = _mapping(payload.get("effect"), field="effect")
    acknowledgement = _mapping(
        effect_payload.get("acknowledgement"),
        field="effect acknowledgement",
    )
    effect = EffectView(
        schema_version=_required_text(
            effect_payload.get("schema_version"),
            field="effect schema_version",
        ),
        id=_required_text(effect_payload.get("id"), field="effect id"),
        idempotency_key=_required_text(
            effect_payload.get("idempotency_key"),
            field="effect idempotency_key",
        ),
        work_item_id=_required_text(
            effect_payload.get("work_item_id"),
            field="effect work_item_id",
        ),
        work_item_version=_positive_integer(
            effect_payload.get("work_item_version"),
            field="effect work_item_version",
        ),
        effect_kind=_required_text(
            effect_payload.get("effect_kind"),
            field="effect kind",
        ),
        target_ref=_required_text(
            effect_payload.get("target_ref"),
            field="effect target_ref",
        ),
        payload_ref=_required_text(
            effect_payload.get("payload_ref"),
            field="effect payload_ref",
        ),
        payload_sha256=_sha256(
            effect_payload.get("payload_sha256"),
            field="effect payload hash",
        ),
        risk=_required_text(
            effect_payload.get("risk"),
            field="effect risk",
        ),
        acknowledgement=AcknowledgementExpectation(
            kind=_required_text(
                acknowledgement.get("kind"),
                field="acknowledgement kind",
            ),
            target_ref=_required_text(
                acknowledgement.get("target_ref"),
                field="acknowledgement target_ref",
            ),
        ),
        requester_ref=_required_text(
            effect_payload.get("requester_ref"),
            field="effect requester_ref",
        ),
        request_sha256=_sha256(
            effect_payload.get("request_sha256"),
            field="effect request hash",
        ),
        status=_required_text(
            effect_payload.get("status"),
            field="effect status",
        ),
        created_at=_required_text(
            effect_payload.get("created_at"),
            field="effect created_at",
        ),
    )
    try:
        raw_payload = base64.b64decode(
            _required_text(
                payload.get("payload_base64"),
                field="payload_base64",
            ),
            validate=True,
        )
    except ValueError as exc:
        raise RuntimeError(
            "owned email attempt returned invalid payload bytes"
        ) from exc
    return OwnedEmailAttempt(
        owner_generation=_positive_integer(
            payload.get("owner_generation"),
            field="attempt owner_generation",
        ),
        work_id=_required_text(payload.get("work_id"), field="work_id"),
        work_version=_positive_integer(
            payload.get("work_version"),
            field="work_version",
        ),
        work_lease_token=work_lease_token,
        effect=effect,
        payload=raw_payload,
        outbox_sequence=_positive_integer(
            payload.get("outbox_sequence"),
            field="outbox_sequence",
        ),
        attempt_count=_positive_integer(
            payload.get("attempt_count"),
            field="attempt_count",
        ),
        outbox_claim_token=outbox_claim_token,
        worker_id=_required_text(
            payload.get("worker_id"),
            field="worker_id",
        ),
        primary_authority_key=_required_text(
            payload.get("primary_authority_key"),
            field="primary_authority_key",
        ),
        primary_authority_holder_ref=_required_text(
            payload.get("primary_authority_holder_ref"),
            field="primary_authority_holder_ref",
        ),
        primary_authority_epoch=_positive_integer(
            payload.get("primary_authority_epoch"),
            field="primary_authority_epoch",
        ),
        primary_fencing_token=primary_fencing_token,
        authority_request_sha256=_sha256(
            payload.get("authority_request_sha256"),
            field="authority request hash",
        ),
        outbox_claim_ref=_required_text(
            payload.get("outbox_claim_ref"),
            field="outbox_claim_ref",
        ),
        primary_authority_ref=_required_text(
            payload.get("primary_authority_ref"),
            field="primary_authority_ref",
        ),
        lease_expires_at=_required_text(
            payload.get("lease_expires_at"),
            field="lease_expires_at",
        ),
    )


def _utc_datetime(value: object, *, field: str) -> datetime:
    normalized = _required_text(value, field=field)
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include timezone")
    return parsed.astimezone(timezone.utc)


def _stale_recovery_outcome(effect: EffectView) -> FailedEffect:
    reason_code = "owned_email_recovery_stale"
    evidence = json.dumps(
        {
            "effect_id": effect.id,
            "request_sha256": effect.request_sha256,
            "reason_code": reason_code,
            "retryable": False,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return FailedEffect(
        reason_code=reason_code,
        evidence_ref=f"effect-attempt:{effect.id}:{reason_code}",
        evidence_sha256=hashlib.sha256(evidence).hexdigest(),
        retryable=False,
    )


def _mapping(value: object, *, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RuntimeError(f"{field} must be an object")
    return value


def _required_text(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    return value.strip()


def _positive_integer(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} must be positive")
    return value


def _sha256(value: object, *, field: str) -> str:
    normalized = _required_text(value, field=field)
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise ValueError(f"{field} must be lowercase SHA-256")
    return normalized


def _rpc_error_message(payload: bytes) -> str | None:
    try:
        decoded = json.loads(payload)
    except (UnicodeError, json.JSONDecodeError):
        return "response body was not valid JSON"
    if not isinstance(decoded, Mapping):
        return None
    message = decoded.get("message")
    return message if isinstance(message, str) else None


__all__ = [
    "NotificationOwner",
    "NotificationOwnershipLost",
    "OwnedEmailAttempt",
    "OwnedEmailCommand",
    "OwnedEmailExistingRequest",
    "OwnedEmailNotification",
    "OwnedEmailReceipt",
    "OwnedEmailRecovery",
    "OwnedEmailRecoverySummary",
    "OwnedEmailRequest",
    "SupabaseOwnedEmailStore",
    "dispatch_email_by_current_owner",
    "read_existing_owned_email_request",
]
