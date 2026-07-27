"""Owner-fenced formal caller for one publisher article projection.

The external interface is one ``sync`` call.  Durable WorkItem creation,
immutable payload storage, EffectRequest/outbox creation, lease fencing,
provider read-back, and settlement stay behind the injected ownership store.
The production adapter is service-role-only and never falls back to a
publishable Supabase key.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol
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
from ._publisher_article_sync import (
    PublisherArticleSyncEffectAdapter,
    encode_publisher_article_sync_payload,
)
from .supabase_rpc import ServiceRoleRpcClient, runtime_environment

_OWNER_FAMILY = "publisher.article.supabase.sync"
_PRIMARY_AUTHORITY_KEY = FORMAL_PRIMARY_AUTHORITY_KEY
_OPERATIONS_CORE_OWNER = "operations_core"
_LEGACY_OWNER = "legacy"
_WORKER_ID = "effect-worker:publisher-article-sync"
_RECEIPT_SCHEMA = "owned-publisher-article-receipt.v1"


class PublisherArticleSyncOwnershipLost(RuntimeError):
    """The caller no longer owns the publisher sync family generation."""


@dataclass(frozen=True)
class PublisherArticleSyncOwner:
    schema_version: str
    effect_family: str
    owner: str
    generation: int
    changed_at: str
    changed_by: str
    change_reason: str


@dataclass(frozen=True)
class OwnedPublisherArticleCommand:
    idempotency_key: str
    article: Mapping[str, object]
    actor_ref: str


@dataclass(frozen=True)
class OwnedPublisherArticleRequest:
    owner_generation: int
    work_id: str
    effect_id: str
    request_sha256: str
    terminal_receipt: OwnedPublisherArticleReceipt | None = None


@dataclass(frozen=True)
class OwnedPublisherArticleAttempt:
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
class OwnedPublisherArticleReceipt:
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
class OwnedPublisherArticleRecoverySummary:
    recovered_count: int
    delivered_count: int
    retry_scheduled_count: int
    receipts: tuple[OwnedPublisherArticleReceipt, ...]


class _OwnedPublisherArticleStore(Protocol):
    def read_owner(self) -> PublisherArticleSyncOwner: ...

    def request(
        self,
        command: OwnedPublisherArticleCommand,
        *,
        owner_generation: int,
    ) -> OwnedPublisherArticleRequest: ...

    def begin(
        self,
        request_view: OwnedPublisherArticleRequest,
        *,
        worker_id: str,
        lease_seconds: int,
        work_lease_token: str,
        outbox_claim_token: str,
        primary_fencing_token: str,
    ) -> OwnedPublisherArticleAttempt: ...

    def recover_due(
        self,
        *,
        owner_generation: int,
        worker_id: str,
        lease_seconds: int,
        work_lease_token: str,
        outbox_claim_token: str,
        primary_fencing_token: str,
    ) -> OwnedPublisherArticleAttempt | None: ...

    def settle(
        self,
        attempt: OwnedPublisherArticleAttempt,
        outcome: EffectAttemptOutcome,
    ) -> OwnedPublisherArticleReceipt: ...


class _PrimaryLeaseGate(Protocol):
    def current_lease(self) -> PrimaryLease: ...


class _OwnedPublisherExecutionContext:
    """Share owner, token, and Primary Authority validation."""

    def __init__(
        self,
        *,
        store: _OwnedPublisherArticleStore,
        primary_authority: _PrimaryLeaseGate,
        worker_id: str,
        lease_seconds: int,
        token_factory: Callable[[], str] | None,
        token_prefix: str,
        operation_label: str,
    ) -> None:
        if not isinstance(worker_id, str) or not worker_id.strip():
            raise ValueError(
                f"owned publisher {operation_label} worker_id is required"
            )
        if (
            isinstance(lease_seconds, bool)
            or not isinstance(lease_seconds, int)
            or lease_seconds <= 0
        ):
            raise ValueError(
                f"owned publisher {operation_label} lease_seconds "
                "must be positive"
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
    ) -> tuple[PublisherArticleSyncOwner, PrimaryLease]:
        primary_lease = self.current_lease()
        owner = self._store.read_owner()
        if (
            owner.effect_family != _OWNER_FAMILY
            or owner.owner != _OPERATIONS_CORE_OWNER
        ):
            raise PublisherArticleSyncOwnershipLost(
                "operations core does not own "
                "publisher.article.supabase.sync"
            )
        return owner, primary_lease

    def token(self, kind: str) -> str:
        token = self._token_factory()
        if not isinstance(token, str) or not token.strip():
            raise ValueError(
                f"owned publisher {self._operation_label} {kind} "
                "token is required"
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
                f"owned publisher {self._operation_label} keepalive "
                "returned no typed PrimaryLease"
            )
        if (
            lease.authority_key != _PRIMARY_AUTHORITY_KEY
            or lease.holder_ref != self.worker_id
        ):
            raise PublisherArticleSyncOwnershipLost(
                f"owned publisher {self._operation_label} keepalive "
                "lease identity mismatch"
            )
        if expected is not None and (
            lease.authority_key != expected.authority_key
            or lease.holder_ref != expected.holder_ref
            or lease.epoch != expected.epoch
            or lease.fencing_token != expected.fencing_token
            or lease.acquired_at != expected.acquired_at
        ):
            raise PublisherArticleSyncOwnershipLost(
                f"owned publisher {self._operation_label} keepalive "
                "lease was replaced"
            )
        return lease

    @staticmethod
    def validate_attempt(
        attempt: OwnedPublisherArticleAttempt,
        *,
        owner_generation: int,
        primary_lease: PrimaryLease,
        expected_work_id: str | None = None,
        expected_effect_id: str | None = None,
    ) -> None:
        if (
            attempt.owner_generation != owner_generation
            or attempt.effect.effect_kind != _OWNER_FAMILY
            or (
                expected_work_id is not None
                and attempt.work_id != expected_work_id
            )
            or (
                expected_effect_id is not None
                and attempt.effect.id != expected_effect_id
            )
            or attempt.primary_authority_key
            != primary_lease.authority_key
            or attempt.primary_authority_holder_ref
            != primary_lease.holder_ref
            or attempt.primary_authority_epoch != primary_lease.epoch
            or attempt.primary_fencing_token
            != primary_lease.fencing_token
        ):
            raise PublisherArticleSyncOwnershipLost(
                "owned publisher attempt drifted from its durable request, "
                "owner, or Primary Authority lease"
            )


class OwnedPublisherArticleSync:
    """Synchronize one article through the current durable owner."""

    def __init__(
        self,
        *,
        store: _OwnedPublisherArticleStore,
        provider: PublisherArticleSyncEffectAdapter,
        primary_authority: _PrimaryLeaseGate,
        worker_id: str = _WORKER_ID,
        lease_seconds: int = 300,
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        self._store = store
        self._provider = provider
        self._execution = _OwnedPublisherExecutionContext(
            store=store,
            primary_authority=primary_authority,
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            token_factory=token_factory,
            token_prefix="owned_publisher",
            operation_label="delivery",
        )

    def sync(
        self,
        command: OwnedPublisherArticleCommand,
    ) -> OwnedPublisherArticleReceipt:
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
            owner_generation=request_view.owner_generation,
            primary_lease=primary_lease,
            expected_work_id=request_view.work_id,
            expected_effect_id=request_view.effect_id,
        )
        self._execution.current_lease(expected=primary_lease)
        outcome = self._provider.deliver(
            attempt.effect,
            attempt.payload,
            authorize_mutation=lambda: self._execution.current_lease(
                expected=primary_lease,
            ),
        )
        receipt = self._store.settle(attempt, outcome)
        self._validate_settlement_receipt(
            receipt,
            attempt=attempt,
            outcome=outcome,
        )
        return receipt

    @staticmethod
    def _validate_terminal_receipt(
        request_view: OwnedPublisherArticleRequest,
    ) -> None:
        receipt = request_view.terminal_receipt
        if receipt is None:
            raise AssertionError("terminal receipt is required")
        if (
            receipt.schema_version != _RECEIPT_SCHEMA
            or receipt.owner_generation != request_view.owner_generation
            or receipt.work_id != request_view.work_id
            or receipt.effect_id != request_view.effect_id
            or receipt.disposition
            not in {"delivered", "dead_lettered"}
            or not _receipt_lifecycle_is_consistent(receipt)
        ):
            raise PublisherArticleSyncOwnershipLost(
                "owned publisher terminal receipt drifted "
                "from its durable request"
            )

    @staticmethod
    def _validate_settlement_receipt(
        receipt: OwnedPublisherArticleReceipt,
        *,
        attempt: OwnedPublisherArticleAttempt,
        outcome: EffectAttemptOutcome,
    ) -> None:
        if not isinstance(receipt, OwnedPublisherArticleReceipt):
            raise TypeError(
                "owned publisher settlement returned no typed receipt"
            )
        if (
            receipt.schema_version != _RECEIPT_SCHEMA
            or receipt.owner_generation != attempt.owner_generation
            or receipt.work_id != attempt.work_id
            or receipt.effect_id != attempt.effect.id
            or receipt.attempt_count != attempt.attempt_count
            or receipt.primary_authority_ref
            != attempt.primary_authority_ref
            or receipt.evidence_ref != outcome.evidence_ref
            or receipt.evidence_sha256 != outcome.evidence_sha256
            or not _receipt_lifecycle_is_consistent(receipt)
            or (
                isinstance(outcome, AcknowledgedEffect)
                and receipt.disposition != "delivered"
            )
            or (
                isinstance(outcome, FailedEffect)
                and not outcome.retryable
                and receipt.disposition != "dead_lettered"
            )
            or (
                isinstance(outcome, FailedEffect)
                and outcome.retryable
                and receipt.disposition
                not in {"retry_scheduled", "dead_lettered"}
            )
        ):
            raise PublisherArticleSyncOwnershipLost(
                "owned publisher settlement receipt drifted "
                "from its durable attempt"
            )

class OwnedPublisherArticleRecovery:
    """Recover due publisher projections through the current durable owner."""

    def __init__(
        self,
        *,
        store: _OwnedPublisherArticleStore,
        provider: PublisherArticleSyncEffectAdapter,
        primary_authority: _PrimaryLeaseGate,
        worker_id: str = _WORKER_ID,
        lease_seconds: int = 300,
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        self._store = store
        self._provider = provider
        self._execution = _OwnedPublisherExecutionContext(
            store=store,
            primary_authority=primary_authority,
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            token_factory=token_factory,
            token_prefix="owned_publisher_recovery",
            operation_label="recovery",
        )

    def recover(
        self,
        *,
        limit: int = 10,
    ) -> OwnedPublisherArticleRecoverySummary:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError(
                "owned publisher recovery limit must be positive"
            )
        owner, primary_lease = self._execution.begin_owner_session()

        receipts: list[OwnedPublisherArticleReceipt] = []
        for _ in range(limit):
            primary_lease = self._execution.current_lease(
                expected=primary_lease,
            )
            attempt = self._store.recover_due(
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
                owner_generation=owner.generation,
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
            receipt = self._store.settle(attempt, outcome)
            OwnedPublisherArticleSync._validate_settlement_receipt(
                receipt,
                attempt=attempt,
                outcome=outcome,
            )
            receipts.append(receipt)

        return OwnedPublisherArticleRecoverySummary(
            recovered_count=len(receipts),
            delivered_count=sum(
                receipt.delivered for receipt in receipts
            ),
            retry_scheduled_count=sum(
                receipt.disposition == "retry_scheduled"
                for receipt in receipts
            ),
            receipts=tuple(receipts),
        )


class SupabaseOwnedPublisherArticleStore:
    """Service-role PostgREST adapter for publisher ownership RPCs."""

    def __init__(
        self,
        *,
        supabase_url: str,
        service_role_key: str,
        timeout_seconds: float = 45.0,
    ) -> None:
        self._client = ServiceRoleRpcClient(
            supabase_url=supabase_url,
            service_role_key=service_role_key,
            timeout_seconds=timeout_seconds,
        )

    @classmethod
    def from_environment(cls) -> SupabaseOwnedPublisherArticleStore:
        values = runtime_environment()
        return cls(
            supabase_url=values.get("SUPABASE_URL", ""),
            service_role_key=values.get(
                "SUPABASE_SERVICE_ROLE_KEY",
                "",
            ),
            timeout_seconds=float(
                values.get("VOLPRED_OPERATIONS_RPC_TIMEOUT_SEC", "45")
            ),
        )

    @property
    def backend_sha256(self) -> str:
        """Identify the bound Supabase backend without exposing its URL."""

        return self._client.backend_sha256

    def read_owner(self) -> PublisherArticleSyncOwner:
        return _owner_from_payload(
            self._rpc("volpred_read_publisher_article_sync_owner", {})
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
    ) -> PublisherArticleSyncOwner:
        return _owner_from_payload(
            self._rpc(
                "volpred_transfer_publisher_article_sync_owner",
                {
                    "p_expected_owner": expected_owner,
                    "p_expected_generation": expected_generation,
                    "p_target_owner": target_owner,
                    "p_actor_ref": actor_ref,
                    "p_reason": reason,
                    "p_rollback_of_generation": (
                        rollback_of_generation
                    ),
                },
            )
        )

    def request(
        self,
        command: OwnedPublisherArticleCommand,
        *,
        owner_generation: int,
    ) -> OwnedPublisherArticleRequest:
        payload_bytes = encode_publisher_article_sync_payload(
            command.article
        )
        payload = _mapping(
            json.loads(payload_bytes),
            field="publisher sync payload",
        )
        response = self._rpc(
            "volpred_request_owned_publisher_article_sync",
            {
                "p_owner_generation": owner_generation,
                "p_idempotency_key": command.idempotency_key,
                "p_payload": payload,
                "p_actor_ref": command.actor_ref,
            },
        )
        receipt_payload = response.get("receipt")
        terminal_receipt = (
            _receipt_from_payload(
                _mapping(
                    receipt_payload,
                    field="owned request terminal receipt",
                )
            )
            if receipt_payload is not None
            else None
        )
        return OwnedPublisherArticleRequest(
            owner_generation=_positive_integer(
                response.get("owner_generation"),
                field="owned request owner_generation",
            ),
            work_id=_required_text(
                response.get("work_id"),
                field="work_id",
            ),
            effect_id=_required_text(
                response.get("effect_id"),
                field="effect_id",
            ),
            request_sha256=_sha256(
                response.get("request_sha256"),
                field="owned request hash",
            ),
            terminal_receipt=terminal_receipt,
        )

    def begin(
        self,
        request_view: OwnedPublisherArticleRequest,
        *,
        worker_id: str,
        lease_seconds: int,
        work_lease_token: str,
        outbox_claim_token: str,
        primary_fencing_token: str,
    ) -> OwnedPublisherArticleAttempt:
        response = self._rpc(
            "volpred_begin_owned_publisher_article_sync",
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
            response,
            work_lease_token=work_lease_token,
            outbox_claim_token=outbox_claim_token,
            primary_fencing_token=primary_fencing_token,
        )

    def recover_due(
        self,
        *,
        owner_generation: int,
        worker_id: str,
        lease_seconds: int,
        work_lease_token: str,
        outbox_claim_token: str,
        primary_fencing_token: str,
    ) -> OwnedPublisherArticleAttempt | None:
        response = self._rpc(
            "volpred_recover_due_owned_publisher_article_sync",
            {
                "p_owner_generation": owner_generation,
                "p_worker_id": worker_id,
                "p_lease_seconds": lease_seconds,
                "p_work_lease_token": work_lease_token,
                "p_outbox_claim_token": outbox_claim_token,
                "p_primary_fencing_token": primary_fencing_token,
            },
        )
        if response.get("recovered") is False:
            return None
        return _attempt_from_payload(
            response,
            work_lease_token=work_lease_token,
            outbox_claim_token=outbox_claim_token,
            primary_fencing_token=primary_fencing_token,
        )

    def settle(
        self,
        attempt: OwnedPublisherArticleAttempt,
        outcome: EffectAttemptOutcome,
    ) -> OwnedPublisherArticleReceipt:
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
            raise TypeError(
                "owned publisher provider returned invalid outcome"
            )
        response = self._rpc(
            "volpred_settle_owned_publisher_article_sync",
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
        return _receipt_from_payload(response)

    def _rpc(
        self,
        function: str,
        payload: Mapping[str, object],
    ) -> Mapping[str, Any]:
        return _mapping(
            self._client.call(function, payload),
            field=f"{function} response",
        )


def _normalize_command(
    command: OwnedPublisherArticleCommand,
) -> OwnedPublisherArticleCommand:
    if not isinstance(command, OwnedPublisherArticleCommand):
        raise TypeError("OwnedPublisherArticleCommand is required")
    payload = encode_publisher_article_sync_payload(command.article)
    decoded = _mapping(
        json.loads(payload),
        field="publisher sync payload",
    )
    article = _mapping(
        decoded.get("article"),
        field="publisher sync article",
    )
    return OwnedPublisherArticleCommand(
        idempotency_key=_required_text(
            command.idempotency_key,
            field="owned publisher idempotency_key",
        ),
        article=dict(article),
        actor_ref=_required_text(
            command.actor_ref,
            field="owned publisher actor_ref",
        ),
    )


def _effect_from_payload(payload: Mapping[str, Any]) -> EffectView:
    acknowledgement = _mapping(
        payload.get("acknowledgement"),
        field="effect acknowledgement",
    )
    return EffectView(
        schema_version=_required_text(
            payload.get("schema_version"),
            field="effect schema_version",
        ),
        id=_required_text(payload.get("id"), field="effect id"),
        idempotency_key=_required_text(
            payload.get("idempotency_key"),
            field="effect idempotency_key",
        ),
        work_item_id=_required_text(
            payload.get("work_item_id"),
            field="effect work_item_id",
        ),
        work_item_version=_positive_integer(
            payload.get("work_item_version"),
            field="effect work_item_version",
        ),
        effect_kind=_required_text(
            payload.get("effect_kind"),
            field="effect kind",
        ),
        target_ref=_required_text(
            payload.get("target_ref"),
            field="effect target_ref",
        ),
        payload_ref=_required_text(
            payload.get("payload_ref"),
            field="effect payload_ref",
        ),
        payload_sha256=_sha256(
            payload.get("payload_sha256"),
            field="effect payload hash",
        ),
        risk=_required_text(payload.get("risk"), field="effect risk"),
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
            payload.get("requester_ref"),
            field="effect requester_ref",
        ),
        request_sha256=_sha256(
            payload.get("request_sha256"),
            field="effect request hash",
        ),
        status=_required_text(
            payload.get("status"),
            field="effect status",
        ),
        created_at=_required_text(
            payload.get("created_at"),
            field="effect created_at",
        ),
    )


def _attempt_from_payload(
    payload: Mapping[str, Any],
    *,
    work_lease_token: str,
    outbox_claim_token: str,
    primary_fencing_token: str,
) -> OwnedPublisherArticleAttempt:
    effect = _effect_from_payload(
        _mapping(payload.get("effect"), field="effect")
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
            "owned publisher attempt returned invalid payload bytes"
        ) from exc
    return OwnedPublisherArticleAttempt(
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


def _owner_from_payload(
    payload: Mapping[str, Any],
) -> PublisherArticleSyncOwner:
    owner = _required_text(
        payload.get("owner"),
        field="publisher sync owner",
    )
    if owner not in {_LEGACY_OWNER, _OPERATIONS_CORE_OWNER}:
        raise RuntimeError(f"unsupported publisher sync owner: {owner}")
    return PublisherArticleSyncOwner(
        schema_version=_required_text(
            payload.get("schema_version"),
            field="publisher sync owner schema_version",
        ),
        effect_family=_required_text(
            payload.get("effect_family"),
            field="publisher sync effect_family",
        ),
        owner=owner,
        generation=_positive_integer(
            payload.get("generation"),
            field="publisher sync owner generation",
        ),
        changed_at=_required_text(
            payload.get("changed_at"),
            field="publisher sync owner changed_at",
        ),
        changed_by=_required_text(
            payload.get("changed_by"),
            field="publisher sync owner changed_by",
        ),
        change_reason=_required_text(
            payload.get("change_reason"),
            field="publisher sync owner change_reason",
        ),
    )


def _receipt_from_payload(
    payload: Mapping[str, Any],
) -> OwnedPublisherArticleReceipt:
    return OwnedPublisherArticleReceipt(
        schema_version=_required_text(
            payload.get("schema_version"),
            field="owned receipt schema_version",
        ),
        owner_generation=_positive_integer(
            payload.get("owner_generation"),
            field="owned receipt owner_generation",
        ),
        work_id=_required_text(
            payload.get("work_id"),
            field="work_id",
        ),
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


def _receipt_lifecycle_is_consistent(
    receipt: OwnedPublisherArticleReceipt,
) -> bool:
    expected_states = {
        "delivered": ("succeeded", "delivered"),
        "retry_scheduled": ("pending", "requested"),
        "dead_lettered": ("failed", "dead_lettered"),
    }
    return (
        receipt.work_status,
        receipt.effect_status,
    ) == expected_states.get(receipt.disposition)


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


__all__ = [
    "OwnedPublisherArticleAttempt",
    "OwnedPublisherArticleCommand",
    "OwnedPublisherArticleReceipt",
    "OwnedPublisherArticleRecovery",
    "OwnedPublisherArticleRecoverySummary",
    "OwnedPublisherArticleRequest",
    "OwnedPublisherArticleSync",
    "PublisherArticleSyncOwner",
    "PublisherArticleSyncOwnershipLost",
    "SupabaseOwnedPublisherArticleStore",
]
