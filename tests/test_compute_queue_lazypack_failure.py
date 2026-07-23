"""Compute-kind failure classification + lazypack escalation (assign_5195e5ae D3).

Two structural holes are pinned here:

1. `_requeue_quota_blocked` read only the agent-runner receipt
   (``job_metadata``), so a compute-kind job killed by a codex quota wall
   failed terminally while the same wall re-queued an agent job.  Compute jobs
   now classify their stderr tail through the supervisor's single-owner
   classifier, with an explicit ``[FAILURE_CLASS]`` producer marker overriding
   the regexes (the lazypack chain stamps ``none`` after its quota-independent
   deterministic layer, so stale codex quota lines cannot fake a quota death).

2. A lazypack job whose whole renderer chain failed left only a failed receipt
   — no task, no owner (the alert claimed a retry that did not exist).  A
   non-quota terminal failure now files an idempotent repair task into the
   canonical pool (requested P1; the gateway's machine-source admission clamp
   — dispatch-lanes R2, 2026-07-21 — admits it at P2 with
   ``priority_capped_from: 1``).

Run: uv run --extra dev python -m pytest tests/test_compute_queue_lazypack_failure.py -v
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import scripts.compute_queue as module

QUOTA_TAIL = "ERROR: You've hit your usage limit. Try again at Jul 25th, 2026.\n"


def _patch_paths(tmp_path: Path, monkeypatch) -> Path:
    queue_dir = tmp_path / "compute_queue"
    log_dir = tmp_path / "logs"
    monkeypatch.setattr(module, "QUEUE_DIR", queue_dir)
    monkeypatch.setattr(module, "LOG_DIR", log_dir)
    monkeypatch.setattr(module, "LOCK_FILE", queue_dir / ".worker.lock")
    monkeypatch.setattr(module, "NEXT_TASKS_PATH", tmp_path / "next_tasks.json")
    queue_dir.mkdir(parents=True)
    log_dir.mkdir(parents=True)
    return queue_dir


def _compute_job(log_dir: Path, job_id: str, stderr_text: str) -> dict:
    stderr = log_dir / f"{job_id}.stderr"
    stderr.write_text(stderr_text, encoding="utf-8")
    return {
        "id": job_id,
        "status": "failed",
        "exit_code": 2,
        "queued_at": "2026-07-20T00:00:00Z",
        "script_path": "scripts/lazypack_async_render.py",
        "args": ["run", "--article-id", "mile_test1",
                 "--plan", "storage/lazypack_jobs/mile_test1/plan.json"],
        "stdout_file": str(log_dir / f"{job_id}.stdout"),
        "stderr_file": str(stderr),
        # deliberately NO job_metadata: compute-kind jobs have no runner receipt
    }


def test_compute_kind_quota_stderr_is_classified(tmp_path, monkeypatch):
    _patch_paths(tmp_path, monkeypatch)
    job = _compute_job(module.LOG_DIR, "lazypack-mile_test1", QUOTA_TAIL)
    assert module._runner_failure_class(job) == "quota"


def test_producer_marker_overrides_stale_quota_lines(tmp_path, monkeypatch):
    """The lazypack chain's `[FAILURE_CLASS] none` beats earlier codex quota noise."""
    _patch_paths(tmp_path, monkeypatch)
    stderr = QUOTA_TAIL + "...\n[FAILURE_CLASS] none\nerror: render step failed rc=2\n"
    job = _compute_job(module.LOG_DIR, "lazypack-mile_test1", stderr)
    assert module._runner_failure_class(job) is None


def test_missing_stderr_reads_as_unclassified(tmp_path, monkeypatch, capsys):
    _patch_paths(tmp_path, monkeypatch)
    job = _compute_job(module.LOG_DIR, "lazypack-mile_test1", QUOTA_TAIL)
    Path(job["stderr_file"]).unlink()
    assert module._runner_failure_class(job) is None
    assert "stderr unreadable" in capsys.readouterr().err


def test_quota_blocked_compute_job_is_requeued_with_backoff(tmp_path, monkeypatch):
    """The structural gap: backoff-requeue must now cover compute-kind jobs."""
    _patch_paths(tmp_path, monkeypatch)
    job = _compute_job(module.LOG_DIR, "lazypack-mile_test1", QUOTA_TAIL)
    assert module._requeue_quota_blocked(job) is True
    assert job["status"] == "queued"
    assert job["quota_requeues"] == 1
    assert job["not_before"]
    assert job["exit_code"] is None


def test_non_quota_failure_is_not_requeued(tmp_path, monkeypatch):
    _patch_paths(tmp_path, monkeypatch)
    stderr = QUOTA_TAIL + "[FAILURE_CLASS] none\n"
    job = _compute_job(module.LOG_DIR, "lazypack-mile_test1", stderr)
    assert module._requeue_quota_blocked(job) is False
    assert job["status"] == "failed"


def test_terminal_lazypack_failure_files_idempotent_repair_task(
    tmp_path, monkeypatch, capsys
):
    _patch_paths(tmp_path, monkeypatch)
    job = _compute_job(module.LOG_DIR, "lazypack-mile_test1",
                       "[FAILURE_CLASS] none\n")
    module._maybe_open_lazypack_repair_task(job)
    tasks = json.loads((tmp_path / "next_tasks.json").read_text(encoding="utf-8"))
    assert len(tasks) == 1
    task = tasks[0]
    assert task["id"] == "lazypack_render_repair_mile_test1"
    # Machine-source P1 is clamped at admission (dispatch-lanes R2): the
    # producer asks for P1, the pool admits P2 with an auditable stamp.
    assert task["priority"] == 2
    assert task["priority_capped_from"] == 1
    assert task["status"] == "pending"
    assert task["task_type"] == "platform_ops"
    assert task["payload"]["job_id"] == "lazypack-mile_test1"
    assert "mile_test1" in task["description"]

    # Second terminal failure for the same article must not mint a second task.
    module._maybe_open_lazypack_repair_task(job)
    tasks = json.loads((tmp_path / "next_tasks.json").read_text(encoding="utf-8"))
    assert len(tasks) == 1
    out = capsys.readouterr().out
    assert "created (P2)" in out
    assert "already pending" in out


def test_non_lazypack_jobs_do_not_escalate(tmp_path, monkeypatch):
    _patch_paths(tmp_path, monkeypatch)
    job = _compute_job(module.LOG_DIR, "collect-us-daily", "boom\n")
    module._maybe_open_lazypack_repair_task(job)
    assert not (tmp_path / "next_tasks.json").exists()


def test_execute_job_wires_quota_requeue_and_escalation(tmp_path, monkeypatch):
    """End-to-end through _execute_job: quota tail → requeue; marker → P1 task."""
    queue_dir = _patch_paths(tmp_path, monkeypatch)

    def _job_file(job_id: str, script_body: str) -> Path:
        script = tmp_path / f"{job_id}.py"
        script.write_text(script_body, encoding="utf-8")
        path = queue_dir / f"{job_id}.json"
        path.write_text(json.dumps({
            "id": job_id,
            "status": "running",
            "queued_at": "2026-07-20T00:00:00Z",
            "script_path": str(script),
            "interpreter": sys.executable,
            "args": ["run", "--article-id", "mile_e2e"],
            "env": {},
            "stdout_file": str(module.LOG_DIR / f"{job_id}.stdout"),
            "stderr_file": str(module.LOG_DIR / f"{job_id}.stderr"),
            "result_artifact": None,
            "timeout_seconds": 30,
        }), encoding="utf-8")
        return path

    quota_body = (
        "import sys\n"
        f"sys.stderr.write({QUOTA_TAIL!r})\n"
        "raise SystemExit(2)\n"
    )
    path = _job_file("lazypack-mile_e2e", quota_body)
    job = json.loads(path.read_text(encoding="utf-8"))
    module._execute_job(path, job)
    receipt = json.loads(path.read_text(encoding="utf-8"))
    assert receipt["status"] == "queued"  # quota → backoff requeue, not terminal
    assert receipt["quota_requeues"] == 1
    assert not (tmp_path / "next_tasks.json").exists()

    terminal_body = (
        "import sys\n"
        f"sys.stderr.write({QUOTA_TAIL!r})\n"
        "sys.stderr.write('[FAILURE_CLASS] none\\n')\n"
        "raise SystemExit(2)\n"
    )
    path = _job_file("lazypack-mile_e2e2", terminal_body)
    job = json.loads(path.read_text(encoding="utf-8"))
    job["args"] = ["run", "--article-id", "mile_e2e2"]
    module._execute_job(path, job)
    receipt = json.loads(path.read_text(encoding="utf-8"))
    assert receipt["status"] == "failed"
    tasks = json.loads((tmp_path / "next_tasks.json").read_text(encoding="utf-8"))
    assert [t["id"] for t in tasks] == ["lazypack_render_repair_mile_e2e2"]
