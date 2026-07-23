from volpred.ops.work_migration import (
    LegacySnapshots,
    preview_legacy_snapshots,
)


def test_next_tasks_snapshot_maps_pending_work_to_canonical_candidate() -> None:
    report = preview_legacy_snapshots(
        LegacySnapshots(
            next_tasks=(
                {
                    "id": "assign_platform_fix",
                    "status": "pending",
                    "task_type": "platform_ops",
                    "title": "Repair the dispatch state machine",
                    "description": "Fix the repeatable workflow, not live data.",
                    "priority": 2,
                    "source": "user",
                    "created_by": "owner",
                    "created_at": "2026-07-23T07:00:00+00:00",
                },
            ),
        )
    )

    assert report.ready is True
    assert report.issues == ()
    assert report.source_counts == {
        "next_tasks": {"seen": 1, "mapped": 1},
        "task_records": {"seen": 0, "mapped": 0},
        "ops_jobs": {"seen": 0, "mapped": 0},
    }
    candidate = report.candidates[0]
    assert candidate.source_system == "next_tasks"
    assert candidate.legacy_id == "assign_platform_fix"
    assert candidate.status == "pending"
    assert candidate.request.idempotency_key == (
        "legacy:next_tasks:assign_platform_fix"
    )
    assert candidate.request.kind == "platform_ops"
    assert candidate.request.required_capabilities == frozenset({"code"})
    assert candidate.request.required_attestations == frozenset()
    assert candidate.request.risk == "safe"
    assert candidate.request.approval == "auto"
    assert candidate.request.payload_ref.startswith(
        "legacy-snapshot://next_tasks/assign_platform_fix?sha256="
    )
    assert candidate.request.requester_ref == "owner"
    assert candidate.created_at == "2026-07-23T07:00:00+00:00"


def test_next_tasks_source_provenance_is_classified_and_auditable() -> None:
    report = preview_legacy_snapshots(
        LegacySnapshots(
            next_tasks=(
                {
                    "id": "auto_candidate",
                    "status": "pending",
                    "task_type": "experiment",
                    "title": "Agent-discovered research",
                    "priority": 3,
                    "source": "auto_discovered",
                    "created_at": "2026-07-23T07:00:00+00:00",
                },
                {
                    "id": "email_candidate",
                    "status": "pending",
                    "task_type": "email_reply",
                    "title": "Owner email request",
                    "priority": 1,
                    "source": "gmail_inbox_poll",
                    "created_at": "2026-07-23T07:00:00+00:00",
                },
                {
                    "id": "legacy_producer_candidate",
                    "status": "pending",
                    "task_type": "experiment",
                    "title": "Legacy producer with preserved provenance",
                    "priority": 3,
                    "source": "diverse_gen",
                    "created_at": "2026-07-23T07:00:00+00:00",
                },
                {
                    "id": "event_candidate",
                    "status": "pending",
                    "task_type": "event_article",
                    "title": "Canonical event materializer output",
                    "priority": 1,
                    "source": "event_expander",
                    "created_at": "2026-07-23T07:00:00+00:00",
                    "deadline": "2026-07-23T08:00:00+00:00",
                    "ref_event_job_id": "event-job-1",
                },
            ),
        )
    )

    assert report.ready is True
    agent_candidate, user_candidate, legacy_producer, event_candidate = (
        report.candidates
    )
    assert agent_candidate.request.source == "agent"
    assert agent_candidate.legacy_source == "auto_discovered"
    assert agent_candidate.source_classification == "exact:auto_discovered"
    assert user_candidate.request.source == "user"
    assert user_candidate.legacy_source == "gmail_inbox_poll"
    assert user_candidate.source_classification == "exact:gmail_inbox_poll"
    assert legacy_producer.request.source == "agent"
    assert legacy_producer.legacy_source == "diverse_gen"
    assert legacy_producer.source_classification == "exact:diverse_gen"
    assert event_candidate.request.source == "schedule"
    assert event_candidate.legacy_source == "event_expander"
    assert event_candidate.source_classification == "exact:event_expander"
    assert event_candidate.ref_event_job_id == "event-job-1"
    assert report.as_dict()["candidates"][0]["source_provenance"] == {
        "legacy": "auto_discovered",
        "canonical": "agent",
        "classification": "exact:auto_discovered",
    }


def test_next_tasks_snapshot_preserves_parent_deadline_claim_and_terminal_history() -> None:
    report = preview_legacy_snapshots(
        LegacySnapshots(
            next_tasks=(
                {
                    "id": "parent_done",
                    "status": "succeeded",
                    "task_type": "experiment",
                    "title": "Verified parent experiment",
                    "priority": 3,
                    "source": "agent",
                    "created_at": "2026-07-22T01:00:00+00:00",
                    "completed_at": "2026-07-22T04:00:00+00:00",
                    "result": "null result retained",
                },
                {
                    "id": "child_running",
                    "status": "in_progress",
                    "task_type": "platform_ops",
                    "title": "Consume the parent result",
                    "priority": 1,
                    "source": "schedule",
                    "created_at": "2026-07-23T08:00:00+08:00",
                    "updated_at": "2026-07-23T08:10:00+08:00",
                    "claimed_at": "2026-07-23T08:04:00+08:00",
                    "started_at": "2026-07-23T08:05:00+08:00",
                    "claimed_by": "codex-worker",
                    "parent_task_id": "parent_done",
                    "deadline": "2026-07-24T09:00:00+08:00",
                    "required_capabilities": ["postgres"],
                    "required_attestations": ["zero_paid"],
                    "risk": "sensitive",
                    "approval": "required",
                },
            ),
        )
    )

    assert report.ready is True
    parent, child = report.candidates
    assert parent.status == "succeeded"
    assert parent.finished_at == "2026-07-22T04:00:00+00:00"
    assert parent.result_summary == "null result retained"
    assert child.status == "running"
    assert child.claimed_by == "codex-worker"
    assert child.claimed_at == "2026-07-23T00:04:00+00:00"
    assert child.started_at == "2026-07-23T00:05:00+00:00"
    assert child.request.parent_id == "parent_done"
    assert child.request.deadline == "2026-07-24T01:00:00+00:00"
    assert child.request.required_capabilities == frozenset(
        {"code", "postgres"}
    )
    assert child.request.required_attestations == frozenset({"zero_paid"})
    assert child.request.risk == "sensitive"
    assert child.request.approval == "required"
    assert child.created_at == "2026-07-23T00:00:00+00:00"
    assert child.updated_at == "2026-07-23T00:10:00+00:00"


def test_next_tasks_snapshot_preserves_real_claim_selector_metadata() -> None:
    report = preview_legacy_snapshots(
        LegacySnapshots(
            next_tasks=(
                {
                    "id": "selector_metadata",
                    "status": "claimed",
                    "task_type": "paper_body",
                    "title": "Keep routing and lease evidence",
                    "priority": 1,
                    "source": "user",
                    "created_at": "2026-07-23T08:00:00+08:00",
                    "claimed_at": "2026-07-23T08:05:00+08:00",
                    "claimed_by": "codex-worker",
                    "dispatch_lane": "manual",
                    "preferred_agent": "codex",
                    "target_agent": "claude",
                    "claim_expires_at": "2026-07-23T08:10:00+08:00",
                    "dreaming": {
                        "signature": "orphaned_experiment:k1800",
                        "pattern_type": "orphaned_experiment",
                    },
                },
            ),
        )
    )

    assert report.ready is True
    candidate = report.candidates[0]
    assert candidate.dispatch_lane == "manual"
    assert candidate.preferred_agent == "codex"
    assert candidate.target_agent == "claude"
    assert candidate.claim_expires_at == "2026-07-23T00:10:00+00:00"
    assert candidate.dreaming == {
        "signature": "orphaned_experiment:k1800",
        "pattern_type": "orphaned_experiment",
    }


def test_task_record_snapshot_maps_legacy_policy_and_running_owner() -> None:
    report = preview_legacy_snapshots(
        LegacySnapshots(
            task_records=(
                {
                    "id": "task_parent",
                    "title": "Parent task",
                    "source": "agent",
                    "task_family": "ops",
                    "priority": 5,
                    "approval_mode": "auto",
                    "risk_level": "safe",
                    "status": "succeeded",
                    "public_effect": "none",
                    "created_at": "2026-07-22T07:00:00+00:00",
                    "updated_at": "2026-07-22T08:00:00+00:00",
                    "finished_at": "2026-07-22T08:00:00+00:00",
                },
                {
                    "id": "task_platform_review",
                    "title": "Review the coordination migration",
                    "description": "Use the fixed ADR and report findings.",
                    "source": "user",
                    "task_family": "review",
                    "priority": 4,
                    "preferred_agent": "codex",
                    "fallback_allowed": False,
                    "approval_mode": "needs_approval",
                    "risk_level": "elevated",
                    "status": "running",
                    "payload": {"scope": "migration"},
                    "parent_task_id": "task_parent",
                    "created_by": "owner",
                    "public_effect": "none",
                    "claimed_by": "codex",
                    "claimed_at": "2026-07-23T07:05:00+00:00",
                    "started_at": "2026-07-23T07:10:00+00:00",
                    "created_at": "2026-07-23T07:00:00+00:00",
                    "updated_at": "2026-07-23T07:10:00+00:00",
                },
            ),
        )
    )

    assert report.ready is True
    candidate = report.candidates[1]
    assert candidate.source_system == "task_records"
    assert candidate.status == "running"
    assert candidate.claimed_by == "codex"
    assert candidate.request.kind == "review"
    assert candidate.request.parent_id == "task_parent"
    assert candidate.request.required_capabilities == frozenset({"code"})
    assert candidate.request.risk == "sensitive"
    assert candidate.request.approval == "required"
    assert candidate.request.requester_ref == "owner"
    assert candidate.preferred_agent == "codex"
    assert candidate.fallback_allowed is False
    assert report.source_counts["task_records"] == {"seen": 2, "mapped": 2}


def test_ops_jobs_snapshot_maps_dry_run_job_without_external_effect() -> None:
    report = preview_legacy_snapshots(
        LegacySnapshots(
            ops_jobs=(
                {
                    "id": "018f0000-0000-7000-8000-000000000001",
                    "action": "strategy_set_active",
                    "scope": "remote",
                    "source": "human",
                    "requested_by": "owner",
                    "payload": {"strategy_id": "shadow-only"},
                    "dry_run": True,
                    "priority": 6,
                    "status": "queued",
                    "worker_id": None,
                    "result": None,
                    "error": None,
                    "dedupe_key": "strategy:shadow-only:preview",
                    "created_at": "2026-07-23T09:00:00+00:00",
                    "started_at": None,
                    "finished_at": None,
                    "updated_at": "2026-07-23T09:00:00+00:00",
                },
            ),
        )
    )

    assert report.ready is True
    candidate = report.candidates[0]
    assert candidate.source_system == "ops_jobs"
    assert candidate.status == "pending"
    assert candidate.request.source == "user"
    assert candidate.request.kind == "ops_job.strategy_set_active"
    assert candidate.request.required_capabilities == frozenset({"code"})
    assert candidate.request.risk == "safe"
    assert candidate.request.approval == "auto"
    assert candidate.request.requester_ref == "owner"
    assert candidate.request.idempotency_key == (
        "legacy:ops_jobs:strategy:shadow-only:preview"
    )
    assert report.source_counts["ops_jobs"] == {"seen": 1, "mapped": 1}


def test_unknown_legacy_status_is_reported_and_not_mapped() -> None:
    report = preview_legacy_snapshots(
        LegacySnapshots(
            next_tasks=(
                {
                    "id": "unknown_status",
                    "status": "silently_new_state",
                    "task_type": "platform_ops",
                    "title": "Must fail closed",
                    "priority": 1,
                    "source": "agent",
                    "created_at": "2026-07-23T09:00:00+00:00",
                },
            ),
        )
    )

    assert report.ready is False
    assert report.candidates == ()
    assert report.source_counts["next_tasks"] == {"seen": 1, "mapped": 0}
    assert tuple(issue.code for issue in report.issues) == ("unknown_status",)
    assert report.issues[0].record_id == "unknown_status"


def test_public_effects_without_effect_delivery_are_fail_closed() -> None:
    report = preview_legacy_snapshots(
        LegacySnapshots(
            task_records=(
                {
                    "id": "task_public",
                    "title": "Publish member-visible answer",
                    "source": "user",
                    "task_family": "member",
                    "priority": 1,
                    "approval_mode": "needs_approval",
                    "risk_level": "elevated",
                    "status": "queued",
                    "public_effect": "member_visible",
                    "created_at": "2026-07-23T09:00:00+00:00",
                },
            ),
            ops_jobs=(
                {
                    "id": "job_public",
                    "action": "send_daily_digest",
                    "source": "system",
                    "dry_run": False,
                    "priority": 1,
                    "status": "queued",
                    "created_at": "2026-07-23T09:00:00+00:00",
                },
            ),
        )
    )

    assert report.ready is False
    assert report.candidates == ()
    assert tuple(issue.code for issue in report.issues) == (
        "unrepresentable_public_effect",
        "unrepresentable_public_effect",
    )


def test_duplicate_legacy_id_across_sources_is_reported() -> None:
    report = preview_legacy_snapshots(
        LegacySnapshots(
            next_tasks=(
                {
                    "id": "shared_id",
                    "status": "pending",
                    "task_type": "platform_ops",
                    "title": "Canonical queue copy",
                    "priority": 1,
                    "source": "agent",
                    "created_at": "2026-07-23T09:00:00+00:00",
                },
            ),
            task_records=(
                {
                    "id": "shared_id",
                    "title": "Audit-trail copy",
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
        )
    )

    assert report.ready is False
    assert len(report.candidates) == 2
    duplicate = next(
        issue for issue in report.issues if issue.code == "duplicate_id"
    )
    assert duplicate.record_id == "shared_id"
    assert duplicate.source_system == "cross_source"
    assert "next_tasks" in duplicate.detail
    assert "task_records" in duplicate.detail


def test_missing_parent_is_reported_without_guessing_a_replacement() -> None:
    report = preview_legacy_snapshots(
        LegacySnapshots(
            next_tasks=(
                {
                    "id": "orphan_child",
                    "status": "pending",
                    "task_type": "experiment",
                    "title": "Child with an absent parent",
                    "priority": 2,
                    "source": "agent",
                    "parent_task_id": "missing_parent",
                    "created_at": "2026-07-23T09:00:00+00:00",
                },
            ),
        )
    )

    assert report.ready is False
    assert len(report.candidates) == 1
    assert report.candidates[0].request.parent_id == "missing_parent"
    missing_parent = next(
        issue for issue in report.issues if issue.code == "missing_parent"
    )
    assert missing_parent.record_id == "orphan_child"
    assert missing_parent.source_system == "next_tasks"
    assert "missing_parent" in missing_parent.detail


def test_simultaneous_claims_across_sources_are_reported() -> None:
    report = preview_legacy_snapshots(
        LegacySnapshots(
            next_tasks=(
                {
                    "id": "double_claimed",
                    "status": "in_progress",
                    "task_type": "platform_ops",
                    "title": "Queue-owned work",
                    "priority": 1,
                    "source": "agent",
                    "claimed_by": "claude-worker",
                    "claimed_at": "2026-07-23T09:01:00+00:00",
                    "started_at": "2026-07-23T09:02:00+00:00",
                    "created_at": "2026-07-23T09:00:00+00:00",
                },
            ),
            task_records=(
                {
                    "id": "double_claimed",
                    "title": "Audit-owned work",
                    "source": "agent",
                    "task_family": "ops",
                    "priority": 1,
                    "approval_mode": "auto",
                    "risk_level": "safe",
                    "status": "claimed",
                    "public_effect": "none",
                    "claimed_by": "codex-worker",
                    "claimed_at": "2026-07-23T09:01:00+00:00",
                    "created_at": "2026-07-23T09:00:00+00:00",
                },
            ),
        )
    )

    assert report.ready is False
    assert tuple(issue.code for issue in report.issues) == (
        "duplicate_id",
        "simultaneous_claim",
    )
    collision = report.issues[1]
    assert collision.record_id == "double_claimed"
    assert "claude-worker" in collision.detail
    assert "codex-worker" in collision.detail


def test_reconciliation_report_has_stable_json_ready_shape() -> None:
    report = preview_legacy_snapshots(
        LegacySnapshots(
            next_tasks=(
                {
                    "id": "json_candidate",
                    "status": "pending",
                    "task_type": "platform_ops",
                    "title": "Machine-readable preview",
                    "priority": 1,
                    "source": "user",
                    "required_capabilities": ["postgres", "code"],
                    "required_attestations": ["zero_paid"],
                    "created_at": "2026-07-23T09:00:00+00:00",
                },
            ),
        )
    )

    payload = report.as_dict()

    assert payload["ready"] is True
    assert payload["candidate_count"] == 1
    assert payload["issue_count"] == 0
    assert payload["candidates"][0]["request"]["required_capabilities"] == [
        "code",
        "postgres",
    ]
    assert payload["candidates"][0]["request"]["required_attestations"] == [
        "zero_paid"
    ]


def test_unknown_work_policy_is_reported_instead_of_emitting_a_candidate() -> None:
    report = preview_legacy_snapshots(
        LegacySnapshots(
            next_tasks=(
                {
                    "id": "invalid_policy",
                    "status": "pending",
                    "task_type": "platform_ops",
                    "title": "Must not become canonical",
                    "priority": 1,
                    "source": "agent",
                    "risk": "mystery",
                    "approval": "bypass",
                    "created_at": "2026-07-23T09:00:00+00:00",
                },
            ),
            task_records=(
                {
                    "id": "invalid_task_record_policy",
                    "title": "Must not default to auto",
                    "source": "agent",
                    "task_family": "ops",
                    "priority": 1,
                    "approval_mode": "bypass",
                    "risk_level": "safe",
                    "status": "queued",
                    "public_effect": "none",
                    "created_at": "2026-07-23T09:00:00+00:00",
                },
            ),
        )
    )

    assert report.ready is False
    assert report.candidates == ()
    assert tuple(issue.code for issue in report.issues) == (
        "unknown_policy",
        "unknown_policy",
    )


def test_conflicting_approval_policy_and_unknown_source_are_fail_closed() -> None:
    report = preview_legacy_snapshots(
        LegacySnapshots(
            next_tasks=(
                {
                    "id": "conflicting_approval",
                    "status": "pending",
                    "task_type": "platform_ops",
                    "title": "Cannot erase approval requirement",
                    "priority": 1,
                    "source": "agent",
                    "risk": "safe",
                    "approval": "auto",
                    "approval_mode": "needs_approval",
                    "created_at": "2026-07-23T09:00:00+00:00",
                },
                {
                    "id": "unknown_source",
                    "status": "pending",
                    "task_type": "platform_ops",
                    "title": "Cannot invent requester provenance",
                    "priority": 1,
                    "source": "gmail_attacker_controlled",
                    "created_at": "2026-07-23T09:00:00+00:00",
                },
            ),
        )
    )

    assert report.ready is False
    assert report.candidates == ()
    assert tuple(issue.code for issue in report.issues) == (
        "unknown_policy",
        "unknown_source",
    )


def test_inconsistent_lifecycle_trace_is_fail_closed() -> None:
    base = {
        "task_type": "platform_ops",
        "priority": 1,
        "source": "agent",
        "created_at": "2026-07-23T09:00:00+00:00",
    }
    report = preview_legacy_snapshots(
        LegacySnapshots(
            next_tasks=(
                {
                    **base,
                    "id": "ownerless_running",
                    "title": "Running without an owner",
                    "status": "in_progress",
                    "claimed_at": "2026-07-23T09:01:00+00:00",
                    "started_at": "2026-07-23T09:02:00+00:00",
                },
                {
                    **base,
                    "id": "claimed_pending",
                    "title": "Pending but already claimed",
                    "status": "pending",
                    "claimed_by": "codex-worker",
                    "claimed_at": "2026-07-23T09:01:00+00:00",
                },
                {
                    **base,
                    "id": "unfinished_terminal",
                    "title": "Terminal without a timestamp",
                    "status": "succeeded",
                },
                {
                    **base,
                    "id": "reasonless_block",
                    "title": "Blocked without a reason",
                    "status": "blocked",
                },
            ),
        )
    )

    assert report.ready is False
    assert len(report.candidates) == 4
    assert tuple(issue.code for issue in report.issues) == (
        "invalid_lifecycle",
        "invalid_lifecycle",
        "invalid_lifecycle",
        "invalid_lifecycle",
    )
    assert {issue.record_id for issue in report.issues} == {
        "ownerless_running",
        "claimed_pending",
        "unfinished_terminal",
        "reasonless_block",
    }


def test_canonical_idempotency_collision_and_payload_identity_are_reported() -> None:
    base = {
        "action": "recalc_metrics",
        "source": "system",
        "dry_run": True,
        "priority": 1,
        "status": "queued",
        "dedupe_key": "recalc:2026-07-23",
        "created_at": "2026-07-23T09:00:00+00:00",
    }
    report = preview_legacy_snapshots(
        LegacySnapshots(
            ops_jobs=(
                {
                    **base,
                    "id": "job_a",
                    "payload": {"scope": "daily"},
                },
                {
                    **base,
                    "id": "job_b",
                    "payload": {"scope": "full"},
                },
            ),
        )
    )

    assert report.ready is False
    assert tuple(issue.code for issue in report.issues) == (
        "duplicate_idempotency_key",
    )
    assert report.issues[0].record_id == "job_a,job_b"
    first, second = report.candidates
    assert first.request.idempotency_key == second.request.idempotency_key
    assert first.request.payload_ref.startswith(
        "legacy-snapshot://ops_jobs/job_a?sha256="
    )
    assert second.request.payload_ref.startswith(
        "legacy-snapshot://ops_jobs/job_b?sha256="
    )
    assert first.request.payload_ref != second.request.payload_ref


def test_empty_identity_and_reversed_lifecycle_time_are_fail_closed() -> None:
    report = preview_legacy_snapshots(
        LegacySnapshots(
            next_tasks=(
                {
                    "id": None,
                    "status": "pending",
                    "task_type": "platform_ops",
                    "title": "Null identity",
                    "priority": 1,
                    "source": "agent",
                    "created_at": "2026-07-23T09:00:00+00:00",
                },
                {
                    "id": "reversed_time",
                    "status": "in_progress",
                    "task_type": "platform_ops",
                    "title": "Start precedes claim",
                    "priority": 1,
                    "source": "agent",
                    "claimed_by": "codex-worker",
                    "claimed_at": "2026-07-23T09:05:00+00:00",
                    "started_at": "2026-07-23T09:04:00+00:00",
                    "updated_at": "2026-07-23T09:06:00+00:00",
                    "created_at": "2026-07-23T09:00:00+00:00",
                },
            ),
            task_records=(
                {
                    "id": "",
                    "title": "Empty identity",
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
        )
    )

    assert report.ready is False
    assert tuple(candidate.legacy_id for candidate in report.candidates) == (
        "reversed_time",
    )
    assert tuple(issue.code for issue in report.issues) == (
        "invalid_record",
        "invalid_record",
        "invalid_lifecycle",
    )
    assert report.issues[2].record_id == "reversed_time"
    assert "claimed_at > started_at" in report.issues[2].detail


def test_identity_bearing_fields_reject_coercion_and_whitespace() -> None:
    report = preview_legacy_snapshots(
        LegacySnapshots(
            next_tasks=(
                {
                    "id": "numeric_requester",
                    "status": "pending",
                    "task_type": "platform_ops",
                    "title": "Requester identity must remain typed",
                    "priority": 1,
                    "source": "user",
                    "created_by": 42,
                    "created_at": "2026-07-23T09:00:00+00:00",
                },
                {
                    "id": "blank_claim_owner",
                    "status": "in_progress",
                    "task_type": "platform_ops",
                    "title": "Claim owner cannot be blank",
                    "priority": 1,
                    "source": "agent",
                    "claimed_by": " ",
                    "claimed_at": "2026-07-23T09:01:00+00:00",
                    "started_at": "2026-07-23T09:02:00+00:00",
                    "created_at": "2026-07-23T09:00:00+00:00",
                },
            ),
            task_records=(
                {
                    "id": "numeric_task_record_owner",
                    "title": "TaskRecord claim owner must remain typed",
                    "source": "agent",
                    "task_family": "ops",
                    "priority": 1,
                    "approval_mode": "auto",
                    "risk_level": "safe",
                    "status": "running",
                    "public_effect": "none",
                    "claimed_by": 7,
                    "claimed_at": "2026-07-23T09:01:00+00:00",
                    "started_at": "2026-07-23T09:02:00+00:00",
                    "created_at": "2026-07-23T09:00:00+00:00",
                },
            ),
            ops_jobs=(
                {
                    "id": "numeric_dedupe",
                    "action": "recalc_metrics",
                    "source": "system",
                    "dry_run": True,
                    "priority": 1,
                    "status": "queued",
                    "dedupe_key": 99,
                    "created_at": "2026-07-23T09:00:00+00:00",
                },
                {
                    "id": "blank_requester",
                    "action": "recalc_metrics",
                    "source": "human",
                    "dry_run": True,
                    "priority": 1,
                    "status": "queued",
                    "requested_by": " ",
                    "created_at": "2026-07-23T09:00:00+00:00",
                },
                {
                    "id": "numeric_worker",
                    "action": "recalc_metrics",
                    "source": "system",
                    "dry_run": True,
                    "priority": 1,
                    "status": "running",
                    "worker_id": 8,
                    "started_at": "2026-07-23T09:01:00+00:00",
                    "created_at": "2026-07-23T09:00:00+00:00",
                },
            ),
        )
    )

    assert report.ready is False
    assert report.candidates == ()
    assert tuple(issue.code for issue in report.issues) == (
        "invalid_record",
        "invalid_record",
        "invalid_record",
        "invalid_record",
        "invalid_record",
        "invalid_record",
    )


def test_parent_identity_rejects_numeric_coercion() -> None:
    report = preview_legacy_snapshots(
        LegacySnapshots(
            next_tasks=(
                {
                    "id": "42",
                    "status": "succeeded",
                    "task_type": "platform_ops",
                    "title": "String parent identity",
                    "priority": 1,
                    "source": "agent",
                    "created_at": "2026-07-23T09:00:00+00:00",
                    "completed_at": "2026-07-23T09:01:00+00:00",
                },
                {
                    "id": "numeric_parent_child",
                    "status": "pending",
                    "task_type": "platform_ops",
                    "title": "Numeric parent must not alias string identity",
                    "priority": 1,
                    "source": "agent",
                    "parent_task_id": 42,
                    "created_at": "2026-07-23T09:02:00+00:00",
                },
            ),
        )
    )

    assert report.ready is False
    assert tuple(candidate.legacy_id for candidate in report.candidates) == ("42",)
    assert tuple(issue.code for issue in report.issues) == ("invalid_record",)
    assert report.issues[0].record_id == "numeric_parent_child"


def test_capability_policy_rejects_empty_or_non_string_tokens() -> None:
    base = {
        "status": "pending",
        "task_type": "platform_ops",
        "priority": 1,
        "source": "agent",
        "created_at": "2026-07-23T09:00:00+00:00",
    }
    report = preview_legacy_snapshots(
        LegacySnapshots(
            next_tasks=(
                {
                    **base,
                    "id": "empty_capabilities",
                    "title": "Explicit capability policy cannot be empty",
                    "required_capabilities": [],
                },
                {
                    **base,
                    "id": "numeric_capability",
                    "title": "Capability identity must remain typed",
                    "required_capabilities": [42],
                },
                {
                    **base,
                    "id": "blank_attestation",
                    "title": "Attestation identity cannot be blank",
                    "required_attestations": [" "],
                },
                {
                    **base,
                    "id": "boolean_attestation",
                    "title": "Attestation identity must remain typed",
                    "required_attestations": [True],
                },
            ),
        )
    )

    assert report.ready is False
    assert report.candidates == ()
    assert tuple(issue.code for issue in report.issues) == (
        "invalid_record",
        "invalid_record",
        "invalid_record",
        "invalid_record",
    )
