"""Hermetic tests for the single-gateway append path (append_next_task)."""

from __future__ import annotations

import json
from datetime import datetime

import pytest
from click.testing import CliRunner

from volpred.cli import cli
from volpred.ops import next_tasks
from volpred.ops.next_tasks import (
    _legacy_priority_to_p,
    append_next_task,
    append_task_record,
)


def test_append_task_record_stamps_an_aware_created_at(tmp_path):
    queue = tmp_path / "next_tasks.json"

    rec, created = append_task_record(
        {
            "id": "external-contract-task",
            "title": "external contract",
            "description": "record-preserving gateway still owns provenance",
            "task_type": "platform_ops",
            "priority": 3,
            "status": "pending",
            "source": "user",
        },
        path=queue,
    )

    stored = json.loads(queue.read_text(encoding="utf-8"))[0]
    parsed = datetime.fromisoformat(rec["created_at"])
    assert created is True
    assert parsed.tzinfo is not None
    assert stored["created_at"] == rec["created_at"]


def test_append_task_record_enforces_active_exact_identity_under_queue_lock(
    tmp_path,
):
    queue = tmp_path / "next_tasks.json"
    first, first_created = append_task_record(
        {
            "id": "review-gate-a-watermark-1",
            "title": "review gate A",
            "description": "first evidence watermark",
            "task_type": "platform_ops",
            "priority": 2,
            "status": "pending",
            "source": "user",
            "gate_review_id": "gate-a",
        },
        path=queue,
        semantic_dedupe=False,
        active_unique_fields=("gate_review_id",),
    )
    second, second_created = append_task_record(
        {
            "id": "review-gate-a-watermark-2",
            "title": "review gate A",
            "description": "concurrent newer evidence watermark",
            "task_type": "platform_ops",
            "priority": 2,
            "status": "pending",
            "source": "user",
            "gate_review_id": "gate-a",
        },
        path=queue,
        semantic_dedupe=False,
        active_unique_fields=("gate_review_id",),
    )

    assert first_created is True
    assert second_created is False
    assert second["id"] == first["id"]
    assert len(json.loads(queue.read_text(encoding="utf-8"))) == 1


def test_append_task_record_rejects_a_naive_created_at(tmp_path):
    queue = tmp_path / "next_tasks.json"

    with pytest.raises(ValueError, match="created_at.*timezone"):
        append_task_record(
            {
                "id": "naive-provenance",
                "title": "invalid provenance",
                "description": "timezone-free timestamps cannot cross the gateway",
                "task_type": "platform_ops",
                "priority": 3,
                "status": "pending",
                "source": "user",
                "created_at": "2026-07-27T12:00:00",
            },
            path=queue,
        )

    assert not queue.exists()


def test_append_task_record_rejects_conflicting_payload_task_type(tmp_path):
    """One task cannot advertise different routing types at two boundaries."""
    queue = tmp_path / "next_tasks.json"

    with pytest.raises(ValueError, match="payload.task_type.*trending_repost"):
        append_task_record(
            {
                "id": "fb-only-followup",
                "title": "post an already-published event article to Facebook",
                "description": "external-only delivery; this cannot fill the draft pool",
                "task_type": "daily_article",
                "payload": {"task_type": "trending_repost"},
                "priority": 2,
                "status": "pending",
                "source": "agent",
            },
            path=queue,
        )

    assert not queue.exists()


def test_append_task_record_rejects_an_absent_parent(tmp_path):
    queue = tmp_path / "next_tasks.json"

    with pytest.raises(ValueError, match="parent_task_id.*missing-parent"):
        append_task_record(
            {
                "id": "orphan-child",
                "title": "orphan",
                "description": "a compute job id is not a task dependency",
                "task_type": "platform_ops",
                "priority": 3,
                "status": "pending",
                "source": "user",
                "parent_task_id": "missing-parent",
            },
            path=queue,
        )

    assert json.loads(queue.read_text(encoding="utf-8")) == []


def test_canonical_append_rejects_unreviewed_source(
    tmp_path,
    monkeypatch,
):
    queue = tmp_path / "storage" / "next_tasks.json"
    queue.parent.mkdir(parents=True)
    queue.write_text("[]\n", encoding="utf-8")
    monkeypatch.setattr(next_tasks, "CANONICAL_NEXT_TASKS", queue)

    with pytest.raises(ValueError, match="unreviewed canonical task source"):
        append_task_record(
            {
                "id": "must-not-reset-shadow-soak",
                "title": "unknown producer",
                "description": "canonical writers must declare provenance",
                "task_type": "platform_ops",
                "priority": 2,
                "status": "pending",
                "source": "new_machine_source_omitted_everywhere",
            },
            path=queue,
        )

    assert json.loads(queue.read_text(encoding="utf-8")) == []


def test_append_creates_pending_record_with_mapped_fields(tmp_path):
    queue = tmp_path / "next_tasks.json"
    rec = append_next_task(
        title="t",
        description="d",
        source="user",
        task_family="research",
        legacy_priority=30,
        path=queue,
    )
    assert rec["status"] == "pending"
    assert rec["task_type"] == "experiment"
    assert rec["priority"] == 2  # 30 → P2
    assert rec["id"].startswith("assign_")

    on_disk = json.loads(queue.read_text(encoding="utf-8"))
    assert [t["id"] for t in on_disk] == [rec["id"]]


def test_append_preserves_existing_rows(tmp_path):
    queue = tmp_path / "next_tasks.json"
    queue.write_text(json.dumps([{"id": "existing", "status": "pending", "priority": 3}]), encoding="utf-8")
    append_next_task(title="t", description="d", path=queue)
    on_disk = json.loads(queue.read_text(encoding="utf-8"))
    assert {t["id"] for t in on_disk} >= {"existing"}
    assert len(on_disk) == 2


def test_append_persists_canonical_issue_reference(tmp_path):
    queue = tmp_path / "next_tasks.json"

    rec = append_next_task(
        title="implement ticket",
        description="follow the existing spec",
        issue_ref="https://github.com/yhlai0911/volpred-research/issues/37",
        path=queue,
    )

    assert rec["issue_ref"] == "#37"
    assert json.loads(queue.read_text(encoding="utf-8"))[0]["issue_ref"] == "#37"


@pytest.mark.parametrize("issue_ref", ["", "#0", "#abc", "issue-37", object()])
def test_append_rejects_invalid_issue_reference(tmp_path, issue_ref):
    queue = tmp_path / "next_tasks.json"

    with pytest.raises(ValueError, match="issue_ref"):
        append_next_task(
            title="invalid ticket",
            description="must not enter the queue",
            issue_ref=issue_ref,
            path=queue,
        )

    assert not queue.exists()


def test_ops_assign_forwards_issue_reference(monkeypatch):
    captured = {}

    def fake_append_next_task(**kwargs):
        captured.update(kwargs)
        return {
            "id": "assign_fixture",
            "priority": 3,
            "task_type": "platform_ops",
            "issue_ref": kwargs["issue_ref"],
        }

    monkeypatch.setattr(next_tasks, "append_next_task", fake_append_next_task)

    result = CliRunner().invoke(
        cli,
        [
            "ops",
            "assign",
            "--title",
            "Implement #37",
            "--description",
            "Use the existing ticket",
            "--issue-ref",
            "#37",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured["issue_ref"] == "#37"


def test_append_rejects_non_list_root(tmp_path):
    queue = tmp_path / "next_tasks.json"
    queue.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError):
        append_next_task(title="t", description="d", path=queue)


@pytest.mark.parametrize(
    "legacy,expected",
    [(1, 1), (10, 1), (30, 2), (50, 2), (80, 3), (100, 3), (101, 4), (500, 4)],
)
def test_legacy_priority_mapping(legacy, expected):
    assert _legacy_priority_to_p(legacy) == expected


def test_unknown_family_falls_back_to_platform_ops(tmp_path):
    rec = append_next_task(
        title="t",
        description="d",
        task_family="something_new",
        path=tmp_path / "q.json",
    )
    assert rec["task_type"] == "platform_ops"
