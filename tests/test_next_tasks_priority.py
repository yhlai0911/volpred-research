from __future__ import annotations

import json

import pytest

from volpred.ops.next_tasks import (
    InvalidTaskPriority,
    backfill_ci_repair_commit,
    normalize_priority,
    normalize_task_priorities,
    priority_sort_key,
)


def test_normalize_priority_accepts_legacy_label_forms() -> None:
    assert normalize_priority(1) == 1
    assert normalize_priority("2") == 2
    assert normalize_priority("P3") == 3
    assert normalize_priority("p4") == 4
    assert normalize_priority("PP1") == 1


def test_normalize_task_priorities_mutates_legacy_strings() -> None:
    tasks = [
        {"id": "a", "priority": "P3"},
        {"id": "b", "priority": "PP1"},
        {"id": "c", "priority": "4"},
        {"id": "d", "priority": 2},
    ]

    changed = normalize_task_priorities(tasks)

    assert changed == 3
    assert [task["priority"] for task in tasks] == [3, 1, 4, 2]


def test_normalize_priority_rejects_invalid_write_values() -> None:
    with pytest.raises(InvalidTaskPriority):
        normalize_priority("urgent")

    with pytest.raises(InvalidTaskPriority):
        normalize_priority(0)


def test_priority_sort_key_sends_invalid_values_to_tail() -> None:
    assert priority_sort_key("P2") == 2
    assert priority_sort_key("urgent", default=999) == 999


def _ci_task(task_id: str, *, owner: str, result: str) -> dict:
    return {
        "id": task_id,
        "task_type": "platform_ops",
        "priority": 2,
        "status": "succeeded",
        "result": result,
        "status_history": [
            {"from": "in_progress", "to": "succeeded", "by": owner},
        ],
    }


def test_ci_commit_backfill_requires_explicit_marker_and_exact_fire_owner(tmp_path) -> None:
    queue = tmp_path / "next_tasks.json"
    queue.write_text(json.dumps([
        _ci_task(
            "ci-red-owned", owner="hourly-slot-1-job-a",
            result="root_cause=fixture; repair_commit=pending_post_commit",
        ),
        _ci_task(
            "ci-red-other-fire", owner="hourly-slot-2-job-b",
            result="root_cause=other; repair_commit=pending_post_commit",
        ),
        _ci_task(
            "ci-red-no-intent", owner="hourly-slot-1-job-a",
            result="root_cause=already fixed elsewhere",
        ),
    ]), encoding="utf-8")

    updated = backfill_ci_repair_commit(
        path=queue,
        claim_owners={"hourly-slot-1-job-a"},
        commit_sha="abcdef1234567890",
    )

    assert updated == ["ci-red-owned"]
    tasks = {task["id"]: task for task in json.loads(queue.read_text(encoding="utf-8"))}
    assert "repair_commit=abcdef1234567890" in tasks["ci-red-owned"]["result"]
    assert "pending_post_commit" in tasks["ci-red-other-fire"]["result"]
    assert "repair_commit" not in tasks["ci-red-no-intent"]["result"]


def test_ci_commit_backfill_rejects_non_commit_evidence(tmp_path) -> None:
    queue = tmp_path / "next_tasks.json"
    task = _ci_task(
        "ci-red-owned", owner="hourly-slot-1-job-a",
        result="root_cause=fixture; repair_commit=pending_post_commit",
    )
    queue.write_text(json.dumps([task]), encoding="utf-8")

    assert backfill_ci_repair_commit(
        path=queue,
        claim_owners={"hourly-slot-1-job-a"},
        commit_sha="not-a-sha",
    ) == []
    assert "pending_post_commit" in queue.read_text(encoding="utf-8")
