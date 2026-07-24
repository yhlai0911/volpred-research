from __future__ import annotations

from dataclasses import replace
import json

import pytest

from volpred.ops.authority import PrimaryLease
from volpred.ops.delivery import (
    ChangeSetProposal,
    ChangeSetView,
    CheckEvidence,
    ContentHash,
    DeliveryReceipt,
    LandChangeSet,
)
from volpred.ops.delivery.owned_change import (
    CommitOwner,
    CommitOwnershipLost,
    OwnedChangeCommand,
    OwnedChangeDelivery,
    build_supabase_owned_change_delivery,
)
from volpred.ops.work import WorkItemView, WorkQuery, WorkSnapshot


def _proposal() -> ChangeSetProposal:
    return ChangeSetProposal(
        idempotency_key="change:owned-shadow-1",
        work_item_id="work-owned-change-1",
        work_item_version=3,
        base_commit="1" * 40,
        workspace_ref="/tmp/owned-change-worktree",
        exact_paths=("src/owned.py",),
        content_hashes=(
            ContentHash(path="src/owned.py", sha256="a" * 64),
        ),
        required_checks=(
            CheckEvidence(
                name="pytest",
                status="passed",
                evidence_ref="pytest:owned-change",
            ),
        ),
        author_ref="agent:change-author",
        author_evidence_ref="execution:owned-change",
    )


def _change_set() -> ChangeSetView:
    proposal = _proposal()
    return ChangeSetView(
        schema_version="changeset.v1",
        id="changeset-owned-1",
        idempotency_key=proposal.idempotency_key,
        work_item_id=proposal.work_item_id,
        work_item_version=proposal.work_item_version,
        base_commit=proposal.base_commit,
        workspace_ref=proposal.workspace_ref,
        exact_paths=proposal.exact_paths,
        content_hashes=proposal.content_hashes,
        required_checks=proposal.required_checks,
        author_ref=proposal.author_ref,
        author_evidence_ref=proposal.author_evidence_ref,
        proposal_sha256="b" * 64,
        status="proposed",
        created_at="2026-07-24T06:00:00+00:00",
    )


def _owner(*, owner: str = "operations_core") -> CommitOwner:
    return CommitOwner(
        schema_version="commit-owner.v1",
        capability="git.commit",
        owner=owner,
        generation=2,
        changed_at="2026-07-24T06:00:00+00:00",
        changed_by="test",
        change_reason="test owner",
    )


def _work(*, status: str = "succeeded") -> WorkItemView:
    return WorkItemView(
        id="work-owned-change-1",
        idempotency_key="work:owned-change-1",
        source="user",
        kind="platform_ops",
        title="Owned Change Delivery",
        priority=1,
        required_capabilities=frozenset({"code"}),
        required_attestations=frozenset(),
        risk="safe",
        approval="auto",
        payload_ref="change:owned-shadow-1",
        status=status,
        version=4 if status == "succeeded" else 3,
        created_at="2026-07-24T05:59:00+00:00",
        updated_at="2026-07-24T06:00:01+00:00",
        result_ref=(
            "change-delivery:changeset-owned-1:" + "2" * 40
            if status == "succeeded"
            else None
        ),
        result_summary=(
            "ChangeSet landed with verified commit read-back"
            if status == "succeeded"
            else None
        ),
        finished_at=(
            "2026-07-24T06:00:01+00:00"
            if status == "succeeded"
            else None
        ),
    )


class _OwnerStore:
    def __init__(self, owner: CommitOwner) -> None:
        self.owner = owner
        self.calls = 0

    def read_owner(self) -> CommitOwner:
        self.calls += 1
        return self.owner


class _Delivery:
    def __init__(self) -> None:
        self.proposals: list[ChangeSetProposal] = []
        self.commands: list[LandChangeSet] = []
        self.change_set = _change_set()

    def propose(self, proposal: ChangeSetProposal) -> ChangeSetView:
        self.proposals.append(proposal)
        return self.change_set

    def land(self, command: LandChangeSet) -> DeliveryReceipt:
        self.commands.append(command)
        return DeliveryReceipt(
            schema_version="change-delivery-receipt.v1",
            change_set_id=self.change_set.id,
            proposal_sha256=self.change_set.proposal_sha256,
            work_item_id=self.change_set.work_item_id,
            work_item_version=self.change_set.work_item_version,
            commit_owner_generation=command.commit_owner_generation,
            commit_owner_ref=(
                "commit-owner:git.commit:"
                f"generation-{command.commit_owner_generation}"
            ),
            authority_request_sha256="c" * 64,
            work_lease_ref="work-lease:work-owned-change-1:v3",
            primary_authority_ref=(
                "primary-authority:operations-core-commits:epoch-1"
            ),
            repository=command.repository,
            commit_sha="2" * 40,
            parent_sha=self.change_set.base_commit,
            exact_paths=self.change_set.exact_paths,
            actor=command.actor,
            status="landed",
            actuation_observed_at="2026-07-24T06:00:00+00:00",
            settled_at="2026-07-24T06:00:01+00:00",
            settlement_ref=(
                "change-delivery:changeset-owned-1:" + "2" * 40
            ),
            settlement_sha256="d" * 64,
        )


class _Coordinator:
    def __init__(self, item: WorkItemView) -> None:
        self.item = item
        self.queries: list[WorkQuery] = []

    def inspect(self, query: WorkQuery) -> WorkSnapshot:
        self.queries.append(query)
        return WorkSnapshot(items=(self.item,))


class _Response:
    def __init__(self, payload: object) -> None:
        self._raw = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._raw


def _command() -> OwnedChangeCommand:
    return OwnedChangeCommand(
        proposal=_proposal(),
        work_lease_token="work-lease-token",
        primary_fencing_token="primary-fencing-token",
        repository="/tmp/owned-change-repo",
        message="[codex] owned shadow change",
        actor="commit-worker:shadow",
    )


def test_deliver_owns_generation_proposal_landing_and_work_readback() -> None:
    owner_store = _OwnerStore(_owner())
    delivery = _Delivery()
    coordinator = _Coordinator(_work())
    owned = OwnedChangeDelivery(
        owner_store=owner_store,
        delivery=delivery,
        coordinator=coordinator,
    )

    receipt = owned.deliver(_command())

    assert receipt.owner == _owner()
    assert receipt.delivery.change_set_id == "changeset-owned-1"
    assert receipt.delivery.commit_sha == "2" * 40
    assert len(delivery.commands) == 1
    assert receipt.work_item == _work()
    assert delivery.proposals == [_proposal()]
    assert delivery.commands[0].commit_owner_generation == 2
    assert coordinator.queries == [WorkQuery(work_id="work-owned-change-1")]


def test_deliver_fails_before_proposal_when_owner_is_legacy() -> None:
    owner_store = _OwnerStore(_owner(owner="legacy"))
    delivery = _Delivery()
    coordinator = _Coordinator(_work(status="running"))

    with pytest.raises(
        CommitOwnershipLost,
        match="does not own git.commit",
    ):
        OwnedChangeDelivery(
            owner_store=owner_store,
            delivery=delivery,
            coordinator=coordinator,
        ).deliver(_command())

    assert delivery.proposals == []
    assert delivery.commands == []
    assert coordinator.queries == []


def test_deliver_rejects_incomplete_work_readback_after_settlement() -> None:
    coordinator = _Coordinator(_work(status="running"))

    with pytest.raises(RuntimeError, match="WorkItem completion read-back"):
        OwnedChangeDelivery(
            owner_store=_OwnerStore(_owner()),
            delivery=_Delivery(),
            coordinator=coordinator,
        ).deliver(_command())


def test_deliver_rejects_owner_generation_drift_in_receipt() -> None:
    delivery = _Delivery()
    original_land = delivery.land

    def drift(command: LandChangeSet) -> DeliveryReceipt:
        return replace(
            original_land(command),
            commit_owner_generation=command.commit_owner_generation + 1,
        )

    delivery.land = drift  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="commit owner generation"):
        OwnedChangeDelivery(
            owner_store=_OwnerStore(_owner()),
            delivery=delivery,
            coordinator=_Coordinator(_work()),
        ).deliver(_command())


def test_supabase_builder_is_a_fail_closed_formal_caller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[str] = []

    def fake_urlopen(call, *, timeout: float):
        observed.append(call.full_url)
        return _Response(
            {
                "schema_version": "commit-owner.v1",
                "capability": "git.commit",
                "owner": "legacy",
                "generation": 1,
                "changed_at": "2026-07-24T05:00:00+00:00",
                "changed_by": "migration",
                "change_reason": "legacy owner until cutover",
            }
        )

    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.co")
    monkeypatch.setenv(
        "SUPABASE_SERVICE_ROLE_KEY", "secret-service-role"
    )
    monkeypatch.setattr(
        "volpred.ops.delivery.supabase_rpc.request.urlopen",
        fake_urlopen,
    )
    primary_lease = PrimaryLease(
        schema_version="primary-lease.v1",
        authority_key="operations-core-commits",
        holder_ref="host:commit-primary",
        epoch=1,
        fencing_token="primary-secret",
        lease_seconds=300,
        acquired_at="2026-07-24T05:00:00+00:00",
        expires_at="2026-07-24T05:05:00+00:00",
    )
    caller = build_supabase_owned_change_delivery(
        primary_lease=primary_lease,
        clock=lambda: pytest.fail("Git must not run under legacy owner"),
        change_set_id_factory=lambda: "unused-change-set",
    )

    with pytest.raises(
        CommitOwnershipLost,
        match="does not own git.commit",
    ):
        caller.deliver(_command())

    assert observed == [
        "https://project.supabase.co/rest/v1/rpc/"
        "volpred_read_commit_owner"
    ]
