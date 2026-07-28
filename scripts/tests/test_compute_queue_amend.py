"""A queued job's spec must be correctable — and an in-flight one must not be.

2026-07-14, twice in one day: a job was enqueued, the author immediately spotted a
defect in its brief, and found there was no way to fix it. `enqueue` rejects a
duplicate id, and no `amend`/`cancel` existed — so the only routes were to hand-edit
the queue JSON (which CLAUDE.md forbids) or to let a 30-minute xhigh agent run against
a brief already known to be wrong. Both happened. The second time cost a full review.

The race underneath it: `run_agent_job.py` opens the brief when the WORKER starts the
job (*/15), not when it was queued. So "enqueue, then edit the brief file" is not an
edit at all — it is a coin flip against the worker, and the loser is silent.

These tests pin the two halves of the fix:
  1. the brief is FROZEN at enqueue (editing the source file afterwards changes nothing);
  2. changing a queued spec is a first-class operation, and refuses once running.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts import compute_queue, task_pool_claim  # noqa: E402


@pytest.fixture
def queue(tmp_path, monkeypatch):
    """Redirect every canonical write into tmp. Tests must never touch storage/."""
    qdir = tmp_path / "queue"
    monkeypatch.setattr(compute_queue, "ROOT", tmp_path)
    monkeypatch.setattr(compute_queue, "QUEUE_DIR", qdir)
    monkeypatch.setattr(compute_queue, "LOCK_FILE", qdir / ".worker.lock")
    monkeypatch.setattr(compute_queue, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(compute_queue, "AGENT_JOB_DIR", tmp_path / "agent_jobs")
    monkeypatch.setattr(compute_queue, "AGENT_BRIEF_DIR", tmp_path / "agent_briefs")
    monkeypatch.setattr(compute_queue, "is_registered_linked_worktree", lambda *_: True)
    monkeypatch.setattr(compute_queue, "_find_task_dispatch_collision", lambda **_k: None)
    task_pool = tmp_path / "next_tasks.json"
    task_pool.write_text(json.dumps([{
        "id": "assign_compute_queue_amend",
        "status": "pending",
        "priority": 1,
        "result": None,
    }]))
    monkeypatch.setattr(task_pool_claim, "NEXT_TASKS", task_pool)
    qdir.mkdir(parents=True)
    return qdir


def _enqueue_agent(brief: Path, job_id: str = "j1", **over) -> int:
    args = argparse.Namespace(
        id=job_id, title=None, brief_file=str(brief), model="claude-opus-5",
        effort="xhigh", cwd=str(brief.parent), result_artifact=None,
        followup_brief=over.get("followup_brief", "collect it"),
        followup_task_type="experiment", followup_priority=1, timeout=600,
        source_task_id=over.get(
            "source_task_id", "assign_compute_queue_amend"
        ),
    )
    return compute_queue.enqueue_agent(args)


def _job(queue: Path, job_id: str = "j1") -> dict:
    return json.loads((queue / f"{job_id}.json").read_text())


def _brief_the_runner_will_read(job: dict) -> str:
    argv = job["args"]
    return Path(argv[argv.index("--brief-file") + 1]).read_text()


def test_brief_is_frozen_at_enqueue_not_read_at_run(queue, tmp_path):
    """Editing the source brief after enqueue must not change what the agent reads."""
    src = tmp_path / "brief.md"
    src.write_text("VERDICT SCHEMA: correct")
    assert _enqueue_agent(src) == 0

    src.write_text("VERDICT SCHEMA: wrong, edited 48s too late")

    # The runner is pointed at the snapshot, and the snapshot did not move.
    assert _brief_the_runner_will_read(_job(queue)) == "VERDICT SCHEMA: correct"


def test_source_brief_deleted_after_enqueue_still_runs(queue, tmp_path):
    """/tmp gets swept. The job must survive its source brief vanishing."""
    src = tmp_path / "brief.md"
    src.write_text("the real brief")
    _enqueue_agent(src)
    src.unlink()

    assert _brief_the_runner_will_read(_job(queue)) == "the real brief"


def test_amend_rewrites_a_queued_brief(queue, tmp_path):
    src = tmp_path / "brief.md"
    src.write_text("v1")
    _enqueue_agent(src)

    fixed = tmp_path / "fixed.md"
    fixed.write_text("v2 — schema now matches the merge gate")
    rc = compute_queue.amend(argparse.Namespace(
        id="j1", brief_file=str(fixed), followup_brief=None,
        followup_task_type=None, followup_priority=None, timeout=None,
    ))

    assert rc == 0
    assert _brief_the_runner_will_read(_job(queue)) == "v2 — schema now matches the merge gate"


def test_amend_updates_followup_brief(queue, tmp_path):
    src = tmp_path / "brief.md"
    src.write_text("b")
    _enqueue_agent(src, followup_brief="stale collection instructions")

    rc = compute_queue.amend(argparse.Namespace(
        id="j1", brief_file=None, followup_brief="read the VERDICT: line",
        followup_task_type=None, followup_priority=None, timeout=None,
    ))

    assert rc == 0
    job = _job(queue)
    assert job["claude_followup"]["brief"] == "read the VERDICT: line"
    assert job["claude_followup"]["task_type"] == "experiment"  # untouched fields survive


@pytest.mark.parametrize("status", ["running", "completed", "failed"])
def test_amend_refuses_once_the_worker_owns_it(queue, tmp_path, status):
    """The whole point: a job in flight is a promise being kept, not a draft."""
    src = tmp_path / "brief.md"
    src.write_text("v1")
    _enqueue_agent(src)

    path = queue / "j1.json"
    job = json.loads(path.read_text())
    job["status"] = status
    path.write_text(json.dumps(job))

    fixed = tmp_path / "fixed.md"
    fixed.write_text("too late")
    rc = compute_queue.amend(argparse.Namespace(
        id="j1", brief_file=str(fixed), followup_brief=None,
        followup_task_type=None, followup_priority=None, timeout=None,
    ))

    assert rc == 2
    assert _brief_the_runner_will_read(_job(queue)) == "v1"


def test_amend_with_no_fields_is_an_error(queue, tmp_path):
    src = tmp_path / "brief.md"
    src.write_text("v1")
    _enqueue_agent(src)

    rc = compute_queue.amend(argparse.Namespace(
        id="j1", brief_file=None, followup_brief=None,
        followup_task_type=None, followup_priority=None, timeout=None,
    ))
    assert rc == 2


def test_cancel_removes_a_queued_job_from_both_run_and_followup(
    queue, tmp_path, capsys
):
    src = tmp_path / "brief.md"
    src.write_text("v1")
    _enqueue_agent(src)

    rc = compute_queue.cancel(argparse.Namespace(id="j1", reason="superseded"))

    assert rc == 0
    job = _job(queue)
    assert job["status"] == "cancelled"
    assert job["cancel_reason"] == "superseded"
    assert job["cancelled_at"] == job["completed_at"]
    # A job that never ran has no result to triage — it must not surface as pending followup.
    assert job["followup_dispatched"] is True

    capsys.readouterr()
    assert compute_queue.list_jobs(argparse.Namespace(
        status=None, pending_followup=True,
        completed_pending_followup=False, json=True,
    )) == 0
    assert json.loads(capsys.readouterr().out) == []

    # run-next only consumes queued receipts; cancellation remains terminal.
    assert compute_queue.run_next(argparse.Namespace()) == 0
    assert "no queued jobs" in capsys.readouterr().out
    assert _job(queue)["status"] == "cancelled"


def test_cancel_requires_an_auditable_reason(queue, tmp_path):
    src = tmp_path / "brief.md"
    src.write_text("v1")
    _enqueue_agent(src)

    assert compute_queue.cancel(argparse.Namespace(id="j1", reason="  ")) == 2
    assert _job(queue)["status"] == "queued"


def test_cancel_refuses_a_running_job(queue, tmp_path):
    src = tmp_path / "brief.md"
    src.write_text("v1")
    _enqueue_agent(src)
    path = queue / "j1.json"
    job = json.loads(path.read_text())
    job["status"] = "running"
    path.write_text(json.dumps(job))

    assert compute_queue.cancel(argparse.Namespace(id="j1", reason="too late")) == 2
    assert _job(queue)["status"] == "running"


def test_amend_on_missing_job_is_an_error(queue, tmp_path):
    rc = compute_queue.amend(argparse.Namespace(
        id="nope", brief_file=None, followup_brief="x",
        followup_task_type=None, followup_priority=None, timeout=None,
    ))
    assert rc == 2
