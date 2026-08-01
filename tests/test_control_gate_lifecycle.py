from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from volpred.ops import control_gate_lifecycle
from volpred.ops.alerts import (
    _parse_control_gate_lifecycle_state,
    _parse_control_gate_source_health_state,
)
from volpred.ops.control_gate_lifecycle import (
    DEFAULT_REGISTRY_PATH,
    audit_control_gates,
    control_gate_inventory_snapshot_hash,
    load_gate_registry,
    record_dispatch_gate_decisions,
)
from volpred.ops.incident import CONTROL_GATE_BY_KIND
from volpred.ops.next_tasks import rollover_active_task_record
from volpred.publisher.publisher import _DEDUP_ACTION_GATE_IDS

NOW = datetime(2026, 7, 30, 6, 0, tzinfo=timezone.utc)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _append_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _registry(*, mode: str = "hard_block", identity: str = "canonical_exact") -> dict:
    return {
        "schema_version": 1,
        "owner": "volpred.ops.control_gate_lifecycle",
        "review_task": {
            "task_type": "platform_ops",
            "priority": 2,
            "source": "control_gate_lifecycle",
        },
        "discovery": {
            "window_hours": 168,
            "high_frequency_threshold": 20,
            "incidents_required": False,
            "candidate_identity_required_after": NOW.isoformat(),
            "sources": [
                {
                    "kind": "jsonl",
                    "path": "logs/control_gate_discovery.jsonl",
                    "required": False,
                    "identity_fields": ["gate_id", "gate"],
                    "decision_fields": ["decision", "action"],
                    "blocking_values": [
                        "block",
                        "hold",
                        "skip",
                        "block_event_stage_coverage",
                    ],
                    "action_gate_aliases": {},
                }
            ],
        },
        "gates": [
            {
                "gate_id": "event_stage_idempotency",
                "owner": "volpred.publisher.publisher",
                "invariant": "one active row per event_key + event_series_slot",
                "mode": mode,
                "identity_strength": identity,
                "protected_graph": {
                    "nodes": ["event_task", "feed_event_stage"],
                    "edges": ["event_task -> feed_event_stage"],
                },
                "blocked_downstream_edges": [
                    "feed_event_stage -> supabase",
                    "feed_event_stage -> reader",
                ],
                "incident_refs": ["incident:test-event-stage"],
                "evidence_sources": [
                    {
                        "kind": "jsonl",
                        "path": "logs/dedup_decisions.jsonl",
                        "match": {
                            "action": ["block_event_stage_coverage"],
                        },
                    }
                ],
                "incident_kinds": [],
                "outcome_join": "candidate_or_event_stage",
                "deadline_required": True,
                "review_policy": {
                    "window_hours": 168,
                    "max_review_age_hours": 336,
                    "min_distinct_candidates": 2,
                    "max_harm_outcomes": 1,
                    "harm_outcomes": [
                        "failed",
                        "missed_deadline",
                        "sequence_coverage_gap",
                        "worker_failed",
                        "unjoined",
                    ],
                    "max_false_positive_signals": 1,
                    "min_incident_occurrences": 2,
                },
                "lifecycle": {
                    "phase": "check",
                    "review_anchor_at": (
                        NOW - timedelta(hours=1)
                    ).isoformat(),
                    "allowed_actions": [
                        "retain",
                        "recalibrate",
                        "downgrade_to_warn",
                        "retire",
                    ],
                },
            }
        ],
    }


def test_registry_rejects_heuristic_hard_block(tmp_path: Path) -> None:
    path = tmp_path / "registry.json"
    _write_json(path, _registry(identity="heuristic"))

    with pytest.raises(ValueError, match="heuristic.*hard_block"):
        load_gate_registry(path)


def test_registry_rejects_cross_gate_review_receipt_identity(
    tmp_path: Path,
) -> None:
    registry = _registry()
    registry["gates"][0]["lifecycle"].update(
        {
            "last_action": "retain",
            "last_reviewed_at": NOW.isoformat(),
            "review_task_id": (
                "control_gate_review_another_gate_20260730_bad"
            ),
        }
    )
    path = tmp_path / "registry.json"
    _write_json(path, registry)

    with pytest.raises(ValueError, match="wrong gate identity"):
        load_gate_registry(path)


def test_registry_rejects_non_hashed_review_receipt_identity(
    tmp_path: Path,
) -> None:
    registry = _registry()
    registry["gates"][0]["lifecycle"].update(
        {
            "last_action": "retain",
            "last_reviewed_at": NOW.isoformat(),
            "review_task_id": (
                "control_gate_review_event_stage_idempotency_manual"
            ),
        }
    )
    path = tmp_path / "registry.json"
    _write_json(path, registry)

    with pytest.raises(ValueError, match="wrong gate identity"):
        load_gate_registry(path)


def test_registry_rejects_transition_reason_filter_for_raw_metric(
    tmp_path: Path,
) -> None:
    registry = _registry()
    registry["gates"][0]["review_policy"][
        "incident_transition_reason_prefixes"
    ] = ["worker_orphaned"]
    path = tmp_path / "registry.json"
    _write_json(path, registry)

    with pytest.raises(
        ValueError,
        match="incident_transition_reason_prefixes.*instance_transitions",
    ):
        load_gate_registry(path)


@pytest.mark.parametrize(
    "prefixes",
    [[], [""], ["worker_orphaned", "worker_orphaned"]],
)
def test_registry_rejects_invalid_transition_reason_prefixes(
    tmp_path: Path,
    prefixes: list[str],
) -> None:
    registry = _registry()
    registry["gates"][0]["review_policy"].update(
        {
            "incident_metric": "instance_transitions",
            "incident_transition_reason_prefixes": prefixes,
        }
    )
    path = tmp_path / "registry.json"
    _write_json(path, registry)

    with pytest.raises(ValueError, match="unique non-empty strings"):
        load_gate_registry(path)


@pytest.mark.parametrize(
    "safe_reasons",
    [[], [""], ["worker_system_terminated"] * 2],
)
def test_registry_rejects_invalid_transition_safe_reasons(
    tmp_path: Path,
    safe_reasons: list[str],
) -> None:
    registry = _registry()
    registry["gates"][0]["review_policy"].update(
        {
            "incident_metric": "instance_transitions",
            "incident_transition_reason_prefixes": ["worker_orphaned"],
            "incident_transition_safe_reasons": safe_reasons,
        }
    )
    path = tmp_path / "registry.json"
    _write_json(path, registry)

    with pytest.raises(ValueError, match="safe_reasons requires unique"):
        load_gate_registry(path)


@pytest.mark.parametrize(
    "receipt_policy",
    [
        {},
        {
            "path": "../outside.jsonl",
            "events": ["checkpointed"],
            "identity_field": "workspace",
            "reason_field": "reason",
            "timestamp_field": "at",
            "max_age_seconds": 120,
        },
        {
            "path": "ops/receipts.jsonl",
            "events": ["checkpointed", "checkpointed"],
            "identity_field": "workspace",
            "reason_field": "reason",
            "timestamp_field": "at",
            "max_age_seconds": 120,
        },
        {
            "path": "ops/receipts.jsonl",
            "events": ["checkpointed"],
            "identity_field": "workspace",
            "reason_field": "reason",
            "timestamp_field": "at",
            "max_age_seconds": 0,
        },
    ],
)
def test_registry_rejects_invalid_transition_reason_receipt(
    tmp_path: Path,
    receipt_policy: dict[str, object],
) -> None:
    registry = _registry()
    registry["gates"][0]["review_policy"].update(
        {
            "incident_metric": "instance_transitions",
            "incident_transition_reason_prefixes": ["worker_orphaned"],
            "incident_transition_reason_receipt": receipt_policy,
        }
    )
    path = tmp_path / "registry.json"
    _write_json(path, registry)

    with pytest.raises(ValueError, match="reason_receipt requires"):
        load_gate_registry(path)


@pytest.mark.parametrize(
    "max_age_seconds",
    [
        True,
        "120",
        "NaN",
        "Infinity",
        [1],
        float("nan"),
        float("inf"),
        1e100,
        10**309,
    ],
    ids=[
        "bool",
        "numeric-string",
        "nan-string",
        "infinity-string",
        "container",
        "nan-number",
        "infinity-number",
        "overflowing-float",
        "overflowing-integer",
    ],
)
def test_registry_requires_finite_numeric_transition_receipt_max_age(
    tmp_path: Path,
    max_age_seconds: object,
) -> None:
    registry = _registry()
    registry["gates"][0]["review_policy"].update(
        {
            "incident_metric": "instance_transitions",
            "incident_transition_reason_prefixes": ["worker_orphaned"],
            "incident_transition_reason_receipt": {
                "path": "ops/receipts.jsonl",
                "events": ["checkpointed"],
                "identity_field": "workspace",
                "reason_field": "reason",
                "timestamp_field": "at",
                "max_age_seconds": max_age_seconds,
            },
        }
    )
    path = tmp_path / "registry.json"
    _write_json(path, registry)

    with pytest.raises(ValueError, match="reason_receipt requires"):
        load_gate_registry(path)


def test_review_watermark_rejects_syntactic_but_wrong_hash() -> None:
    watermark = NOW - timedelta(hours=2)
    reviewed_at = NOW - timedelta(hours=1)
    valid_id = control_gate_lifecycle._review_task_id(
        "event_stage_idempotency",
        watermark,
    )
    forged_id = valid_id[:-1] + ("0" if valid_id[-1] != "0" else "1")
    gate = _registry()["gates"][0]
    gate["lifecycle"].update(
        {
            "last_action": "retain",
            "last_reviewed_at": reviewed_at.isoformat(),
            "review_task_id": forged_id,
        }
    )
    task = {
        "id": forged_id,
        "status": "succeeded",
        "gate_review_id": "event_stage_idempotency",
        "gate_decision": "retain",
        "completed_at": NOW.isoformat(),
        "gate_live_readback": "verified",
        "gate_registry_reviewed_at": reviewed_at.isoformat(),
        "gate_review_watermark": watermark.isoformat(),
    }

    assert control_gate_lifecycle._review_watermark(gate, [task]) is None


def test_review_harm_policy_includes_worker_failure() -> None:
    gate = _registry(mode="shadow", identity="heuristic")["gates"][0]
    gate["review_policy"].update(
        {
            "max_raw_triggers": 999,
            "min_distinct_candidates": 999,
            "max_harm_outcomes": 1,
            "harm_outcomes": ["worker_failed"],
        }
    )

    due, reasons = control_gate_lifecycle._review_due(
        gate,
        now=NOW,
        review_anchor_at=NOW - timedelta(hours=1),
        trigger_count=1,
        distinct_candidates=1,
        incident_occurrences=0,
        outcomes={"worker_failed": 1},
    )

    assert due is True
    assert reasons == ["harm_outcomes=1>=1"]


def test_warn_only_unjoined_candidate_is_not_gate_harm() -> None:
    gate = _registry(mode="warn", identity="heuristic")["gates"][0]
    gate["review_policy"].update(
        {
            "max_raw_triggers": 999,
            "min_distinct_candidates": 999,
            "max_harm_outcomes": 1,
            "harm_outcomes": ["blocked"],
            "max_false_positive_signals": 999,
            "min_incident_occurrences": 999,
        }
    )

    due, reasons = control_gate_lifecycle._review_due(
        gate,
        now=NOW,
        review_anchor_at=NOW - timedelta(hours=1),
        trigger_count=1,
        distinct_candidates=1,
        incident_occurrences=0,
        outcomes={"unjoined": 1, "blocked": 0},
    )

    assert due is False
    assert reasons == []


def test_warn_only_block_resurrection_is_immediate_gate_harm() -> None:
    gate = _registry(mode="warn", identity="heuristic")["gates"][0]
    gate["review_policy"].update(
        {
            "max_raw_triggers": 999,
            "min_distinct_candidates": 999,
            "max_harm_outcomes": 1,
            "harm_outcomes": ["blocked"],
            "max_false_positive_signals": 999,
            "min_incident_occurrences": 999,
        }
    )
    outcomes, _ = control_gate_lifecycle._join_outcomes(
        [{
            "candidate_id": "candidate-with-resurrected-lock",
            "action": "block_arc_dup",
        }],
        tasks=[],
        feed=[],
        dispatch_completions=[],
        now=NOW,
        strategy="candidate_or_feed",
        deadline_required=False,
    )

    due, reasons = control_gate_lifecycle._review_due(
        gate,
        now=NOW,
        review_anchor_at=NOW - timedelta(hours=1),
        trigger_count=1,
        distinct_candidates=1,
        incident_occurrences=0,
        outcomes=outcomes,
    )

    assert outcomes["blocked"] == 1
    assert due is True
    assert reasons == ["harm_outcomes=1>=1"]


@pytest.mark.parametrize(
    ("evidence", "feed_item", "expected"),
    [
        (
            {"candidate_id": "mile_candidate"},
            {"id": "mile_candidate", "status": "published"},
            "published",
        ),
        (
            {"new_title": "Same   Research Title"},
            {
                "id": "mile_title",
                "title": "same research title",
                "status": "published",
            },
            "published",
        ),
        (
            {"reason": "K1719 already covered for audience=general"},
            {
                "id": "mile_k",
                "status": "draft",
                "audience": "general",
                "details": {"experiment_refs": ["K1719"]},
            },
            "queued",
        ),
        (
            {"candidate_id": "question-7"},
            {
                "id": "mile_qa",
                "status": "published",
                "details": {"question_id": "question-7"},
            },
            "published",
        ),
    ],
)
def test_candidate_or_feed_joins_typed_publisher_identity(
    evidence: dict,
    feed_item: dict,
    expected: str,
) -> None:
    outcomes, health = control_gate_lifecycle._join_outcomes(
        [evidence],
        tasks=[],
        feed=[feed_item],
        dispatch_completions=[],
        now=NOW,
        strategy="candidate_or_feed",
        deadline_required=False,
    )

    assert health["malformed_task_deadlines"] == []
    assert outcomes[expected] == 1
    assert outcomes["unjoined"] == 0


def test_candidate_or_feed_joins_published_event_stage_identity() -> None:
    outcomes, health = control_gate_lifecycle._join_outcomes(
        [{
            "candidate_id": "nfp_us_2026_08_07:T-7",
            "action": "warn_thin_signature",
        }],
        tasks=[],
        feed=[{
            "id": "mile_event",
            "status": "published",
            "audience": "event",
            "details": {
                "event_key": "NFP_US_2026_08_07",
                "event_series_slot": "T-7",
            },
        }],
        dispatch_completions=[],
        now=NOW,
        strategy="candidate_or_feed",
        deadline_required=False,
    )

    assert health["malformed_task_deadlines"] == []
    assert outcomes["published"] == 1
    assert outcomes["unjoined"] == 0


def test_k_coverage_does_not_join_across_audience_scope() -> None:
    outcomes, _ = control_gate_lifecycle._join_outcomes(
        [{
            "candidate_id": "K1719",
            "reason": "K1719 already covered for audience=general",
            "action": "warn_coverage_metadata_gap",
        }],
        tasks=[],
        feed=[{
            "id": "mile_research",
            "status": "published",
            "audience": "research",
            "details": {"experiment_refs": ["K1719"]},
        }],
        dispatch_completions=[],
        now=NOW,
        strategy="candidate_or_feed",
        deadline_required=False,
    )

    assert outcomes["published"] == 0
    assert outcomes["unjoined"] == 1


def test_blocked_publisher_candidate_is_classified_not_unjoined() -> None:
    outcomes, _ = control_gate_lifecycle._join_outcomes(
        [{
            "candidate_id": "mile_never_written",
            "action": "block_depth_floor",
        }],
        tasks=[],
        feed=[],
        dispatch_completions=[],
        now=NOW,
        strategy="candidate_or_feed",
        deadline_required=False,
    )

    assert outcomes["blocked"] == 1
    assert outcomes["unjoined"] == 1


@pytest.mark.parametrize(
    ("mode", "identity", "message"),
    [
        ("", "canonical_exact", "mode"),
        ("mystery", "canonical_exact", "mode"),
        ("shadow", "", "identity_strength"),
        ("shadow", "unknown", "identity_strength"),
    ],
)
def test_registry_rejects_undefined_mode_or_identity_policy(
    tmp_path: Path,
    mode: str,
    identity: str,
    message: str,
) -> None:
    path = tmp_path / "registry.json"
    _write_json(path, _registry(mode=mode, identity=identity))

    with pytest.raises(ValueError, match=message):
        load_gate_registry(path)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("owner", "", "owner"),
        ("invariant", "", "invariant"),
        ("incident_refs", None, "incident_refs"),
        ("evidence_sources", [], "evidence_sources"),
        ("outcome_join", "", "outcome_join"),
    ],
)
def test_registry_requires_closed_loop_contract_fields(
    tmp_path: Path,
    field: str,
    value: object,
    message: str,
) -> None:
    registry = _registry()
    registry["gates"][0][field] = value
    path = tmp_path / "registry.json"
    _write_json(path, registry)

    with pytest.raises(ValueError, match=message):
        load_gate_registry(path)


def test_project_registry_lists_known_problematic_gates() -> None:
    registry = load_gate_registry(DEFAULT_REGISTRY_PATH)
    gates = {row["gate_id"]: row for row in registry["gates"]}

    assert {
        "event_stage_idempotency",
        "event_reaction_coverage",
        "hourly_pregate",
        "dispatch_collision",
        "dispatch_starvation_lockout",
        "phase_z_baseline_ownership",
        "worktree_merge_ownership",
        "dispatch_worker_ownership",
        "task_generation",
        "publish_throttle",
        "anti_ai_style",
        "release_content_audit",
        "release_lazypack_completeness",
        "member_qa_publish_identity",
        "release_pool_arc_dedup",
        "event_cross_stage_similarity",
        "publisher_title_identity",
        "publisher_content_depth",
        "publisher_digest_identity",
        "publisher_digest_recap",
        "publisher_arc_dedup",
        "publisher_k_coverage",
        "publisher_coverage_metadata_gap",
        "publisher_cluster_cap",
    } <= gates.keys()
    assert gates["hourly_pregate"]["mode"] == "shadow"
    assert gates["dispatch_starvation_lockout"]["mode"] == "selection_constraint"
    worktree = gates["worktree_merge_ownership"]
    assert (
        worktree["review_policy"]["incident_metric"]
        == "instance_transitions"
    )
    assert worktree["lifecycle"]["last_action"] == "retain"
    assert worktree["lifecycle"]["review_task_id"] == (
        "control_gate_review_worktree_merge_ownership_"
        "20260730T120906_435413c1f352"
    )
    assert "incident_transition_reason_prefixes" not in worktree[
        "review_policy"
    ]
    worker = gates["dispatch_worker_ownership"]
    assert worker["review_policy"][
        "incident_transition_reason_prefixes"
    ] == [
        "worker_orphaned",
        "worker_unknown_external",
        "worker_system_termination_unconfirmed",
        "worker_kill_failed_orphan",
        "worker_timeout_unverified",
        "worker_orphan_unverified",
    ]
    assert worker["review_policy"][
        "incident_transition_safe_reasons"
    ] == [
        "worker_system_terminated",
        "worker_superseded_generation",
    ]
    assert worker["review_policy"][
        "incident_transition_reason_receipt"
    ] == {
        "path": "ops/dispatch_workspace_receipts.jsonl",
        "events": ["checkpointed"],
        "identity_field": "workspace",
        "reason_field": "reason",
        "timestamp_field": "at",
        "max_age_seconds": 120,
    }
    assert worker["lifecycle"]["last_action"] == "recalibrate"
    assert worker["lifecycle"]["review_task_id"] == (
        "control_gate_review_dispatch_worker_ownership_"
        "20260801T150057_3e7a1bfdc47b"
    )
    task_generation = gates["task_generation"]
    assert task_generation["lifecycle"]["last_action"] == "recalibrate"
    assert task_generation["lifecycle"]["review_task_id"] == (
        "control_gate_review_task_generation_"
        "20260730T090031_ec3b7176e81d"
    )
    exact_k = gates["publisher_k_coverage"]
    assert exact_k["mode"] == "hard_block"
    assert exact_k["identity_strength"] == "canonical_exact"
    assert exact_k["evidence_sources"][0]["match"]["action"] == [
        "block_k_coverage"
    ]
    metadata_gap = gates["publisher_coverage_metadata_gap"]
    assert metadata_gap["mode"] == "warn"
    assert metadata_gap["identity_strength"] == "heuristic"
    assert metadata_gap["evidence_sources"][0]["match"]["action"] == [
        "warn_coverage_metadata_gap"
    ]
    assert metadata_gap["lifecycle"]["last_action"] == "retain"
    assert metadata_gap["lifecycle"]["review_task_id"] == (
        "control_gate_review_publisher_coverage_metadata_gap_"
        "20260729T210710_03eb3f99062d"
    )
    publisher_arc = gates["publisher_arc_dedup"]
    assert publisher_arc["mode"] == "warn"
    assert publisher_arc["lifecycle"]["last_action"] == "recalibrate"
    assert publisher_arc["lifecycle"]["review_task_id"] == (
        "control_gate_review_publisher_arc_dedup_"
        "20260801T105224_ea7015b3295f"
    )
    assert publisher_arc["review_policy"]["harm_outcomes"] == [
        "failed",
        "missed_deadline",
        "sequence_coverage_gap",
        "worker_failed",
        "blocked",
    ]
    assert publisher_arc["review_policy"]["max_harm_outcomes"] == 1
    # Historical block labels stay registered as resurrection detectors even
    # though the live gate is advisory-only.
    publisher_arc_actions = set(
        publisher_arc["evidence_sources"][0]["match"]["action"]
    )
    assert {"block_arc_dup", "block_same_ref_recycle"} <= (
        publisher_arc_actions
    )
    for gate_id, gate in gates.items():
        review_task_id = gate["lifecycle"].get("review_task_id")
        if review_task_id:
            assert review_task_id.startswith(f"control_gate_review_{gate_id}_")
    assert all(
        row["identity_strength"] != "heuristic"
        for row in gates.values()
        if row["mode"] in {"hard_block", "fail_closed", "mutex"}
    )
    assert all(
        row["review_policy"]["max_review_age_hours"] > 0
        for row in gates.values()
    )
    dedup_source = next(
        source
        for source in registry["discovery"]["sources"]
        if source["path"] == "logs/dedup_decisions.jsonl"
    )
    assert dedup_source["action_gate_aliases"] == _DEDUP_ACTION_GATE_IDS
    incident_gate_by_kind = {
        kind: gate["gate_id"]
        for gate in gates.values()
        for kind in gate["incident_kinds"]
    }
    assert incident_gate_by_kind == CONTROL_GATE_BY_KIND


def test_registry_rejects_duplicate_incident_kind_ownership(
    tmp_path: Path,
) -> None:
    registry = _registry()
    first = registry["gates"][0]
    first["incident_kinds"] = ["shared_control_kind"]
    second = json.loads(json.dumps(first))
    second["gate_id"] = "second_gate"
    registry["gates"].append(second)
    path = tmp_path / "registry.json"
    _write_json(path, registry)

    with pytest.raises(ValueError, match="owned by both"):
        load_gate_registry(path)


def test_inventory_rejects_registered_but_wrong_explicit_incident_gate(
    tmp_path: Path,
) -> None:
    storage = tmp_path / "storage"
    registry = _registry()
    expected = registry["gates"][0]
    expected["incident_kinds"] = ["phase_z_baseline_missing"]
    wrong = json.loads(json.dumps(expected))
    wrong["gate_id"] = "wrong_but_registered_gate"
    wrong["incident_kinds"] = []
    registry["gates"].append(wrong)
    registry_path = tmp_path / "registry.json"
    _write_json(registry_path, registry)
    _write_json(storage / "next_tasks.json", [])
    _write_json(storage / "reports" / "feed.json", [])
    _write_json(
        storage / "ops" / "incidents.json",
        {
            "incidents": {
                "inc-mismatch": {
                    "kind": "phase_z_baseline_missing",
                    "is_control_intervention": True,
                    "control_gate_id": "wrong_but_registered_gate",
                    "last_seen_at": (
                        NOW - timedelta(minutes=1)
                    ).isoformat(),
                }
            }
        },
    )

    verdict = audit_control_gates(
        storage_dir=str(storage),
        registry_path=registry_path,
        queue_path=storage / "next_tasks.json",
        now=NOW,
        materialize_reviews=True,
    )

    gaps = verdict["inventory"]["unregistered_incident_controls"]
    assert len(gaps) == 1
    assert gaps[0]["explicit_gate_mismatch"] is True
    assert gaps[0]["expected_gate_id"] == "event_stage_idempotency"
    assert "expected=event_stage_idempotency" in " ".join(
        gaps[0]["reasons"]
    )
    assert verdict["inventory_review_tasks"]["created_count"] == 1
    assert verdict["audit_health"]["healthy"] is False


def test_inventory_snapshot_hash_covers_full_evidence_rows() -> None:
    common = {
        "gate_id": "same_gate",
        "registered": False,
        "trigger_count": 1,
        "blocking_count": 1,
        "distinct_candidates": 1,
        "latest_at": NOW.isoformat(),
    }
    first = control_gate_inventory_snapshot_hash(
        watermark=NOW.isoformat(),
        gaps=[{**common, "reasons": ["first evidence"]}],
        unclassified=[],
    )
    second = control_gate_inventory_snapshot_hash(
        watermark=NOW.isoformat(),
        gaps=[{**common, "reasons": ["changed evidence"]}],
        unclassified=[],
    )

    assert first != second


def test_inventory_discovers_unregistered_blocking_and_high_frequency_gates(
    tmp_path: Path,
) -> None:
    storage = tmp_path / "storage"
    registry = _registry()
    registry["discovery"]["high_frequency_threshold"] = 3
    registry["discovery"]["sources"][0]["path"] = (
        "logs/dedup_decisions.jsonl"
    )
    registry["discovery"]["sources"][0]["action_gate_aliases"] = {
        "block_event_stage_coverage": "event_stage_idempotency",
    }
    registry_path = tmp_path / "registry.json"
    _write_json(registry_path, registry)
    _write_json(storage / "next_tasks.json", [])
    _write_json(storage / "reports" / "feed.json", [])
    _append_jsonl(
        storage / "logs" / "dedup_decisions.jsonl",
        [
            {
                "ts": (NOW - timedelta(minutes=5)).isoformat(),
                "gate": "unknown_blocker",
                "action": "block_new_guard",
                "target_id": "blocked-1",
            },
            *[
                {
                    "ts": (NOW - timedelta(minutes=index)).isoformat(),
                    "gate": "unknown_frequent_warn",
                    "decision": "warn",
                    "target_id": f"warn-{index}",
                }
                for index in range(1, 4)
            ],
            {
                "ts": (NOW - timedelta(minutes=1)).isoformat(),
                "gate": "low_frequency_warn",
                "decision": "warn",
                "target_id": "warn-once",
            },
            {
                "ts": (NOW - timedelta(minutes=1)).isoformat(),
                "action": "block_event_stage_coverage",
                "candidate_id": "registered-alias:T+0",
            },
        ],
    )

    verdict = audit_control_gates(
        storage_dir=str(storage),
        registry_path=registry_path,
        queue_path=storage / "next_tasks.json",
        now=NOW,
        materialize_reviews=True,
    )

    gaps = {
        row["gate_id"]: row
        for row in verdict["inventory"]["unregistered_gates"]
    }
    assert set(gaps) == {"unknown_blocker", "unknown_frequent_warn"}
    assert gaps["unknown_blocker"]["blocking_count"] == 1
    assert gaps["unknown_frequent_warn"]["trigger_count"] == 3
    registered_alias = next(
        row
        for row in verdict["inventory"]["observed_gates"]
        if row["gate_id"] == "event_stage_idempotency"
    )
    assert registered_alias["blocking_count"] == 1
    assert verdict["audit_health"]["healthy"] is False
    source_state = _parse_control_gate_source_health_state(
        {"details": {"audit_health": verdict["audit_health"]}}
    )
    assert source_state["breached"] is True
    assert "inventory" in source_state["title"]
    assert verdict["inventory_review_tasks"]["created_count"] == 1
    queue = json.loads(
        (storage / "next_tasks.json").read_text(encoding="utf-8")
    )
    inventory_tasks = [
        row
        for row in queue
        if row.get("control_gate_inventory_review") is True
    ]
    assert len(inventory_tasks) == 1
    assert inventory_tasks[0]["inventory_watermark"]
    assert inventory_tasks[0]["id"].startswith(
        "control_gate_inventory_review_"
    )


def test_inventory_refreshes_active_task_and_reopens_terminal_gap(
    tmp_path: Path,
) -> None:
    storage = tmp_path / "storage"
    registry = _registry()
    registry["discovery"]["sources"][0]["path"] = (
        "logs/dedup_decisions.jsonl"
    )
    registry_path = tmp_path / "registry.json"
    queue_path = storage / "next_tasks.json"
    _write_json(registry_path, registry)
    _write_json(queue_path, [])
    _write_json(storage / "reports" / "feed.json", [])
    decision_path = storage / "logs" / "dedup_decisions.jsonl"
    _append_jsonl(
        decision_path,
        [{
            "ts": (NOW - timedelta(minutes=2)).isoformat(),
            "gate": "unknown_a",
            "action": "block_a",
            "target_id": "candidate-a",
        }],
    )

    first = audit_control_gates(
        storage_dir=str(storage),
        registry_path=registry_path,
        queue_path=queue_path,
        now=NOW,
        materialize_reviews=True,
    )
    first_id = first["inventory_review_tasks"]["created_ids"][0]
    _append_jsonl(
        decision_path,
        [{
            "ts": (NOW + timedelta(seconds=30)).isoformat(),
            "gate": "unknown_b",
            "action": "deny_b",
            "target_id": "candidate-b",
        }],
    )

    rolled = audit_control_gates(
        storage_dir=str(storage),
        registry_path=registry_path,
        queue_path=queue_path,
        now=NOW + timedelta(minutes=1),
        materialize_reviews=True,
    )

    assert rolled["inventory_review_tasks"]["created_count"] == 1
    assert rolled["inventory_review_tasks"]["refreshed_ids"] == []
    rolled_id = rolled["inventory_review_tasks"]["created_ids"][0]
    assert rolled_id != first_id
    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    superseded = next(row for row in queue if row["id"] == first_id)
    assert superseded["status"] == "superseded"
    assert superseded["superseded_by"] == rolled_id
    active = next(row for row in queue if row["id"] == rolled_id)
    assert active["inventory_gate_ids"] == ["unknown_a", "unknown_b"]
    assert active["inventory_refresh_count"] == 1
    refreshed_hash = active["inventory_snapshot_hash"]

    active["status"] = "succeeded"
    _write_json(queue_path, queue)
    reopened = audit_control_gates(
        storage_dir=str(storage),
        registry_path=registry_path,
        queue_path=queue_path,
        now=NOW + timedelta(minutes=2),
        materialize_reviews=True,
    )

    assert reopened["inventory_review_tasks"]["created_count"] == 1
    reopened_id = reopened["inventory_review_tasks"]["created_ids"][0]
    assert reopened_id != rolled_id
    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    reopened_task = next(row for row in queue if row["id"] == reopened_id)
    assert reopened_task["status"] == "pending"
    assert reopened_task["inventory_gate_ids"] == ["unknown_a", "unknown_b"]
    assert reopened_task["inventory_snapshot_hash"] == refreshed_hash


def test_active_inventory_rollover_merges_inside_queue_lock(
    tmp_path: Path,
) -> None:
    queue_path = tmp_path / "storage" / "next_tasks.json"
    _write_json(
        queue_path,
        [{
            "id": "inventory",
            "status": "pending",
            "control_gate_inventory_review": True,
            "inventory_gate_ids": ["x"],
        }],
    )

    def add_gate(gate_id: str) -> None:
        def replacement_builder(current: dict) -> dict:
            gate_ids = sorted({
                *(current.get("inventory_gate_ids") or []),
                gate_id,
            })
            return {
                **current,
                "id": "inventory-" + "-".join(gate_ids),
                "status": "pending",
                "inventory_gate_ids": gate_ids,
            }

        _, superseded_id = rollover_active_task_record(
            path=queue_path,
            active_unique_fields=("control_gate_inventory_review",),
            identity={"control_gate_inventory_review": True},
            replacement_builder=replacement_builder,
        )
        assert superseded_id is not None

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(add_gate, ["y", "z"]))

    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    active = next(row for row in queue if row["status"] == "pending")
    assert active["inventory_gate_ids"] == ["x", "y", "z"]


@pytest.mark.parametrize(
    "owned_status",
    [
        "pending_main_thread",
        "claimed",
        "in_progress",
        "awaiting_agent_job",
        "blocked",
    ],
)
def test_inventory_rollover_preserves_owned_or_blocked_task(
    tmp_path: Path,
    owned_status: str,
) -> None:
    queue_path = tmp_path / "storage" / "next_tasks.json"
    original = {
        "id": "inventory-owned",
        "status": owned_status,
        "claimed_by": "worker-1",
        "control_gate_inventory_review": True,
        "inventory_gate_ids": ["x"],
    }
    _write_json(queue_path, [original])

    replacement, superseded_id = rollover_active_task_record(
        path=queue_path,
        active_unique_fields=("control_gate_inventory_review",),
        identity={"control_gate_inventory_review": True},
        replacement_builder=lambda current: {
            **current,
            "id": "inventory-new",
            "status": "pending",
            "inventory_gate_ids": ["x", "y"],
        },
    )

    assert replacement is None
    assert superseded_id is None
    assert json.loads(queue_path.read_text(encoding="utf-8")) == [original]


@pytest.mark.parametrize("owned_status", ["pending_main_thread", "in_progress"])
def test_owned_inventory_task_persists_new_gap_past_window_and_reopens(
    tmp_path: Path,
    owned_status: str,
) -> None:
    storage = tmp_path / "storage"
    registry = _registry()
    registry["discovery"]["sources"][0]["path"] = (
        "logs/dedup_decisions.jsonl"
    )
    registry_path = tmp_path / "registry.json"
    queue_path = storage / "next_tasks.json"
    _write_json(registry_path, registry)
    _write_json(queue_path, [])
    _write_json(storage / "reports" / "feed.json", [])
    decision_path = storage / "logs" / "dedup_decisions.jsonl"
    _append_jsonl(
        decision_path,
        [{
            "ts": (NOW - timedelta(minutes=2)).isoformat(),
            "gate": "unknown_a",
            "action": "block_a",
            "target_id": "candidate-a",
        }],
    )
    first = audit_control_gates(
        storage_dir=str(storage),
        registry_path=registry_path,
        queue_path=queue_path,
        now=NOW,
        materialize_reviews=True,
    )
    first_id = first["inventory_review_tasks"]["created_ids"][0]
    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    queue[0].update({"status": owned_status})
    if owned_status == "in_progress":
        queue[0]["claimed_by"] = "worker-1"
    else:
        queue[0]["dispatch_lane"] = "main_thread"
    _write_json(queue_path, queue)
    _append_jsonl(
        decision_path,
        [{
            "ts": (NOW + timedelta(seconds=30)).isoformat(),
            "gate": "unknown_b",
            "action": "block_b",
            "target_id": "candidate-b",
        }],
    )

    deferred = audit_control_gates(
        storage_dir=str(storage),
        registry_path=registry_path,
        queue_path=queue_path,
        now=NOW + timedelta(minutes=1),
        materialize_reviews=True,
    )

    actuation = deferred["inventory_review_tasks"]
    assert actuation["created_count"] == 0
    assert actuation["refreshed_ids"] == [first_id]
    assert actuation["deferred_ids"] == []
    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    assert len(queue) == 1
    assert queue[0]["status"] == owned_status
    if owned_status == "pending_main_thread":
        assert queue[0]["dispatch_lane"] == "main_thread"
    assert queue[0]["inventory_gate_ids"] == ["unknown_a", "unknown_b"]
    assert queue[0]["inventory_scope_updates"][-1]["added_gate_ids"] == [
        "unknown_b"
    ]

    # Both source rows have aged outside the 168h discovery window, but the
    # lock-protected task snapshot remains the durable handoff.
    expired = audit_control_gates(
        storage_dir=str(storage),
        registry_path=registry_path,
        queue_path=queue_path,
        now=NOW + timedelta(days=8),
        materialize_reviews=False,
    )
    assert [
        row["gate_id"]
        for row in expired["inventory"]["unregistered_gates"]
    ] == ["unknown_a", "unknown_b"]
    assert expired["inventory"]["carried_forward_task_id"] == first_id

    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    queue[0]["status"] = "succeeded"
    _write_json(queue_path, queue)
    next_generation = audit_control_gates(
        storage_dir=str(storage),
        registry_path=registry_path,
        queue_path=queue_path,
        now=NOW + timedelta(days=8, minutes=1),
        materialize_reviews=True,
    )
    assert next_generation["inventory_review_tasks"]["created_count"] == 1
    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    active = next(row for row in queue if row["status"] == "pending")
    assert active["inventory_gate_ids"] == ["unknown_a", "unknown_b"]


def test_unclassified_scope_survives_expiry_until_typed_resolution(
    tmp_path: Path,
) -> None:
    storage = tmp_path / "storage"
    registry = _registry()
    registry["discovery"]["sources"][0]["path"] = (
        "logs/dedup_decisions.jsonl"
    )
    registry_path = tmp_path / "registry.json"
    queue_path = storage / "next_tasks.json"
    _write_json(registry_path, registry)
    _write_json(queue_path, [])
    _write_json(storage / "reports" / "feed.json", [])
    _write_json(storage / "ops" / "incidents.json", {"incidents": {}})
    _append_jsonl(
        storage / "logs" / "dedup_decisions.jsonl",
        [{
            "ts": (NOW - timedelta(minutes=1)).isoformat(),
            "gate_id": "conflicting_a",
            "gate": "conflicting_b",
            "action": "block_conflict",
            "target_id": "candidate-conflict",
        }],
    )

    first = audit_control_gates(
        storage_dir=str(storage),
        registry_path=registry_path,
        queue_path=queue_path,
        now=NOW,
        materialize_reviews=True,
    )
    task_id = first["inventory_review_tasks"]["created_ids"][0]
    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    task = next(row for row in queue if row["id"] == task_id)
    task["status"] = "in_progress"
    signal_id = task["inventory_unclassified_blocking"][0][
        "inventory_signal_id"
    ]
    _write_json(queue_path, queue)

    expired = audit_control_gates(
        storage_dir=str(storage),
        registry_path=registry_path,
        queue_path=queue_path,
        now=NOW + timedelta(days=8),
        materialize_reviews=False,
    )
    assert expired["inventory"]["unclassified_blocking_count"] == 1
    assert expired["inventory"]["unclassified_blocking"][0][
        "inventory_signal_id"
    ] == signal_id

    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    task = next(row for row in queue if row["id"] == task_id)
    task["inventory_unclassified_resolutions"] = [{
        "signal_id": signal_id,
        "disposition": "producer_fixed",
        "rationale": "producer now emits one exact gate_id",
        "live_readback": "new decision receipt has gate_id=conflicting_a only",
    }]
    _write_json(queue_path, queue)
    resolved = audit_control_gates(
        storage_dir=str(storage),
        registry_path=registry_path,
        queue_path=queue_path,
        now=NOW + timedelta(days=8, minutes=1),
        materialize_reviews=False,
    )
    assert resolved["inventory"]["unclassified_blocking_count"] == 0
    assert resolved["audit_health"]["healthy"] is True


def test_inventory_keeps_high_frequency_action_only_signals(
    tmp_path: Path,
) -> None:
    storage = tmp_path / "storage"
    registry = _registry()
    registry["discovery"]["high_frequency_threshold"] = 3
    registry["discovery"]["sources"][0]["path"] = (
        "logs/dedup_decisions.jsonl"
    )
    registry_path = tmp_path / "registry.json"
    _write_json(registry_path, registry)
    _write_json(storage / "next_tasks.json", [])
    _write_json(storage / "reports" / "feed.json", [])
    _append_jsonl(
        storage / "logs" / "dedup_decisions.jsonl",
        [
            {
                "ts": (NOW - timedelta(minutes=index)).isoformat(),
                "action": "warn_unknown_pressure",
                "target_id": f"candidate-{index}",
            }
            for index in range(1, 4)
        ],
    )

    verdict = audit_control_gates(
        storage_dir=str(storage),
        registry_path=registry_path,
        queue_path=storage / "next_tasks.json",
        now=NOW,
    )

    assert verdict["inventory"]["unregistered_gates"] == [
        {
            "gate_id": "action:warn_unknown_pressure",
            "registered": False,
            "trigger_count": 3,
            "blocking_count": 0,
            "distinct_candidates": 3,
            "latest_at": (NOW - timedelta(minutes=1)).isoformat(),
            "reasons": ["raw_triggers=3>=3"],
        }
    ]
    assert verdict["audit_health"]["healthy"] is False


def test_explicit_gate_identity_wins_over_historical_action_alias() -> None:
    source = {
        "identity_fields": ["gate_id", "gate"],
        "decision_fields": ["decision", "action"],
        "action_gate_aliases": {
            "block_arc_dup": "publisher_arc_dedup",
        },
    }

    normalized, conflict = (
        control_gate_lifecycle._canonicalize_decision_row(
            {
                "gate": "task_generation",
                "action": "block_arc_dup",
            },
            source,
        )
    )

    assert normalized["gate_id"] == "task_generation"
    assert conflict is False


def test_conflicting_explicit_gate_fields_are_unhealthy_and_not_joined(
    tmp_path: Path,
) -> None:
    storage = tmp_path / "storage"
    registry = _registry()
    registry["discovery"]["sources"][0]["path"] = (
        "logs/dedup_decisions.jsonl"
    )
    registry_path = tmp_path / "registry.json"
    _write_json(registry_path, registry)
    _write_json(storage / "next_tasks.json", [])
    _write_json(storage / "reports" / "feed.json", [])
    _append_jsonl(
        storage / "logs" / "dedup_decisions.jsonl",
        [{
            "ts": (NOW - timedelta(minutes=1)).isoformat(),
            "gate_id": "event_stage_idempotency",
            "gate": "publisher_arc_dedup",
            "action": "block_event_stage_coverage",
            "candidate_id": "conflicted",
        }],
    )

    verdict = audit_control_gates(
        storage_dir=str(storage),
        registry_path=registry_path,
        queue_path=storage / "next_tasks.json",
        now=NOW,
        materialize_reviews=True,
    )

    assert verdict["audit_health"]["healthy"] is False
    assert verdict["inventory"]["unclassified_blocking_count"] == 1
    assert verdict["inventory_review_tasks"]["created_count"] == 1
    assert verdict["gates"][0]["evidence"]["trigger_count"] == 0
    assert any(
        row["error"] == "decision_identity_conflicts"
        for row in verdict["audit_health"]["unhealthy_sources"]
    )


def test_inventory_discovers_incident_only_control_and_materializes_once(
    tmp_path: Path,
) -> None:
    storage = tmp_path / "storage"
    registry = _registry()
    registry_path = tmp_path / "registry.json"
    _write_json(registry_path, registry)
    _write_json(storage / "next_tasks.json", [])
    _write_json(storage / "reports" / "feed.json", [])
    _write_json(
        storage / "ops" / "incidents.json",
        {
            "incidents": {
                "inc-release": {
                    "kind": "content_gate_deadlock",
                    "is_control_intervention": True,
                    "control_gate_id": "release_content_quality",
                    "state": "open",
                    "occurrence_count": 2,
                    "last_seen_at": (
                        NOW - timedelta(minutes=5)
                    ).isoformat(),
                }
            }
        },
    )

    first = audit_control_gates(
        storage_dir=str(storage),
        registry_path=registry_path,
        queue_path=storage / "next_tasks.json",
        now=NOW,
        materialize_reviews=True,
    )
    second = audit_control_gates(
        storage_dir=str(storage),
        registry_path=registry_path,
        queue_path=storage / "next_tasks.json",
        now=NOW,
        materialize_reviews=True,
    )

    assert first["inventory"]["unregistered_incident_controls"] == [
        {
            "gate_id": "release_content_quality",
            "incident_kind": "content_gate_deadlock",
            "incident_count": 1,
            "occurrence_count": 2,
            "latest_at": (NOW - timedelta(minutes=5)).isoformat(),
                "incident_ids": ["inc-release"],
                "expected_gate_id": None,
                "explicit_gate_mismatch": False,
                "reasons": ["incident_occurrences=2"],
            }
    ]
    assert first["inventory_review_tasks"]["created_count"] == 1
    assert second["inventory_review_tasks"]["created_count"] == 0
    assert second["inventory_review_tasks"]["existing_ids"]
    assert first["audit_health"]["healthy"] is False


def test_inventory_gap_reopens_after_terminal_task_without_false_suppression(
    tmp_path: Path,
) -> None:
    storage = tmp_path / "storage"
    registry = _registry()
    registry["discovery"]["sources"][0]["path"] = (
        "logs/dedup_decisions.jsonl"
    )
    registry_path = tmp_path / "registry.json"
    _write_json(registry_path, registry)
    _write_json(storage / "reports" / "feed.json", [])
    _write_json(storage / "next_tasks.json", [])
    _append_jsonl(
        storage / "logs" / "dedup_decisions.jsonl",
        [{
            "ts": (NOW - timedelta(minutes=5)).isoformat(),
            "gate": "unknown_lock",
            "decision": "block",
            "candidate_id": "candidate-1",
        }],
    )

    first = audit_control_gates(
        storage_dir=str(storage),
        registry_path=registry_path,
        queue_path=storage / "next_tasks.json",
        now=NOW,
        materialize_reviews=True,
    )
    queue = json.loads(
        (storage / "next_tasks.json").read_text(encoding="utf-8")
    )
    terminal_id = first["inventory_review_tasks"]["created_ids"][0]
    queue[0]["status"] = "failed"
    _write_json(storage / "next_tasks.json", queue)

    verdict = audit_control_gates(
        storage_dir=str(storage),
        registry_path=registry_path,
        queue_path=storage / "next_tasks.json",
        now=NOW + timedelta(seconds=1),
        materialize_reviews=True,
    )

    assert verdict["inventory_review_tasks"]["created_count"] == 1
    assert verdict["inventory_review_tasks"]["existing_ids"] == []
    queue = json.loads(
        (storage / "next_tasks.json").read_text(encoding="utf-8")
    )
    active = [
        row
        for row in queue
        if row.get("control_gate_inventory_review") is True
        and row.get("status") == "pending"
    ]
    assert len(active) == 1
    assert (
        active[0]["supersedes_inventory_task_id"]
        == terminal_id
    )


def test_action_alias_is_reused_by_gate_evidence_and_outcome_join(
    tmp_path: Path,
) -> None:
    storage = tmp_path / "storage"
    registry = _registry()
    source = registry["discovery"]["sources"][0]
    source["path"] = "logs/dedup_decisions.jsonl"
    source["action_gate_aliases"] = {
        "legacy_event_stage_block": "event_stage_idempotency"
    }
    registry["gates"][0]["evidence_sources"][0]["match"] = {
        "gate_id": ["event_stage_idempotency"]
    }
    registry_path = tmp_path / "registry.json"
    _write_json(registry_path, registry)
    _write_json(storage / "next_tasks.json", [])
    _write_json(
        storage / "reports" / "feed.json",
        [
            {
                "id": "event-live",
                "status": "published",
                "event_key": "FOMC_2026_07_29",
                "event_series_slot": "T+0",
            }
        ],
    )
    _append_jsonl(
        storage / "logs" / "dedup_decisions.jsonl",
        [{
            "ts": (NOW - timedelta(minutes=5)).isoformat(),
            "action": "legacy_event_stage_block",
            "candidate_id": "fomc_2026_07_29:T0",
        }],
    )

    verdict = audit_control_gates(
        storage_dir=str(storage),
        registry_path=registry_path,
        queue_path=storage / "next_tasks.json",
        now=NOW,
    )

    gate = verdict["gates"][0]
    assert gate["evidence"]["trigger_count"] == 1
    assert gate["outcomes"]["published"] == 1
    assert gate["outcomes"]["unjoined"] == 0


def test_synthetic_candidate_identity_after_ratchet_is_unhealthy(
    tmp_path: Path,
) -> None:
    storage = tmp_path / "storage"
    registry = _registry()
    registry["discovery"]["candidate_identity_required_after"] = (
        NOW - timedelta(hours=1)
    ).isoformat()
    registry_path = tmp_path / "registry.json"
    _write_json(registry_path, registry)
    _write_json(storage / "next_tasks.json", [])
    _write_json(storage / "reports" / "feed.json", [])
    _append_jsonl(
        storage / "logs" / "dedup_decisions.jsonl",
        [{
            "ts": (NOW - timedelta(minutes=5)).isoformat(),
            "action": "block_event_stage_coverage",
            "candidate_id": "title:synthetic",
        }],
    )

    verdict = audit_control_gates(
        storage_dir=str(storage),
        registry_path=registry_path,
        queue_path=storage / "next_tasks.json",
        now=NOW,
    )

    unhealthy = verdict["audit_health"]["unhealthy_sources"]
    assert any(
        row["error"] == "synthetic_candidate_identity_after_ratchet"
        for row in unhealthy
    )


def test_periodic_review_becomes_due_without_new_gate_evidence(
    tmp_path: Path,
) -> None:
    storage = tmp_path / "storage"
    registry = _registry()
    gate = registry["gates"][0]
    gate["review_policy"]["max_review_age_hours"] = 168
    gate["lifecycle"]["review_anchor_at"] = (
        NOW - timedelta(hours=169)
    ).isoformat()
    registry_path = tmp_path / "registry.json"
    _write_json(registry_path, registry)
    _write_json(storage / "next_tasks.json", [])
    _write_json(storage / "reports" / "feed.json", [])
    for relative in (
        "logs/dedup_decisions.jsonl",
        "logs/control_gate_discovery.jsonl",
    ):
        path = storage / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")

    verdict = audit_control_gates(
        storage_dir=str(storage),
        registry_path=registry_path,
        queue_path=storage / "next_tasks.json",
        now=NOW,
        materialize_reviews=True,
    )

    gate_verdict = verdict["gates"][0]
    assert gate_verdict["review"] == {
        "due": True,
        "reasons": ["review_age_hours=169.0>=168"],
    }
    queue = json.loads(
        (storage / "next_tasks.json").read_text(encoding="utf-8")
    )
    assert len(queue) == 1
    assert queue[0]["gate_review_watermark"] == NOW.isoformat()


def test_audit_joins_harm_outcomes_and_materializes_one_review_task(
    tmp_path: Path,
) -> None:
    storage = tmp_path / "storage"
    registry_path = tmp_path / "registry.json"
    queue_path = storage / "next_tasks.json"
    state_path = storage / "ops" / "control_gate_lifecycle_latest.json"
    _write_json(registry_path, _registry())
    _write_json(
        queue_path,
        [
            {
                "id": "event_article_fomc_tplus0",
                "title": "FOMC T+0",
                "task_type": "event_article",
                "priority": 1,
                "status": "pending",
                "created_at": (NOW - timedelta(days=2)).isoformat(),
                "deadline": (NOW - timedelta(hours=1)).isoformat(),
                "event_key": "FOMC_2026_07_29",
                "event_series_slot": "T+0",
                "dispatch_lane": "main_thread",
            }
        ],
    )
    _write_json(storage / "reports" / "feed.json", [])
    _append_jsonl(
        storage / "logs" / "dedup_decisions.jsonl",
        [
            {
                "ts": (NOW - timedelta(hours=3)).isoformat(),
                "action": "block_event_stage_coverage",
                "candidate_id": "fomc_2026_07_29:T+0",
                "target_id": "event_article_fomc_tplus0",
                "reason": "exact stage",
            },
            {
                "ts": (NOW - timedelta(hours=2)).isoformat(),
                "action": "block_event_stage_coverage",
                "candidate_id": "cpi_us_2026_07_14:T+0",
                "target_id": "event_article_cpi_tplus0",
                "reason": "exact stage",
            },
        ],
    )

    first = audit_control_gates(
        storage_dir=str(storage),
        registry_path=registry_path,
        queue_path=queue_path,
        state_path=state_path,
        now=NOW,
        materialize_reviews=True,
        write_state=True,
    )
    second = audit_control_gates(
        storage_dir=str(storage),
        registry_path=registry_path,
        queue_path=queue_path,
        state_path=state_path,
        now=NOW,
        materialize_reviews=True,
        write_state=True,
    )

    gate = first["gates"][0]
    assert gate["evidence"]["trigger_count"] == 2
    assert gate["evidence"]["distinct_candidates"] == 2
    assert gate["outcomes"]["missed_deadline"] == 1
    assert gate["outcomes"]["sequence_coverage_gap"] == 1
    assert gate["review"]["due"] is True
    assert gate["pdca_phase"] == "act"
    assert first["review_tasks"]["created_count"] == 1
    assert second["review_tasks"]["created_count"] == 0
    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    review_rows = [
        row
        for row in queue
        if row["id"].startswith("control_gate_review_event_stage_idempotency_")
    ]
    assert len(review_rows) == 1
    assert (
        "retain / recalibrate / downgrade_to_warn / retire"
        in review_rows[0]["description"]
    )
    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert persisted["registry_owner"] == "volpred.ops.control_gate_lifecycle"


def test_repeated_same_candidate_still_triggers_frequency_review(
    tmp_path: Path,
) -> None:
    storage = tmp_path / "storage"
    registry = _registry()
    registry["gates"][0]["review_policy"] = {
        **registry["gates"][0]["review_policy"],
        "min_distinct_candidates": 99,
        "max_harm_outcomes": 99,
        "max_raw_triggers": 3,
    }
    registry_path = tmp_path / "registry.json"
    _write_json(registry_path, registry)
    _write_json(storage / "next_tasks.json", [])
    _write_json(storage / "reports" / "feed.json", [])
    _append_jsonl(
        storage / "logs" / "dedup_decisions.jsonl",
        [
            {
                "ts": (NOW - timedelta(minutes=index)).isoformat(),
                "action": "block_event_stage_coverage",
                "candidate_id": "same-event:T+0",
            }
            for index in range(1, 4)
        ],
    )

    verdict = audit_control_gates(
        storage_dir=str(storage),
        registry_path=registry_path,
        queue_path=storage / "next_tasks.json",
        now=NOW,
    )

    gate = verdict["gates"][0]
    assert gate["evidence"]["trigger_count"] == 3
    assert gate["evidence"]["distinct_candidates"] == 1
    assert gate["review"] == {
        "due": True,
        "reasons": ["raw_triggers=3>=3"],
    }


def test_event_candidate_joins_published_exact_stage(tmp_path: Path) -> None:
    storage = tmp_path / "storage"
    registry_path = tmp_path / "registry.json"
    _write_json(registry_path, _registry())
    _write_json(storage / "next_tasks.json", [])
    _write_json(
        storage / "reports" / "feed.json",
        [
            {
                "id": "mile_fomc_live",
                "status": "published",
                "event_key": "FOMC_2026_07_29",
                "event_type": "FOMC",
                "event_date": "2026-07-29",
                "event_series_slot": "T+0",
            }
        ],
    )
    _append_jsonl(
        storage / "logs" / "dedup_decisions.jsonl",
        [
            {
                "ts": (NOW - timedelta(hours=1)).isoformat(),
                "action": "block_event_stage_coverage",
                "candidate_id": "fomc_2026_07_29:T0",
            }
        ],
    )

    verdict = audit_control_gates(
        storage_dir=str(storage),
        registry_path=registry_path,
        queue_path=storage / "next_tasks.json",
        now=NOW,
    )

    assert verdict["gates"][0]["outcomes"]["published"] == 1
    assert verdict["gates"][0]["outcomes"]["unjoined"] == 0


def test_dispatch_report_decisions_are_durable_and_stable(tmp_path: Path) -> None:
    storage = tmp_path / "storage"
    report = {
        "generated_at": NOW.isoformat(),
        "dispatch_candidates": [{"id": "task-old"}],
        "starvation": {
            "locked": True,
            "starved_tasks": [
                {
                    "id": "task-old",
                    "age_hours": 80,
                    "threshold_hours": 72,
                }
            ],
            "collision_blocked_tasks": [
                {
                    "id": "task-collision",
                    "worktree": ".claude/worktrees/task-collision",
                    "commit": "abc123",
                }
            ],
        },
    }

    receipt = record_dispatch_gate_decisions(
        report,
        storage_dir=str(storage),
    )

    assert receipt == {
        "recorded": 2,
        "gate_ids": [
            "dispatch_collision",
            "dispatch_starvation_lockout",
        ],
    }
    rows = [
        json.loads(line)
        for line in (storage / "logs" / "control_gate_decisions.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert {
        (row["gate_id"], row["candidate_id"], row["decision"])
        for row in rows
    } == {
        ("dispatch_collision", "task-collision", "block"),
        ("dispatch_starvation_lockout", "task-old", "constrain"),
    }


def test_starvation_decision_requires_an_actual_candidate_edge(tmp_path: Path) -> None:
    storage = tmp_path / "storage"
    report = {
        "generated_at": NOW.isoformat(),
        "free_slots": 0,
        "dispatch_candidates": [],
        "starvation": {
            "locked": True,
            "starved_tasks": [
                {
                    "id": "task-observed-but-not-admitted",
                    "age_hours": 80,
                    "threshold_hours": 72,
                }
            ],
            "collision_blocked_tasks": [],
        },
    }

    receipt = record_dispatch_gate_decisions(
        report,
        storage_dir=str(storage),
    )

    assert receipt == {"recorded": 0, "gate_ids": []}
    assert not (storage / "logs" / "control_gate_decisions.jsonl").exists()


def test_candidate_task_join_uses_candidate_id_and_detects_failed_cut_edge(
    tmp_path: Path,
) -> None:
    storage = tmp_path / "storage"
    registry = _registry()
    gate = registry["gates"][0]
    gate["gate_id"] = "dispatch_collision"
    gate["outcome_join"] = "candidate_task"
    gate["deadline_required"] = False
    gate["evidence_sources"][0] = {
        "kind": "jsonl",
        "path": "logs/control_gate_decisions.jsonl",
        "match": {"gate_id": ["dispatch_collision"]},
    }
    registry_path = tmp_path / "registry.json"
    _write_json(registry_path, registry)
    _write_json(
        storage / "next_tasks.json",
        [{"id": "task-collision", "status": "failed"}],
    )
    _write_json(storage / "reports" / "feed.json", [])
    _append_jsonl(
        storage / "logs" / "control_gate_decisions.jsonl",
        [{
            "ts": (NOW - timedelta(hours=1)).isoformat(),
            "gate_id": "dispatch_collision",
            "decision": "block",
            "candidate_id": "task-collision",
        }],
    )

    verdict = audit_control_gates(
        storage_dir=str(storage),
        registry_path=registry_path,
        queue_path=storage / "next_tasks.json",
        now=NOW,
    )

    assert verdict["gates"][0]["outcomes"]["failed"] == 1
    assert verdict["gates"][0]["outcomes"]["unjoined"] == 0


def test_failed_or_expired_unpublished_event_is_sequence_gap(tmp_path: Path) -> None:
    storage = tmp_path / "storage"
    registry_path = tmp_path / "registry.json"
    _write_json(registry_path, _registry())
    _write_json(
        storage / "next_tasks.json",
        [{
            "id": "event_article_fomc_tplus0",
            "status": "expired",
            "event_key": "FOMC_2026_07_29",
            "event_series_slot": "T+0",
        }],
    )
    _write_json(storage / "reports" / "feed.json", [])
    _append_jsonl(
        storage / "logs" / "dedup_decisions.jsonl",
        [{
            "ts": (NOW - timedelta(hours=1)).isoformat(),
            "action": "block_event_stage_coverage",
            "candidate_id": "fomc_2026_07_29:T+0",
            "target_id": "event_article_fomc_tplus0",
        }],
    )

    verdict = audit_control_gates(
        storage_dir=str(storage),
        registry_path=registry_path,
        queue_path=storage / "next_tasks.json",
        now=NOW,
    )

    assert verdict["gates"][0]["outcomes"]["sequence_coverage_gap"] == 1


def test_repeated_observation_is_not_implicitly_retry(tmp_path: Path) -> None:
    storage = tmp_path / "storage"
    registry_path = tmp_path / "registry.json"
    _write_json(registry_path, _registry())
    _write_json(storage / "next_tasks.json", [])
    _write_json(storage / "reports" / "feed.json", [])
    _append_jsonl(
        storage / "logs" / "dedup_decisions.jsonl",
        [
            {
                "ts": (NOW - timedelta(minutes=index)).isoformat(),
                "action": "block_event_stage_coverage",
                "candidate_id": "same-event:T+0",
            }
            for index in (1, 2)
        ],
    )

    verdict = audit_control_gates(
        storage_dir=str(storage),
        registry_path=registry_path,
        queue_path=storage / "next_tasks.json",
        now=NOW,
    )

    assert verdict["gates"][0]["outcomes"]["retry"] == 0


def test_dispatch_signature_joins_downstream_fire_and_claim_receipts(
    tmp_path: Path,
) -> None:
    storage = tmp_path / "storage"
    registry = _registry(mode="shadow", identity="heuristic")
    gate = registry["gates"][0]
    gate["gate_id"] = "hourly_pregate"
    gate["outcome_join"] = "dispatch_signature"
    gate["deadline_required"] = False
    gate["evidence_sources"][0] = {
        "kind": "jsonl",
        "path": "logs/hourly_pregate.jsonl",
        "match": {"mode": ["shadow", "real"]},
    }
    registry_path = tmp_path / "registry.json"
    _write_json(registry_path, registry)
    _write_json(storage / "next_tasks.json", [])
    _write_json(storage / "reports" / "feed.json", [])
    decision_at = NOW - timedelta(hours=1)
    _append_jsonl(
        storage / "logs" / "hourly_pregate.jsonl",
        [{
            "ts": decision_at.isoformat(),
            "mode": "shadow",
            "would_skip": False,
            "reasons": {"signature": "sig-1"},
        }],
    )
    _write_json(
        storage / "ops" / "dispatch_state.json",
        {
            "completions": [
                {
                    "fire_at": (
                        decision_at - timedelta(seconds=30)
                    ).isoformat(),
                    "exit_code": 0,
                    "outcome": "completed",
                    "workspace": {
                        "task_id": "must-not-join-prior-fire",
                        "claim_session_id": "prior-session",
                    },
                },
                {
                    "fire_at": (
                        decision_at + timedelta(seconds=30)
                    ).isoformat(),
                    "exit_code": 0,
                    "outcome": "completed",
                    "workspace": {
                        "task_id": "task-claimed",
                        "claim_session_id": "dispatch-session",
                    },
                },
            ]
        },
    )

    verdict = audit_control_gates(
        storage_dir=str(storage),
        registry_path=registry_path,
        queue_path=storage / "next_tasks.json",
        now=NOW,
    )

    outcomes = verdict["gates"][0]["outcomes"]
    assert outcomes["dispatch_fire"] == 1
    assert outcomes["task_claim"] == 1
    assert outcomes["observed"] == 0
    assert outcomes["unjoined"] == 0


def test_dispatch_signature_does_not_call_unbound_workspace_a_task_claim(
    tmp_path: Path,
) -> None:
    storage = tmp_path / "storage"
    registry = _registry(mode="shadow", identity="heuristic")
    gate = registry["gates"][0]
    gate.update(
        {
            "gate_id": "hourly_pregate",
            "outcome_join": "dispatch_signature",
            "deadline_required": False,
        }
    )
    gate["evidence_sources"][0] = {
        "kind": "jsonl",
        "path": "logs/hourly_pregate.jsonl",
        "match": {"mode": ["shadow"]},
    }
    registry_path = tmp_path / "registry.json"
    _write_json(registry_path, registry)
    _write_json(storage / "next_tasks.json", [])
    _write_json(storage / "reports" / "feed.json", [])
    decision_at = NOW - timedelta(hours=1)
    _append_jsonl(
        storage / "logs" / "hourly_pregate.jsonl",
        [{
            "ts": decision_at.isoformat(),
            "mode": "shadow",
            "reasons": {"signature": "sig-unbound"},
        }],
    )
    _write_json(
        storage / "ops" / "dispatch_state.json",
        {
            "completions": [{
                "fire_at": (
                    decision_at + timedelta(seconds=1)
                ).isoformat(),
                "exit_code": 0,
                "workspace": {"task_id": "task-without-claim-session"},
            }]
        },
    )

    verdict = audit_control_gates(
        storage_dir=str(storage),
        registry_path=registry_path,
        queue_path=storage / "next_tasks.json",
        now=NOW,
    )

    outcomes = verdict["gates"][0]["outcomes"]
    assert outcomes["dispatch_fire"] == 1
    assert outcomes["task_claim"] == 0


def test_bad_evidence_timestamp_is_diagnostic_not_audit_crash(
    tmp_path: Path,
) -> None:
    storage = tmp_path / "storage"
    registry_path = tmp_path / "registry.json"
    _write_json(registry_path, _registry())
    _write_json(storage / "next_tasks.json", [])
    _write_json(storage / "reports" / "feed.json", [])
    _append_jsonl(
        storage / "logs" / "dedup_decisions.jsonl",
        [{"ts": "not-a-time", "action": "block_event_stage_coverage"}],
    )

    verdict = audit_control_gates(
        storage_dir=str(storage),
        registry_path=registry_path,
        queue_path=storage / "next_tasks.json",
        now=NOW,
    )

    gate = verdict["gates"][0]
    assert gate["evidence"]["malformed_rows"] == 1
    assert gate["evidence"]["source_health"][0]["ok"] is False
    assert verdict["audit_health"]["healthy"] is False


def test_missing_timestamp_bad_deadline_and_incident_time_are_unhealthy(
    tmp_path: Path,
) -> None:
    storage = tmp_path / "storage"
    registry = _registry()
    event_gate = registry["gates"][0]
    incident_gate = json.loads(json.dumps(event_gate))
    incident_gate["gate_id"] = "phase_z_baseline_ownership"
    incident_gate["outcome_join"] = "incident_or_generation"
    incident_gate["deadline_required"] = False
    incident_gate["incident_kinds"] = ["phase_z_baseline_missing"]
    incident_gate["evidence_sources"][0] = {
        "kind": "jsonl",
        "path": "ops/phase_z_rejections.jsonl",
        "match": {},
    }
    registry["gates"] = [event_gate, incident_gate]
    registry_path = tmp_path / "registry.json"
    _write_json(registry_path, registry)
    _write_json(
        storage / "next_tasks.json",
        [{
            "id": "bad-deadline-task",
            "status": "pending",
            "deadline": "not-a-deadline",
            "event_key": "FOMC_2026_07_29",
            "event_series_slot": "T+0",
        }],
    )
    _write_json(storage / "reports" / "feed.json", [])
    _write_json(
        storage / "ops" / "incidents.json",
        {
            "incidents": {
                "inc_bad_time": {
                    "kind": "phase_z_baseline_missing",
                    "last_seen_at": "bad-time",
                }
            }
        },
    )
    _append_jsonl(
        storage / "logs" / "dedup_decisions.jsonl",
        [
            {
                "action": "block_event_stage_coverage",
                "candidate_id": "missing-time:T+0",
            },
            {
                "ts": (NOW - timedelta(minutes=1)).isoformat(),
                "action": "block_event_stage_coverage",
                "candidate_id": "FOMC_2026_07_29:T+0",
                "target_id": "bad-deadline-task",
            },
        ],
    )
    phase_path = storage / "ops" / "phase_z_rejections.jsonl"
    phase_path.parent.mkdir(parents=True, exist_ok=True)
    phase_path.write_text("", encoding="utf-8")

    verdict = audit_control_gates(
        storage_dir=str(storage),
        registry_path=registry_path,
        queue_path=storage / "next_tasks.json",
        now=NOW,
    )

    assert verdict["audit_health"]["healthy"] is False
    unhealthy_errors = {
        row["error"]
        for row in verdict["audit_health"]["unhealthy_sources"]
    }
    assert "malformed_timestamp_rows" in unhealthy_errors
    assert "missing_or_malformed_task_deadlines" in unhealthy_errors
    assert "missing_or_malformed_incident_timestamp" in unhealthy_errors


def test_instance_incident_reviews_count_only_new_graph_transitions(
    tmp_path: Path,
) -> None:
    storage = tmp_path / "storage"
    registry = _registry()
    gate = registry["gates"][0]
    gate["gate_id"] = "dispatch_worker_ownership"
    gate["outcome_join"] = "incident_or_generation"
    gate["deadline_required"] = False
    gate["incident_kinds"] = ["worker_orphaned"]
    gate["review_policy"]["incident_metric"] = "instance_transitions"
    gate["evidence_sources"][0] = {
        "kind": "jsonl",
        "path": "logs/control_gate_decisions.jsonl",
        "match": {"gate_id": ["dispatch_worker_ownership"]},
    }
    registry_path = tmp_path / "registry.json"
    _write_json(registry_path, registry)
    _write_json(storage / "next_tasks.json", [])
    _write_json(storage / "reports" / "feed.json", [])
    decisions = storage / "logs" / "control_gate_decisions.jsonl"
    decisions.parent.mkdir(parents=True, exist_ok=True)
    decisions.write_text("", encoding="utf-8")
    incident_path = storage / "ops" / "incidents.json"
    _write_json(
        incident_path,
        {
            "incidents": {
                "inc-worker": {
                    "incident_id": "inc-worker",
                    "kind": "worker_orphaned",
                    "state": "mitigating",
                    "occurrence_count": 5139,
                    "episode_count": 1,
                    "last_seen_at": (NOW - timedelta(minutes=1)).isoformat(),
                }
            }
        },
    )

    quiet = audit_control_gates(
        storage_dir=str(storage),
        registry_path=registry_path,
        queue_path=storage / "next_tasks.json",
        now=NOW,
    )
    assert quiet["gates"][0]["evidence"]["incident_occurrences"] == 0
    assert quiet["gates"][0]["evidence"]["incident_observations"] == 5139
    assert quiet["gates"][0]["review"]["due"] is False

    payload = json.loads(incident_path.read_text(encoding="utf-8"))
    payload["incidents"]["inc-worker"]["instance_transition_tracking"] = True
    payload["incidents"]["inc-worker"]["instance_transitions"] = [
        {
            "at": (NOW - timedelta(minutes=3)).isoformat(),
            "instance_key": "slot-a",
            "transition": "opened",
        },
        {
            "at": (NOW - timedelta(minutes=2)).isoformat(),
            "instance_key": "slot-b",
            "transition": "opened",
        },
    ]
    _write_json(incident_path, payload)
    changed = audit_control_gates(
        storage_dir=str(storage),
        registry_path=registry_path,
        queue_path=storage / "next_tasks.json",
        now=NOW,
    )
    assert changed["gates"][0]["evidence"]["incident_occurrences"] == 2
    assert changed["gates"][0]["review"]["reasons"] == [
        "incident_occurrences=2>=2"
    ]


def test_instance_transition_metric_has_exact_window_and_health_contract(
    tmp_path: Path,
) -> None:
    start = NOW - timedelta(hours=1)
    count, diagnostics = (
        control_gate_lifecycle._incident_occurrences_since(
            {
                "instance_transition_tracking": True,
                "instance_transitions": [
                    {
                        "at": start.isoformat(),
                        "instance_key": "excluded-start",
                        "transition": "opened",
                    },
                    {
                        "at": (start + timedelta(microseconds=1)).isoformat(),
                        "instance_key": "included-after-start",
                        "transition": "opened",
                    },
                    {
                        "at": NOW.isoformat(),
                        "instance_key": "included-now",
                        "transition": "reopened",
                    },
                    {
                        "at": (NOW + timedelta(microseconds=1)).isoformat(),
                        "instance_key": "excluded-future",
                        "transition": "opened",
                    },
                    {
                        "at": "not-a-time",
                        "instance_key": "bad-time",
                        "transition": "opened",
                    },
                    {
                        "at": NOW.isoformat(),
                        "instance_key": "bad-type",
                        "transition": "evidence_changed",
                    },
                ],
            },
            window_start=start,
            now=NOW,
        )
    )
    assert count == 2
    assert diagnostics == [
        "transition[4]_invalid_at",
        "transition[5]_invalid_type:evidence_changed",
    ]

    storage = tmp_path / "storage"
    registry = _registry()
    gate = registry["gates"][0]
    gate["gate_id"] = "dispatch_worker_ownership"
    gate["outcome_join"] = "incident_or_generation"
    gate["deadline_required"] = False
    gate["incident_kinds"] = ["worker_orphaned"]
    gate["review_policy"]["incident_metric"] = "instance_transitions"
    registry_path = tmp_path / "registry.json"
    _write_json(registry_path, registry)
    _write_json(storage / "next_tasks.json", [])
    _write_json(storage / "reports" / "feed.json", [])
    _write_json(storage / "logs" / "dedup_decisions.jsonl", [])
    _write_json(
        storage / "ops" / "incidents.json",
        {
            "incidents": {
                "inc-worker": {
                    "incident_id": "inc-worker",
                    "kind": "worker_orphaned",
                    "state": "mitigating",
                    "last_seen_at": (NOW - timedelta(minutes=1)).isoformat(),
                    "instance_transition_tracking": True,
                    "instance_transitions": [
                        {
                            "at": "not-a-time",
                            "instance_key": "bad-time",
                            "transition": "opened",
                        }
                    ],
                }
            }
        },
    )
    verdict = audit_control_gates(
        storage_dir=str(storage),
        registry_path=registry_path,
        queue_path=storage / "next_tasks.json",
        now=NOW,
    )
    assert verdict["audit_health"]["healthy"] is False
    assert any(
        row["error"] == "malformed_instance_transition_rows"
        for row in verdict["audit_health"]["unhealthy_sources"]
    )


def test_worker_ownership_review_excludes_safe_settlement_transitions(
    tmp_path: Path,
) -> None:
    """Normal termination/supersession is not a worker-ownership breach."""
    storage = tmp_path / "storage"
    registry = _registry()
    gate = registry["gates"][0]
    gate["gate_id"] = "dispatch_worker_ownership"
    gate["outcome_join"] = "incident_or_generation"
    gate["deadline_required"] = False
    gate["incident_kinds"] = ["worker_orphaned"]
    gate["review_policy"].update(
        {
            "incident_metric": "instance_transitions",
            "incident_transition_reason_prefixes": [
                "worker_orphaned",
                "worker_unknown_external",
                "worker_system_termination_unconfirmed",
                "worker_kill_failed_orphan",
                "worker_timeout_unverified",
                "worker_orphan_unverified",
            ],
            "incident_transition_safe_reasons": [
                "worker_system_terminated",
                "worker_superseded_generation",
            ],
            "incident_transition_reason_receipt": {
                "path": "ops/dispatch_workspace_receipts.jsonl",
                "events": ["checkpointed"],
                "identity_field": "workspace",
                "reason_field": "reason",
                "timestamp_field": "at",
                "max_age_seconds": 120,
            },
        }
    )
    gate["evidence_sources"][0] = {
        "kind": "jsonl",
        "path": "logs/control_gate_decisions.jsonl",
        "match": {"gate_id": ["dispatch_worker_ownership"]},
    }
    registry_path = tmp_path / "registry.json"
    _write_json(registry_path, registry)
    _write_json(storage / "next_tasks.json", [])
    _write_json(storage / "reports" / "feed.json", [])
    _write_json(storage / "ops" / "dispatch_state.json", {"completions": []})
    decisions = storage / "logs" / "control_gate_decisions.jsonl"
    decisions.parent.mkdir(parents=True, exist_ok=True)
    decisions.write_text("", encoding="utf-8")
    receipt_path = storage / "ops" / "dispatch_workspace_receipts.jsonl"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_rows = [
        {
            "event": "checkpointed",
            "workspace": f"safe-{index}",
            "reason": (
                "worker_system_terminated"
                if index == 0
                else "worker_superseded_generation"
            ),
            "at": (NOW - timedelta(minutes=5 - index, milliseconds=1)).isoformat(),
        }
        for index in range(5)
    ]
    receipt_path.write_text(
        "".join(json.dumps(row) + "\n" for row in receipt_rows),
        encoding="utf-8",
    )
    incident_path = storage / "ops" / "incidents.json"
    transitions = [
        {
            "at": (NOW - timedelta(minutes=5 - index)).isoformat(),
            "instance_key": f"safe-{index}",
            "transition": "opened",
        }
        for index in range(5)
    ]
    transitions.append(
        {
            "at": (NOW - timedelta(seconds=30)).isoformat(),
            "instance_key": "unsafe-orphan",
            "transition": "opened",
            "reason": "worker_orphaned",
        }
    )
    instances = [
        {
            "key": f"safe-{index}",
            # Mutable detector detail is deliberately contradictory.  The
            # review must use the immutable checkpoint receipt that preceded
            # the transition, never the latest incident projection.
            "detail": {"reason": "worker_orphaned"},
        }
        for index in range(5)
    ]
    instances.append(
        {"key": "unsafe-orphan", "detail": {"reason": "worker_orphaned"}}
    )
    _write_json(
        incident_path,
        {
            "incidents": {
                "inc-worker": {
                    "incident_id": "inc-worker",
                    "kind": "worker_orphaned",
                    "state": "mitigating",
                    "occurrence_count": 99,
                    "last_seen_at": (NOW - timedelta(seconds=1)).isoformat(),
                    "instance_transition_tracking": True,
                    "instance_transitions": transitions,
                    "instances": instances,
                }
            }
        },
    )

    verdict = audit_control_gates(
        storage_dir=str(storage),
        registry_path=registry_path,
        queue_path=storage / "next_tasks.json",
        now=NOW,
    )
    evidence = verdict["gates"][0]["evidence"]
    assert evidence["incident_occurrences"] == 1
    assert evidence["incident_excluded_occurrences"] == 5
    assert evidence["incident_excluded_reasons"] == {
        "worker_superseded_generation": 4,
        "worker_system_terminated": 1,
    }
    assert verdict["gates"][0]["review"]["due"] is False
    assert verdict["audit_health"]["healthy"] is True


@pytest.mark.parametrize(
    "receipt_rows",
    [
        [],
        [
            {
                "event": "checkpointed",
                "workspace": "missing-instance-detail",
                "reason": "worker_orphaned",
                # Simultaneous is not evidence that preceded the edge.
                "at": NOW.isoformat(),
            }
        ],
        [
            {
                "event": "checkpointed",
                "workspace": "missing-instance-detail",
                "reason": "worker_orphaned",
                "at": (NOW - timedelta(seconds=2)).isoformat(),
            },
            {
                "event": "checkpointed",
                "workspace": "missing-instance-detail",
                "reason": "worker_system_terminated",
                "at": (NOW - timedelta(seconds=1)).isoformat(),
            },
        ],
    ],
    ids=["missing", "simultaneous", "conflicting"],
)
def test_worker_ownership_review_fails_closed_on_unjoinable_reason(
    tmp_path: Path,
    receipt_rows: list[dict[str, object]],
) -> None:
    storage = tmp_path / "storage"
    registry = _registry()
    gate = registry["gates"][0]
    gate["gate_id"] = "dispatch_worker_ownership"
    gate["outcome_join"] = "incident_or_generation"
    gate["deadline_required"] = False
    gate["incident_kinds"] = ["worker_orphaned"]
    gate["review_policy"].update(
        {
            "incident_metric": "instance_transitions",
            "incident_transition_reason_prefixes": ["worker_orphaned"],
            "incident_transition_safe_reasons": [
                "worker_system_terminated"
            ],
            "incident_transition_reason_receipt": {
                "path": "ops/dispatch_workspace_receipts.jsonl",
                "events": ["checkpointed"],
                "identity_field": "workspace",
                "reason_field": "reason",
                "timestamp_field": "at",
                "max_age_seconds": 120,
            },
        }
    )
    gate["evidence_sources"][0] = {
        "kind": "jsonl",
        "path": "logs/control_gate_decisions.jsonl",
        "match": {"gate_id": ["dispatch_worker_ownership"]},
    }
    registry_path = tmp_path / "registry.json"
    _write_json(registry_path, registry)
    _write_json(storage / "next_tasks.json", [])
    _write_json(storage / "reports" / "feed.json", [])
    _write_json(storage / "ops" / "dispatch_state.json", {"completions": []})
    decisions = storage / "logs" / "control_gate_decisions.jsonl"
    decisions.parent.mkdir(parents=True, exist_ok=True)
    decisions.write_text("", encoding="utf-8")
    receipts = storage / "ops" / "dispatch_workspace_receipts.jsonl"
    receipts.parent.mkdir(parents=True, exist_ok=True)
    receipts.write_text(
        "".join(json.dumps(row) + "\n" for row in receipt_rows),
        encoding="utf-8",
    )
    _write_json(
        storage / "ops" / "incidents.json",
        {
            "incidents": {
                "inc-worker": {
                    "incident_id": "inc-worker",
                    "kind": "worker_orphaned",
                    "state": "mitigating",
                    "last_seen_at": NOW.isoformat(),
                    "instance_transition_tracking": True,
                    "instance_transitions": [
                        {
                            "at": NOW.isoformat(),
                            "instance_key": "missing-instance-detail",
                            "transition": "opened",
                        }
                    ],
                    "instances": [],
                }
            }
        },
    )

    verdict = audit_control_gates(
        storage_dir=str(storage),
        registry_path=registry_path,
        queue_path=storage / "next_tasks.json",
        now=NOW,
    )
    assert verdict["gates"][0]["evidence"]["incident_occurrences"] == 0
    assert (
        verdict["gates"][0]["evidence"]["incident_excluded_occurrences"]
        == 0
    )
    assert verdict["audit_health"]["healthy"] is False
    assert any(
        row["error"] == "malformed_instance_transition_rows"
        for row in verdict["audit_health"]["unhealthy_sources"]
    )


def test_worker_ownership_review_fails_closed_on_unknown_reason(
    tmp_path: Path,
) -> None:
    storage = tmp_path / "storage"
    registry = _registry()
    gate = registry["gates"][0]
    gate["gate_id"] = "dispatch_worker_ownership"
    gate["outcome_join"] = "incident_or_generation"
    gate["deadline_required"] = False
    gate["incident_kinds"] = ["worker_orphaned"]
    gate["review_policy"].update(
        {
            "incident_metric": "instance_transitions",
            "incident_transition_reason_prefixes": ["worker_orphaned"],
            "incident_transition_safe_reasons": [
                "worker_system_terminated"
            ],
        }
    )
    gate["evidence_sources"][0] = {
        "kind": "jsonl",
        "path": "logs/control_gate_decisions.jsonl",
        "match": {"gate_id": ["dispatch_worker_ownership"]},
    }
    registry_path = tmp_path / "registry.json"
    _write_json(registry_path, registry)
    _write_json(storage / "next_tasks.json", [])
    _write_json(storage / "reports" / "feed.json", [])
    _write_json(storage / "ops" / "dispatch_state.json", {"completions": []})
    decisions = storage / "logs" / "control_gate_decisions.jsonl"
    decisions.parent.mkdir(parents=True, exist_ok=True)
    decisions.write_text("", encoding="utf-8")
    _write_json(
        storage / "ops" / "incidents.json",
        {
            "incidents": {
                "inc-worker": {
                    "incident_id": "inc-worker",
                    "kind": "worker_orphaned",
                    "state": "mitigating",
                    "last_seen_at": NOW.isoformat(),
                    "instance_transition_tracking": True,
                    "instance_transitions": [
                        {
                            "at": NOW.isoformat(),
                            "instance_key": "novel-reason",
                            "transition": "opened",
                            "reason": "worker_future_settlement",
                        }
                    ],
                }
            }
        },
    )

    verdict = audit_control_gates(
        storage_dir=str(storage),
        registry_path=registry_path,
        queue_path=storage / "next_tasks.json",
        now=NOW,
    )
    evidence = verdict["gates"][0]["evidence"]
    assert evidence["incident_occurrences"] == 0
    assert evidence["incident_excluded_occurrences"] == 0
    assert evidence["incident_unknown_occurrences"] == 1
    assert evidence["incident_unknown_reasons"] == {
        "worker_future_settlement": 1
    }
    assert verdict["audit_health"]["healthy"] is False


def test_worker_ownership_review_fails_closed_on_malformed_receipt_source(
    tmp_path: Path,
) -> None:
    storage = tmp_path / "storage"
    registry = _registry()
    gate = registry["gates"][0]
    gate["gate_id"] = "dispatch_worker_ownership"
    gate["outcome_join"] = "incident_or_generation"
    gate["deadline_required"] = False
    gate["incident_kinds"] = ["worker_orphaned"]
    gate["review_policy"].update(
        {
            "incident_metric": "instance_transitions",
            "incident_transition_reason_prefixes": ["worker_orphaned"],
            "incident_transition_reason_receipt": {
                "path": "ops/dispatch_workspace_receipts.jsonl",
                "events": ["checkpointed"],
                "identity_field": "workspace",
                "reason_field": "reason",
                "timestamp_field": "at",
                "max_age_seconds": 120,
            },
        }
    )
    gate["evidence_sources"][0] = {
        "kind": "jsonl",
        "path": "logs/control_gate_decisions.jsonl",
        "match": {"gate_id": ["dispatch_worker_ownership"]},
    }
    registry_path = tmp_path / "registry.json"
    _write_json(registry_path, registry)
    _write_json(storage / "next_tasks.json", [])
    _write_json(storage / "reports" / "feed.json", [])
    _write_json(storage / "ops" / "dispatch_state.json", {"completions": []})
    decisions = storage / "logs" / "control_gate_decisions.jsonl"
    decisions.parent.mkdir(parents=True, exist_ok=True)
    decisions.write_text("", encoding="utf-8")
    receipts = storage / "ops" / "dispatch_workspace_receipts.jsonl"
    receipts.parent.mkdir(parents=True, exist_ok=True)
    receipts.write_text("[]\n", encoding="utf-8")
    _write_json(
        storage / "ops" / "incidents.json",
        {
            "incidents": {
                "inc-worker": {
                    "incident_id": "inc-worker",
                    "kind": "worker_orphaned",
                    "state": "mitigating",
                    "last_seen_at": NOW.isoformat(),
                    "instance_transition_tracking": True,
                    "instance_transitions": [
                        {
                            "at": NOW.isoformat(),
                            "instance_key": "missing-receipt",
                            "transition": "opened",
                        }
                    ],
                    # A scalar/non-list projection used to crash the mutable
                    # fallback comprehension.  It must now be irrelevant.
                    "instances": 7,
                }
            }
        },
    )

    verdict = audit_control_gates(
        storage_dir=str(storage),
        registry_path=registry_path,
        queue_path=storage / "next_tasks.json",
        now=NOW,
    )
    assert verdict["audit_health"]["healthy"] is False
    errors = {
        row["error"] for row in verdict["audit_health"]["unhealthy_sources"]
    }
    assert "malformed_jsonl_rows" in errors
    assert "malformed_instance_transition_rows" in errors


def test_completed_adjudication_consumes_old_evidence_until_new_trigger(
    tmp_path: Path,
) -> None:
    storage = tmp_path / "storage"
    registry_path = tmp_path / "registry.json"
    reviewed_at = NOW - timedelta(hours=2)
    consumed_through = NOW - timedelta(hours=2, minutes=30)
    registry = _registry()
    registry["gates"][0]["lifecycle"].update(
        {
            "phase": "check",
            "last_action": "retain",
            "last_reviewed_at": reviewed_at.isoformat(),
            "review_task_id": control_gate_lifecycle._review_task_id(
                "event_stage_idempotency",
                consumed_through,
            ),
        }
    )
    review_task_id = registry["gates"][0]["lifecycle"]["review_task_id"]
    _write_json(registry_path, registry)
    _write_json(
        storage / "next_tasks.json",
        [{
            "id": review_task_id,
            "status": "succeeded",
            "gate_review_id": "event_stage_idempotency",
            "gate_decision": "retain",
            "completed_at": reviewed_at.isoformat(),
            "gate_live_readback": "registry and downstream state verified",
            "gate_registry_reviewed_at": reviewed_at.isoformat(),
            "gate_review_watermark": consumed_through.isoformat(),
        }],
    )
    _write_json(storage / "reports" / "feed.json", [])
    evidence_path = storage / "logs" / "dedup_decisions.jsonl"
    _append_jsonl(
        evidence_path,
        [{
            "ts": consumed_through.isoformat(),
            "action": "block_event_stage_coverage",
            "candidate_id": "old-event:T+0",
        }],
    )

    clean = audit_control_gates(
        storage_dir=str(storage),
        registry_path=registry_path,
        queue_path=storage / "next_tasks.json",
        now=NOW,
        materialize_reviews=True,
    )
    assert clean["gates"][0]["evidence"]["trigger_count"] == 0
    assert clean["review_tasks"]["created_count"] == 0

    _append_jsonl(
        evidence_path,
        [{
            "ts": (NOW - timedelta(hours=1)).isoformat(),
            "action": "block_event_stage_coverage",
            "candidate_id": "new-event:T+0",
        }],
    )
    registry["gates"][0]["review_policy"]["max_raw_triggers"] = 1
    _write_json(registry_path, registry)
    next_cycle = audit_control_gates(
        storage_dir=str(storage),
        registry_path=registry_path,
        queue_path=storage / "next_tasks.json",
        now=NOW,
        materialize_reviews=True,
    )
    assert next_cycle["review_tasks"]["created_count"] == 1


def test_retired_gate_stays_quiet_until_new_evidence_resurrects_it(
    tmp_path: Path,
) -> None:
    storage = tmp_path / "storage"
    watermark = NOW - timedelta(days=10)
    reviewed_at = NOW - timedelta(days=9)
    completed_at = NOW - timedelta(days=8)
    registry = _registry(mode="shadow", identity="heuristic")
    gate = registry["gates"][0]
    gate["gate_id"] = "hourly_pregate"
    gate["outcome_join"] = "dispatch_signature"
    gate["deadline_required"] = False
    gate["evidence_sources"][0] = {
        "kind": "jsonl",
        "path": "logs/hourly_pregate.jsonl",
        "match": {"mode": ["shadow", "real"]},
    }
    review_task_id = control_gate_lifecycle._review_task_id(
        "hourly_pregate",
        watermark,
    )
    gate["lifecycle"].update(
        {
            "phase": "retired",
            "last_action": "retire",
            "last_reviewed_at": reviewed_at.isoformat(),
            "review_task_id": review_task_id,
        }
    )
    registry_path = tmp_path / "registry.json"
    _write_json(registry_path, registry)
    _write_json(
        storage / "next_tasks.json",
        [{
            "id": review_task_id,
            "status": "succeeded",
            "gate_review_id": "hourly_pregate",
            "gate_decision": "retire",
            "completed_at": completed_at.isoformat(),
            "gate_live_readback": "runtime producer absent",
            "gate_registry_reviewed_at": reviewed_at.isoformat(),
            "gate_review_watermark": watermark.isoformat(),
        }],
    )
    _write_json(storage / "reports" / "feed.json", [])
    _write_json(storage / "ops" / "dispatch_state.json", {"completions": []})
    evidence_path = storage / "logs" / "hourly_pregate.jsonl"
    _write_json(evidence_path, [])

    quiet = audit_control_gates(
        storage_dir=str(storage),
        registry_path=registry_path,
        queue_path=storage / "next_tasks.json",
        now=NOW,
    )
    gate_verdict = quiet["gates"][0]
    assert gate_verdict["review"] == {"due": False, "reasons": []}
    assert gate_verdict["pdca_phase"] == "retired"

    _append_jsonl(
        evidence_path,
        [{
            "ts": (NOW - timedelta(minutes=1)).isoformat(),
            "mode": "shadow",
            "would_skip": True,
            "reasons": {"signature": "legacy-resurrection"},
        }],
    )
    resurrected = audit_control_gates(
        storage_dir=str(storage),
        registry_path=registry_path,
        queue_path=storage / "next_tasks.json",
        now=NOW,
    )
    assert resurrected["gates"][0]["review"] == {
        "due": True,
        "reasons": ["retired_gate_evidence=1"],
    }
    assert resurrected["gates"][0]["pdca_phase"] == "act"


def test_registry_act_without_complete_review_receipt_does_not_consume_evidence(
    tmp_path: Path,
) -> None:
    storage = tmp_path / "storage"
    registry_path = tmp_path / "registry.json"
    reviewed_at = NOW - timedelta(hours=1)
    task_watermark = NOW - timedelta(hours=2)
    registry = _registry()
    registry["gates"][0]["lifecycle"].update(
        {
            "last_action": "retain",
            "last_reviewed_at": reviewed_at.isoformat(),
            "review_task_id": control_gate_lifecycle._review_task_id(
                "event_stage_idempotency",
                task_watermark,
            ),
        }
    )
    review_task_id = registry["gates"][0]["lifecycle"]["review_task_id"]
    _write_json(registry_path, registry)
    _write_json(
        storage / "next_tasks.json",
        [{
            "id": review_task_id,
            "status": "in_progress",
            "gate_review_id": "event_stage_idempotency",
            "gate_decision": "retain",
            "gate_live_readback": "not yet accepted",
            "gate_registry_reviewed_at": reviewed_at.isoformat(),
            "gate_review_watermark": task_watermark.isoformat(),
        }],
    )
    _write_json(storage / "reports" / "feed.json", [])
    _append_jsonl(
        storage / "logs" / "dedup_decisions.jsonl",
        [{
            "ts": (NOW - timedelta(hours=3)).isoformat(),
            "action": "block_event_stage_coverage",
            "candidate_id": "must-remain-visible:T+0",
        }],
    )

    verdict = audit_control_gates(
        storage_dir=str(storage),
        registry_path=registry_path,
        queue_path=storage / "next_tasks.json",
        now=NOW,
    )

    assert verdict["gates"][0]["window"]["last_reviewed_at"] is None
    assert verdict["gates"][0]["evidence"]["trigger_count"] == 1


def test_distinct_gate_edges_are_not_collapsed_by_generic_task_dedupe(
    tmp_path: Path,
) -> None:
    storage = tmp_path / "storage"
    registry = _registry()
    first = registry["gates"][0]
    first["gate_id"] = "dispatch_collision"
    first["outcome_join"] = "candidate_task"
    first["deadline_required"] = False
    first["evidence_sources"][0] = {
        "kind": "jsonl",
        "path": "logs/control_gate_decisions.jsonl",
        "match": {"gate_id": ["dispatch_collision"]},
    }
    second = json.loads(json.dumps(first))
    second["gate_id"] = "dispatch_starvation_lockout"
    second["evidence_sources"][0]["match"] = {
        "gate_id": ["dispatch_starvation_lockout"]
    }
    registry["gates"] = [first, second]
    registry_path = tmp_path / "registry.json"
    _write_json(registry_path, registry)
    _write_json(
        storage / "next_tasks.json",
        [
            {"id": "collision-task", "status": "pending"},
            {"id": "starved-task", "status": "pending"},
        ],
    )
    _write_json(storage / "reports" / "feed.json", [])
    _append_jsonl(
        storage / "logs" / "control_gate_decisions.jsonl",
        [
            {
                "ts": (NOW - timedelta(minutes=1)).isoformat(),
                "gate_id": "dispatch_collision",
                "candidate_id": "collision-task",
            },
            {
                "ts": (NOW - timedelta(minutes=1)).isoformat(),
                "gate_id": "dispatch_starvation_lockout",
                "candidate_id": "starved-task",
            },
        ],
    )
    for gate in registry["gates"]:
        gate["review_policy"]["max_raw_triggers"] = 1
    _write_json(registry_path, registry)

    verdict = audit_control_gates(
        storage_dir=str(storage),
        registry_path=registry_path,
        queue_path=storage / "next_tasks.json",
        now=NOW,
        materialize_reviews=True,
    )

    assert verdict["review_tasks"]["created_count"] == 2
    assert {
        row["gate_review_id"]
        for row in json.loads(
            (storage / "next_tasks.json").read_text(encoding="utf-8")
        )
        if row.get("gate_review_id")
    } == {"dispatch_collision", "dispatch_starvation_lockout"}


def test_alert_readback_exposes_due_gate_without_creating_a_second_queue(
    tmp_path: Path,
) -> None:
    storage = tmp_path / "storage"
    _write_json(storage / "next_tasks.json", [])
    _write_json(storage / "reports" / "feed.json", [])
    _write_json(storage / "ops" / "incidents.json", {"incidents": {}})
    for relative in (
        "logs/dedup_decisions.jsonl",
        "logs/hourly_pregate.jsonl",
        "ops/phase_z_rejections.jsonl",
    ):
        path = storage / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    _append_jsonl(
        storage / "logs" / "control_gate_decisions.jsonl",
        [
            {
                "ts": (NOW - timedelta(hours=index)).isoformat(),
                "gate_id": "dispatch_collision",
                "decision": "block",
                "candidate_id": f"task-collision-{index}",
            }
            for index in range(1, 4)
        ],
    )

    state = _parse_control_gate_lifecycle_state(str(storage), NOW)

    assert state["breached"] is True
    assert state["id"] == "control_gate_lifecycle"
    assert state["details"]["self_materialized_review"] is False
    assert "dispatch_collision" in {
        row["gate_id"] for row in state["details"]["due_gates"]
    }
    assert json.loads((storage / "next_tasks.json").read_text(encoding="utf-8")) == []


def test_alert_audit_crash_is_not_marked_self_materialized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _crash(**_kwargs: object) -> dict:
        raise RuntimeError("evidence source unavailable")

    monkeypatch.setattr(control_gate_lifecycle, "audit_control_gates", _crash)

    state = _parse_control_gate_lifecycle_state(str(tmp_path / "storage"), NOW)

    assert state["breached"] is True
    assert state["details"]["self_materialized_review"] is False
    assert "evidence source unavailable" in state["details"]["error"]


def test_due_gate_does_not_suppress_another_gate_unhealthy_source(
    tmp_path: Path,
) -> None:
    storage = tmp_path / "storage"
    _write_json(
        storage / "next_tasks.json",
        [{
            "id": "event_article_fomc_2026-07-29_tplus0",
            "status": "pending",
        }],
    )
    _write_json(storage / "reports" / "feed.json", [])
    _write_json(storage / "ops" / "incidents.json", {"incidents": {}})
    _write_json(
        storage / "ops" / "dispatch_state.json",
        {"completions": []},
    )
    for relative in (
        "logs/hourly_pregate.jsonl",
        "ops/phase_z_rejections.jsonl",
    ):
        path = storage / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    _append_jsonl(
        storage / "logs" / "dedup_decisions.jsonl",
        [
            {
                "ts": (NOW - timedelta(minutes=index)).isoformat(),
                "gate": "event_reaction_coverage",
                "target_id": "event_article_fomc_2026-07-29_tplus0",
                "decision": "warn",
            }
            for index in range(1, 21)
        ],
    )
    # control_gate_decisions.jsonl deliberately absent: dispatch evidence
    # health must remain visible even though event_reaction_coverage is due.

    state = _parse_control_gate_lifecycle_state(str(storage), NOW)
    source_state = _parse_control_gate_source_health_state(state)

    assert state["breached"] is True
    assert state["details"]["due_gates"]
    assert source_state["breached"] is True
    assert source_state["details"]["unhealthy_sources"]
    assert source_state["details"]["self_materialized_review"] is False
