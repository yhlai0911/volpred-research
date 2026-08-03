from __future__ import annotations

import json
from pathlib import Path

from scripts import compute_queue as cq
from scripts import compute_task_admission as admission
from scripts import task_pool_claim as tpc


def _sandbox(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    script = root / "scripts" / "job.py"
    script.write_text("print('ok')\n", encoding="utf-8")
    next_tasks = root / "storage" / "next_tasks.json"
    next_tasks.parent.mkdir(parents=True)
    queue = root / "storage" / "ops" / "compute_queue"
    logs = root / "storage" / "logs" / "compute"
    monkeypatch.setattr(admission, "ROOT", root)
    monkeypatch.setattr(admission, "ADMISSION_LOCK", queue / ".admission.lock")
    monkeypatch.setattr(tpc, "ROOT", root)
    monkeypatch.setattr(tpc, "NEXT_TASKS", next_tasks)
    monkeypatch.setattr(cq, "ROOT", root)
    monkeypatch.setattr(cq, "QUEUE_DIR", queue)
    monkeypatch.setattr(cq, "LOG_DIR", logs)
    monkeypatch.setattr(cq, "LOCK_FILE", queue / ".worker.lock")
    return next_tasks, queue


def _task(task_id: str = "compute-demo") -> dict:
    return {
        "id": task_id,
        "title": "CPU-only demo",
        "task_type": "experiment",
        "priority": 2,
        "status": "pending",
        "compute_spec": {
            "script": "scripts/job.py",
            "args": ["--seed", "42"],
            "result_artifact": "experiments/demo/result.json",
            "output_paths": ["experiments/demo/result.json"],
            "timeout_seconds": 120,
        },
    }


def test_admission_enqueues_without_claude_lane(tmp_path: Path, monkeypatch) -> None:
    next_tasks, queue = _sandbox(tmp_path, monkeypatch)
    next_tasks.write_text(json.dumps([_task()]), encoding="utf-8")

    report = admission.admit()

    assert report["enqueued"] == 1
    jobs = [json.loads(path.read_text()) for path in queue.glob("*.json")]
    assert len(jobs) == 1
    assert jobs[0]["kind"] == "compute"
    assert jobs[0]["source_task_id"] == "compute-demo"
    assert jobs[0]["routing"]["token_cost_estimate"] == 0
    task = json.loads(next_tasks.read_text())[0]
    assert task["status"] == "awaiting_agent_job"
    assert task["compute_job_id"] == jobs[0]["id"]
    assert task["compute_admission"]["state"] == "reserved"

    # The second tick sees the canonical awaiting state and cannot duplicate it.
    assert admission.admit()["candidate_count"] == 0


def test_dry_run_does_not_mutate_pool_or_queue(tmp_path: Path, monkeypatch) -> None:
    next_tasks, queue = _sandbox(tmp_path, monkeypatch)
    next_tasks.write_text(json.dumps([_task()]), encoding="utf-8")

    report = admission.admit(dry_run=True)

    assert report["enqueued"] == 0
    assert report["results"][0]["status"] == "eligible"
    assert json.loads(next_tasks.read_text())[0]["status"] == "pending"
    assert not list(queue.glob("*.json"))


def test_invalid_spec_is_visible_and_not_guessed(tmp_path: Path, monkeypatch) -> None:
    next_tasks, queue = _sandbox(tmp_path, monkeypatch)
    bad = _task()
    bad["compute_spec"]["script"] = "scripts/missing.py"
    next_tasks.write_text(json.dumps([bad]), encoding="utf-8")

    report = admission.admit(dry_run=True)

    assert report["results"][0]["status"] == "invalid"
    assert "does not exist" in report["results"][0]["reason"]
    assert not list(queue.glob("*.json"))
