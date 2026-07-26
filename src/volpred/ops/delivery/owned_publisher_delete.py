"""Owner-fenced formal caller for one immutable publisher delete batch.

The external interface is one ``delete`` call. Durable WorkItem creation,
immutable payload storage, EffectRequest/outbox creation, lease fencing,
provider read-back, and settlement stay behind the injected ownership store.
The production adapter is service-role-only and never falls back to a
publishable Supabase key.
"""

from __future__ import annotations

import base64
from collections.abc import Callable, Mapping
from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any, Protocol
from uuid import uuid4

from volpred.ops.authority import PrimaryLease

from ._effect import (
    AcknowledgedEffect,
    AcknowledgementExpectation,
    EffectAttemptOutcome,
    EffectView,
    FailedEffect,
)
from ._publisher_article_delete import (
    PreparedPublisherArticleDelete,
    PublisherArticleDeleteApprovalReadback,
    PublisherArticleDeleteAuthorization,
    PublisherArticleDeleteCandidateReadback,
    PublisherArticleDeleteEffectAdapter,
)
from .supabase_rpc import ServiceRoleRpcClient, runtime_environment


_OWNER_FAMILY = "publisher.article.supabase.delete"
_PRIMARY_AUTHORITY_KEY = "publisher:article.supabase.delete"
_OPERATIONS_CORE_OWNER = "operations_core"
_LEGACY_OWNER = "legacy"
_WORKER_ID = "effect-worker:publisher-article-delete"
_RECEIPT_SCHEMA = "owned-publisher-delete-receipt.v1"


class PublisherArticleDeleteOwnershipLost(RuntimeError):
    """The caller no longer owns the publisher delete family generation."""


@dataclass(frozen=True)
class PublisherArticleDeleteOwner:
    schema_version: str
    effect_family: str
    owner: str
    generation: int
    changed_at: str
    changed_by: str
    change_reason: str


@dataclass(frozen=True)
class OwnedPublisherDeleteCommand:
    prepared: PreparedPublisherArticleDelete
    actor_ref: str


@dataclass(frozen=True)
class OwnedPublisherDeleteRequest:
    owner_generation: int
    work_id: str
    effect_id: str
    request_sha256: str
    terminal_receipt: OwnedPublisherDeleteReceipt | None = None


@dataclass(frozen=True)
class OwnedPublisherDeleteAttempt:
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
class OwnedPublisherDeleteReceipt:
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
class OwnedPublisherDeleteReconciliationReceipt:
    schema_version: str
    effect_id: str
    attempt_count: int
    stale_owner_generation: int
    current_owner_generation: int
    approval_ref: str
    reason_code: str
    evidence_ref: str
    evidence_sha256: str
    recorded_at: str


@dataclass(frozen=True)
class OwnedPublisherDeleteReconciliationSummary:
    schema_version: str
    reconciled_count: int
    receipts: tuple[OwnedPublisherDeleteReconciliationReceipt, ...]


class _OwnedPublisherDeleteStore(Protocol):
    def read_owner(self) -> PublisherArticleDeleteOwner: ...

    def request(
        self,
        command: OwnedPublisherDeleteCommand,
        *,
        owner_generation: int,
    ) -> OwnedPublisherDeleteRequest: ...

    def begin(
        self,
        request_view: OwnedPublisherDeleteRequest,
        *,
        worker_id: str,
        lease_seconds: int,
        work_lease_token: str,
        outbox_claim_token: str,
        primary_fencing_token: str,
    ) -> OwnedPublisherDeleteAttempt: ...

    def settle(
        self,
        attempt: OwnedPublisherDeleteAttempt,
        outcome: EffectAttemptOutcome,
    ) -> OwnedPublisherDeleteReceipt: ...


class _OwnedPublisherDeleteReconciliationStore(Protocol):
    def reconcile_stale_retries(
        self,
        *,
        limit: int,
        actor_ref: str,
    ) -> OwnedPublisherDeleteReconciliationSummary: ...


class _PrimaryLeaseGate(Protocol):
    def current_lease(self) -> PrimaryLease: ...


class _PublisherDeleteProviderFactory(Protocol):
    def __call__(
        self,
        attempt: OwnedPublisherDeleteAttempt,
    ) -> PublisherArticleDeleteEffectAdapter: ...


class OwnedPublisherArticleDelete:
    """Execute one immutable destructive scope through the durable owner."""

    def __init__(
        self,
        *,
        store: _OwnedPublisherDeleteStore,
        provider_factory: _PublisherDeleteProviderFactory,
        primary_authority: _PrimaryLeaseGate,
        worker_id: str = _WORKER_ID,
        lease_seconds: int = 300,
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        if not isinstance(worker_id, str) or not worker_id.strip():
            raise ValueError("owned publisher delete worker_id is required")
        if (
            isinstance(lease_seconds, bool)
            or not isinstance(lease_seconds, int)
            or lease_seconds <= 0
        ):
            raise ValueError("owned publisher delete lease_seconds must be positive")
        self._store = store
        self._provider_factory = provider_factory
        self._primary_authority = primary_authority
        self._worker_id = worker_id.strip()
        self._lease_seconds = lease_seconds
        self._token_factory = token_factory or (
            lambda: f"owned_delete_{uuid4().hex}"
        )

    def delete(
        self,
        command: OwnedPublisherDeleteCommand,
    ) -> OwnedPublisherDeleteReceipt:
        normalized = _normalize_command(command)
        primary_lease = self._current_primary_lease()
        owner = self._store.read_owner()
        if (
            owner.effect_family != _OWNER_FAMILY
            or owner.owner != _OPERATIONS_CORE_OWNER
        ):
            raise PublisherArticleDeleteOwnershipLost(
                "operations core does not own "
                "publisher.article.supabase.delete"
            )
        request_view = self._store.request(
            normalized,
            owner_generation=owner.generation,
        )
        if request_view.terminal_receipt is not None:
            self._validate_terminal_receipt(request_view)
            return request_view.terminal_receipt
        primary_lease = self._current_primary_lease(
            expected=primary_lease,
        )
        attempt = self._store.begin(
            request_view,
            worker_id=self._worker_id,
            lease_seconds=self._lease_seconds,
            work_lease_token=self._token("work"),
            outbox_claim_token=self._token("outbox"),
            primary_fencing_token=primary_lease.fencing_token,
        )
        self._validate_attempt(
            attempt,
            request_view=request_view,
            primary_lease=primary_lease,
        )
        self._current_primary_lease(expected=primary_lease)
        provider = self._provider_factory(attempt)
        if not isinstance(provider, PublisherArticleDeleteEffectAdapter):
            raise TypeError(
                "owned publisher delete provider factory returned invalid adapter"
            )
        outcome = provider.deliver(
            attempt.effect,
            attempt.payload,
            authorize_mutation=lambda: self._current_primary_lease(
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

    def _token(self, kind: str) -> str:
        token = self._token_factory()
        if not isinstance(token, str) or not token.strip():
            raise ValueError(
                f"owned publisher delete {kind} token is required"
            )
        return token.strip()

    def _current_primary_lease(
        self,
        *,
        expected: PrimaryLease | None = None,
    ) -> PrimaryLease:
        lease = self._primary_authority.current_lease()
        if not isinstance(lease, PrimaryLease):
            raise TypeError(
                "owned publisher delete keepalive returned no typed "
                "PrimaryLease"
            )
        if (
            lease.authority_key != _PRIMARY_AUTHORITY_KEY
            or lease.holder_ref != self._worker_id
        ):
            raise PublisherArticleDeleteOwnershipLost(
                "owned publisher delete keepalive lease identity mismatch"
            )
        if expected is not None and (
            lease.authority_key != expected.authority_key
            or lease.holder_ref != expected.holder_ref
            or lease.epoch != expected.epoch
            or lease.fencing_token != expected.fencing_token
            or lease.acquired_at != expected.acquired_at
        ):
            raise PublisherArticleDeleteOwnershipLost(
                "owned publisher delete keepalive lease was replaced"
            )
        return lease

    @staticmethod
    def _validate_terminal_receipt(
        request_view: OwnedPublisherDeleteRequest,
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
            raise PublisherArticleDeleteOwnershipLost(
                "owned publisher terminal receipt drifted "
                "from its durable request"
            )

    @staticmethod
    def _validate_settlement_receipt(
        receipt: OwnedPublisherDeleteReceipt,
        *,
        attempt: OwnedPublisherDeleteAttempt,
        outcome: EffectAttemptOutcome,
    ) -> None:
        if not isinstance(receipt, OwnedPublisherDeleteReceipt):
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
            raise PublisherArticleDeleteOwnershipLost(
                "owned publisher settlement receipt drifted "
                "from its durable attempt"
            )

    @staticmethod
    def _validate_attempt(
        attempt: OwnedPublisherDeleteAttempt,
        *,
        request_view: OwnedPublisherDeleteRequest,
        primary_lease: PrimaryLease,
    ) -> None:
        if (
            attempt.owner_generation != request_view.owner_generation
            or attempt.work_id != request_view.work_id
            or attempt.effect.id != request_view.effect_id
        ):
            raise PublisherArticleDeleteOwnershipLost(
                "owned publisher begin drifted from its durable request"
            )
        if (
            attempt.primary_authority_key
            != primary_lease.authority_key
            or attempt.primary_authority_holder_ref
            != primary_lease.holder_ref
            or attempt.primary_authority_epoch != primary_lease.epoch
            or attempt.primary_fencing_token
            != primary_lease.fencing_token
        ):
            raise PublisherArticleDeleteOwnershipLost(
                "owned publisher begin used a different "
                "Primary Authority lease"
            )


class OwnedPublisherDeleteReconciliation:
    """Terminalize impossible stale retries without invoking a provider."""

    def __init__(
        self,
        *,
        store: _OwnedPublisherDeleteReconciliationStore,
        actor_ref: str,
    ) -> None:
        self._store = store
        self._actor_ref = _required_text(
            actor_ref,
            field="publisher delete reconciliation actor_ref",
        )

    def reconcile(
        self,
        *,
        limit: int,
    ) -> OwnedPublisherDeleteReconciliationSummary:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError(
                "publisher delete reconciliation limit must be positive"
            )
        return self._store.reconcile_stale_retries(
            limit=limit,
            actor_ref=self._actor_ref,
        )


class SupabaseOwnedPublisherDeleteStore:
    """Service-role PostgREST adapter for delete ownership RPCs."""

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
    def from_environment(cls) -> SupabaseOwnedPublisherDeleteStore:
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

    def read_owner(self) -> PublisherArticleDeleteOwner:
        return _owner_from_payload(
            self._rpc("volpred_read_publisher_article_delete_owner", {})
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
    ) -> PublisherArticleDeleteOwner:
        return _owner_from_payload(
            self._rpc(
                "volpred_transfer_publisher_article_delete_owner",
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

    def record_approval(
        self,
        authorization: PublisherArticleDeleteAuthorization,
        *,
        actor_ref: str,
    ) -> PublisherArticleDeleteApprovalReadback:
        response = _mapping(
            self._rpc(
                "volpred_record_publisher_article_delete_approval",
                {
                    "p_authorization": _authorization_payload(
                        authorization
                    ),
                    "p_actor_ref": _required_text(
                        actor_ref,
                        field="publisher delete approval actor_ref",
                    ),
                },
            ),
            field="publisher delete approval record",
        )
        return _approval_readback_from_payload(response)

    def revoke_approval(
        self,
        *,
        approval_ref: str,
        actor_ref: str,
        reason: str,
    ) -> PublisherArticleDeleteApprovalReadback:
        response = _mapping(
            self._rpc(
                "volpred_revoke_publisher_article_delete_approval",
                {
                    "p_approval_ref": _required_text(
                        approval_ref,
                        field="publisher delete approval_ref",
                    ),
                    "p_actor_ref": _required_text(
                        actor_ref,
                        field="publisher delete approval actor_ref",
                    ),
                    "p_reason": _required_text(
                        reason,
                        field="publisher delete approval revoke reason",
                    ),
                },
            ),
            field="publisher delete approval revoke",
        )
        return _approval_readback_from_payload(response)

    def reconcile_stale_retries(
        self,
        *,
        limit: int,
        actor_ref: str,
    ) -> OwnedPublisherDeleteReconciliationSummary:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError(
                "publisher delete reconciliation limit must be positive"
            )
        return _reconciliation_summary_from_payload(
            self._rpc(
                "volpred_reconcile_stale_owned_publisher_article_delete",
                {
                    "p_limit": limit,
                    "p_actor_ref": _required_text(
                        actor_ref,
                        field=(
                            "publisher delete reconciliation actor_ref"
                        ),
                    ),
                },
            )
        )

    def request(
        self,
        command: OwnedPublisherDeleteCommand,
        *,
        owner_generation: int,
    ) -> OwnedPublisherDeleteRequest:
        payload = _mapping(
            json.loads(command.prepared.payload),
            field="publisher delete payload",
        )
        response = self._rpc(
            "volpred_request_owned_publisher_article_delete",
            {
                "p_owner_generation": owner_generation,
                "p_idempotency_key": (
                    command.prepared.request.idempotency_key
                ),
                "p_payload_text": command.prepared.payload.decode("utf-8"),
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
        return OwnedPublisherDeleteRequest(
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
        request_view: OwnedPublisherDeleteRequest,
        *,
        worker_id: str,
        lease_seconds: int,
        work_lease_token: str,
        outbox_claim_token: str,
        primary_fencing_token: str,
    ) -> OwnedPublisherDeleteAttempt:
        response = self._rpc(
            "volpred_begin_owned_publisher_article_delete",
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
        effect = _effect_from_payload(
            _mapping(response.get("effect"), field="effect")
        )
        try:
            raw_payload = base64.b64decode(
                _required_text(
                    response.get("payload_base64"),
                    field="payload_base64",
                ),
                validate=True,
            )
        except ValueError as exc:
            raise RuntimeError(
                "owned publisher delete begin returned invalid payload bytes"
            ) from exc
        return OwnedPublisherDeleteAttempt(
            owner_generation=_positive_integer(
                response.get("owner_generation"),
                field="attempt owner_generation",
            ),
            work_id=_required_text(
                response.get("work_id"),
                field="work_id",
            ),
            work_version=_positive_integer(
                response.get("work_version"),
                field="work_version",
            ),
            work_lease_token=work_lease_token,
            effect=effect,
            payload=raw_payload,
            outbox_sequence=_positive_integer(
                response.get("outbox_sequence"),
                field="outbox_sequence",
            ),
            attempt_count=_positive_integer(
                response.get("attempt_count"),
                field="attempt_count",
            ),
            outbox_claim_token=outbox_claim_token,
            worker_id=_required_text(
                response.get("worker_id"),
                field="worker_id",
            ),
            primary_authority_key=_required_text(
                response.get("primary_authority_key"),
                field="primary_authority_key",
            ),
            primary_authority_holder_ref=_required_text(
                response.get("primary_authority_holder_ref"),
                field="primary_authority_holder_ref",
            ),
            primary_authority_epoch=_positive_integer(
                response.get("primary_authority_epoch"),
                field="primary_authority_epoch",
            ),
            primary_fencing_token=primary_fencing_token,
            authority_request_sha256=_sha256(
                response.get("authority_request_sha256"),
                field="authority request hash",
            ),
            outbox_claim_ref=_required_text(
                response.get("outbox_claim_ref"),
                field="outbox_claim_ref",
            ),
            primary_authority_ref=_required_text(
                response.get("primary_authority_ref"),
                field="primary_authority_ref",
            ),
            lease_expires_at=_required_text(
                response.get("lease_expires_at"),
                field="lease_expires_at",
            ),
        )

    def settle(
        self,
        attempt: OwnedPublisherDeleteAttempt,
        outcome: EffectAttemptOutcome,
    ) -> OwnedPublisherDeleteReceipt:
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
                "owned publisher delete provider returned invalid outcome"
            )
        response = self._rpc(
            "volpred_settle_owned_publisher_article_delete",
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


class SupabasePublisherArticleDeleteApprovalVerifier:
    """Read one scope-bound approval through a service-role-only RPC."""

    def __init__(self, *, client: ServiceRoleRpcClient) -> None:
        self._client = client

    def readback(
        self,
        authorization: PublisherArticleDeleteAuthorization,
    ) -> PublisherArticleDeleteApprovalReadback:
        response = _mapping(
            self._client.call(
                "volpred_read_publisher_article_delete_approval",
                {
                    "p_approval_ref": authorization.approval_ref,
                },
            ),
            field="publisher delete approval read-back",
        )
        return _approval_readback_from_payload(response)


class SupabasePublisherArticleDeleteProjection:
    """Exact candidate read-back plus transaction-fenced compare-delete."""

    def __init__(
        self,
        *,
        client: ServiceRoleRpcClient,
        attempt: OwnedPublisherDeleteAttempt,
        authorization: PublisherArticleDeleteAuthorization,
    ) -> None:
        self._client = client
        self._attempt = attempt
        self._authorization = authorization

    def readback(
        self,
        expected_candidate: Mapping[str, object],
    ) -> PublisherArticleDeleteCandidateReadback:
        return _read_publisher_article_delete_candidate(
            self._client,
            expected_candidate,
        )

    def delete(self, expected_candidate: Mapping[str, object]) -> bool:
        attempt = self._attempt
        parameters = {
            "p_owner_generation": attempt.owner_generation,
            "p_effect_id": attempt.effect.id,
            "p_attempt_count": attempt.attempt_count,
            "p_worker_id": attempt.worker_id,
            "p_primary_authority_key": attempt.primary_authority_key,
            "p_primary_authority_holder_ref": (
                attempt.primary_authority_holder_ref
            ),
            "p_primary_authority_epoch": attempt.primary_authority_epoch,
            "p_primary_fencing_token": attempt.primary_fencing_token,
            "p_authorization": _authorization_payload(
                self._authorization
            ),
            "p_expected_candidate": dict(expected_candidate),
        }
        try:
            execution = _mapping(
                self._client.call(
                    "volpred_execute_publisher_article_compare_delete",
                    parameters,
                ),
                field="publisher compare-delete execution",
            )
            if (
                execution.get("schema_version")
                != "publisher-article-compare-delete-execution.v1"
                or not isinstance(execution.get("ok"), bool)
            ):
                raise RuntimeError(
                    "publisher compare-delete execution envelope drifted"
                )
            if not execution["ok"]:
                database_error = _mapping(
                    execution.get("error"),
                    field="publisher compare-delete database error",
                )
                context = str(database_error.get("context") or "")
                location_match = re.search(
                    r"line \d+(?: at [^\n]+)?",
                    context,
                )
                location = (
                    location_match.group(0)
                    if location_match is not None
                    else "no line context"
                )
                raise RuntimeError(
                    "publisher compare-delete database error "
                    f"{database_error.get('sqlstate')}: "
                    f"{database_error.get('message')}; {location}"
                )
            raw_response = execution.get("result")
        except Exception as error:
            diagnostic = _mapping(
                self._client.call(
                    "volpred_diagnose_publisher_article_compare_delete",
                    parameters,
                ),
                field="publisher compare-delete diagnostic",
            )
            failed_checks = sorted(
                key
                for key, value in diagnostic.items()
                if key != "schema_version" and value is not True
            )
            raise RuntimeError(
                f"{error}; preflight_failed_checks="
                + json.dumps(failed_checks, separators=(",", ":"))
            ) from error
        response = _mapping(
            raw_response,
            field="publisher compare-delete response",
        )
        deleted = response.get("deleted")
        if not isinstance(deleted, bool):
            raise RuntimeError("publisher compare-delete deleted must be boolean")
        return deleted


class SupabasePublisherArticleDeleteRestoreProjection:
    """Service-role-only atomic projection for one exact recovery batch."""

    def __init__(
        self,
        *,
        client: ServiceRoleRpcClient,
    ) -> None:
        self._client = client

    @classmethod
    def from_environment(
        cls,
    ) -> SupabasePublisherArticleDeleteRestoreProjection:
        values = runtime_environment()
        return cls(
            client=ServiceRoleRpcClient(
                supabase_url=values.get("SUPABASE_URL", ""),
                service_role_key=values.get(
                    "SUPABASE_SERVICE_ROLE_KEY",
                    "",
                ),
                timeout_seconds=float(
                    values.get(
                        "VOLPRED_OPERATIONS_RPC_TIMEOUT_SEC",
                        "45",
                    )
                ),
            )
        )

    def readback(
        self,
        expected_candidate: Mapping[str, object],
    ) -> PublisherArticleDeleteCandidateReadback:
        return _read_publisher_article_delete_candidate(
            self._client,
            expected_candidate,
        )

    def restore_batch(
        self,
        expected_candidates: tuple[Mapping[str, object], ...],
    ) -> bool:
        if not expected_candidates:
            raise ValueError("publisher delete restore batch must not be empty")
        candidates = [dict(candidate) for candidate in expected_candidates]
        response = _mapping(
            self._client.call(
                "volpred_restore_publisher_article_delete_batch",
                {"p_expected_candidates": candidates},
            ),
            field="publisher delete restore response",
        )
        if (
            response.get("schema_version")
            != "publisher-article-delete-restore-batch.v1"
        ):
            raise RuntimeError(
                "publisher delete restore response schema drifted"
            )
        candidate_count = response.get("candidate_count")
        restored_count = response.get("restored_count")
        restored = response.get("restored")
        if (
            isinstance(candidate_count, bool)
            or not isinstance(candidate_count, int)
            or candidate_count != len(candidates)
            or isinstance(restored_count, bool)
            or not isinstance(restored_count, int)
            or restored_count < 0
            or restored_count > candidate_count
            or restored is not True
        ):
            raise RuntimeError(
                "publisher delete restore response identity drifted"
            )
        return True


class SupabasePublisherDeleteProviderFactory:
    """Bind each provider instance to one durable attempt and approval."""

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
    def from_environment(cls) -> SupabasePublisherDeleteProviderFactory:
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

    def __call__(
        self,
        attempt: OwnedPublisherDeleteAttempt,
    ) -> PublisherArticleDeleteEffectAdapter:
        payload = _mapping(
            json.loads(attempt.payload),
            field="publisher delete attempt payload",
        )
        authorization = _authorization_from_payload(
            _mapping(
                payload.get("authorization"),
                field="publisher delete authorization",
            )
        )
        return PublisherArticleDeleteEffectAdapter(
            approval=SupabasePublisherArticleDeleteApprovalVerifier(
                client=self._client,
            ),
            projection=SupabasePublisherArticleDeleteProjection(
                client=self._client,
                attempt=attempt,
                authorization=authorization,
            ),
        )


def _authorization_payload(
    authorization: PublisherArticleDeleteAuthorization,
) -> dict[str, str]:
    return {
        "approval_ref": authorization.approval_ref,
        "approver_ref": authorization.approver_ref,
        "approved_at": authorization.approved_at,
        "scope_sha256": authorization.scope_sha256,
    }


def _read_publisher_article_delete_candidate(
    client: ServiceRoleRpcClient,
    expected_candidate: Mapping[str, object],
) -> PublisherArticleDeleteCandidateReadback:
    article = _mapping(
        expected_candidate.get("article"),
        field="publisher delete expected article",
    )
    article_id = _required_text(
        article.get("id"),
        field="publisher delete expected article id",
    )
    response = _mapping(
        client.call(
            "volpred_read_publisher_article_delete_candidate",
            {"p_article_id": article_id},
        ),
        field="publisher delete candidate read-back",
    )
    candidate = response.get("candidate")
    if candidate is not None:
        candidate = dict(
            _mapping(
                candidate,
                field="publisher delete candidate",
            )
        )
    return PublisherArticleDeleteCandidateReadback(
        article_id=_required_text(
            response.get("article_id"),
            field="publisher delete read-back article_id",
        ),
        candidate=candidate,
        evidence_ref=_required_text(
            response.get("evidence_ref"),
            field="publisher delete candidate evidence_ref",
        ),
        evidence_sha256=_sha256(
            response.get("evidence_sha256"),
            field="publisher delete candidate evidence hash",
        ),
    )


def _authorization_from_payload(
    payload: Mapping[str, Any],
) -> PublisherArticleDeleteAuthorization:
    if set(payload) != {
        "approval_ref",
        "approver_ref",
        "approved_at",
        "scope_sha256",
    }:
        raise RuntimeError("publisher delete authorization fields drifted")
    return PublisherArticleDeleteAuthorization(
        approval_ref=_required_text(
            payload.get("approval_ref"),
            field="publisher delete approval_ref",
        ),
        approver_ref=_required_text(
            payload.get("approver_ref"),
            field="publisher delete approver_ref",
        ),
        approved_at=_required_text(
            payload.get("approved_at"),
            field="publisher delete approved_at",
        ),
        scope_sha256=_sha256(
            payload.get("scope_sha256"),
            field="publisher delete approval scope hash",
        ),
    )


def _approval_readback_from_payload(
    payload: Mapping[str, Any],
) -> PublisherArticleDeleteApprovalReadback:
    observed = _authorization_from_payload(
        _mapping(
            payload.get("authorization"),
            field="publisher delete approval authorization",
        )
    )
    active = payload.get("active")
    if not isinstance(active, bool):
        raise RuntimeError("publisher delete approval active must be boolean")
    return PublisherArticleDeleteApprovalReadback(
        authorization=observed,
        active=active,
        evidence_ref=_required_text(
            payload.get("evidence_ref"),
            field="publisher delete approval evidence_ref",
        ),
        evidence_sha256=_sha256(
            payload.get("evidence_sha256"),
            field="publisher delete approval evidence hash",
        ),
    )


def _normalize_command(
    command: OwnedPublisherDeleteCommand,
) -> OwnedPublisherDeleteCommand:
    if not isinstance(command, OwnedPublisherDeleteCommand):
        raise TypeError("OwnedPublisherDeleteCommand is required")
    prepared = command.prepared
    if not isinstance(prepared, PreparedPublisherArticleDelete):
        raise TypeError("prepared publisher delete intent is required")
    request = prepared.request
    if (
        request.effect_kind != _OWNER_FAMILY
        or request.target_ref != "supabase:articles"
        or request.risk != "destructive"
        or request.acknowledgement.kind
        != "publisher.article.supabase.delete.readback"
        or request.acknowledgement.target_ref != request.target_ref
        or hashlib.sha256(prepared.payload).hexdigest()
        != request.payload_sha256
    ):
        raise ValueError("prepared publisher delete effect contract drifted")
    decoded = _mapping(
        json.loads(prepared.payload),
        field="publisher delete payload",
    )
    if (
        decoded.get("schema_version") != "publisher-article-delete.v1"
        or _sha256(
            decoded.get("scope_sha256"),
            field="publisher delete scope hash",
        )
        != prepared.scope_sha256
    ):
        raise ValueError("prepared publisher delete payload identity drifted")
    return OwnedPublisherDeleteCommand(
        prepared=prepared,
        actor_ref=_required_text(
            command.actor_ref,
            field="owned publisher delete actor_ref",
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


def _owner_from_payload(
    payload: Mapping[str, Any],
) -> PublisherArticleDeleteOwner:
    owner = _required_text(
        payload.get("owner"),
        field="publisher delete owner",
    )
    if owner not in {_LEGACY_OWNER, _OPERATIONS_CORE_OWNER}:
        raise RuntimeError(f"unsupported publisher delete owner: {owner}")
    return PublisherArticleDeleteOwner(
        schema_version=_required_text(
            payload.get("schema_version"),
            field="publisher delete owner schema_version",
        ),
        effect_family=_required_text(
            payload.get("effect_family"),
            field="publisher delete effect_family",
        ),
        owner=owner,
        generation=_positive_integer(
            payload.get("generation"),
            field="publisher delete owner generation",
        ),
        changed_at=_required_text(
            payload.get("changed_at"),
            field="publisher delete owner changed_at",
        ),
        changed_by=_required_text(
            payload.get("changed_by"),
            field="publisher delete owner changed_by",
        ),
        change_reason=_required_text(
            payload.get("change_reason"),
            field="publisher delete owner change_reason",
        ),
    )


def _receipt_from_payload(
    payload: Mapping[str, Any],
) -> OwnedPublisherDeleteReceipt:
    return OwnedPublisherDeleteReceipt(
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
    receipt: OwnedPublisherDeleteReceipt,
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


def _reconciliation_summary_from_payload(
    payload: Mapping[str, Any],
) -> OwnedPublisherDeleteReconciliationSummary:
    if (
        payload.get("schema_version")
        != "owned-publisher-delete-reconciliation-summary.v1"
    ):
        raise RuntimeError(
            "owned publisher delete reconciliation summary schema drift"
        )
    receipts_payload = payload.get("receipts")
    if not isinstance(receipts_payload, list):
        raise RuntimeError(
            "owned publisher delete reconciliation receipts must be a list"
        )
    receipts: list[OwnedPublisherDeleteReconciliationReceipt] = []
    for value in receipts_payload:
        receipt = _mapping(
            value,
            field="owned publisher delete reconciliation receipt",
        )
        if (
            receipt.get("schema_version")
            != "owned-publisher-delete-reconciliation-receipt.v1"
        ):
            raise RuntimeError(
                "owned publisher delete reconciliation receipt schema drift"
            )
        receipts.append(
            OwnedPublisherDeleteReconciliationReceipt(
                schema_version=str(receipt["schema_version"]),
                effect_id=_required_text(
                    receipt.get("effect_id"),
                    field="reconciliation effect_id",
                ),
                attempt_count=_positive_integer(
                    receipt.get("attempt_count"),
                    field="reconciliation attempt_count",
                ),
                stale_owner_generation=_positive_integer(
                    receipt.get("stale_owner_generation"),
                    field="reconciliation stale_owner_generation",
                ),
                current_owner_generation=_positive_integer(
                    receipt.get("current_owner_generation"),
                    field="reconciliation current_owner_generation",
                ),
                approval_ref=_required_text(
                    receipt.get("approval_ref"),
                    field="reconciliation approval_ref",
                ),
                reason_code=_required_text(
                    receipt.get("reason_code"),
                    field="reconciliation reason_code",
                ),
                evidence_ref=_required_text(
                    receipt.get("evidence_ref"),
                    field="reconciliation evidence_ref",
                ),
                evidence_sha256=_sha256(
                    receipt.get("evidence_sha256"),
                    field="reconciliation evidence_sha256",
                ),
                recorded_at=_required_text(
                    receipt.get("recorded_at"),
                    field="reconciliation recorded_at",
                ),
            )
        )
    reconciled_count = payload.get("reconciled_count")
    if (
        isinstance(reconciled_count, bool)
        or not isinstance(reconciled_count, int)
        or reconciled_count < 0
        or reconciled_count != len(receipts)
    ):
        raise RuntimeError(
            "owned publisher delete reconciliation count drift"
        )
    return OwnedPublisherDeleteReconciliationSummary(
        schema_version=str(payload["schema_version"]),
        reconciled_count=reconciled_count,
        receipts=tuple(receipts),
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


__all__ = [
    "OwnedPublisherDeleteAttempt",
    "OwnedPublisherDeleteCommand",
    "OwnedPublisherDeleteReconciliation",
    "OwnedPublisherDeleteReconciliationReceipt",
    "OwnedPublisherDeleteReconciliationSummary",
    "OwnedPublisherDeleteReceipt",
    "OwnedPublisherDeleteRequest",
    "OwnedPublisherArticleDelete",
    "PublisherArticleDeleteOwner",
    "PublisherArticleDeleteOwnershipLost",
    "SupabasePublisherArticleDeleteApprovalVerifier",
    "SupabasePublisherArticleDeleteProjection",
    "SupabasePublisherArticleDeleteRestoreProjection",
    "SupabasePublisherDeleteProviderFactory",
    "SupabaseOwnedPublisherDeleteStore",
]
