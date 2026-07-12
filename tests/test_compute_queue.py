from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from scripts import audit_silent_fallbacks
import scripts.compute_queue as module


def _patch_queue_paths(tmp_path: Path, monkeypatch) -> Path:
    queue_dir = tmp_path / "compute_queue"
    log_dir = tmp_path / "logs"
    monkeypatch.setattr(module, "QUEUE_DIR", queue_dir)
    monkeypatch.setattr(module, "LOG_DIR", log_dir)
    monkeypatch.setattr(module, "LOCK_FILE", queue_dir / ".worker.lock")
    return queue_dir


def test_list_jobs_warns_and_skips_bad_job_json(tmp_path: Path, monkeypatch, capsys):
    queue_dir = _patch_queue_paths(tmp_path, monkeypatch)
    queue_dir.mkdir(parents=True)
    (queue_dir / "bad.json").write_text("{bad json", encoding="utf-8")
    (queue_dir / "good.json").write_text(
        json.dumps(
            {
                "id": "good",
                "status": "queued",
                "title": "valid compute job",
                "queued_at": "2026-06-23T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )

    rc = module.list_jobs(
        SimpleNamespace(
            status=None,
            pending_followup=False,
            completed_pending_followup=False,
            json=True,
        )
    )

    captured = capsys.readouterr()
    assert rc == 0
    assert "[compute_queue] WARN list job JSON read failed; skipping" in captured.err
    assert "bad.json" in captured.err
    payload = json.loads(captured.out)
    assert [item["id"] for item in payload] == ["good"]


def test_run_next_warns_and_skips_bad_job_json(tmp_path: Path, monkeypatch, capsys):
    queue_dir = _patch_queue_paths(tmp_path, monkeypatch)
    queue_dir.mkdir(parents=True)
    (queue_dir / "bad.json").write_text("{bad json", encoding="utf-8")

    rc = module.run_next(SimpleNamespace())

    captured = capsys.readouterr()
    assert rc == 0
    assert "[compute_queue] WARN run-next job JSON read failed; skipping" in captured.err
    assert "no queued jobs" in captured.out


def test_acquire_lock_warns_when_lock_cannot_be_written(
    tmp_path: Path,
    monkeypatch,
    capsys,
):
    lock_path = tmp_path / "missing-parent" / ".worker.lock"
    monkeypatch.setattr(module, "LOCK_FILE", lock_path)

    assert module._acquire_lock() is False

    captured = capsys.readouterr()
    assert "[compute_queue] WARN worker lock write failed; skipping run" in captured.err
    assert ".worker.lock" in captured.err
    assert "FileNotFoundError" in captured.err


def test_compute_queue_has_no_silent_fallback_audit_findings() -> None:
    findings = audit_silent_fallbacks.audit_file(Path(module.__file__))

    assert findings == []


def _queued_job(queue_dir: Path, log_dir: Path, *, artifact: Path | None) -> Path:
    path = queue_dir / "artifact-postcondition.json"
    path.write_text(
        json.dumps(
            {
                "id": "artifact-postcondition",
                "status": "queued",
                "title": "artifact postcondition",
                "queued_at": "2026-07-12T00:00:00Z",
                "script_path": "unused.py",
                "interpreter": "python",
                "args": [],
                "env": {},
                "stdout_file": str(log_dir / "job.stdout"),
                "stderr_file": str(log_dir / "job.stderr"),
                "result_artifact": str(artifact) if artifact is not None else None,
                "timeout_seconds": 10,
            }
        ),
        encoding="utf-8",
    )
    return path


def test_run_next_fails_closed_when_declared_artifact_is_missing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    queue_dir = _patch_queue_paths(tmp_path, monkeypatch)
    queue_dir.mkdir(parents=True)
    job_path = _queued_job(queue_dir, module.LOG_DIR, artifact=tmp_path / "missing.json")
    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0))

    assert module.run_next(SimpleNamespace()) == 0

    job = json.loads(job_path.read_text())
    assert job["status"] == "failed"
    assert job["process_exit_code"] == 0
    assert job["exit_code"] == 3
    assert job["failure_reason"] == "result_artifact_missing"


def test_run_next_completes_when_artifact_exists_or_is_not_declared(
    tmp_path: Path,
    monkeypatch,
) -> None:
    queue_dir = _patch_queue_paths(tmp_path, monkeypatch)
    queue_dir.mkdir(parents=True)
    artifact = tmp_path / "result.json"
    artifact.write_text("{}")
    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0))

    existing_job = _queued_job(queue_dir, module.LOG_DIR, artifact=artifact)
    assert module.run_next(SimpleNamespace()) == 0
    assert json.loads(existing_job.read_text())["status"] == "completed"

    existing_job.unlink()
    no_artifact_job = _queued_job(queue_dir, module.LOG_DIR, artifact=None)
    assert module.run_next(SimpleNamespace()) == 0
    assert json.loads(no_artifact_job.read_text())["status"] == "completed"


def test_pending_followup_distinguishes_completed_collection_and_failed_agent_triage(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    queue_dir = _patch_queue_paths(tmp_path, monkeypatch)
    queue_dir.mkdir(parents=True)
    monkeypatch.setattr(module, "ROOT", Path("/repo"))
    base = {
        "followup_dispatched": False,
        "claude_followup": {"brief": "interpret validated result", "task_type": "experiment", "priority": 1},
    }
    jobs = [
        {
            **base,
            "id": "completed-agent",
            "status": "completed",
            "kind": "agent",
            "cwd": "/repo/.claude/worktrees/done",
        },
        {
            **base,
            "id": "failed-agent",
            "status": "failed",
            "exit_code": -1,
            "kind": "agent",
            "cwd": "/repo/.claude/worktrees/partial",
            "result_artifact": "/repo/.claude/worktrees/partial/experiments/kx/kx_results.json",
            "job_metadata": "/repo/storage/ops/agent_jobs/failed-agent.json",
            "stdout_file": "/repo/storage/logs/compute/failed-agent.stdout",
            "stderr_file": "/repo/storage/logs/compute/failed-agent.stderr",
        },
        {**base, "id": "failed-compute", "status": "failed", "kind": "compute", "cwd": None},
        {**base, "id": "failed-agent-main", "status": "failed", "kind": "agent", "cwd": "/repo"},
        {
            **base,
            "id": "already-dispatched",
            "status": "failed",
            "kind": "agent",
            "cwd": "/repo/.claude/worktrees/old",
            "followup_dispatched": True,
        },
    ]
    for job in jobs:
        (queue_dir / f"{job['id']}.json").write_text(json.dumps(job), encoding="utf-8")

    rc = module.list_jobs(
        SimpleNamespace(
            status=None,
            pending_followup=True,
            completed_pending_followup=False,
            json=True,
        )
    )

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert [(row["id"], row["followup_mode"]) for row in payload] == [
        ("completed-agent", "collect_completed"),
        ("failed-agent", "triage_failed"),
    ]
    failed = payload[1]
    assert failed["claude_followup"]["task_type"] == "platform_ops"
    assert failed["claude_followup"]["priority"] == 1
    assert "did not complete successfully" in failed["claude_followup"]["brief"]
    assert "Do not treat any artifact as a successful result" in failed["claude_followup"]["brief"]
    assert "/repo/.claude/worktrees/partial" in failed["claude_followup"]["brief"]


def test_pending_followup_triages_legacy_failed_agent_with_cwd_arg(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    queue_dir = _patch_queue_paths(tmp_path, monkeypatch)
    queue_dir.mkdir(parents=True)
    legacy = {
        "id": "legacy-failed-agent",
        "status": "failed",
        "script_path": "scripts/run_agent_job.py",
        "args": ["--brief-file", "/tmp/b.md", "--cwd", "/repo/.claude/worktrees/legacy"],
        "followup_dispatched": False,
        "claude_followup": None,
    }
    (queue_dir / "legacy.json").write_text(json.dumps(legacy), encoding="utf-8")

    assert module.list_jobs(
        SimpleNamespace(
            status=None,
            pending_followup=True,
            completed_pending_followup=False,
            json=True,
        )
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["followup_mode"] == "triage_failed"
    assert payload[0]["claude_followup"]["priority"] == 2


def test_legacy_completed_only_filter_does_not_return_failed_agent(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    queue_dir = _patch_queue_paths(tmp_path, monkeypatch)
    queue_dir.mkdir(parents=True)
    failed = {
        "id": "failed-agent",
        "status": "failed",
        "kind": "agent",
        "cwd": "/repo/.claude/worktrees/partial",
        "followup_dispatched": False,
        "claude_followup": {"brief": "collect", "task_type": "experiment", "priority": 1},
    }
    (queue_dir / "failed.json").write_text(json.dumps(failed), encoding="utf-8")

    assert module.list_jobs(
        SimpleNamespace(
            status=None,
            pending_followup=False,
            completed_pending_followup=True,
            json=True,
        )
    ) == 0
    assert json.loads(capsys.readouterr().out) == []


def test_hourly_prompt_routes_both_followup_modes() -> None:
    prompt = (Path(__file__).resolve().parents[1] / "scripts/cron_hourly_dispatch_prompt.md").read_text()

    assert "list --pending-followup --json" in prompt
    assert "collect_completed" in prompt
    assert "triage_failed" in prompt
    assert "不得把 failed job 或殘留 artifact 當成功結果" in prompt
