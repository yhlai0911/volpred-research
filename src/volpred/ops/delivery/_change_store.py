"""Private durable state contract for Change Delivery.

The store owns the immutable proposal, the token-redacted actuation checkpoint,
and the final delivery receipt.  Raw WorkLease and Primary Authority tokens are
never part of this seam; only the payload-bound landing-command digest is
retained.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from threading import RLock
from typing import Protocol

from . import ChangeSetConflict, ChangeSetView, DeliveryReceipt
from ._git_actuator import CommitActuationReceipt


@dataclass(frozen=True)
class ChangeSetRecord:
    view: ChangeSetView
    land_command_sha256: str | None = None
    actuation: CommitActuationReceipt | None = None
    delivery: DeliveryReceipt | None = None


class ChangeSetStore(Protocol):
    def create(self, view: ChangeSetView) -> ChangeSetRecord: ...

    def load(self, change_set_id: str) -> ChangeSetRecord: ...

    def load_by_idempotency_key(
        self,
        idempotency_key: str,
    ) -> ChangeSetRecord | None: ...

    def checkpoint_actuation(
        self,
        *,
        change_set_id: str,
        proposal_sha256: str,
        land_command_sha256: str,
        actuation: CommitActuationReceipt,
    ) -> ChangeSetRecord: ...

    def mark_landed(
        self,
        *,
        change_set_id: str,
        proposal_sha256: str,
        land_command_sha256: str,
        delivery: DeliveryReceipt,
    ) -> ChangeSetRecord: ...


class InMemoryChangeSetStore:
    """Process-local adapter used by interface tests and shadow callers."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._by_id: dict[str, ChangeSetRecord] = {}
        self._id_by_idempotency_key: dict[str, str] = {}

    def create(self, view: ChangeSetView) -> ChangeSetRecord:
        with self._lock:
            existing_id = self._id_by_idempotency_key.get(view.idempotency_key)
            if existing_id is not None:
                existing = self._by_id[existing_id]
                if existing.view.proposal_sha256 != view.proposal_sha256:
                    raise ChangeSetConflict(
                        "ChangeSet idempotency key conflicts with its original payload"
                    )
                return existing
            if view.id in self._by_id:
                raise ValueError(f"duplicate ChangeSet id: {view.id}")
            record = ChangeSetRecord(view=view)
            self._by_id[view.id] = record
            self._id_by_idempotency_key[view.idempotency_key] = view.id
            return record

    def load(self, change_set_id: str) -> ChangeSetRecord:
        with self._lock:
            try:
                return self._by_id[change_set_id]
            except KeyError as exc:
                raise ValueError(f"unknown ChangeSet: {change_set_id}") from exc

    def load_by_idempotency_key(
        self,
        idempotency_key: str,
    ) -> ChangeSetRecord | None:
        with self._lock:
            change_set_id = self._id_by_idempotency_key.get(idempotency_key)
            return (
                self._by_id[change_set_id]
                if change_set_id is not None
                else None
            )

    def checkpoint_actuation(
        self,
        *,
        change_set_id: str,
        proposal_sha256: str,
        land_command_sha256: str,
        actuation: CommitActuationReceipt,
    ) -> ChangeSetRecord:
        with self._lock:
            current = self.load(change_set_id)
            self._require_identity(
                current,
                proposal_sha256=proposal_sha256,
                land_command_sha256=land_command_sha256,
            )
            if current.actuation is not None:
                if current.actuation != actuation:
                    raise ChangeSetConflict(
                        "ChangeSet actuation conflicts with its durable checkpoint"
                    )
                return current
            if current.view.status != "proposed":
                raise ChangeSetConflict(
                    f"ChangeSet cannot checkpoint actuation from {current.view.status}"
                )
            updated = replace(
                current,
                view=replace(current.view, status="commit_unsettled"),
                land_command_sha256=land_command_sha256,
                actuation=actuation,
            )
            self._by_id[change_set_id] = updated
            return updated

    def mark_landed(
        self,
        *,
        change_set_id: str,
        proposal_sha256: str,
        land_command_sha256: str,
        delivery: DeliveryReceipt,
    ) -> ChangeSetRecord:
        with self._lock:
            current = self.load(change_set_id)
            self._require_identity(
                current,
                proposal_sha256=proposal_sha256,
                land_command_sha256=land_command_sha256,
            )
            if current.delivery is not None:
                if current.delivery != delivery:
                    raise ChangeSetConflict(
                        "ChangeSet delivery conflicts with its durable receipt"
                    )
                return current
            if current.view.status != "commit_unsettled":
                raise ChangeSetConflict(
                    f"ChangeSet cannot land from {current.view.status}"
                )
            if (
                current.actuation is None
                or delivery.authority_request_sha256
                != current.actuation.authority_request_sha256
            ):
                raise ChangeSetConflict(
                    "ChangeSet delivery does not match its actuation checkpoint"
                )
            updated = replace(
                current,
                view=replace(current.view, status="landed"),
                delivery=delivery,
            )
            self._by_id[change_set_id] = updated
            return updated

    @staticmethod
    def _require_identity(
        record: ChangeSetRecord,
        *,
        proposal_sha256: str,
        land_command_sha256: str,
    ) -> None:
        if record.view.proposal_sha256 != proposal_sha256:
            raise ChangeSetConflict(
                "ChangeSet proposal identity drifted from durable state"
            )
        if (
            record.land_command_sha256 is not None
            and record.land_command_sha256 != land_command_sha256
        ):
            raise ChangeSetConflict(
                "ChangeSet landing command conflicts with its original payload"
            )


__all__ = [
    "ChangeSetRecord",
    "ChangeSetStore",
    "InMemoryChangeSetStore",
]
