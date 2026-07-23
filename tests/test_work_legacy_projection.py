from datetime import datetime, timezone

import pytest

from volpred.ops.task_pool_selection import select_task_for_claim
from volpred.ops.work import (
    ApprovalGranted,
    WorkCoordinator,
    WorkEventView,
    WorkItemView,
    WorkQuery,
    WorkRequest,
    WorkSnapshot,
)
from volpred.ops.work.legacy import LegacySnapshots
from volpred.ops.work.memory import InMemoryCoordinationStore
from volpred.ops.work_migration import preview_legacy_snapshots
from volpred.ops.work_projection import project_legacy_next_tasks


FIXED_NOW = datetime(2026, 7, 23, 16, 15, tzinfo=timezone.utc)


def _assert_contains(
    row: dict[str, object],
    expected: dict[str, object],
) -> None:
    assert {key: row[key] for key in expected} == expected


def _work_item(**overrides: object) -> WorkItemView:
    values: dict[str, object] = {
        "id": "work_pending",
        "idempotency_key": "owner:projection:pending",
        "source": "user",
        "kind": "platform_ops",
        "title": "Keep legacy readers compatible",
        "priority": 1,
        "required_capabilities": frozenset({"code"}),
        "required_attestations": frozenset(),
        "risk": "safe",
        "approval": "auto",
        "payload_ref": "issue:9",
        "status": "pending",
        "version": 1,
        "created_at": "2026-07-23T16:00:00+00:00",
        "updated_at": "2026-07-23T16:00:00+00:00",
    }
    values.update(overrides)
    return WorkItemView(**values)  # type: ignore[arg-type]


def test_pending_projection_is_compatible_with_the_legacy_read_selector() -> None:
    item = _work_item()
    snapshot = WorkSnapshot(
        items=(item,),
        events=(
            WorkEventView(
                work_id=item.id,
                kind="submitted",
                version=1,
                created_at=item.created_at,
            ),
        ),
    )

    projection = project_legacy_next_tasks(snapshot)
    rows = projection.read()

    assert projection.schema_version == "next-tasks-read-projection.v1"
    assert projection.row_count == 1
    assert rows == [
        {
            "id": "work_pending",
            "status": "pending",
            "task_type": "platform_ops",
            "title": "Keep legacy readers compatible",
            "priority": 1,
            "source": "user",
            "created_at": "2026-07-23T16:00:00+00:00",
            "updated_at": "2026-07-23T16:00:00+00:00",
            "required_capabilities": ["code"],
            "required_attestations": [],
            "risk": "safe",
            "approval": "auto",
            "coordinator_version": 1,
        }
    ]
    selection = select_task_for_claim(
        rows,
        owner="codex-vscode",
        main_thread=False,
        observed_at=FIXED_NOW,
    )
    assert selection.selected_task_id == item.id

    rows[0]["title"] = "caller mutation"
    assert projection.read()[0]["title"] == item.title
    assert snapshot.items == (item,)


def test_projection_preserves_claim_parent_deadline_and_terminal_disposition() -> None:
    awaiting = _work_item(
        id="work_awaiting",
        idempotency_key="owner:projection:awaiting",
        title="Needs owner approval",
        status="awaiting_approval",
        approval="required",
        risk="destructive",
    )
    claimed = _work_item(
        id="work_claimed",
        idempotency_key="owner:projection:claimed",
        title="Claimed work",
        status="claimed",
        version=2,
        parent_id="work_parent",
        deadline="2026-07-24T00:00:00+00:00",
        claimed_by="worker-a",
        claim_expires_at="2026-07-23T16:20:00+00:00",
        updated_at="2026-07-23T16:05:00+00:00",
    )
    running = _work_item(
        id="work_running",
        idempotency_key="owner:projection:running",
        title="Running work",
        status="running",
        version=3,
        claimed_by="worker-b",
        claim_expires_at="2026-07-23T16:25:00+00:00",
        updated_at="2026-07-23T16:06:00+00:00",
    )
    succeeded = _work_item(
        id="work_succeeded",
        idempotency_key="owner:projection:succeeded",
        title="Completed work",
        status="succeeded",
        version=4,
        result_ref="receipt:work_succeeded",
        result_summary="verified downstream",
        finished_at="2026-07-23T16:10:00+00:00",
        updated_at="2026-07-23T16:10:00+00:00",
    )
    snapshot = WorkSnapshot(
        items=(awaiting, claimed, running, succeeded),
        events=(
            WorkEventView(
                work_id=claimed.id,
                kind="acquired",
                version=2,
                created_at="2026-07-23T16:05:00+00:00",
            ),
            WorkEventView(
                work_id=running.id,
                kind="acquired",
                version=2,
                created_at="2026-07-23T16:04:00+00:00",
            ),
            WorkEventView(
                work_id=running.id,
                kind="started",
                version=3,
                created_at="2026-07-23T16:06:00+00:00",
            ),
            WorkEventView(
                work_id=succeeded.id,
                kind="completed",
                version=4,
                created_at="2026-07-23T16:10:00+00:00",
            ),
        ),
    )

    rows = {
        row["id"]: row
        for row in project_legacy_next_tasks(snapshot).read()
    }

    assert rows["work_awaiting"]["status"] == "blocked_on_user"
    assert (
        rows["work_awaiting"]["blocked_reason"]
        == "awaiting_owner_approval"
    )
    _assert_contains(rows["work_claimed"], {
        "status": "claimed",
        "claimed_by": "worker-a",
        "claimed_at": "2026-07-23T16:05:00+00:00",
        "claim_expires_at": "2026-07-23T16:20:00+00:00",
        "parent_task_id": "work_parent",
        "deadline": "2026-07-24T00:00:00+00:00",
    })
    _assert_contains(rows["work_running"], {
        "status": "in_progress",
        "claimed_by": "worker-b",
        "claimed_at": "2026-07-23T16:04:00+00:00",
        "started_at": "2026-07-23T16:06:00+00:00",
        "claim_expires_at": "2026-07-23T16:25:00+00:00",
    })
    _assert_contains(rows["work_succeeded"], {
        "status": "succeeded",
        "completed_at": "2026-07-23T16:10:00+00:00",
        "result": "verified downstream",
        "result_ref": "receipt:work_succeeded",
    })


def test_projection_identity_is_stable_across_adapter_result_order() -> None:
    lower_priority = _work_item(
        id="work_b",
        idempotency_key="owner:projection:b",
        priority=2,
    )
    higher_priority = _work_item(
        id="work_a",
        idempotency_key="owner:projection:a",
        priority=1,
    )

    first = project_legacy_next_tasks(
        WorkSnapshot(items=(lower_priority, higher_priority))
    )
    second = project_legacy_next_tasks(
        WorkSnapshot(items=(higher_priority, lower_priority))
    )

    assert [row["id"] for row in first.read()] == ["work_a", "work_b"]
    assert first.read() == second.read()
    assert first.sha256 == second.sha256


def test_projection_fails_closed_on_duplicate_work_identity() -> None:
    first = _work_item(title="first")
    duplicate = _work_item(
        idempotency_key="owner:projection:duplicate",
        title="duplicate",
    )

    with pytest.raises(ValueError, match="duplicate WorkItem id: work_pending"):
        project_legacy_next_tasks(WorkSnapshot(items=(first, duplicate)))


def test_projection_fails_closed_when_active_claim_evidence_is_incomplete() -> None:
    claimed = _work_item(
        status="claimed",
        version=2,
        claimed_by="worker-a",
        claim_expires_at="2026-07-23T16:20:00+00:00",
        updated_at="2026-07-23T16:05:00+00:00",
    )

    with pytest.raises(
        ValueError,
        match="claimed WorkItem work_pending has no acquired event",
    ):
        project_legacy_next_tasks(WorkSnapshot(items=(claimed,)))


def test_owner_approved_work_round_trips_through_the_legacy_import_contract() -> None:
    coordinator = WorkCoordinator(
        InMemoryCoordinationStore(),
        clock=lambda: FIXED_NOW,
        id_factory=lambda: "work_approved",
    )
    awaiting = coordinator.submit(
        WorkRequest(
            idempotency_key="owner:projection:approved",
            source="user",
            kind="platform_ops",
            title="Owner-approved destructive work",
            priority=1,
            required_capabilities=frozenset({"code"}),
            required_attestations=frozenset(),
            risk="destructive",
            approval="required",
            payload_ref="issue:9",
        )
    )
    approved = coordinator.record(
        ApprovalGranted(
            work_id=awaiting.id,
            expected_version=awaiting.version,
            approved_by="owner:yhlai0911",
            evidence_ref="approval:issue-9",
        )
    )

    projection = project_legacy_next_tasks(
        coordinator.inspect(WorkQuery(work_id=approved.id))
    )
    report = preview_legacy_snapshots(
        LegacySnapshots(next_tasks=tuple(projection.read()))
    )

    assert report.ready is True
    assert report.candidates[0].status == "pending"
    assert projection.read()[0]["approval"] == "required"
    assert projection.read()[0]["approval_state"] == "approved"
