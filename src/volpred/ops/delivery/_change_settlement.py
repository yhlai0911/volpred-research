"""Private durable-settlement contract for Change Delivery commits."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Protocol

from . import DeliveryReceipt
from ._git_actuator import CommitActuationReceipt


@dataclass(frozen=True)
class CommitSettlement:
    change_set_id: str
    repository: str
    work_lease_token: str
    primary_fencing_token: str
    actuation: CommitActuationReceipt


class CommitSettlementStore(Protocol):
    def settle(self, command: CommitSettlement) -> DeliveryReceipt: ...


class CommitSettlementBlocked(RuntimeError):
    """The external commit could not be durably acknowledged."""


def commit_settlement_sha256(command: CommitSettlement) -> str:
    """Bind the exact verified actuation without persisting raw lease tokens."""

    receipt = command.actuation
    encoded = json.dumps(
        {
            "schema_version": "change-delivery-settlement.v1",
            "change_set_id": command.change_set_id,
            "proposal_sha256": receipt.proposal_sha256,
            "work_item_id": receipt.work_item_id,
            "work_item_version": receipt.work_item_version,
            "authority_request_sha256": receipt.authority_request_sha256,
            "work_lease_ref": receipt.work_lease_ref,
            "primary_authority_ref": receipt.primary_authority_ref,
            "repository": command.repository,
            "commit_sha": receipt.commit_sha,
            "parent_sha": receipt.parent_sha,
            "exact_paths": list(receipt.exact_paths),
            "actor": receipt.actor,
            "status": receipt.status,
            "actuation_observed_at": receipt.observed_at,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "CommitSettlement",
    "CommitSettlementBlocked",
    "CommitSettlementStore",
    "commit_settlement_sha256",
]
