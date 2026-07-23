"""Shadow Work Coordinator public interface.

This module is intentionally disconnected from the live task pool.  It is the
test-first implementation of the interface accepted in
``docs/operations_core_module_design.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re
from typing import Callable, Protocol
from uuid import uuid4


_SUPPORTED_RISKS = frozenset({"safe", "sensitive", "destructive"})
_SUPPORTED_REQUEST_APPROVALS = frozenset({"auto", "required"})


class ClaimLost(RuntimeError):
    """The caller no longer owns the WorkItem claim."""


@dataclass(frozen=True)
class WorkRequest:
    idempotency_key: str
    source: str
    kind: str
    title: str
    priority: int
    required_capabilities: frozenset[str]
    required_attestations: frozenset[str]
    risk: str
    approval: str
    payload_ref: str
    parent_id: str | None = None
    deadline: str | None = None
    requester_ref: str | None = None


@dataclass(frozen=True)
class WorkItemView:
    id: str
    idempotency_key: str
    source: str
    kind: str
    title: str
    priority: int
    required_capabilities: frozenset[str]
    required_attestations: frozenset[str]
    risk: str
    approval: str
    payload_ref: str
    status: str
    version: int
    created_at: str
    parent_id: str | None = None
    deadline: str | None = None
    requester_ref: str | None = None
    updated_at: str | None = None
    blocked_reason: str | None = None
    claimed_by: str | None = None
    claim_expires_at: str | None = None
    latest_verified_checkpoint_id: str | None = None
    last_release_reason: str | None = None
    result_ref: str | None = None
    result_summary: str | None = None
    finished_at: str | None = None


@dataclass(frozen=True)
class WorkerOffer:
    worker_id: str
    capabilities: frozenset[str]
    attestations: frozenset[str]
    lease_seconds: int


@dataclass(frozen=True)
class WorkLease:
    token: str
    work_item: WorkItemView
    expires_at: str
    resume_checkpoint_id: str | None = None


@dataclass(frozen=True)
class ApprovalGranted:
    work_id: str
    expected_version: int
    approved_by: str
    evidence_ref: str


@dataclass(frozen=True)
class Started:
    work_id: str
    lease_token: str
    expected_version: int


@dataclass(frozen=True)
class Checkpointed:
    report_id: str
    work_id: str
    lease_token: str
    expected_version: int
    artifact_ref: str
    artifact_sha256: str
    verification_ref: str


@dataclass(frozen=True)
class Released:
    work_id: str
    lease_token: str
    expected_version: int
    reason: str


@dataclass(frozen=True)
class Completed:
    report_id: str
    work_id: str
    lease_token: str
    expected_version: int
    result_ref: str
    summary: str


@dataclass(frozen=True)
class VerifiedCheckpointView:
    id: str
    work_id: str
    artifact_ref: str
    artifact_sha256: str
    verification_ref: str
    created_at: str


@dataclass(frozen=True)
class WorkReceiptView:
    id: str
    work_id: str
    outcome: str
    result_ref: str
    summary: str
    created_at: str


@dataclass(frozen=True)
class WorkEventView:
    work_id: str
    kind: str
    version: int
    created_at: str
    actor_ref: str | None = None
    evidence_ref: str | None = None


@dataclass(frozen=True)
class WorkQuery:
    work_id: str | None = None


@dataclass(frozen=True)
class WorkSnapshot:
    items: tuple[WorkItemView, ...]
    events: tuple[WorkEventView, ...] = ()
    checkpoints: tuple[VerifiedCheckpointView, ...] = ()
    receipts: tuple[WorkReceiptView, ...] = ()


class _CoordinationStore(Protocol):
    def create_if_absent(
        self, idempotency_key: str, candidate: WorkItemView
    ) -> WorkItemView: ...

    def inspect(self, query: WorkQuery) -> tuple[WorkItemView, ...]: ...

    def inspect_events(self, query: WorkQuery) -> tuple[WorkEventView, ...]: ...

    def acquire(
        self,
        offer: WorkerOffer,
        *,
        token: str,
        claimed_at: str,
        expires_at: str,
    ) -> WorkLease | None: ...

    def approve(
        self,
        report: ApprovalGranted,
        *,
        created_at: str,
    ) -> WorkItemView: ...

    def start(
        self,
        work_id: str,
        *,
        lease_token: str,
        expected_version: int,
        observed_at: str,
    ) -> WorkItemView: ...

    def checkpoint(
        self,
        report: Checkpointed,
        *,
        checkpoint_id: str,
        created_at: str,
    ) -> WorkItemView: ...

    def inspect_checkpoints(
        self, query: WorkQuery
    ) -> tuple[VerifiedCheckpointView, ...]: ...

    def release(self, report: Released, *, observed_at: str) -> WorkItemView: ...

    def complete(self, report: Completed, *, created_at: str) -> WorkItemView: ...

    def inspect_receipts(self, query: WorkQuery) -> tuple[WorkReceiptView, ...]: ...


class WorkCoordinator:
    """Own durable work identity behind the accepted four-method interface."""

    def __init__(
        self,
        store: _CoordinationStore,
        *,
        clock: Callable[[], datetime],
        id_factory: Callable[[], str],
        token_factory: Callable[[], str] | None = None,
        checkpoint_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._store = store
        self._clock = clock
        self._id_factory = id_factory
        self._token_factory = token_factory or (lambda: f"claim_{uuid4().hex}")
        self._checkpoint_id_factory = checkpoint_id_factory or (
            lambda: f"checkpoint_{uuid4().hex}"
        )

    def submit(self, request: WorkRequest) -> WorkItemView:
        if (
            request.risk not in _SUPPORTED_RISKS
            or request.approval not in _SUPPORTED_REQUEST_APPROVALS
        ):
            raise ValueError(
                f"unsupported work policy: risk={request.risk!r}, "
                f"approval={request.approval!r}"
            )
        requires_approval = request.approval == "required" or request.risk != "safe"
        deadline = None
        if request.deadline is not None:
            parsed_deadline = datetime.fromisoformat(request.deadline)
            if parsed_deadline.tzinfo is None:
                raise ValueError("deadline must include a timezone")
            deadline = parsed_deadline.astimezone(timezone.utc).isoformat()
        created_at = self._clock().isoformat()
        candidate = WorkItemView(
            id=self._id_factory(),
            idempotency_key=request.idempotency_key,
            source=request.source,
            kind=request.kind,
            title=request.title,
            priority=request.priority,
            required_capabilities=request.required_capabilities,
            required_attestations=request.required_attestations,
            risk=request.risk,
            approval=request.approval,
            payload_ref=request.payload_ref,
            parent_id=request.parent_id,
            deadline=deadline,
            requester_ref=request.requester_ref or request.source,
            status="awaiting_approval" if requires_approval else "pending",
            version=1,
            created_at=created_at,
            updated_at=created_at,
        )
        return self._store.create_if_absent(request.idempotency_key, candidate)

    def inspect(self, query: WorkQuery) -> WorkSnapshot:
        return WorkSnapshot(
            items=self._store.inspect(query),
            events=self._store.inspect_events(query),
            checkpoints=self._store.inspect_checkpoints(query),
            receipts=self._store.inspect_receipts(query),
        )

    def acquire(self, offer: WorkerOffer) -> WorkLease | None:
        if offer.lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        now = self._clock()
        token = self._token_factory()
        if not token:
            raise ValueError("claim token is required")
        return self._store.acquire(
            offer,
            token=token,
            claimed_at=now.isoformat(),
            expires_at=(now + timedelta(seconds=offer.lease_seconds)).isoformat(),
        )

    def record(
        self,
        report: ApprovalGranted | Started | Checkpointed | Released | Completed,
    ) -> WorkItemView:
        if isinstance(report, ApprovalGranted):
            return self._store.approve(
                report,
                created_at=self._clock().isoformat(),
            )
        if isinstance(report, Started):
            return self._store.start(
                report.work_id,
                lease_token=report.lease_token,
                expected_version=report.expected_version,
                observed_at=self._clock().isoformat(),
            )
        if isinstance(report, Released):
            return self._store.release(report, observed_at=self._clock().isoformat())
        if isinstance(report, Completed):
            return self._store.complete(
                report,
                created_at=self._clock().isoformat(),
            )
        if not re.fullmatch(r"[0-9a-f]{64}", report.artifact_sha256):
            raise ValueError("checkpoint artifact_sha256 must be 64 lowercase hex characters")
        if not report.report_id:
            raise ValueError("checkpoint report_id is required")
        return self._store.checkpoint(
            report,
            checkpoint_id=report.report_id,
            created_at=self._clock().isoformat(),
        )


__all__ = [
    "ApprovalGranted",
    "Checkpointed",
    "ClaimLost",
    "Completed",
    "Released",
    "Started",
    "VerifiedCheckpointView",
    "WorkCoordinator",
    "WorkEventView",
    "WorkItemView",
    "WorkLease",
    "WorkQuery",
    "WorkRequest",
    "WorkReceiptView",
    "WorkSnapshot",
    "WorkerOffer",
]
