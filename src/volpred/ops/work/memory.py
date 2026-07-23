"""Transaction-safe in-memory coordination adapter for interface tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from threading import RLock

from . import (
    ApprovalGranted,
    Checkpointed,
    ClaimLost,
    Completed,
    Released,
    VerifiedCheckpointView,
    WorkEventView,
    WorkItemView,
    WorkLease,
    WorkQuery,
    WorkReceiptView,
    WorkerOffer,
)


class InMemoryCoordinationStore:
    def __init__(self) -> None:
        self._lock = RLock()
        self._by_id: dict[str, WorkItemView] = {}
        self._id_by_idempotency_key: dict[str, str] = {}
        self._claim_token_by_id: dict[str, str] = {}
        self._events_by_work_id: dict[str, list[WorkEventView]] = {}
        self._checkpoints_by_work_id: dict[str, list[VerifiedCheckpointView]] = {}
        self._receipts_by_work_id: dict[str, list[WorkReceiptView]] = {}
        self._checkpoint_by_report_id: dict[str, VerifiedCheckpointView] = {}
        self._terminal_by_report_id: dict[str, WorkItemView] = {}

    def _append_event(
        self,
        item: WorkItemView,
        *,
        kind: str,
        created_at: str,
        actor_ref: str | None = None,
        evidence_ref: str | None = None,
    ) -> None:
        self._events_by_work_id.setdefault(item.id, []).append(
            WorkEventView(
                work_id=item.id,
                kind=kind,
                version=item.version,
                created_at=created_at,
                actor_ref=actor_ref,
                evidence_ref=evidence_ref,
            )
        )

    def _require_active_claim(
        self,
        current: WorkItemView,
        *,
        lease_token: str,
        expected_version: int,
        observed_at: str,
        valid_statuses: frozenset[str],
    ) -> None:
        if self._claim_token_by_id.get(current.id) != lease_token:
            raise ClaimLost(current.id)
        if (
            current.claim_expires_at is None
            or datetime.fromisoformat(current.claim_expires_at)
            <= datetime.fromisoformat(observed_at)
        ):
            raise ClaimLost(current.id)
        if current.version != expected_version:
            raise ValueError(
                f"stale work item version: expected {expected_version}, "
                f"found {current.version}"
            )
        if current.status not in valid_statuses:
            raise ValueError(
                f"cannot mutate work item {current.id} from {current.status}"
            )

    def create_if_absent(
        self, idempotency_key: str, candidate: WorkItemView
    ) -> WorkItemView:
        with self._lock:
            existing_id = self._id_by_idempotency_key.get(idempotency_key)
            if existing_id is not None:
                return self._by_id[existing_id]
            self._by_id[candidate.id] = candidate
            self._id_by_idempotency_key[idempotency_key] = candidate.id
            self._append_event(
                candidate,
                kind="submitted",
                created_at=candidate.created_at,
            )
            return candidate

    def inspect(self, query: WorkQuery) -> tuple[WorkItemView, ...]:
        with self._lock:
            if query.work_id is not None:
                item = self._by_id.get(query.work_id)
                return (item,) if item is not None else ()
            return tuple(self._by_id[key] for key in sorted(self._by_id))

    def inspect_events(self, query: WorkQuery) -> tuple[WorkEventView, ...]:
        with self._lock:
            if query.work_id is None:
                return tuple(
                    event
                    for work_id in sorted(self._events_by_work_id)
                    for event in self._events_by_work_id[work_id]
                )
            return tuple(self._events_by_work_id.get(query.work_id, ()))

    def inspect_checkpoints(
        self, query: WorkQuery
    ) -> tuple[VerifiedCheckpointView, ...]:
        with self._lock:
            if query.work_id is None:
                return tuple(
                    checkpoint
                    for work_id in sorted(self._checkpoints_by_work_id)
                    for checkpoint in self._checkpoints_by_work_id[work_id]
                )
            return tuple(self._checkpoints_by_work_id.get(query.work_id, ()))

    def inspect_receipts(self, query: WorkQuery) -> tuple[WorkReceiptView, ...]:
        with self._lock:
            if query.work_id is None:
                return tuple(
                    receipt
                    for work_id in sorted(self._receipts_by_work_id)
                    for receipt in self._receipts_by_work_id[work_id]
                )
            return tuple(self._receipts_by_work_id.get(query.work_id, ()))

    def acquire(
        self,
        offer: WorkerOffer,
        *,
        token: str,
        claimed_at: str,
        expires_at: str,
    ) -> WorkLease | None:
        with self._lock:
            candidates = sorted(
                (
                    item
                    for item in self._by_id.values()
                    if (
                        item.status == "pending"
                        or (
                            item.status in {"claimed", "running"}
                            and item.claim_expires_at is not None
                            and datetime.fromisoformat(item.claim_expires_at)
                            <= datetime.fromisoformat(claimed_at)
                        )
                    )
                    and item.required_capabilities <= offer.capabilities
                    and item.required_attestations <= offer.attestations
                    and (
                        item.parent_id is None
                        or (
                            item.parent_id in self._by_id
                            and self._by_id[item.parent_id].status == "succeeded"
                        )
                    )
                ),
                key=lambda item: (
                    item.priority,
                    item.deadline is None,
                    item.deadline or "",
                    item.created_at,
                    item.id,
                ),
            )
            if not candidates:
                return None
            current = candidates[0]
            claimed = replace(
                current,
                status="claimed",
                version=current.version + 1,
                claimed_by=offer.worker_id,
                claim_expires_at=expires_at,
                updated_at=claimed_at,
            )
            self._by_id[claimed.id] = claimed
            self._claim_token_by_id[claimed.id] = token
            self._append_event(claimed, kind="acquired", created_at=claimed_at)
            return WorkLease(
                token=token,
                work_item=claimed,
                expires_at=expires_at,
                resume_checkpoint_id=claimed.latest_verified_checkpoint_id,
            )

    def approve(
        self,
        report: ApprovalGranted,
        *,
        created_at: str,
    ) -> WorkItemView:
        with self._lock:
            current = self._by_id.get(report.work_id)
            if current is None:
                raise ValueError(f"unknown work item: {report.work_id}")
            if current.version != report.expected_version:
                raise ValueError(
                    f"stale work item version: expected {report.expected_version}, "
                    f"found {current.version}"
                )
            if current.status != "awaiting_approval":
                raise ValueError(
                    f"cannot approve work item {report.work_id} from {current.status}"
                )
            if not report.approved_by or not report.evidence_ref:
                raise ValueError("approval requires actor and evidence references")
            approved = replace(
                current,
                approval="approved",
                status="pending",
                version=current.version + 1,
                updated_at=created_at,
            )
            self._by_id[report.work_id] = approved
            self._append_event(
                approved,
                kind="approval_granted",
                created_at=created_at,
                actor_ref=report.approved_by,
                evidence_ref=report.evidence_ref,
            )
            return approved

    def start(
        self,
        work_id: str,
        *,
        lease_token: str,
        expected_version: int,
        observed_at: str,
    ) -> WorkItemView:
        with self._lock:
            current = self._by_id.get(work_id)
            if current is None:
                raise ValueError(f"unknown work item: {work_id}")
            self._require_active_claim(
                current,
                lease_token=lease_token,
                expected_version=expected_version,
                observed_at=observed_at,
                valid_statuses=frozenset({"claimed"}),
            )
            running = replace(
                current,
                status="running",
                version=current.version + 1,
                updated_at=observed_at,
            )
            self._by_id[work_id] = running
            self._append_event(running, kind="started", created_at=observed_at)
            return running

    def checkpoint(
        self,
        report: Checkpointed,
        *,
        checkpoint_id: str,
        created_at: str,
    ) -> WorkItemView:
        with self._lock:
            current = self._by_id.get(report.work_id)
            if current is None:
                raise ValueError(f"unknown work item: {report.work_id}")
            replay = self._checkpoint_by_report_id.get(report.report_id)
            if replay is not None:
                if (
                    replay.work_id != report.work_id
                    or replay.artifact_ref != report.artifact_ref
                    or replay.artifact_sha256 != report.artifact_sha256
                    or replay.verification_ref != report.verification_ref
                ):
                    raise ValueError(
                        f"checkpoint report {report.report_id} conflicts "
                        "with its original payload"
                    )
                return current
            self._require_active_claim(
                current,
                lease_token=report.lease_token,
                expected_version=report.expected_version,
                observed_at=created_at,
                valid_statuses=frozenset({"running"}),
            )
            checkpoint = VerifiedCheckpointView(
                id=checkpoint_id,
                work_id=report.work_id,
                artifact_ref=report.artifact_ref,
                artifact_sha256=report.artifact_sha256,
                verification_ref=report.verification_ref,
                created_at=created_at,
            )
            self._checkpoints_by_work_id.setdefault(report.work_id, []).append(
                checkpoint
            )
            self._checkpoint_by_report_id[report.report_id] = checkpoint
            checkpointed = replace(
                current,
                version=current.version + 1,
                latest_verified_checkpoint_id=checkpoint.id,
                updated_at=created_at,
            )
            self._by_id[report.work_id] = checkpointed
            self._append_event(
                checkpointed,
                kind="checkpointed",
                created_at=created_at,
            )
            return checkpointed

    def release(self, report: Released, *, observed_at: str) -> WorkItemView:
        with self._lock:
            current = self._by_id.get(report.work_id)
            if current is None:
                raise ValueError(f"unknown work item: {report.work_id}")
            self._require_active_claim(
                current,
                lease_token=report.lease_token,
                expected_version=report.expected_version,
                observed_at=observed_at,
                valid_statuses=frozenset({"claimed", "running"}),
            )
            released = replace(
                current,
                status="pending",
                version=current.version + 1,
                claimed_by=None,
                claim_expires_at=None,
                last_release_reason=report.reason,
                updated_at=observed_at,
            )
            self._by_id[report.work_id] = released
            self._claim_token_by_id.pop(report.work_id, None)
            self._append_event(released, kind="released", created_at=observed_at)
            return released

    def complete(self, report: Completed, *, created_at: str) -> WorkItemView:
        with self._lock:
            replay = self._terminal_by_report_id.get(report.report_id)
            if replay is not None:
                if replay.id != report.work_id:
                    raise ValueError(
                        f"completion report {report.report_id} belongs to {replay.id}"
                    )
                return replay
            current = self._by_id.get(report.work_id)
            if current is None:
                raise ValueError(f"unknown work item: {report.work_id}")
            self._require_active_claim(
                current,
                lease_token=report.lease_token,
                expected_version=report.expected_version,
                observed_at=created_at,
                valid_statuses=frozenset({"running"}),
            )
            completed = replace(
                current,
                status="succeeded",
                version=current.version + 1,
                claimed_by=None,
                claim_expires_at=None,
                result_ref=report.result_ref,
                result_summary=report.summary,
                finished_at=created_at,
                updated_at=created_at,
            )
            receipt = WorkReceiptView(
                id=report.report_id,
                work_id=report.work_id,
                outcome="succeeded",
                result_ref=report.result_ref,
                summary=report.summary,
                created_at=created_at,
            )
            self._by_id[report.work_id] = completed
            self._receipts_by_work_id.setdefault(report.work_id, []).append(receipt)
            self._terminal_by_report_id[report.report_id] = completed
            self._claim_token_by_id.pop(report.work_id, None)
            self._append_event(completed, kind="completed", created_at=created_at)
            return completed
