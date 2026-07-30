from __future__ import annotations

import json
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
    load_gate_registry,
    record_dispatch_gate_decisions,
)

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
                    "min_distinct_candidates": 2,
                    "max_harm_outcomes": 1,
                    "max_false_positive_signals": 1,
                    "min_incident_occurrences": 2,
                },
                "lifecycle": {
                    "phase": "check",
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
    } <= gates.keys()
    assert gates["hourly_pregate"]["mode"] == "shadow"
    assert gates["dispatch_starvation_lockout"]["mode"] == "selection_constraint"
    assert all(
        row["identity_strength"] != "heuristic"
        for row in gates.values()
        if row["mode"] in {"hard_block", "fail_closed", "mutex"}
    )


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
            "review_task_id": "review-old",
        }
    )
    _write_json(registry_path, registry)
    _write_json(
        storage / "next_tasks.json",
        [{
            "id": "review-old",
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


def test_registry_act_without_complete_review_receipt_does_not_consume_evidence(
    tmp_path: Path,
) -> None:
    storage = tmp_path / "storage"
    registry_path = tmp_path / "registry.json"
    reviewed_at = NOW - timedelta(hours=1)
    registry = _registry()
    registry["gates"][0]["lifecycle"].update(
        {
            "last_action": "retain",
            "last_reviewed_at": reviewed_at.isoformat(),
            "review_task_id": "review-crashed-before-complete",
        }
    )
    _write_json(registry_path, registry)
    _write_json(
        storage / "next_tasks.json",
        [{
            "id": "review-crashed-before-complete",
            "status": "in_progress",
            "gate_review_id": "event_stage_idempotency",
            "gate_decision": "retain",
            "gate_live_readback": "not yet accepted",
            "gate_registry_reviewed_at": reviewed_at.isoformat(),
            "gate_review_watermark": (
                NOW - timedelta(hours=2)
            ).isoformat(),
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
