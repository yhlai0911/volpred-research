"""Regression tests for the evidence-bound task provenance migration."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from scripts import migrate_task_pool_provenance as migration
from volpred.ops.work import WorkerOffer
from volpred.ops.work.legacy import LegacySnapshots
from volpred.ops.work_shadow_replay import replay_legacy_selection


def test_missing_created_at_uses_earliest_lifecycle_evidence():
    tasks = [
        {
            "id": "live-task",
            "status": "in_progress",
            "claimed_at": "2026-07-26T22:02:22.826768+00:00",
            "started_at": "2026-07-26T22:02:26.253522+00:00",
        }
    ]

    changes = migration.migrate_records(tasks, git_evidence={})

    assert "created_at" not in tasks[0]
    assert tasks[0]["created_at_observed_not_after"] == (
        "2026-07-26T22:02:22.826768+00:00"
    )
    assert tasks[0]["creation_time_evidence"]["evidence_field"] == "claimed_at"
    assert changes == [
        {
            "id": "live-task",
            "field": "created_at_observed_not_after",
            "from": None,
            "to": "2026-07-26T22:02:22.826768+00:00",
            "evidence": {"kind": "lifecycle", "field": "claimed_at"},
        }
    ]
    assert (
        datetime.fromisoformat(tasks[0]["created_at_observed_not_after"]).tzinfo
        is not None
    )


def test_missing_created_at_uses_verified_git_evidence():
    tasks = [{"id": "historic-task", "status": "pending"}]
    evidence = {
        "historic-task": migration.GitEvidence(
            commit="a" * 40,
            committed_at="2026-07-21T15:28:05+00:00",
        )
    }

    changes = migration.migrate_records(tasks, git_evidence=evidence)

    assert "created_at" not in tasks[0]
    assert tasks[0]["created_at_observed_not_after"] == (
        "2026-07-21T15:28:05+00:00"
    )
    assert tasks[0]["creation_time_evidence"]["evidence_commit"] == "a" * 40
    assert changes[0]["evidence"] == {"kind": "git", "commit": "a" * 40}


def test_unproven_missing_created_at_fails_closed():
    tasks = [{"id": "unknown-task", "status": "pending"}]

    with pytest.raises(migration.ProvenanceMigrationError, match="unknown-task"):
        migration.migrate_records(tasks, git_evidence={})

    assert "created_at" not in tasks[0]


def test_reviewed_field_preimage_drift_fails_closed():
    tasks = [
        {
            "id": "drifted-task",
            "status": "succeeded",
            "created_at": "2026-07-01T00:00:00+00:00",
        }
    ]

    with pytest.raises(migration.ProvenanceMigrationError, match="preimage drift"):
        migration.migrate_records(
            tasks,
            git_evidence={},
            reviewed_fields={
                "drifted-task": {
                    "status": migration.FieldEvidence(
                        value="awaiting_agent_job",
                        evidence_ref="review://expected-running",
                        replace=True,
                        expected="in_progress",
                    )
                }
            },
        )

    assert tasks[0]["status"] == "succeeded"


def test_reviewed_fields_are_backfilled_with_evidence():
    tasks = [
        {
            "id": "owner-bound",
            "status": "blocked_on_user",
            "created_at": "2026-07-01T00:00:00+00:00",
        }
    ]
    reviewed_fields = {
        "owner-bound": {
            "source": migration.FieldEvidence(
                value="user",
                evidence_ref="review://owner-bound/source",
            ),
            "blocked_reason": migration.FieldEvidence(
                value="awaiting_owner_decision",
                evidence_ref="review://owner-bound/status",
            ),
            "parent_task_id": migration.FieldEvidence(
                value=None,
                evidence_ref="review://owner-bound/external-receipt",
                replace=True,
            ),
        }
    }
    tasks[0]["parent_task_id"] = "not-a-task"

    changes = migration.migrate_records(
        tasks,
        git_evidence={},
        reviewed_fields=reviewed_fields,
    )

    assert tasks[0]["source"] == "user"
    assert tasks[0]["blocked_reason"] == "awaiting_owner_decision"
    assert "parent_task_id" not in tasks[0]
    assert tasks[0]["parent_task_id_original"] == "not-a-task"
    assert tasks[0]["provenance_migration"]["source"]["evidence_ref"] == (
        "review://owner-bound/source"
    )
    assert [change["field"] for change in changes] == [
        "source",
        "blocked_reason",
        "parent_task_id",
    ]


def test_apply_recovers_immutable_receipt_after_post_write_crash(tmp_path):
    queue = tmp_path / "next_tasks.json"
    receipt_path = tmp_path / "receipt.json"
    queue.write_text(
        json.dumps(
            [
                {
                    "id": "issue9_shadow_reconciliation_closure_20260727",
                    "status": "in_progress",
                    "task_type": "platform_ops",
                    "title": "Issue 9",
                    "priority": 1,
                    "source": "owner_interactive",
                    "claimed_at": "2026-07-26T22:02:22.826768+00:00",
                    "started_at": "2026-07-26T22:02:26.253522+00:00",
                },
                {
                    "id": "K1715",
                    "status": "in_progress",
                    "created_at": "2026-07-20T00:00:00+00:00",
                }
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(migration.InjectedMigrationCrash):
        migration.run(
            path=queue,
            apply=True,
            receipt_path=receipt_path,
            fail_after_queue_write=True,
        )

    intent_path = migration.intent_path_for(receipt_path)
    assert intent_path.exists()
    assert not receipt_path.exists()
    assert "created_at_observed_not_after" in queue.read_text(encoding="utf-8")

    recovered = migration.run(
        path=queue,
        apply=True,
        receipt_path=receipt_path,
    )
    first_receipt_bytes = receipt_path.read_bytes()

    assert recovered["recovered_from_intent"] is True
    assert recovered["changes"]
    recovered_tasks = {
        task["id"]: task for task in json.loads(queue.read_text(encoding="utf-8"))
    }
    assert recovered_tasks["K1715"]["status"] == "awaiting_agent_job"
    assert receipt_path.exists()

    replay = migration.run(
        path=queue,
        apply=True,
        receipt_path=receipt_path,
    )
    assert replay == recovered
    assert receipt_path.read_bytes() == first_receipt_bytes


def test_dry_run_hashes_the_proposed_queue_without_writing(tmp_path):
    queue = tmp_path / "next_tasks.json"
    original = [
        {
            "id": "issue9_shadow_reconciliation_closure_20260727",
            "status": "in_progress",
            "task_type": "platform_ops",
            "title": "Issue 9",
            "priority": 1,
            "source": "owner_interactive",
            "claimed_at": "2026-07-26T22:02:22.826768+00:00",
            "started_at": "2026-07-26T22:02:26.253522+00:00",
        }
    ]
    queue.write_text(json.dumps(original) + "\n", encoding="utf-8")

    receipt = migration.run(path=queue, apply=False)

    assert receipt["changes"]
    assert receipt["before_sha256"] != receipt["after_sha256"]
    assert json.loads(queue.read_text(encoding="utf-8")) == original


def test_immutable_publish_never_streams_into_final_path(
    tmp_path,
    monkeypatch,
) -> None:
    target = tmp_path / "receipt.json"

    def fail_publish(_source, _target):
        raise OSError("injected atomic publish failure")

    monkeypatch.setattr(migration.os, "link", fail_publish)

    with pytest.raises(OSError, match="atomic publish failure"):
        migration._create_immutable_json(target, {"schema_version": 1})

    assert not target.exists()


def test_reviewed_lifecycle_repairs_leave_no_reconciliation_issue():
    common = {
        "title": "reviewed lifecycle",
        "task_type": "platform_ops",
        "priority": 3,
        "source": "agent",
        "created_at": "2026-06-01T00:00:00+00:00",
    }
    tasks = [
        {
            **common,
            "id": "K1438_vix1d_spy_intraday_vol_covariate",
            "status": "blocked",
            "claimed_by": "hourly-slot-1-805f4d4c32b442af8ed385c83b595ce3",
            "claimed_at": "2026-07-21T09:36:35.216554+00:00",
            "started_at": "2026-07-21T09:36:36.312051+00:00",
            "completed_at": "2026-06-09T10:28:11.725039+00:00",
            "blocked_reason": "awaiting_external_data",
        },
        {
            **common,
            "id": "K1715",
            "status": "in_progress",
            "compute_job_id": "agent-brief_k1715_adjudicate-27247d",
        },
        {
            **common,
            "id": "k_reruns_0050_snapshot_contaminated_20260719",
            "status": "blocked",
        },
    ]

    migration.migrate_records(
        tasks,
        git_evidence={},
        target_ids=migration.REVIEWED_TARGET_IDS,
        reviewed_fields=migration.REVIEWED_FIELD_EVIDENCE,
    )
    ledger = replay_legacy_selection(
        LegacySnapshots(next_tasks=tuple(tasks)),
        offer=WorkerOffer(
            worker_id="scheduled-shadow",
            capabilities=frozenset({"code"}),
            attestations=frozenset(),
            lease_seconds=300,
        ),
        observed_at=datetime(2026, 7, 27, tzinfo=UTC),
        observation_id="reviewed-lifecycle",
    )

    assert ledger.reconciliation_issues == ()
