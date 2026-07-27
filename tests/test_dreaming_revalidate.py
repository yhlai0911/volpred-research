"""Dreaming snapshots must be re-verified before anyone acts on them.

The incident these tests lock down (2026-07-17, 4/4): `orphaned_experiment` tasks
queued 07-12~07-13 were still dispatched on 07-17 demanding knowledge.json entries
that `kb_backfill_unrecorded_experiments` had written on 07-14. Following the stale
description writes duplicates.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from volpred.ops import dreaming_revalidate as dr


def _task(kid: str = "k1697", *, task_id: str | None = None, status: str = "pending") -> dict:
    return {
        "id": task_id or f"dreaming_orphaned_experiment_{kid}",
        "title": f"[dreaming] orphaned_experiment:{kid}",
        "description": f"收尾 experiments/{kid}_foo/：讀 results.json → 寫 knowledge.json",
        "task_type": "experiment",
        "status": status,
        "source": "dreaming",
        "dreaming": {
            "signature": f"orphaned_experiment:{kid}",
            "pattern_type": "orphaned_experiment",
            "occurrences": 1,
        },
    }


@pytest.fixture()
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A miniature repo whose `storage/` the revalidator scans."""
    storage = tmp_path / "storage"
    (storage / "memory").mkdir(parents=True)
    (storage / "reports").mkdir(parents=True)
    (tmp_path / "paper").mkdir()
    (storage / "memory" / "knowledge.json").write_text("[]", encoding="utf-8")
    (storage / "reports" / "feed.json").write_text("[]", encoding="utf-8")
    (storage / "next_tasks.json").write_text("[]", encoding="utf-8")

    monkeypatch.setattr(dr, "project_path", lambda rel: tmp_path / rel)
    import volpred.ops.loop_health as loop_health

    def _load(_storage_dir: str) -> list[dict]:
        return json.loads((storage / "next_tasks.json").read_text(encoding="utf-8"))

    monkeypatch.setattr(loop_health, "_load_next_tasks", _load)
    return tmp_path


def _write_queue(repo: Path, tasks: list[dict]) -> None:
    (repo / "storage" / "next_tasks.json").write_text(
        json.dumps(tasks, ensure_ascii=False), encoding="utf-8"
    )


def test_condition_still_true_leaves_the_task_alone(repo: Path) -> None:
    task = _task()
    _write_queue(repo, [task])

    verdict = dr.revalidate(task)

    assert verdict is not None
    assert verdict.cleared is False
    assert verdict.reason == "still_orphaned"
    assert task["status"] == "pending"


def test_knowledge_entry_written_after_queueing_clears_the_task(repo: Path) -> None:
    """The actual incident: backfill satisfied the demand three days later."""
    task = _task("k1699")
    _write_queue(repo, [task])
    (repo / "storage" / "memory" / "knowledge.json").write_text(
        json.dumps([{"experiment_id": "K1699", "finding": "null result"}]), encoding="utf-8"
    )

    verdict = dr.revalidate(task)

    assert verdict is not None and verdict.cleared is True
    assert "knowledge.json" in verdict.detail
    # The agent must be steered to revise, not to add a second entry.
    assert "revise_knowledge_entry.py" in verdict.detail


def test_the_task_does_not_count_as_its_own_consumer(repo: Path) -> None:
    """Without self-exclusion the revalidator clears 100% of what it checks.

    The dreaming task is itself an OPEN task whose description contains the K-id,
    so a naive re-scan finds its own text and declares every orphan consumed.
    """
    task = _task("k1608")
    _write_queue(repo, [task])  # the only open task mentioning k1608 is the task itself

    verdict = dr.revalidate(task)

    assert verdict is not None and verdict.cleared is False


def test_a_different_open_task_still_counts_as_an_owner(repo: Path) -> None:
    """Self-exclusion must not weaken the detector's real semantics."""
    task = _task("k1609")
    other = {
        "id": "assign_someone_else",
        "status": "in_progress",
        "description": "收尾 k1609 的結果並寫入知識庫",
    }
    _write_queue(repo, [task, other])

    verdict = dr.revalidate(task)

    assert verdict is not None and verdict.cleared is True
    assert "open task" in verdict.detail


def test_feed_and_paper_also_clear(repo: Path) -> None:
    task = _task("k1610")
    _write_queue(repo, [task])
    (repo / "paper" / "body.tex").write_text(r"\section{K1610 results}", encoding="utf-8")

    verdict = dr.revalidate(task)

    assert verdict is not None and verdict.cleared is True
    assert "paper" in verdict.detail


def test_non_dreaming_task_gets_no_opinion(repo: Path) -> None:
    assert dr.revalidate({"id": "assign_x", "status": "pending", "source": "user"}) is None


def test_unregistered_pattern_gets_no_opinion(repo: Path) -> None:
    """Silence means 'no opinion', never 'condition cleared'."""
    task = _task()
    task["dreaming"]["pattern_type"] = "semantic_concentration"
    _write_queue(repo, [task])

    assert dr.revalidate(task) is None


def test_terminal_task_is_never_reopened(repo: Path) -> None:
    task = _task(status="succeeded")
    _write_queue(repo, [task])

    assert dr.revalidate(task) is None


def test_unparseable_signature_fails_open(repo: Path) -> None:
    task = _task()
    task["dreaming"]["signature"] = "orphaned_experiment:not-a-kid"
    _write_queue(repo, [task])

    assert dr.revalidate(task) is None


def test_sweep_closes_cleared_and_keeps_the_rest(repo: Path) -> None:
    cleared, still_open = _task("k1620"), _task("k1621")
    _write_queue(repo, [cleared, still_open])
    (repo / "storage" / "memory" / "knowledge.json").write_text(
        json.dumps([{"experiment_id": "K1620"}]), encoding="utf-8"
    )

    closed = dr.sweep_cleared([cleared, still_open], by="dispatcher", now="2026-07-19T06:00:00Z")

    assert [c["id"] for c in closed] == [cleared["id"]]
    assert cleared["status"] == "succeeded"
    assert dr.CLEARED_RESULT in cleared["result"]
    assert cleared["status_history"][-1]["note"] == dr.CLEARED_NOTE
    assert still_open["status"] == "pending"


def test_sweep_never_closes_work_another_fire_is_doing(repo: Path) -> None:
    """Flipping a live agent's task to succeeded underneath it is worse than a no-op."""
    in_flight = _task("k1640", status="in_progress")
    in_flight["claimed_by"] = "hourly-slot-2"
    _write_queue(repo, [in_flight])
    (repo / "storage" / "memory" / "knowledge.json").write_text(
        json.dumps([{"experiment_id": "K1640"}]), encoding="utf-8"
    )

    closed = dr.sweep_cleared([in_flight], by="dispatcher", now="2026-07-19T06:00:00Z")

    assert closed == []
    assert in_flight["status"] == "in_progress"


def test_close_records_why_so_the_no_op_is_auditable(repo: Path) -> None:
    task = _task("k1630")
    task["claimed_by"] = "hourly-slot-4"
    task["claimed_at"] = "2026-07-19T04:00:00Z"
    task["claim_expires_at"] = "2026-07-19T06:00:00Z"
    task["claim_session_id"] = "session-4"
    verdict = dr.Revalidation("orphaned_experiment", True, dr.CLEARED_REASON, "k1630 已被消費")

    dr.close_as_cleared(task, verdict, by="hourly-slot-4", now="2026-07-19T06:00:00Z")

    assert task["status"] == "succeeded"
    assert all(
        field not in task
        for field in (
            "claimed_by",
            "claimed_at",
            "claim_expires_at",
            "claim_session_id",
        )
    )
    assert "k1630 已被消費" in task["result"]
    assert task["status_history"][-1]["by"] == "hourly-slot-4"
