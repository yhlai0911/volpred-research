"""A quota wall is a clock, and the queue must wait it out by itself.

2026-07-16, 20:45-22:00 CST: the session window closed and the next five agent
jobs each died five seconds in on "You've hit your session limit · resets
10:20pm". No compute, no tokens, five untouched worktrees.

`run_agent_job.py` had classified all five correctly (`failure_class: quota`) and
written it into each receipt. Nothing read the field. So every one of them was
filed as `triage_failed` — five separate work orders, each asking a whole dispatch
fire to go inspect a worktree nobody had written to and rediscover the same clock.

These tests pin what the field is FOR:
  1. a quota death re-queues itself and waits, instead of failing;
  2. a waiting job is not picked up early (that would just re-hit the wall);
  3. patience is finite — a weekly window outlasts the queue, and then it fails
     for real, with a brief that says quota rather than "go look in the worktree";
  4. only a job that never ran may be re-queued blind; anything with a worktree
     worth reading is refused.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts import compute_queue  # noqa: E402


@pytest.fixture
def queue(tmp_path, monkeypatch):
    """Redirect every canonical write into tmp. Tests must never touch storage/."""
    qdir = tmp_path / "queue"
    monkeypatch.setattr(compute_queue, "QUEUE_DIR", qdir)
    monkeypatch.setattr(compute_queue, "LOCK_FILE", qdir / ".worker.lock")
    monkeypatch.setattr(compute_queue, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(compute_queue, "AGENT_JOB_DIR", tmp_path / "agent_jobs")
    qdir.mkdir(parents=True)
    return qdir


def _agent_job(queue_dir: Path, tmp_path: Path, job_id: str, failure_class: str | None,
               **overrides) -> Path:
    """A failed agent job plus the runner receipt that says what killed it."""
    meta = tmp_path / f"{job_id}.meta.json"
    meta.write_text(json.dumps({
        "failure_class": failure_class,
        "attempts": 1,
        "exit_code": 1,
        "result_artifact_exists": False,
    }))
    job = {
        "id": job_id,
        "title": job_id,
        "kind": "agent",
        "script_path": "scripts/run_agent_job.py",
        "status": "failed",
        "queued_at": "2026-07-16T07:00:00+00:00",
        "started_at": "2026-07-16T12:45:00+00:00",
        "completed_at": "2026-07-16T12:45:06+00:00",
        "exit_code": 1,
        "cwd": str(tmp_path / "worktree"),
        "job_metadata": str(meta),
        "stdout_file": str(tmp_path / f"{job_id}.stdout"),
        "stderr_file": str(tmp_path / f"{job_id}.stderr"),
        "timeout_seconds": 10800,
        "claude_followup": {"brief": "collect it", "task_type": "experiment", "priority": 2},
        "followup_dispatched": False,
    }
    job.update(overrides)
    path = queue_dir / f"{job_id}.json"
    path.write_text(json.dumps(job))
    return path


def test_quota_death_requeues_and_waits(queue, tmp_path):
    job = json.loads(_agent_job(queue, tmp_path, "k1708", "quota").read_text())

    assert compute_queue._requeue_quota_blocked(job) is True

    assert job["status"] == "queued"
    assert job["quota_requeues"] == 1
    # The attempt computed nothing; leaving its receipt on the job would describe
    # a run that never happened.
    assert job["exit_code"] is None
    assert job["started_at"] is None
    assert job["completed_at"] is None
    # It keeps its place in line rather than going to the back.
    assert job["queued_at"] == "2026-07-16T07:00:00+00:00"
    assert len(job["requeue_history"]) == 1
    assert job["requeue_history"][0]["reason"] == "quota"

    waiting_until = datetime.fromisoformat(job["not_before"])
    assert waiting_until > datetime.now(timezone.utc)


def test_worker_requeues_instead_of_failing_a_quota_death(queue, tmp_path):
    """End-to-end through run_next: the wiring, not just the helper."""
    path = _agent_job(
        queue, tmp_path, "k1708", "quota",
        status="queued",
        started_at=None,
        completed_at=None,
        exit_code=None,
        interpreter="python3",
        script_path="-c",
        args=["import sys; sys.exit(1)"],  # stands in for the CLI's quota banner exit
    )
    assert compute_queue.run_next(argparse.Namespace()) == 0

    job = json.loads(path.read_text())
    assert job["status"] == "queued"
    assert job["quota_requeues"] == 1
    assert job["not_before"]
    # It never finished, so it must not carry a finish time.
    assert job["completed_at"] is None
    assert compute_queue._pending_followup_view(job) is None  # nothing to nag a fire about


def test_real_failure_is_not_requeued(queue, tmp_path):
    """A job with a worktree worth reading must not be silently re-run."""
    job = json.loads(_agent_job(queue, tmp_path, "k1709", None).read_text())
    assert compute_queue._requeue_quota_blocked(job) is False
    assert job["status"] == "failed"


def test_worker_skips_a_job_still_waiting_out_its_window(queue, tmp_path, capsys):
    """Starting it early only re-hits the same wall."""
    _agent_job(
        queue, tmp_path, "k1708", "quota",
        status="queued",
        not_before=(datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat(),
    )
    assert compute_queue.run_next(argparse.Namespace()) == 0
    assert "1 waiting on not_before" in capsys.readouterr().out


def test_worker_picks_up_a_job_whose_window_has_passed(queue, tmp_path):
    job = json.loads(_agent_job(
        queue, tmp_path, "k1708", "quota",
        status="queued",
        not_before=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
    ).read_text())
    assert compute_queue._sleeping_until(job) is None


def test_unparseable_not_before_runs_rather_than_strands(queue, tmp_path):
    """A corrupt timestamp must not park a job in the queue forever."""
    job = json.loads(_agent_job(
        queue, tmp_path, "k1708", "quota", status="queued", not_before="not-a-date",
    ).read_text())
    assert compute_queue._sleeping_until(job) is None


def test_patience_runs_out_and_the_brief_says_quota(queue, tmp_path):
    """A weekly window outlasts the queue — then it is genuinely a person's turn."""
    job = json.loads(_agent_job(
        queue, tmp_path, "k1708", "quota",
        quota_requeues=compute_queue.QUOTA_REQUEUE_MAX,
    ).read_text())

    assert compute_queue._requeue_quota_blocked(job) is False
    assert job["status"] == "failed"

    row = compute_queue._pending_followup_view(job)
    brief = row["claude_followup"]["brief"]
    assert row["followup_mode"] == "triage_failed"
    assert "OUT OF PATIENCE ON QUOTA" in brief
    assert "no work was performed" in brief
    # The generic advice is what wasted the five fires: there is nothing to salvage.
    assert "Inspect what actually exists in the worktree" not in brief


@pytest.mark.parametrize("failure_class", ["quota", "auth"])
def test_requeue_cli_accepts_a_job_that_never_ran(queue, tmp_path, failure_class):
    path = _agent_job(queue, tmp_path, "k1708", failure_class)

    assert compute_queue.requeue(argparse.Namespace(id="k1708")) == 0

    job = json.loads(path.read_text())
    assert job["status"] == "queued"
    assert job["not_before"] is None  # a manual requeue is a deliberate "now"
    assert job["exit_code"] is None
    assert job["requeue_history"][0]["reason"] == f"manual:{failure_class}"


def test_requeue_cli_accepts_pre_spawn_policy_denial(
    queue,
    tmp_path,
) -> None:
    """Provider policy evidence proves the worktree was never touched."""
    path = _agent_job(
        queue,
        tmp_path,
        "retired-model",
        "policy_denial_pre_spawn",
    )
    metadata_path = Path(json.loads(path.read_text())["job_metadata"])
    metadata = json.loads(metadata_path.read_text())
    metadata["agent_spawned"] = False
    metadata["agent_spawn_attempts"] = 0
    metadata_path.write_text(json.dumps(metadata))

    assert compute_queue.requeue(argparse.Namespace(id="retired-model")) == 0

    job = json.loads(path.read_text())
    assert job["status"] == "queued"
    assert job["requeue_history"][0]["reason"] == (
        "manual:policy_denial_pre_spawn"
    )


def test_requeue_cli_refuses_a_job_with_a_worktree_to_triage(queue, tmp_path, capsys):
    _agent_job(queue, tmp_path, "k1709", None)
    assert compute_queue.requeue(argparse.Namespace(id="k1709")) == 2
    assert "Only auth/quota" in capsys.readouterr().err


def test_requeue_cli_refuses_a_job_that_is_not_failed(queue, tmp_path, capsys):
    _agent_job(queue, tmp_path, "k1708", "quota", status="running")
    assert compute_queue.requeue(argparse.Namespace(id="k1708")) == 2
    assert "not failed" in capsys.readouterr().err


def test_followup_then_requeue_is_mutually_exclusive(queue, tmp_path, capsys):
    """A triage owner prevents a blind retry from writing the same worktree."""
    path = _agent_job(queue, tmp_path, "k1710", "quota")

    assert compute_queue.mark_followup_dispatched(
        argparse.Namespace(id="k1710", next_task_id="triage-k1710")
    ) == 0
    assert compute_queue.requeue(argparse.Namespace(id="k1710")) == 2

    job = json.loads(path.read_text())
    assert job["status"] == "failed"
    assert job["followup_dispatched"] is True
    assert job["followup_next_task_id"] == "triage-k1710"
    assert "disposition is owned by followup triage-k1710" in capsys.readouterr().err


def test_requeue_then_followup_is_mutually_exclusive(queue, tmp_path, capsys):
    """The reciprocal lock order refuses to attach triage to a queued retry."""
    path = _agent_job(queue, tmp_path, "k1711", "auth")

    assert compute_queue.requeue(argparse.Namespace(id="k1711")) == 0
    assert compute_queue.mark_followup_dispatched(
        argparse.Namespace(id="k1711", next_task_id="triage-k1711")
    ) == 2

    job = json.loads(path.read_text())
    assert job["status"] == "queued"
    assert job["followup_dispatched"] is False
    assert "status=queued, not terminal" in capsys.readouterr().err


def test_automatic_quota_requeue_refuses_followup_owned_receipt(queue, tmp_path):
    job = json.loads(_agent_job(
        queue,
        tmp_path,
        "k1712",
        "quota",
        followup_dispatched=True,
        followup_next_task_id="triage-k1712",
    ).read_text())

    assert compute_queue._requeue_quota_blocked(job) is False
    assert job["status"] == "failed"
