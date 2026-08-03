from __future__ import annotations

import json
from datetime import datetime, timezone

from volpred.ops.article_continuity import maintain_article_continuity
from volpred.ops.task_pool_selection import dispatch_preempt_rank_key


NOW = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)


def _write_tasks(path, tasks):
    path.write_text(json.dumps(tasks), encoding="utf-8")


def test_dry_release_pool_promotes_batch_and_requests_exact_oldest_article(tmp_path):
    queue = tmp_path / "next_tasks.json"
    _write_tasks(
        queue,
        [
            {
                "id": "newer",
                "task_type": "daily_article",
                "status": "pending",
                "priority": 4,
                "created_at": "2026-08-03T11:00:00Z",
            },
            {
                "id": "oldest",
                "task_type": "daily_article",
                "status": "pending",
                "priority": 3,
                "created_at": "2026-08-03T09:00:00Z",
            },
            {
                "id": "ops",
                "task_type": "platform_ops",
                "status": "pending",
                "priority": 1,
            },
        ],
    )
    requests: list[str] = []

    result = maintain_article_continuity(
        queue_path=queue,
        releasable_count=0,
        request_fire=requests.append,
        now=NOW,
        floor=6,
    )

    tasks = {task["id"]: task for task in json.loads(queue.read_text())}
    assert result["selected_task_id"] == "oldest"
    assert result["promoted_count"] == 2
    assert requests == ["article_continuity:oldest"]
    assert tasks["oldest"]["dispatch_preempt"] is True
    assert tasks["oldest"]["dispatch_preempt_source"] == "article_continuity"
    assert tasks["oldest"]["dispatch_preempt_rank"] == -100
    assert tasks["newer"]["priority"] == 1
    assert "dispatch_preempt" not in tasks["newer"]
    assert tasks["ops"] == {
        "id": "ops",
        "task_type": "platform_ops",
        "status": "pending",
        "priority": 1,
    }


def test_existing_active_article_prevents_parallel_article_preemption(tmp_path):
    queue = tmp_path / "next_tasks.json"
    _write_tasks(
        queue,
        [
            {
                "id": "active",
                "task_type": "daily_article",
                "status": "in_progress",
                "priority": 1,
            },
            {
                "id": "pending",
                "task_type": "daily_article",
                "status": "pending",
                "priority": 4,
            },
        ],
    )
    requests: list[str] = []

    result = maintain_article_continuity(
        queue_path=queue,
        releasable_count=0,
        request_fire=requests.append,
        now=NOW,
    )

    assert result["reason"] == "article_in_flight"
    assert requests == []
    pending = json.loads(queue.read_text())[1]
    assert pending["priority"] == 1
    assert "dispatch_preempt" not in pending


def test_releasable_draft_clears_only_continuity_owned_preemption(tmp_path):
    queue = tmp_path / "next_tasks.json"
    _write_tasks(
        queue,
        [
            {
                "id": "article",
                "task_type": "daily_article",
                "status": "pending",
                "priority": 1,
                "dispatch_preempt": True,
                "dispatch_preempt_source": "article_continuity",
                "dispatch_preempt_rank": -100,
                "article_continuity_requested_at": "2026-08-03T10:00:00Z",
            },
            {
                "id": "incident",
                "task_type": "platform_ops",
                "status": "pending",
                "priority": 1,
                "dispatch_preempt": True,
                "dispatch_preempt_source": "ci_red",
            },
        ],
    )

    result = maintain_article_continuity(
        queue_path=queue,
        releasable_count=1,
        request_fire=lambda _reason: None,
        now=NOW,
    )

    tasks = {task["id"]: task for task in json.loads(queue.read_text())}
    assert result["reason"] == "release_pool_stocked"
    assert tasks["article"].get("dispatch_preempt") is None
    assert tasks["incident"]["dispatch_preempt"] is True


def test_continuity_preempt_wins_scheduled_machine_preempt_only():
    incident = {
        "id": "ci-red",
        "priority": 1,
        "task_type": "platform_ops",
        "dispatch_preempt": True,
    }
    article = {
        "id": "article",
        "priority": 1,
        "task_type": "daily_article",
        "dispatch_preempt": True,
        "dispatch_preempt_rank": -100,
    }

    assert sorted(
        [incident, article], key=dispatch_preempt_rank_key
    )[0] is article
