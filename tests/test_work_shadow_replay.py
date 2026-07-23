import builtins
import hashlib
import json
import socket
from datetime import datetime, timezone
from pathlib import Path

import pytest

from volpred.ops import work_shadow_replay
from volpred.ops.work import WorkCoordinator, WorkerOffer
from volpred.ops.work_migration import LegacySnapshots
from volpred.ops.work_shadow_replay import (
    append_shadow_observation,
    replay_legacy_selection,
)


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
        task_records=(
            {
                "id": "audit_only",
                "title": "Audit record is not a next_tasks claim candidate",
                "source": "agent",
                "task_family": "ops",
                "priority": 1,
                "approval_mode": "auto",
                "risk_level": "safe",
                "status": "queued",
                "public_effect": "none",
                "created_at": "2026-07-23T09:00:00+00:00",
            },
        ),
        ops_jobs=(
            {
                "id": "018f0000-0000-7000-8000-000000000099",
                "action": "strategy_set_active",
                "source": "human",
                "requested_by": "owner",
                "dry_run": True,
                "priority": 1,
                "status": "queued",
                "dedupe_key": "shadow:non-global",
                "created_at": "2026-07-23T09:00:00+00:00",
                "updated_at": "2026-07-23T09:00:00+00:00",
            },
        ),
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
        "task_records": 1,
        "ops_jobs": 1,
    }
    assert ledger.selection_scope == "next_tasks"
    assert {
        comparison.candidate_ref for comparison in ledger.comparisons
    } == {
        "legacy://next_tasks/deadline_first",
        "legacy://next_tasks/no_deadline",
    }
    assert {
        dimension.name
        for comparison in ledger.comparisons
        for dimension in comparison.dimensions
    } == {
        "priority",
        "readiness",
        "capability",
        "attestation",
        "claim_ownership",
        "lease_expiry",
        "dispatch_lane",
        "preferred_agent",
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


def test_replay_freezes_caller_snapshot_before_aba_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mutable_task = _pending_task("aba_task")
    snapshots = LegacySnapshots(next_tasks=(mutable_task,))
    canonicalize = work_shadow_replay._canonical_snapshot_bytes
    expected_sha256 = hashlib.sha256(canonicalize(snapshots)).hexdigest()
    original_reads = 0

    def mutate_between_reads(candidate: LegacySnapshots) -> bytes:
        nonlocal original_reads
        payload = canonicalize(candidate)
        if candidate is snapshots:
            original_reads += 1
            mutable_task["priority"] = 9 if original_reads == 1 else 1
        return payload

    monkeypatch.setattr(
        work_shadow_replay,
        "_canonical_snapshot_bytes",
        mutate_between_reads,
    )

    ledger = replay_legacy_selection(
        snapshots,
        offer=_offer(),
        observed_at=FIXED_NOW,
        observation_id="obs_aba",
    )

    assert original_reads == 1
    assert ledger.snapshot.sha256 == expected_sha256
    assert ledger.legacy_selection.snapshot_sha256 == expected_sha256
    assert ledger.coordinator_selection.snapshot_sha256 == expected_sha256


def test_replay_runs_legacy_selection_before_importer_filtering() -> None:
    raw_legacy_winner = _pending_task("raw_legacy_winner", priority=1)
    raw_legacy_winner["source"] = "unreviewed_legacy_producer"
    mapped_coordinator_winner = _pending_task(
        "mapped_coordinator_winner",
        priority=2,
    )

    ledger = replay_legacy_selection(
        LegacySnapshots(
            next_tasks=(
                raw_legacy_winner,
                mapped_coordinator_winner,
            )
        ),
        offer=_offer(),
        observed_at=FIXED_NOW,
        observation_id="obs_raw_legacy_selection",
    )

    assert ledger.legacy_selection.selected_candidate_ref == (
        "legacy://next_tasks/raw_legacy_winner"
    )
    assert ledger.coordinator_selection.selected_candidate_ref == (
        "legacy://next_tasks/mapped_coordinator_winner"
    )
    assert {
        comparison.candidate_ref for comparison in ledger.comparisons
    } == {
        "legacy://next_tasks/raw_legacy_winner",
        "legacy://next_tasks/mapped_coordinator_winner",
    }
    raw_comparison = next(
        comparison
        for comparison in ledger.comparisons
        if comparison.candidate_ref
        == "legacy://next_tasks/raw_legacy_winner"
    )
    assert raw_comparison.legacy_eligible is True
    assert raw_comparison.coordinator_eligible is False
    assert all(
        dimension.coordinator_reason_codes == ()
        and any(
            evidence_ref.startswith("migration://")
            for evidence_ref in dimension.evidence_refs
        )
        and all(
            not evidence_ref.startswith(
                "selector://work-coordinator/"
            )
            for evidence_ref in dimension.evidence_refs
        )
        for dimension in raw_comparison.dimensions
    )
    assert ledger.selection_difference is not None
    assert ledger.selection_difference.classification == "legacy_corruption"
    assert (
        ledger.selection_difference.classification_reason_code
        == "reconciliation:unknown_source"
    )
    assert (
        "reconciliation://next_tasks/raw_legacy_winner/record-0/unknown_source"
        in ledger.selection_difference.evidence_refs
    )


def test_unmapped_non_winner_is_a_stable_comparison_not_a_winner_change() -> None:
    mapped_winner = _pending_task("mapped_winner", priority=1)
    unmapped_non_winner = _pending_task("unmapped_non_winner", priority=2)
    unmapped_non_winner["source"] = "unreviewed_legacy_producer"
    snapshots = LegacySnapshots(
        next_tasks=(mapped_winner, unmapped_non_winner)
    )

    first = replay_legacy_selection(
        snapshots,
        offer=_offer(),
        observed_at=FIXED_NOW,
        observation_id="obs_unmapped_non_winner_1",
    )
    second = replay_legacy_selection(
        snapshots,
        offer=_offer(),
        observed_at=FIXED_NOW,
        observation_id="obs_unmapped_non_winner_2",
    )

    assert first.legacy_selection.selected_candidate_ref == (
        "legacy://next_tasks/mapped_winner"
    )
    assert first.coordinator_selection.selected_candidate_ref == (
        "legacy://next_tasks/mapped_winner"
    )
    assert first.selection_difference is None
    first_unmapped = next(
        comparison
        for comparison in first.comparisons
        if comparison.candidate_ref
        == "legacy://next_tasks/unmapped_non_winner"
    )
    second_unmapped = next(
        comparison
        for comparison in second.comparisons
        if comparison.candidate_ref
        == "legacy://next_tasks/unmapped_non_winner"
    )
    assert first_unmapped == second_unmapped
    assert first_unmapped.legacy_eligible is True
    assert first_unmapped.coordinator_eligible is False
    assert all(
        dimension.classification == "legacy_corruption"
        and dimension.classification_reason_code
        == "reconciliation:unknown_source"
        for dimension in first_unmapped.dimensions
    )


def test_replay_preserves_task_id_and_p_label_selection_semantics() -> None:
    alias = _pending_task("placeholder", priority=1)
    alias.pop("id")
    alias["task_id"] = "a_alias"
    alias["priority"] = "P1"
    ordinary = _pending_task("z_ordinary", priority=1)

    ledger = replay_legacy_selection(
        LegacySnapshots(next_tasks=(alias, ordinary)),
        offer=_offer(),
        observed_at=FIXED_NOW,
        observation_id="obs_alias_semantics",
    )

    assert ledger.reconciliation_issues == ()
    assert ledger.legacy_selection.selected_candidate_ref == (
        "legacy://next_tasks/a_alias"
    )
    assert ledger.coordinator_selection.selected_candidate_ref == (
        "legacy://next_tasks/a_alias"
    )
    assert {
        comparison.candidate_ref for comparison in ledger.comparisons
    } == {
        "legacy://next_tasks/a_alias",
        "legacy://next_tasks/z_ordinary",
    }


def test_duplicate_identity_fails_closed_without_cross_record_evidence() -> None:
    first = _pending_task("duplicate", priority=1)
    second = _pending_task("duplicate", priority=1)
    second.update(
        {
            "status": "claimed",
            "claimed_by": "other-worker",
            "claimed_at": "2026-07-23T09:00:00+00:00",
        }
    )

    ledger = replay_legacy_selection(
        LegacySnapshots(next_tasks=(first, second)),
        offer=_offer(),
        observed_at=FIXED_NOW,
        observation_id="obs_duplicate_identity",
    )

    assert ledger.legacy_selection.selected_candidate_ref is None
    assert ledger.legacy_selection.eligible_candidate_refs == ()
    assert ledger.coordinator_selection.selected_candidate_ref is None
    assert ledger.coordinator_selection.eligible_candidate_refs == ()
    assert len(ledger.comparisons) == 2
    assert len(
        {
            comparison.candidate_ref
            for comparison in ledger.comparisons
        }
    ) == 2
    assert all(
        comparison.legacy_eligible is False
        and comparison.coordinator_eligible is False
        for comparison in ledger.comparisons
    )
    ownership = [
        next(
            dimension
            for dimension in comparison.dimensions
            if dimension.name == "claim_ownership"
        )
        for comparison in ledger.comparisons
    ]
    assert {dimension.legacy["claimed_by"] for dimension in ownership} == {
        None,
        "other-worker",
    }
    assert all(
        dimension.classification == "legacy_corruption"
        and dimension.classification_reason_code
        == "reconciliation:duplicate_id,duplicate_idempotency_key"
        for dimension in ownership
    )


def test_indexed_mapping_issue_stays_on_its_duplicate_record() -> None:
    mapped = _pending_task("mixed_duplicate", priority=1)
    unmapped = _pending_task("mixed_duplicate", priority=1)
    unmapped["source"] = "unreviewed_legacy_producer"

    ledger = replay_legacy_selection(
        LegacySnapshots(next_tasks=(mapped, unmapped)),
        offer=_offer(),
        observed_at=FIXED_NOW,
        observation_id="obs_mixed_duplicate",
    )

    by_record_index = {
        int(comparison.candidate_ref.split("record_index=", 1)[1].split("&", 1)[0]):
        comparison
        for comparison in ledger.comparisons
    }
    first_reasons = {
        dimension.classification_reason_code
        for dimension in by_record_index[0].dimensions
    }
    second_reasons = {
        dimension.classification_reason_code
        for dimension in by_record_index[1].dimensions
    }
    assert first_reasons == {"reconciliation:duplicate_id"}
    assert second_reasons == {
        "reconciliation:duplicate_id,unknown_source"
    }
    assert all(
        "reconciliation://next_tasks/mixed_duplicate/record-1/unknown_source"
        not in dimension.evidence_refs
        for dimension in by_record_index[0].dimensions
    )
    assert all(
        "reconciliation://next_tasks/mixed_duplicate/record-1/unknown_source"
        in dimension.evidence_refs
        for dimension in by_record_index[1].dimensions
    )


def test_cross_source_duplicate_with_unmapped_copy_fails_closed() -> None:
    task = _pending_task("mixed_source_duplicate")
    mapped_copy = {
        "id": "mixed_source_duplicate",
        "title": "Mapped audit-trail copy",
        "source": "agent",
        "task_family": "ops",
        "priority": 1,
        "approval_mode": "auto",
        "risk_level": "safe",
        "status": "queued",
        "public_effect": "none",
        "created_at": "2026-07-23T09:00:00+00:00",
    }
    unmapped_copy = {
        "id": "mixed_source_duplicate",
        "title": "Unmappable audit-trail copy",
        "source": "agent",
        "task_family": "unknown_family",
        "priority": 1,
        "approval_mode": "auto",
        "risk_level": "safe",
        "status": "queued",
        "public_effect": "none",
        "created_at": "2026-07-23T09:00:00+00:00",
    }

    ledger = replay_legacy_selection(
        LegacySnapshots(
            next_tasks=(task,),
            task_records=(mapped_copy, unmapped_copy),
        ),
        offer=_offer(),
        observed_at=FIXED_NOW,
        observation_id="obs_mixed_source_duplicate",
    )

    assert [
        (issue["source_system"], issue["record_id"], issue["code"])
        for issue in ledger.reconciliation_issues
    ] == [
        ("task_records", "mixed_source_duplicate", "unknown_kind"),
        ("cross_source", "mixed_source_duplicate", "duplicate_id"),
    ]
    assert ledger.legacy_selection.selected_candidate_ref == (
        "legacy://next_tasks/mixed_source_duplicate"
    )
    assert ledger.coordinator_selection.selected_candidate_ref is None
    comparison = ledger.comparisons[0]
    assert comparison.coordinator_eligible is False
    assert all(
        dimension.classification == "legacy_corruption"
        and dimension.classification_reason_code
        == "reconciliation:duplicate_id"
        and dimension.coordinator_reason_codes == ()
        and (
            "reconciliation://cross_source/mixed_source_duplicate/duplicate_id"
            in dimension.evidence_refs
        )
        for dimension in comparison.dimensions
    )
    assert ledger.selection_difference is not None
    assert ledger.selection_difference.classification == "legacy_corruption"
    assert ledger.selection_difference.classification_reason_code == (
        "reconciliation:duplicate_id"
    )


def test_missing_identity_produces_record_bound_corruption_evidence() -> None:
    missing_identity = _pending_task("placeholder")
    missing_identity.pop("id")

    ledger = replay_legacy_selection(
        LegacySnapshots(next_tasks=(missing_identity,)),
        offer=_offer(),
        observed_at=FIXED_NOW,
        observation_id="obs_missing_identity",
    )

    assert ledger.legacy_selection.selected_candidate_ref is None
    assert ledger.coordinator_selection.selected_candidate_ref is None
    assert len(ledger.comparisons) == 1
    comparison = ledger.comparisons[0]
    assert comparison.candidate_ref.startswith(
        "legacy://next_tasks/_missing-id?record_index=0&sha256="
    )
    assert comparison.legacy_eligible is False
    assert comparison.coordinator_eligible is False
    assert all(
        dimension.classification == "legacy_corruption"
        and dimension.classification_reason_code
        == "reconciliation:invalid_record"
        and (
            "reconciliation://next_tasks/_record_0/invalid_record"
            in dimension.evidence_refs
        )
        for dimension in comparison.dimensions
    )
    assert ledger.reconciliation_issues[0]["record_index"] == 0
    assert ledger.reconciliation_issues[0]["evidence_ref"] == (
        "reconciliation://next_tasks/_record_0/invalid_record"
    )


def test_unrepresentable_parent_corruption_propagates_to_child_readiness() -> None:
    first_parent = _pending_task("duplicate_parent", priority=9)
    first_parent.update(
        {
            "status": "succeeded",
            "completed_at": "2026-07-23T09:05:00+00:00",
        }
    )
    second_parent = dict(first_parent)
    child = _pending_task(
        "child",
        priority=1,
        parent_task_id="duplicate_parent",
    )

    ledger = replay_legacy_selection(
        LegacySnapshots(
            next_tasks=(first_parent, second_parent, child)
        ),
        offer=_offer(),
        observed_at=FIXED_NOW,
        observation_id="obs_duplicate_parent",
    )

    assert ledger.legacy_selection.selected_candidate_ref == (
        "legacy://next_tasks/child"
    )
    assert ledger.coordinator_selection.selected_candidate_ref is None
    child_comparison = next(
        comparison
        for comparison in ledger.comparisons
        if comparison.candidate_ref == "legacy://next_tasks/child"
    )
    child_dimensions = {
        dimension.name: dimension
        for dimension in child_comparison.dimensions
    }
    assert child_dimensions["readiness"].matches is True
    assert child_dimensions["readiness"].classification is None
    parent_dimension = child_dimensions["parent"]
    assert parent_dimension.classification == "legacy_corruption"
    assert parent_dimension.classification_reason_code == (
        "reconciliation:duplicate_id,duplicate_idempotency_key"
    )
    assert (
        "reconciliation://next_tasks/duplicate_parent/duplicate_id"
        in parent_dimension.evidence_refs
    )
    assert ledger.selection_difference is not None
    assert ledger.selection_difference.classification == "legacy_corruption"
    assert ledger.selection_difference.classification_reason_code == (
        "reconciliation:duplicate_id,duplicate_idempotency_key"
    )


def test_present_but_unmapped_parent_is_not_reported_as_absent() -> None:
    parent = _pending_task("unmapped_parent", priority=9)
    parent.update(
        {
            "status": "succeeded",
            "completed_at": "2026-07-23T09:05:00+00:00",
            "source": "unreviewed_legacy_producer",
        }
    )
    child = _pending_task(
        "child_of_unmapped",
        priority=1,
        parent_task_id="unmapped_parent",
    )

    ledger = replay_legacy_selection(
        LegacySnapshots(next_tasks=(parent, child)),
        offer=_offer(),
        observed_at=FIXED_NOW,
        observation_id="obs_unmapped_parent",
    )

    issue_codes = {
        (issue["record_id"], issue["code"])
        for issue in ledger.reconciliation_issues
    }
    assert ("unmapped_parent", "unknown_source") in issue_codes
    assert ("child_of_unmapped", "unrepresentable_parent") in issue_codes
    assert ("child_of_unmapped", "missing_parent") not in issue_codes
    assert all(
        "absent from supplied snapshots" not in issue["detail"]
        for issue in ledger.reconciliation_issues
    )
    child_comparison = next(
        comparison
        for comparison in ledger.comparisons
        if comparison.candidate_ref
        == "legacy://next_tasks/child_of_unmapped"
    )
    parent_dimension = next(
        dimension
        for dimension in child_comparison.dimensions
        if dimension.name == "parent"
    )
    assert parent_dimension.classification == "legacy_corruption"
    assert parent_dimension.classification_reason_code == (
        "reconciliation:unknown_source,unrepresentable_parent"
    )
    assert (
        "reconciliation://next_tasks/unmapped_parent/record-0/unknown_source"
        in parent_dimension.evidence_refs
    )
    assert (
        "reconciliation://next_tasks/child_of_unmapped/unrepresentable_parent"
        in parent_dimension.evidence_refs
    )
    assert ledger.selection_difference is not None
    assert ledger.selection_difference.classification == "legacy_corruption"
    assert ledger.selection_difference.classification_reason_code == (
        "reconciliation:unknown_source,unrepresentable_parent"
    )


def test_task_record_parent_is_dependency_context_not_selection_candidate() -> None:
    child = _pending_task(
        "child_of_task_record",
        priority=1,
        parent_task_id="completed_task_record",
    )
    completed_parent = {
        "id": "completed_task_record",
        "title": "Completed dependency outside next_tasks selection scope",
        "source": "agent",
        "task_family": "ops",
        "priority": 9,
        "approval_mode": "auto",
        "risk_level": "safe",
        "status": "succeeded",
        "public_effect": "none",
        "created_at": "2026-07-23T08:00:00+00:00",
        "finished_at": "2026-07-23T09:00:00+00:00",
    }

    ledger = replay_legacy_selection(
        LegacySnapshots(
            next_tasks=(child,),
            task_records=(completed_parent,),
        ),
        offer=_offer(),
        observed_at=FIXED_NOW,
        observation_id="obs_task_record_parent",
    )

    assert ledger.reconciliation_issues == ()
    assert ledger.legacy_selection.selected_candidate_ref == (
        "legacy://next_tasks/child_of_task_record"
    )
    assert ledger.coordinator_selection.selected_candidate_ref == (
        "legacy://next_tasks/child_of_task_record"
    )
    assert ledger.selection_difference is None
    assert {
        comparison.candidate_ref for comparison in ledger.comparisons
    } == {"legacy://next_tasks/child_of_task_record"}
    parent_dimension = next(
        dimension
        for dimension in ledger.comparisons[0].dimensions
        if dimension.name == "parent"
    )
    assert parent_dimension.coordinator["satisfied"] is True
    assert parent_dimension.coordinator_reason_codes == ("parent_succeeded",)
    assert parent_dimension.matches is False
    assert parent_dimension.classification == "policy_change"
    assert (
        parent_dimension.classification_reason_code
        == "coordinator_parent_readiness"
    )


def test_parent_lifecycle_issue_does_not_replace_selector_causality() -> None:
    child = _pending_task(
        "child_of_lifecycle_issue",
        parent_task_id="unfinished_parent",
    )
    unfinished_parent = {
        "id": "unfinished_parent",
        "title": "Succeeded status with incomplete audit trace",
        "source": "agent",
        "task_family": "ops",
        "priority": 9,
        "approval_mode": "auto",
        "risk_level": "safe",
        "status": "succeeded",
        "public_effect": "none",
        "created_at": "2026-07-23T08:00:00+00:00",
    }

    ledger = replay_legacy_selection(
        LegacySnapshots(
            next_tasks=(child,),
            task_records=(unfinished_parent,),
        ),
        offer=_offer(),
        observed_at=FIXED_NOW,
        observation_id="obs_parent_lifecycle_issue",
    )

    assert any(
        issue["code"] == "invalid_lifecycle"
        and issue["record_id"] == "unfinished_parent"
        for issue in ledger.reconciliation_issues
    )
    assert ledger.coordinator_selection.selected_candidate_ref == (
        "legacy://next_tasks/child_of_lifecycle_issue"
    )
    parent_dimension = next(
        dimension
        for dimension in ledger.comparisons[0].dimensions
        if dimension.name == "parent"
    )
    assert parent_dimension.classification == "policy_change"
    assert parent_dimension.classification_reason_code == (
        "coordinator_parent_readiness"
    )
    assert all(
        "invalid_lifecycle" not in evidence_ref
        for evidence_ref in parent_dimension.evidence_refs
    )


def test_comma_in_parent_id_does_not_hide_idempotency_corruption() -> None:
    child = _pending_task(
        "child_of_ambiguous_dependencies",
        parent_task_id="job,a",
    )
    base_job = {
        "action": "recalc_metrics",
        "source": "system",
        "requested_by": "owner",
        "dry_run": True,
        "priority": 9,
        "status": "succeeded",
        "dedupe_key": "shared-dedupe-key",
        "created_at": "2026-07-23T08:00:00+00:00",
        "finished_at": "2026-07-23T09:00:00+00:00",
    }

    ledger = replay_legacy_selection(
        LegacySnapshots(
            next_tasks=(child,),
            ops_jobs=(
                {**base_job, "id": "job,a"},
                {**base_job, "id": "job-b"},
            ),
        ),
        offer=_offer(),
        observed_at=FIXED_NOW,
        observation_id="obs_comma_parent_id",
    )

    collision = next(
        issue
        for issue in ledger.reconciliation_issues
        if issue["code"] == "duplicate_idempotency_key"
    )
    assert collision["affected_record_ids"] == ["job,a", "job-b"]
    assert collision["evidence_ref"] == (
        "reconciliation://ops_jobs/_records/duplicate_idempotency_key"
        "?record_id=job%2Ca&record_id=job-b"
    )
    assert ledger.legacy_selection.selected_candidate_ref == (
        "legacy://next_tasks/child_of_ambiguous_dependencies"
    )
    assert ledger.coordinator_selection.selected_candidate_ref is None
    parent_dimension = next(
        dimension
        for dimension in ledger.comparisons[0].dimensions
        if dimension.name == "parent"
    )
    assert parent_dimension.classification == "legacy_corruption"
    assert parent_dimension.classification_reason_code == (
        "reconciliation:duplicate_idempotency_key"
    )
    assert collision["evidence_ref"] in parent_dimension.evidence_refs


def test_no_parent_projection_remains_an_exact_match() -> None:
    ledger = replay_legacy_selection(
        LegacySnapshots(next_tasks=(_pending_task("standalone"),)),
        offer=_offer(),
        observed_at=FIXED_NOW,
        observation_id="obs_no_parent",
    )

    parent_dimension = next(
        dimension
        for dimension in ledger.comparisons[0].dimensions
        if dimension.name == "parent"
    )
    assert parent_dimension.matches is True
    assert parent_dimension.classification is None
    assert parent_dimension.classification_reason_code is None


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
            dimension.classification_reason_code,
            dimension.legacy_reason_codes,
            dimension.coordinator_reason_codes,
            dimension.evidence_refs,
        )
        for comparison in first.comparisons
        for dimension in comparison.dimensions
        if not dimension.matches
    }
    second_differences = {
        (comparison.candidate_ref, dimension.name): (
            dimension.classification,
            dimension.classification_reason_code,
            dimension.legacy_reason_codes,
            dimension.coordinator_reason_codes,
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
        for (
            classification,
            _reason,
            _legacy_reasons,
            _coordinator_reasons,
            evidence_refs,
        ) in first_differences.values()
    )
    assert all(
        reason
        not in {
            "unregistered_selector_reason_pair",
            "unexplained_selection_difference",
        }
        for _, reason, _, _, _ in first_differences.values()
    )
    attestation = first_differences[
        ("legacy://next_tasks/child", "attestation")
    ]
    assert attestation[0] == "policy_change"
    assert attestation[1] == "coordinator_attestation_contract"
    assert attestation[2] == ("legacy_attestation_not_enforced",)
    assert attestation[3] == (
        "coordinator_attestation_enforced",
        "attestation_mismatch",
    )
    assert first_differences[
        ("legacy://next_tasks/child", "parent")
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
    parent = next(
        dimension
        for dimension in ledger.comparisons[0].dimensions
        if dimension.name == "parent"
    )
    assert parent.matches is False
    assert parent.classification == "legacy_corruption"
    assert parent.classification_reason_code == "reconciliation:missing_parent"
    assert (
        "reconciliation://next_tasks/orphan/missing_parent"
        in parent.evidence_refs
    )


def test_reconciliation_only_marks_affected_dimensions_as_corruption() -> None:
    orphan = _pending_task(
        "orphan_with_deadline",
        parent_task_id="missing_parent",
        deadline="2026-07-24T00:00:00+00:00",
    )

    ledger = replay_legacy_selection(
        LegacySnapshots(next_tasks=(orphan,)),
        offer=_offer(),
        observed_at=FIXED_NOW,
        observation_id="obs_scoped_corruption",
    )

    dimensions = {
        dimension.name: dimension
        for dimension in ledger.comparisons[0].dimensions
    }
    assert dimensions["parent"].classification == "legacy_corruption"
    assert dimensions["deadline"].classification == "policy_change"
    assert (
        dimensions["deadline"].classification_reason_code
        == "coordinator_deadline_ordering"
    )
    assert all(
        "reconciliation://next_tasks/orphan_with_deadline/missing_parent"
        not in evidence_ref
        for evidence_ref in dimensions["deadline"].evidence_refs
    )


def test_succeeded_parent_gate_is_an_explicit_policy_change() -> None:
    parent = _pending_task("completed_parent", priority=9)
    parent.update(
        {
            "status": "succeeded",
            "completed_at": "2026-07-23T09:05:00+00:00",
            "result": "done",
        }
    )
    child = _pending_task(
        "ready_child",
        parent_task_id="completed_parent",
    )

    ledger = replay_legacy_selection(
        LegacySnapshots(next_tasks=(parent, child)),
        offer=_offer(),
        observed_at=FIXED_NOW,
        observation_id="obs_succeeded_parent",
    )

    child_comparison = next(
        comparison
        for comparison in ledger.comparisons
        if comparison.candidate_ref == "legacy://next_tasks/ready_child"
    )
    parent_dimension = next(
        dimension
        for dimension in child_comparison.dimensions
        if dimension.name == "parent"
    )
    assert parent_dimension.classification == "policy_change"
    assert (
        parent_dimension.classification_reason_code
        == "coordinator_parent_readiness"
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

    lane = next(
        dimension
        for dimension in ledger.comparisons[0].dimensions
        if dimension.name == "dispatch_lane"
    )
    assert lane.legacy["claimable"] is False
    assert lane.coordinator["claimable"] is True
    assert lane.classification == "implementation_bug"
    assert (
        lane.classification_reason_code
        == "migration_missing_dispatch_lane_capability_mapping"
    )


def test_replay_uses_real_selector_reasons_for_routing_and_lease_policy() -> None:
    manual = _pending_task("manual", priority=1)
    manual["dispatch_lane"] = "manual"
    preferred = _pending_task("preferred", priority=2)
    preferred["task_type"] = "paper_body"
    preferred["preferred_agent"] = "codex"
    expired_claim = _pending_task("expired_claim", priority=3)
    expired_claim.update(
        {
            "status": "claimed",
            "claimed_by": "old-worker",
            "claimed_at": "2026-07-23T09:00:00+00:00",
            "claim_expires_at": "2026-07-23T09:29:59+00:00",
        }
    )

    ledger = replay_legacy_selection(
        LegacySnapshots(
            next_tasks=(manual, preferred, expired_claim),
        ),
        offer=WorkerOffer(
            worker_id="codex-shadow",
            capabilities=frozenset({"code"}),
            attestations=frozenset(),
            lease_seconds=300,
        ),
        observed_at=FIXED_NOW,
        observation_id="obs_real_selectors",
    )

    assert ledger.schema_version == "work-shadow-replay.v2"
    assert ledger.selection_scope == "next_tasks"
    assert ledger.legacy_selection.selected_candidate_ref == (
        "legacy://next_tasks/preferred"
    )
    assert ledger.coordinator_selection.selected_candidate_ref == (
        "legacy://next_tasks/manual"
    )
    by_candidate = {
        comparison.candidate_ref: {
            dimension.name: dimension
            for dimension in comparison.dimensions
        }
        for comparison in ledger.comparisons
    }
    manual_lane = by_candidate["legacy://next_tasks/manual"]["dispatch_lane"]
    assert manual_lane.legacy_reason_codes == ("main_thread_lane",)
    assert "ready_pending" in manual_lane.coordinator_reason_codes
    assert manual_lane.classification == "implementation_bug"
    assert (
        manual_lane.classification_reason_code
        == "migration_missing_dispatch_lane_capability_mapping"
    )
    preference = by_candidate["legacy://next_tasks/preferred"][
        "preferred_agent"
    ]
    assert preference.classification == "policy_change"
    assert (
        preference.classification_reason_code
        == "provider_execution_capability_routing"
    )
    lease = by_candidate["legacy://next_tasks/expired_claim"]["lease_expiry"]
    assert "already_claimed" in lease.legacy_reason_codes
    assert "ready_expired_claim" in lease.coordinator_reason_codes
    assert lease.classification == "policy_change"
    assert (
        lease.classification_reason_code
        == "coordinator_expired_lease_reclaim"
    )


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


def test_created_at_tie_break_has_an_explicit_ranking_classification() -> None:
    newer_but_lexically_first = _pending_task("a_new")
    newer_but_lexically_first["created_at"] = "2026-07-23T09:10:00+00:00"
    older_but_lexically_last = _pending_task("z_old")
    older_but_lexically_last["created_at"] = "2026-07-23T09:00:00+00:00"

    ledger = replay_legacy_selection(
        LegacySnapshots(
            next_tasks=(
                newer_but_lexically_first,
                older_but_lexically_last,
            )
        ),
        offer=_offer(),
        observed_at=FIXED_NOW,
        observation_id="obs_created_at_rank",
    )

    assert ledger.legacy_selection.selected_candidate_ref == (
        "legacy://next_tasks/a_new"
    )
    assert ledger.coordinator_selection.selected_candidate_ref == (
        "legacy://next_tasks/z_old"
    )
    assert ledger.selection_difference is not None
    assert ledger.selection_difference.classification == "policy_change"
    assert (
        ledger.selection_difference.classification_reason_code
        == "coordinator_ranking_contract"
    )


def test_legacy_winner_uses_exact_pending_list_before_direct_claim_gate() -> None:
    blocked = _pending_task("blocked_p1", priority=1)
    blocked["status"] = "blocked"
    same_owner_claimed = _pending_task("same_owner_claimed_p1", priority=1)
    same_owner_claimed.update(
        {
            "status": "claimed",
            "claimed_by": "codex-shadow",
            "claimed_at": "2026-07-23T09:00:00+00:00",
        }
    )
    pending = _pending_task("pending_p2", priority=2)

    ledger = replay_legacy_selection(
        LegacySnapshots(
            next_tasks=(blocked, same_owner_claimed, pending),
        ),
        offer=WorkerOffer(
            worker_id="codex-shadow",
            capabilities=frozenset({"code"}),
            attestations=frozenset(),
            lease_seconds=300,
        ),
        observed_at=FIXED_NOW,
        observation_id="obs_pending_list_scope",
    )

    assert ledger.legacy_selection.selected_candidate_ref == (
        "legacy://next_tasks/pending_p2"
    )
    assert ledger.legacy_selection.eligible_candidate_refs == (
        "legacy://next_tasks/pending_p2",
    )


def test_managed_event_deadline_uses_the_production_admission_reason() -> None:
    expired = _pending_task(
        "expired_event",
        deadline="2026-07-23T09:29:59+00:00",
    )
    expired.update(
        {
            "task_type": "event_article",
            "source": "event_expander",
            "ref_event_job_id": "event-1",
        }
    )

    ledger = replay_legacy_selection(
        LegacySnapshots(next_tasks=(expired,)),
        offer=WorkerOffer(
            worker_id="shadow-worker",
            capabilities=frozenset({"code", "content"}),
            attestations=frozenset(),
            lease_seconds=300,
        ),
        observed_at=FIXED_NOW,
        observation_id="obs_expired_event",
    )

    dimensions = {
        dimension.name: dimension
        for dimension in ledger.comparisons[0].dimensions
    }
    readiness = dimensions["readiness"]
    assert readiness.legacy_reason_codes == (
        "deadline_expired",
        "legacy_managed_event_deadline_gate",
    )
    assert "ready_pending" in readiness.coordinator_reason_codes
    assert readiness.classification == "policy_change"
    assert (
        readiness.classification_reason_code
        == "schedule_materializer_event_deadline_contract"
    )
    deadline = dimensions["deadline"]
    assert "deadline_expired" in deadline.legacy_reason_codes
    assert deadline.classification == "policy_change"
    assert (
        deadline.classification_reason_code
        == "schedule_materializer_event_deadline_contract"
    )


def test_terminal_mapping_uses_explicit_selector_policy_evidence() -> None:
    null_result = _pending_task("null_result")
    null_result["status"] = "succeeded_null_result"
    null_result["completed_at"] = "2026-07-23T09:15:00+00:00"

    ledger = replay_legacy_selection(
        LegacySnapshots(next_tasks=(null_result,)),
        offer=_offer(),
        observed_at=FIXED_NOW,
        observation_id="obs_terminal_mapping",
    )

    terminal = next(
        dimension
        for dimension in ledger.comparisons[0].dimensions
        if dimension.name == "terminal_disposition"
    )
    assert terminal.matches is False
    assert terminal.legacy_reason_codes == ("legacy_terminal_mapping",)
    assert terminal.coordinator_reason_codes == (
        "coordinator_terminal_mapping",
    )
    assert terminal.classification == "policy_change"
    assert (
        terminal.classification_reason_code
        == "coordinator_terminal_mapping"
    )


def test_capability_and_claim_differences_use_registered_policy_reasons() -> None:
    capability = _pending_task("capability_gap", priority=1)
    capability["required_capabilities"] = ["research"]
    expired_claim = _pending_task("expired_owner", priority=2)
    expired_claim.update(
        {
            "status": "claimed",
            "claimed_by": "old-worker",
            "claimed_at": "2026-07-23T09:00:00+00:00",
            "claim_expires_at": "2026-07-23T09:29:59+00:00",
        }
    )

    ledger = replay_legacy_selection(
        LegacySnapshots(next_tasks=(capability, expired_claim)),
        offer=_offer(),
        observed_at=FIXED_NOW,
        observation_id="obs_registered_dimensions",
    )
    by_candidate = {
        comparison.candidate_ref: {
            dimension.name: dimension
            for dimension in comparison.dimensions
        }
        for comparison in ledger.comparisons
    }

    capability_dimension = by_candidate[
        "legacy://next_tasks/capability_gap"
    ]["capability"]
    assert capability_dimension.classification == "policy_change"
    assert (
        capability_dimension.classification_reason_code
        == "coordinator_capability_contract"
    )
    ownership = by_candidate["legacy://next_tasks/expired_owner"][
        "claim_ownership"
    ]
    assert ownership.classification == "policy_change"
    assert (
        ownership.classification_reason_code
        == "coordinator_expired_lease_reclaim"
    )
    assert ledger.selection_difference is not None
    assert (
        ledger.selection_difference.classification_reason_code
        == "coordinator_capability_contract"
    )


def test_live_same_owner_and_missing_expiry_claims_have_explicit_reasons() -> None:
    same_owner = _pending_task("same_owner_live", priority=1)
    same_owner.update(
        {
            "status": "claimed",
            "claimed_by": "shadow-worker",
            "claimed_at": "2026-07-23T09:00:00+00:00",
            "claim_expires_at": "2026-07-23T09:31:00+00:00",
        }
    )
    missing_expiry = _pending_task("missing_expiry", priority=2)
    missing_expiry.update(
        {
            "status": "claimed",
            "claimed_by": "old-worker",
            "claimed_at": "2026-07-23T09:00:00+00:00",
        }
    )
    expired_same_owner = _pending_task("expired_same_owner", priority=3)
    expired_same_owner.update(
        {
            "status": "claimed",
            "claimed_by": "shadow-worker",
            "claimed_at": "2026-07-23T09:00:00+00:00",
            "claim_expires_at": "2026-07-23T09:29:59+00:00",
        }
    )

    ledger = replay_legacy_selection(
        LegacySnapshots(
            next_tasks=(
                same_owner,
                missing_expiry,
                expired_same_owner,
            )
        ),
        offer=_offer(),
        observed_at=FIXED_NOW,
        observation_id="obs_claim_edges",
    )
    by_candidate = {
        comparison.candidate_ref: {
            dimension.name: dimension
            for dimension in comparison.dimensions
        }
        for comparison in ledger.comparisons
    }

    same_owner_readiness = by_candidate[
        "legacy://next_tasks/same_owner_live"
    ]["readiness"]
    assert same_owner_readiness.classification == "policy_change"
    assert (
        same_owner_readiness.classification_reason_code
        == "coordinator_inline_lease_contract"
    )
    missing_expiry_lease = by_candidate[
        "legacy://next_tasks/missing_expiry"
    ]["lease_expiry"]
    assert missing_expiry_lease.classification == "implementation_bug"
    assert (
        missing_expiry_lease.classification_reason_code
        == "claim_expiry_unrepresentable"
    )
    expired_comparison = next(
        comparison
        for comparison in ledger.comparisons
        if comparison.candidate_ref
        == "legacy://next_tasks/expired_same_owner"
    )
    assert expired_comparison.legacy_eligible is False
    assert expired_comparison.coordinator_eligible is True
    assert ledger.selection_difference is not None
    assert (
        ledger.selection_difference.classification_reason_code
        == "coordinator_expired_lease_reclaim"
    )


def test_blocked_direct_claim_policy_does_not_invent_a_list_winner() -> None:
    blocked = _pending_task("blocked_direct_claim")
    blocked.update(
        {
            "status": "blocked",
            "blocked_reason": "dependency_pending",
        }
    )

    ledger = replay_legacy_selection(
        LegacySnapshots(next_tasks=(blocked,)),
        offer=_offer(),
        observed_at=FIXED_NOW,
        observation_id="obs_blocked_direct_claim",
    )

    comparison = ledger.comparisons[0]
    assert comparison.legacy_eligible is False
    assert comparison.coordinator_eligible is False
    assert ledger.legacy_selection.selected_candidate_ref is None
    assert ledger.coordinator_selection.selected_candidate_ref is None
    assert ledger.selection_difference is None


def test_replay_has_no_filesystem_read_or_work_submission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_call(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("shadow replay crossed its snapshot-only boundary")

    monkeypatch.setattr(Path, "read_text", unexpected_call)
    monkeypatch.setattr(Path, "read_bytes", unexpected_call)
    monkeypatch.setattr(Path, "open", unexpected_call)
    monkeypatch.setattr(builtins, "open", unexpected_call)
    monkeypatch.setattr(socket, "create_connection", unexpected_call)
    monkeypatch.setattr(socket.socket, "connect", unexpected_call)
    monkeypatch.setattr(WorkCoordinator, "submit", unexpected_call)

    ledger = replay_legacy_selection(
        LegacySnapshots(next_tasks=(_pending_task("isolated"),)),
        offer=_offer(),
        observed_at=FIXED_NOW,
        observation_id="obs_no_live_io",
    )

    assert ledger.legacy_selection.selected_candidate_ref == (
        "legacy://next_tasks/isolated"
    )


def test_replay_excludes_dreaming_work_without_live_revalidation_evidence() -> None:
    dreaming = _pending_task("dreaming_orphan", priority=1)
    dreaming.update(
        {
            "task_type": "experiment",
            "source": "dreaming",
            "dreaming": {
                "signature": "orphaned_experiment:k1800",
                "pattern_type": "orphaned_experiment",
            },
        }
    )
    ordinary = _pending_task("ordinary", priority=2)

    ledger = replay_legacy_selection(
        LegacySnapshots(next_tasks=(dreaming, ordinary)),
        offer=WorkerOffer(
            worker_id="codex-shadow",
            capabilities=frozenset({"code", "research"}),
            attestations=frozenset(),
            lease_seconds=300,
        ),
        observed_at=FIXED_NOW,
        observation_id="obs_dreaming_revalidation",
    )

    assert ledger.legacy_selection.selected_candidate_ref == (
        "legacy://next_tasks/ordinary"
    )
    dreaming_comparison = next(
        comparison
        for comparison in ledger.comparisons
        if comparison.candidate_ref
        == "legacy://next_tasks/dreaming_orphan"
    )
    readiness = next(
        dimension
        for dimension in dreaming_comparison.dimensions
        if dimension.name == "readiness"
    )
    assert readiness.legacy_reason_codes == (
        "live_revalidation_required",
    )
    assert readiness.classification == "implementation_bug"
    assert (
        readiness.classification_reason_code
        == "replay_missing_live_revalidation_evidence"
    )


def test_observation_receipts_accumulate_without_overwrite(
    tmp_path: Path,
) -> None:
    snapshots = LegacySnapshots(
        next_tasks=(_pending_task("scheduled_replay"),)
    )
    first = replay_legacy_selection(
        snapshots,
        offer=_offer(),
        observed_at=FIXED_NOW,
        observation_id="obs_append_1",
    )
    first_path = append_shadow_observation(first, directory=tmp_path)
    first_bytes = first_path.read_bytes()

    with pytest.raises(FileExistsError):
        append_shadow_observation(first, directory=tmp_path)

    second = replay_legacy_selection(
        snapshots,
        offer=_offer(),
        observed_at=FIXED_NOW,
        observation_id="obs_append_2",
    )
    second_path = append_shadow_observation(second, directory=tmp_path)

    assert first_path.name == "obs_append_1.json"
    assert second_path.name == "obs_append_2.json"
    assert first_path.read_bytes() == first_bytes
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "obs_append_1.json",
        "obs_append_2.json",
    ]
    assert json.loads(first_bytes)["snapshot"]["sha256"] == (
        first.snapshot.sha256
    )
