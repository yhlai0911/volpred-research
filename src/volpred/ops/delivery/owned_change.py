"""Formal Work Coordinator caller for owner-fenced Change Delivery.

This module keeps the external interface small: one command verifies the
durable Git owner generation, proposes and lands one immutable ChangeSet, then
reads the Work Coordinator terminal receipt produced atomically by PostgreSQL
settlement.  It never changes live Git ownership itself.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from psycopg import Connection

from volpred.ops.authority import PrimaryLease
from volpred.ops.work import WorkItemView, WorkQuery, WorkSnapshot

from . import (
    ChangeDelivery,
    ChangeSetProposal,
    ChangeSetView,
    DeliveryReceipt,
    LandChangeSet,
)


_COMMIT_CAPABILITY = "git.commit"
_OPERATIONS_CORE_OWNER = "operations_core"
_COMPLETION_SUMMARY = "ChangeSet landed with verified commit read-back"


class CommitOwnershipLost(RuntimeError):
    """Operations Core does not hold the requested Git owner generation."""


@dataclass(frozen=True)
class CommitOwner:
    schema_version: str
    capability: str
    owner: str
    generation: int
    changed_at: str
    changed_by: str
    change_reason: str

    @property
    def owner_ref(self) -> str:
        return (
            f"commit-owner:{self.capability}:generation-{self.generation}"
        )


@dataclass(frozen=True)
class OwnedChangeCommand:
    proposal: ChangeSetProposal
    work_lease_token: str
    primary_fencing_token: str
    repository: str
    message: str
    actor: str


@dataclass(frozen=True)
class OwnedChangeReceipt:
    owner: CommitOwner
    delivery: DeliveryReceipt
    work_item: WorkItemView


class _CommitOwnerStore(Protocol):
    def read_owner(self) -> CommitOwner: ...


class _ChangeDelivery(Protocol):
    def propose(self, proposal: ChangeSetProposal) -> ChangeSetView: ...

    def land(self, command: LandChangeSet) -> DeliveryReceipt: ...


class _WorkReadModel(Protocol):
    def inspect(self, query: WorkQuery) -> WorkSnapshot: ...


class OwnedChangeDelivery:
    """Own generation check, Change Delivery, and terminal Work read-back."""

    def __init__(
        self,
        *,
        owner_store: _CommitOwnerStore,
        delivery: _ChangeDelivery,
        coordinator: _WorkReadModel,
    ) -> None:
        self._owner_store = owner_store
        self._delivery = delivery
        self._coordinator = coordinator

    def deliver(self, command: OwnedChangeCommand) -> OwnedChangeReceipt:
        if not isinstance(command, OwnedChangeCommand):
            raise TypeError("OwnedChangeCommand is required")
        owner = self._owner_store.read_owner()
        if (
            owner.schema_version != "commit-owner.v1"
            or owner.capability != _COMMIT_CAPABILITY
            or owner.owner != _OPERATIONS_CORE_OWNER
            or owner.generation <= 0
        ):
            raise CommitOwnershipLost(
                "operations core does not own git.commit"
            )

        change_set = self._delivery.propose(command.proposal)
        if (
            change_set.work_item_id != command.proposal.work_item_id
            or change_set.work_item_version
            != command.proposal.work_item_version
        ):
            raise RuntimeError(
                "ChangeSet proposal read-back drifted from its WorkItem"
            )
        delivery = self._delivery.land(
            LandChangeSet(
                change_set_id=change_set.id,
                commit_owner_generation=owner.generation,
                work_lease_token=command.work_lease_token,
                primary_fencing_token=command.primary_fencing_token,
                repository=command.repository,
                message=command.message,
                actor=command.actor,
            )
        )
        if (
            delivery.commit_owner_generation != owner.generation
            or delivery.commit_owner_ref != owner.owner_ref
        ):
            raise RuntimeError(
                "Change Delivery receipt commit owner generation drifted"
            )

        snapshot = self._coordinator.inspect(
            WorkQuery(work_id=delivery.work_item_id)
        )
        if len(snapshot.items) != 1:
            raise RuntimeError(
                "WorkItem completion read-back returned an invalid cardinality"
            )
        completed = snapshot.items[0]
        if (
            completed.id != delivery.work_item_id
            or completed.status != "succeeded"
            or completed.version != delivery.work_item_version + 1
            or completed.result_ref != delivery.settlement_ref
            or completed.result_summary != _COMPLETION_SUMMARY
            or completed.finished_at is None
            or completed.claimed_by is not None
        ):
            raise RuntimeError(
                "WorkItem completion read-back did not match Change Delivery"
            )
        return OwnedChangeReceipt(
            owner=owner,
            delivery=delivery,
            work_item=completed,
        )


ConnectionFactory = Callable[[], Connection[Any]]


def build_postgres_owned_change_delivery(
    connection_factory: ConnectionFactory,
    *,
    primary_lease: PrimaryLease,
    clock: Callable[[], datetime],
    change_set_id_factory: Callable[[], str],
    writer_cli: Path | None = None,
) -> OwnedChangeDelivery:
    """Wire every durable adapter for the non-live formal commit caller."""

    from volpred.ops.work import WorkCoordinator
    from volpred.ops.work.postgres import PostgresCoordinationStore

    from ._git_actuator import GitCommitActuator
    from .postgres_change_store import PostgresChangeSetStore
    from .postgres_commit_authority import PostgresCommitAuthority
    from .postgres_commit_ownership import PostgresCommitOwnerStore
    from .postgres_commit_settlement import PostgresCommitSettlement

    authority = PostgresCommitAuthority(
        connection_factory,
        primary_lease=primary_lease,
    )
    actuator = (
        GitCommitActuator(clock=clock, authority=authority)
        if writer_cli is None
        else GitCommitActuator(
            clock=clock,
            authority=authority,
            writer_cli=writer_cli,
        )
    )
    delivery = ChangeDelivery(
        clock=clock,
        id_factory=change_set_id_factory,
        actuator=actuator,
        settlement=PostgresCommitSettlement(
            connection_factory,
            primary_lease=primary_lease,
        ),
        store=PostgresChangeSetStore(connection_factory),
    )
    coordinator = WorkCoordinator(
        PostgresCoordinationStore(connection_factory),
        clock=clock,
        id_factory=lambda: "unused-owned-change-read-model-id",
    )
    return OwnedChangeDelivery(
        owner_store=PostgresCommitOwnerStore(connection_factory),
        delivery=delivery,
        coordinator=coordinator,
    )


def build_supabase_owned_change_delivery(
    *,
    primary_lease: PrimaryLease,
    clock: Callable[[], datetime],
    change_set_id_factory: Callable[[], str],
    writer_cli: Path | None = None,
) -> OwnedChangeDelivery:
    """Wire the production service-role adapters without changing ownership."""

    from volpred.ops.work.supabase import SupabaseWorkReadModel

    from ._git_actuator import GitCommitActuator
    from .supabase_change_store import SupabaseChangeSetStore
    from .supabase_commit_authority import SupabaseCommitAuthority
    from .supabase_commit_ownership import SupabaseCommitOwnerStore
    from .supabase_commit_settlement import SupabaseCommitSettlement
    from .supabase_rpc import runtime_environment

    values = runtime_environment()
    supabase_url = values.get("SUPABASE_URL", "")
    service_role_key = values.get("SUPABASE_SERVICE_ROLE_KEY", "")
    timeout_seconds = float(
        values.get("VOLPRED_OPERATIONS_RPC_TIMEOUT_SEC", "45")
    )
    authority = SupabaseCommitAuthority(
        supabase_url=supabase_url,
        service_role_key=service_role_key,
        primary_lease=primary_lease,
        timeout_seconds=timeout_seconds,
    )
    actuator = (
        GitCommitActuator(clock=clock, authority=authority)
        if writer_cli is None
        else GitCommitActuator(
            clock=clock,
            authority=authority,
            writer_cli=writer_cli,
        )
    )
    delivery = ChangeDelivery(
        clock=clock,
        id_factory=change_set_id_factory,
        actuator=actuator,
        settlement=SupabaseCommitSettlement(
            supabase_url=supabase_url,
            service_role_key=service_role_key,
            primary_lease=primary_lease,
            timeout_seconds=timeout_seconds,
        ),
        store=SupabaseChangeSetStore(
            supabase_url=supabase_url,
            service_role_key=service_role_key,
            timeout_seconds=timeout_seconds,
        ),
    )
    return OwnedChangeDelivery(
        owner_store=SupabaseCommitOwnerStore(
            supabase_url=supabase_url,
            service_role_key=service_role_key,
            timeout_seconds=timeout_seconds,
        ),
        delivery=delivery,
        coordinator=SupabaseWorkReadModel(
            supabase_url=supabase_url,
            service_role_key=service_role_key,
            timeout_seconds=timeout_seconds,
        ),
    )


__all__ = [
    "CommitOwner",
    "CommitOwnershipLost",
    "OwnedChangeCommand",
    "OwnedChangeDelivery",
    "OwnedChangeReceipt",
    "build_postgres_owned_change_delivery",
    "build_supabase_owned_change_delivery",
]
