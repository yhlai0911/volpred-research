"""The stranded-binding detector must name the failing clause, not just say no.

Regression cover for the 2026-07-28 silent stall: 10 of 10 queued jobs were
unstartable for 36h while the worker printed "no queued jobs" and exited 0.
The detector only earns its keep if it separates "queue is empty" from "queue
is dead", so that distinction is what these tests pin.
"""
from __future__ import annotations

import json
from pathlib import Path

from scripts import audit_compute_queue_bindings as audit
import scripts.compute_queue as cq


def _queue(tmp_path: Path, monkeypatch) -> Path:
    queue_dir = tmp_path / "compute_queue"
    queue_dir.mkdir(parents=True)
    monkeypatch.setattr(cq, "QUEUE_DIR", queue_dir)
    return queue_dir


def _write_job(queue_dir: Path, job_id: str, **over) -> None:
    job = {"id": job_id, "title": job_id, "status": "queued", "queued_at": "2026-07-28T00:00:00Z"}
    job.update(over)
    (queue_dir / f"{job_id}.json").write_text(json.dumps(job), encoding="utf-8")


def _bound_task(task_id: str, job_id: str) -> dict:
    """A source task in the one shape that lets its job start."""
    return {
        "id": task_id,
        "status": "awaiting_agent_job",
        "compute_job_id": job_id,
        "blocked_reason": "external_compute_job_active",
    }


def test_valid_binding_is_startable(tmp_path, monkeypatch):
    queue_dir = _queue(tmp_path, monkeypatch)
    _write_job(queue_dir, "job-a", source_task_id="task-a")

    verdict = audit.audit([_bound_task("task-a", "job-a")])

    assert verdict["stranded"] == 0
    assert verdict["startable"] == 1
    assert verdict["queue_dead"] is False


def test_job_without_source_task_is_startable(tmp_path, monkeypatch):
    """No binding to go stale — the worker starts it on merit alone."""
    queue_dir = _queue(tmp_path, monkeypatch)
    _write_job(queue_dir, "job-free")

    verdict = audit.audit([])

    assert verdict["stranded"] == 0
    assert verdict["jobs"][0]["startable"] is True


def test_binding_left_pinned_to_finished_job_is_stranded(tmp_path, monkeypatch):
    """The dominant real shape: task still points at the job that already ran.

    A newly enqueued job against that same source task can never bind, so it
    sits queued forever without anything reporting an error.
    """
    queue_dir = _queue(tmp_path, monkeypatch)
    _write_job(queue_dir, "job-new", source_task_id="task-a")
    stale = {
        "id": "task-a",
        "status": "awaiting_agent_job",
        "compute_job_id": "job-old-completed",
        "blocked_reason": "external_compute_receipt_pending_collection",
    }

    verdict = audit.audit([stale])

    assert verdict["stranded"] == 1
    # Naming the clause is the point: "invalid" alone sends the next shift
    # re-deriving which of the three conditions actually failed.
    reasons = verdict["jobs"][0]["reasons"]
    assert any("job-old-completed" in r for r in reasons)
    assert any("external_compute_receipt_pending_collection" in r for r in reasons)


def test_all_stranded_reports_queue_dead(tmp_path, monkeypatch):
    """A queue where nothing can run must not read as an empty queue."""
    queue_dir = _queue(tmp_path, monkeypatch)
    _write_job(queue_dir, "job-1", source_task_id="task-1")
    _write_job(queue_dir, "job-2", source_task_id="task-2")

    verdict = audit.audit(
        [
            {"id": "task-1", "status": "awaiting_agent_job",
             "compute_job_id": "other", "blocked_reason": "external_compute_job_active"},
            {"id": "task-2", "status": "failed",
             "compute_job_id": None, "blocked_reason": None},
        ]
    )

    assert verdict["queue_dead"] is True
    assert verdict["stranded"] == verdict["queued_total"] == 2


def test_empty_queue_is_not_queue_dead(tmp_path, monkeypatch):
    _queue(tmp_path, monkeypatch)

    verdict = audit.audit([])

    assert verdict["queued_total"] == 0
    assert verdict["queue_dead"] is False


def test_missing_source_task_is_stranded(tmp_path, monkeypatch):
    """A job pointing at a task that no longer exists can never bind either."""
    queue_dir = _queue(tmp_path, monkeypatch)
    _write_job(queue_dir, "job-orphan", source_task_id="task-gone")

    verdict = audit.audit([])

    assert verdict["stranded"] == 1
    assert verdict["jobs"][0]["reasons"] == ["source_task_missing_from_pool"]


def test_reason_text_comes_from_compute_queue_canonical_predicate(
    tmp_path,
    monkeypatch,
):
    """The audit must not grow a second copy of binding policy."""
    queue_dir = _queue(tmp_path, monkeypatch)
    _write_job(queue_dir, "job-a", source_task_id="task-a")
    monkeypatch.setattr(
        cq,
        "_source_task_binding_issues",
        lambda *_args, **_kwargs: ("canonical-new-rule",),
    )

    verdict = audit.audit([_bound_task("task-a", "job-a")])

    assert verdict["jobs"][0]["startable"] is False
    assert verdict["jobs"][0]["reasons"] == ["canonical-new-rule"]


def test_non_queued_jobs_are_ignored(tmp_path, monkeypatch):
    """Only queued jobs can be stranded; finished ones are not the audit's business."""
    queue_dir = _queue(tmp_path, monkeypatch)
    _write_job(queue_dir, "job-done", status="completed", source_task_id="task-a")
    _write_job(queue_dir, "job-run", status="running", source_task_id="task-a")

    verdict = audit.audit([])

    assert verdict["queued_total"] == 0
