from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest

from volpred.ops.work import WorkCoordinator, WorkItemView, WorkerOffer
from volpred.ops.work.memory import InMemoryCoordinationStore
from volpred.ops.work.selection import select_acquirable_work


OBSERVED_AT = datetime(2026, 7, 23, 4, 0, tzinfo=timezone.utc)
OFFER = WorkerOffer(
    worker_id="codex-worker",
    capabilities=frozenset({"code", "review"}),
    attestations=frozenset({"zero-paid"}),
    lease_seconds=300,
)


def _item(
    work_id: str,
    *,
    priority: int = 5,
    status: str = "pending",
    required_capabilities: frozenset[str] = frozenset({"code"}),
    required_attestations: frozenset[str] = frozenset(),
    parent_id: str | None = None,
    deadline: str | None = None,
    created_at: str = "2026-07-23T03:00:00+00:00",
    claim_expires_at: str | None = None,
) -> WorkItemView:
    return WorkItemView(
        id=work_id,
        idempotency_key=f"test:{work_id}",
        source="test",
        kind="platform_ops",
        title=work_id,
        priority=priority,
        required_capabilities=required_capabilities,
        required_attestations=required_attestations,
        risk="safe",
        approval="auto",
        payload_ref=f"test:{work_id}",
        status=status,
        version=1,
        created_at=created_at,
        parent_id=parent_id,
        deadline=deadline,
        updated_at=created_at,
        claim_expires_at=claim_expires_at,
    )


def test_selector_requires_attestations_and_explains_the_winner() -> None:
    requires_formal_review = _item(
        "requires-formal-review",
        priority=1,
        required_attestations=frozenset({"formal-review"}),
    )
    winner = _item("winner", priority=2)

    selection = select_acquirable_work(
        (requires_formal_review, winner),
        offer=OFFER,
        observed_at=OBSERVED_AT,
    )
    decisions = {decision.work_id: decision for decision in selection.decisions}

    assert selection.selected_id == "winner"
    assert decisions["requires-formal-review"].eligible is False
    assert decisions["requires-formal-review"].reason_codes == (
        "ready_pending",
        "attestation_mismatch",
    )
    assert decisions["requires-formal-review"].missing_attestations == frozenset(
        {"formal-review"}
    )
    assert decisions["winner"].eligible is True
    assert decisions["winner"].reason_codes == ("ready_pending", "selected")
    with pytest.raises(FrozenInstanceError):
        selection.selected_id = "different"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        decisions["winner"].eligible = False  # type: ignore[misc]


def test_selector_uses_non_selectable_dependency_context_for_parent_readiness() -> None:
    parent = _item("parent", priority=1, status="succeeded")
    child = _item("child", priority=2, parent_id="parent")

    selection = select_acquirable_work(
        (child,),
        dependency_items=(parent,),
        offer=OFFER,
        observed_at=OBSERVED_AT,
    )

    assert selection.selected_id == "child"
    assert tuple(decision.work_id for decision in selection.decisions) == (
        "child",
    )
    assert selection.decisions[0].parent_status == "succeeded"
    assert selection.decisions[0].reason_codes == (
        "ready_pending",
        "parent_succeeded",
        "selected",
    )


def test_selector_rejects_duplicate_ids_across_selection_context() -> None:
    candidate = _item("ambiguous")
    dependency = _item("ambiguous", status="succeeded")

    with pytest.raises(
        ValueError,
        match="work selection context contains duplicate work ids",
    ):
        select_acquirable_work(
            (candidate,),
            dependency_items=(dependency,),
            offer=OFFER,
            observed_at=OBSERVED_AT,
        )


def test_selector_distinguishes_live_expired_and_missing_claim_expiry() -> None:
    live = _item(
        "live",
        priority=1,
        status="claimed",
        claim_expires_at="2026-07-23T04:00:00.000001+00:00",
    )
    missing_expiry = _item("missing-expiry", priority=1, status="running")
    expired = _item(
        "expired",
        priority=2,
        status="running",
        claim_expires_at="2026-07-23T03:59:59+00:00",
    )
    expires_exactly_now = _item(
        "expires-exactly-now",
        priority=1,
        status="claimed",
        claim_expires_at="2026-07-23T05:00:00+01:00",
    )
    finished = _item("finished", priority=1, status="succeeded")

    selection = select_acquirable_work(
        (live, missing_expiry, expired, expires_exactly_now, finished),
        offer=OFFER,
        observed_at=OBSERVED_AT,
    )
    decisions = {decision.work_id: decision for decision in selection.decisions}

    assert selection.selected_id == "expires-exactly-now"
    assert decisions["live"].reason_codes == ("live_claim",)
    assert decisions["missing-expiry"].reason_codes == ("claim_expiry_missing",)
    assert decisions["expired"].reason_codes == (
        "ready_expired_claim",
        "eligible_not_selected_by_rank",
    )
    assert decisions["expires-exactly-now"].reason_codes == (
        "ready_expired_claim",
        "selected",
    )
    assert decisions["finished"].reason_codes == ("status_not_acquirable",)


def test_selector_reports_capability_and_parent_gates() -> None:
    waiting_parent = _item(
        "waiting-parent",
        priority=9,
        required_capabilities=frozenset({"research"}),
    )
    succeeded_parent = _item("succeeded-parent", status="succeeded")
    capability_mismatch = _item(
        "capability-mismatch",
        priority=1,
        required_capabilities=frozenset({"code", "research"}),
    )
    parent_missing = _item("parent-missing", priority=2, parent_id="absent")
    parent_waiting = _item(
        "parent-waiting",
        priority=3,
        parent_id="waiting-parent",
    )
    winner = _item(
        "child-of-succeeded",
        priority=4,
        parent_id="succeeded-parent",
    )

    selection = select_acquirable_work(
        (
            waiting_parent,
            succeeded_parent,
            capability_mismatch,
            parent_missing,
            parent_waiting,
            winner,
        ),
        offer=OFFER,
        observed_at=OBSERVED_AT,
    )
    decisions = {decision.work_id: decision for decision in selection.decisions}

    assert selection.selected_id == "child-of-succeeded"
    assert decisions["capability-mismatch"].missing_capabilities == frozenset(
        {"research"}
    )
    assert decisions["capability-mismatch"].reason_codes == (
        "ready_pending",
        "capability_mismatch",
    )
    assert decisions["parent-missing"].parent_status is None
    assert decisions["parent-missing"].reason_codes == (
        "ready_pending",
        "parent_missing",
    )
    assert decisions["parent-waiting"].parent_status == "pending"
    assert decisions["parent-waiting"].reason_codes == (
        "ready_pending",
        "parent_not_succeeded",
    )
    assert decisions["child-of-succeeded"].parent_status == "succeeded"
    assert decisions["child-of-succeeded"].reason_codes == (
        "ready_pending",
        "parent_succeeded",
        "selected",
    )


def test_selector_ranks_real_instants_then_null_deadlines_created_at_and_id() -> None:
    later_instant_but_lexically_first = _item(
        "later-deadline",
        deadline="2026-07-23T03:30:00-01:00",
    )
    earlier_instant = _item(
        "earlier-deadline",
        deadline="2026-07-23T05:00:00+01:00",
    )
    earlier_created_instant = _item(
        "created-a",
        deadline="2026-07-24T00:00:00+00:00",
        created_at="2026-07-23T04:00:00+01:00",
    )
    later_created_instant = _item(
        "created-b",
        deadline="2026-07-24T00:00:00+00:00",
        created_at="2026-07-23T03:30:00+00:00",
    )
    id_tie_a = _item(
        "id-a",
        deadline="2026-07-25T00:00:00+00:00",
    )
    id_tie_b = _item(
        "id-b",
        deadline="2026-07-25T00:00:00+00:00",
    )
    no_deadline = _item("no-deadline")

    selection = select_acquirable_work(
        (
            no_deadline,
            later_instant_but_lexically_first,
            earlier_instant,
            later_created_instant,
            earlier_created_instant,
            id_tie_b,
            id_tie_a,
        ),
        offer=OFFER,
        observed_at=OBSERVED_AT,
    )

    assert selection.selected_id == "earlier-deadline"
    assert tuple(decision.work_id for decision in selection.decisions) == (
        "earlier-deadline",
        "later-deadline",
        "created-a",
        "created-b",
        "id-a",
        "id-b",
        "no-deadline",
    )
    earlier_decision = next(
        decision
        for decision in selection.decisions
        if decision.work_id == "earlier-deadline"
    )
    assert earlier_decision.rank_key == (
        5,
        False,
        datetime(2026, 7, 23, 4, 0, tzinfo=timezone.utc),
        datetime(2026, 7, 23, 3, 0, tzinfo=timezone.utc),
        "earlier-deadline",
    )


def test_priority_precedes_an_earlier_deadline() -> None:
    priority_one = _item("priority-one", priority=1)
    priority_two_with_earlier_deadline = _item(
        "priority-two",
        priority=2,
        deadline="2026-07-23T03:30:00+00:00",
    )

    selection = select_acquirable_work(
        (priority_two_with_earlier_deadline, priority_one),
        offer=OFFER,
        observed_at=OBSERVED_AT,
    )

    assert selection.selected_id == "priority-one"


def test_work_coordinator_acquire_uses_the_shared_real_instant_ranking() -> None:
    store = InMemoryCoordinationStore()
    store.create_if_absent(
        "test:later",
        _item(
            "later",
            deadline="2026-07-23T03:30:00-01:00",
        ),
    )
    store.create_if_absent(
        "test:earlier",
        _item(
            "earlier",
            deadline="2026-07-23T05:00:00+01:00",
        ),
    )
    coordinator = WorkCoordinator(
        store,
        clock=lambda: OBSERVED_AT,
        id_factory=lambda: "unused",
        token_factory=lambda: "claim-selection-policy",
    )

    lease = coordinator.acquire(OFFER)

    assert lease is not None
    assert lease.work_item.id == "earlier"
    assert lease.work_item.status == "claimed"
    assert lease.work_item.version == 2
    assert lease.token == "claim-selection-policy"
