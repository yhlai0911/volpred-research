import json
from datetime import datetime, timezone

from volpred.ops.work import WorkerOffer
from volpred.ops.work_migration import LegacySnapshots
from volpred.ops.work_shadow_replay import replay_legacy_selection


FIXED_NOW = datetime(2026, 7, 23, 9, 30, tzinfo=timezone.utc)


def _pending_task(
    task_id: str,
    *,
    priority: int = 1,
    deadline: str | None = None,
    parent_task_id: str | None = None,
) -> dict[str, object]:
    task: dict[str, object] = {
        "id": task_id,
        "status": "pending",
        "task_type": "platform_ops",
        "title": task_id,
        "priority": priority,
        "source": "user",
        "created_at": "2026-07-23T09:00:00+00:00",
    }
    if deadline is not None:
        task["deadline"] = deadline
    if parent_task_id is not None:
        task["parent_task_id"] = parent_task_id
    return task


def _offer() -> WorkerOffer:
    return WorkerOffer(
        worker_id="shadow-worker",
        capabilities=frozenset({"code"}),
        attestations=frozenset(),
        lease_seconds=300,
    )


def test_replay_uses_one_immutable_snapshot_for_both_selection_policies() -> None:
    snapshots = LegacySnapshots(
        next_tasks=(
            _pending_task(
                "deadline_first",
                deadline="2026-07-24T00:00:00+00:00",
            ),
            _pending_task("no_deadline"),
        ),
        task_records=(),
        ops_jobs=(),
    )
    before = json.dumps(
        {
            "next_tasks": snapshots.next_tasks,
            "task_records": snapshots.task_records,
            "ops_jobs": snapshots.ops_jobs,
        },
        sort_keys=True,
    )

    ledger = replay_legacy_selection(
        snapshots,
        offer=_offer(),
        observed_at=FIXED_NOW,
        observation_id="obs_immutable",
    )

    assert (
        ledger.snapshot.sha256
        == ledger.legacy_selection.snapshot_sha256
        == ledger.coordinator_selection.snapshot_sha256
    )
    assert ledger.snapshot.source_counts == {
        "next_tasks": 2,
        "task_records": 0,
        "ops_jobs": 0,
    }
    assert {
        dimension.name
        for comparison in ledger.comparisons
        for dimension in comparison.dimensions
    } == {
        "priority",
        "readiness",
        "capability",
        "claim_ownership",
        "parent",
        "deadline",
        "terminal_disposition",
    }
    assert json.dumps(
        {
            "next_tasks": snapshots.next_tasks,
            "task_records": snapshots.task_records,
            "ops_jobs": snapshots.ops_jobs,
        },
        sort_keys=True,
    ) == before


def test_every_difference_has_a_stable_classification_and_evidence() -> None:
    parent = _pending_task("parent", priority=9)
    child = _pending_task(
        "child",
        priority=1,
        parent_task_id="parent",
    )
    child["required_attestations"] = ["formal-review"]
    snapshots = LegacySnapshots(next_tasks=(parent, child))

    first = replay_legacy_selection(
        snapshots,
        offer=_offer(),
        observed_at=FIXED_NOW,
        observation_id="obs_classification_1",
    )
    second = replay_legacy_selection(
        snapshots,
        offer=_offer(),
        observed_at=FIXED_NOW,
        observation_id="obs_classification_2",
    )

    first_differences = {
        (comparison.candidate_ref, dimension.name): (
            dimension.classification,
            dimension.evidence_refs,
        )
        for comparison in first.comparisons
        for dimension in comparison.dimensions
        if not dimension.matches
    }
    second_differences = {
        (comparison.candidate_ref, dimension.name): (
            dimension.classification,
            dimension.evidence_refs,
        )
        for comparison in second.comparisons
        for dimension in comparison.dimensions
        if not dimension.matches
    }

    assert first_differences == second_differences
    assert first_differences
    assert all(
        classification
        in {"policy_change", "legacy_corruption", "implementation_bug"}
        and evidence_refs
        for classification, evidence_refs in first_differences.values()
    )
    assert first_differences[
        ("legacy://next_tasks/child", "capability")
    ][0] == "policy_change"
    assert first_differences[
        ("legacy://next_tasks/child", "readiness")
    ][0] == "policy_change"


def test_reconciliation_corruption_drives_difference_classification() -> None:
    snapshots = LegacySnapshots(
        next_tasks=(
            _pending_task(
                "orphan",
                parent_task_id="missing_parent",
            ),
        )
    )

    ledger = replay_legacy_selection(
        snapshots,
        offer=_offer(),
        observed_at=FIXED_NOW,
        observation_id="obs_corruption",
    )

    assert ledger.reconciliation_issues == (
        {
            "classification": "legacy_corruption",
            "code": "missing_parent",
            "source_system": "next_tasks",
            "record_id": "orphan",
            "detail": (
                "parent id is absent from supplied snapshots: missing_parent"
            ),
            "evidence_ref": (
                "reconciliation://next_tasks/orphan/missing_parent"
            ),
        },
    )
    readiness = next(
        dimension
        for dimension in ledger.comparisons[0].dimensions
        if dimension.name == "readiness"
    )
    assert readiness.matches is False
    assert readiness.classification == "legacy_corruption"
    assert (
        "reconciliation://next_tasks/orphan/missing_parent"
        in readiness.evidence_refs
    )


def test_unrepresented_main_thread_lane_is_classified_as_implementation_bug() -> None:
    main_thread_only = _pending_task("main_thread_only")
    main_thread_only["status"] = "pending_main_thread"

    ledger = replay_legacy_selection(
        LegacySnapshots(next_tasks=(main_thread_only,)),
        offer=_offer(),
        observed_at=FIXED_NOW,
        observation_id="obs_lane_gap",
    )

    readiness = next(
        dimension
        for dimension in ledger.comparisons[0].dimensions
        if dimension.name == "readiness"
    )
    assert readiness.legacy is False
    assert readiness.coordinator is True
    assert readiness.classification == "implementation_bug"


def test_selection_winner_difference_is_classified_with_evidence() -> None:
    snapshots = LegacySnapshots(
        next_tasks=(
            _pending_task("a_no_deadline"),
            _pending_task(
                "z_deadline",
                deadline="2026-07-24T00:00:00+00:00",
            ),
        )
    )

    ledger = replay_legacy_selection(
        snapshots,
        offer=_offer(),
        observed_at=FIXED_NOW,
        observation_id="obs_winner",
    )

    assert ledger.legacy_selection.selected_candidate_ref == (
        "legacy://next_tasks/a_no_deadline"
    )
    assert ledger.coordinator_selection.selected_candidate_ref == (
        "legacy://next_tasks/z_deadline"
    )
    assert ledger.selection_difference is not None
    assert ledger.selection_difference.classification == "policy_change"
    assert ledger.selection_difference.evidence_refs
