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


def _enqueue_args(**over):
    values = {
        "id": "owned-output-job",
        "title": "owned output job",
        "script": "scripts/example.py",
        "interpreter": "python",
        "script_args": [],
        "env": [],
        "result_artifact": "results/final.json",
        "output_paths": None,
        "followup_brief": None,
        "followup_task_type": None,
        "followup_priority": None,
        "timeout": 60,
        "timeout_parent_job_id": None,
        "split_stage": None,
    }
    values.update(over)
    return SimpleNamespace(**values)


def test_enqueue_requires_explicit_output_ownership(
    tmp_path: Path,
    monkeypatch,
) -> None:
    queue_dir = _patch_queue_paths(tmp_path, monkeypatch)
    monkeypatch.setattr(module, "ROOT", tmp_path)

    assert module.enqueue(_enqueue_args()) == 0
    job = json.loads((queue_dir / "owned-output-job.json").read_text())

    assert job["result_artifact"] == "results/final.json"
    assert job["output_paths"] == []  # postcondition is not Git ownership


def test_enqueue_normalizes_and_deduplicates_explicit_output_paths(
    tmp_path: Path,
    monkeypatch,
) -> None:
    queue_dir = _patch_queue_paths(tmp_path, monkeypatch)
    monkeypatch.setattr(module, "ROOT", tmp_path)

    args = _enqueue_args(output_paths=["results/a.json", "results/a.json", "results/b.png"])
    assert module.enqueue(args) == 0
    job = json.loads((queue_dir / "owned-output-job.json").read_text())

    assert job["output_paths"] == ["results/a.json", "results/b.png"]


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


def test_run_next_marks_timeout_as_split_required(
    tmp_path: Path,
    monkeypatch,
) -> None:
    queue_dir = _patch_queue_paths(tmp_path, monkeypatch)
    queue_dir.mkdir(parents=True)
    job_path = _queued_job(queue_dir, module.LOG_DIR, artifact=None)

    def time_out(*args, **kwargs):
        raise module.subprocess.TimeoutExpired(cmd=args[0], timeout=10)

    monkeypatch.setattr(module.subprocess, "run", time_out)

    assert module.run_next(SimpleNamespace()) == 0
    job = json.loads(job_path.read_text())
    assert job["status"] == "failed"
    assert job["exit_code"] == -1
    assert job["failure_reason"] == "timeout"
    assert job["split_required"] is True
    assert job["timed_out_at"]


def test_worker_preserves_child_output_writeback_on_nonzero_exit(
    tmp_path: Path,
    monkeypatch,
) -> None:
    queue_dir = _patch_queue_paths(tmp_path, monkeypatch)
    queue_dir.mkdir(parents=True)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    job_path = _queued_job(queue_dir, module.LOG_DIR, artifact=None)
    panel = tmp_path / "storage" / "lazypack_jobs" / "mile_x" / "panels" / "1.png"

    def failed_child(*args, **kwargs):
        panel.parent.mkdir(parents=True)
        panel.write_bytes(b"panel")
        assert module.record_output_paths("artifact-postcondition", [panel]) is True
        return SimpleNamespace(returncode=9)

    monkeypatch.setattr(module.subprocess, "run", failed_child)

    assert module.run_next(SimpleNamespace()) == 0
    job = json.loads(job_path.read_text())
    assert job["status"] == "failed"
    assert job["exit_code"] == 9
    assert job["output_paths"] == [
        "storage/lazypack_jobs/mile_x/panels/1.png"
    ]
    assert job["output_paths_updated_at"]


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
        {
            **base,
            "id": "timeout-compute",
            "status": "failed",
            "kind": "compute",
            "failure_reason": "timeout",
            "split_required": True,
            "timeout_seconds": 3600,
        },
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
        ("failed-agent", "split_required"),
        ("timeout-compute", "split_required"),
    ]
    failed = payload[1]
    assert failed["claude_followup"]["task_type"] == "platform_ops"
    assert failed["claude_followup"]["priority"] == 1
    assert "SPLIT REQUIRED" in failed["claude_followup"]["brief"]
    assert "Do NOT re-enqueue" in failed["claude_followup"]["brief"]
    assert "/repo/.claude/worktrees/partial" in failed["claude_followup"]["brief"]
    assert failed["split_contract"]["minimum_child_stages"] == 2


def test_enqueue_rejects_unchanged_retry_after_timeout_and_accepts_split_child(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    queue_dir = _patch_queue_paths(tmp_path, monkeypatch)
    queue_dir.mkdir(parents=True)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    parent = {
        "id": "timed-out-parent",
        "status": "failed",
        "failure_reason": "timeout",
        "split_required": True,
        "timeout_seconds": 60,
        "kind": "compute",
        "script_path": "scripts/example.py",
        "interpreter": "python",
        "args": [],
        "cwd": None,
        "result_artifact": "results/final.json",
    }
    (queue_dir / "timed-out-parent.json").write_text(json.dumps(parent), encoding="utf-8")

    assert module.enqueue(_enqueue_args(id="unchanged-retry")) == 2
    assert "unchanged retry" in capsys.readouterr().err
    assert not (queue_dir / "unchanged-retry.json").exists()

    split = _enqueue_args(
        id="split-child",
        script_args=["--shard", "1"],
        timeout=30,
        timeout_parent_job_id="timed-out-parent",
        split_stage="compute-shard-1",
    )
    assert module.enqueue(split) == 0
    child = json.loads((queue_dir / "split-child.json").read_text())
    assert child["parent_timeout_job_id"] == "timed-out-parent"
    assert child["split_stage"] == "compute-shard-1"


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


def test_pending_followup_detects_agent_inner_timeout_from_runner_metadata(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(module, "ROOT", tmp_path)
    metadata = tmp_path / "agent-metadata.json"
    metadata.write_text(json.dumps({"timed_out": True}), encoding="utf-8")
    worktree = tmp_path / ".claude" / "worktrees" / "inner-timeout"
    job = {
        "id": "inner-timeout-agent",
        "status": "failed",
        "exit_code": 1,
        "kind": "agent",
        "cwd": str(worktree),
        "job_metadata": str(metadata),
        "followup_dispatched": False,
        "timeout_seconds": 5400,
    }

    view = module._pending_followup_view(job)

    assert view is not None
    assert view["followup_mode"] == "split_required"
    assert view["split_contract"]["child_timeout_lt_seconds"] == 5400


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
    assert "split_required" in prompt
    assert "triage_failed" in prompt
    assert "不得把 failed job 或殘留 artifact 當成功結果" in prompt


def _write_verdict(root: Path, experiment: str, payload: dict) -> None:
    d = root / "experiments" / experiment
    d.mkdir(parents=True, exist_ok=True)
    (d / "review_verdict.json").write_text(json.dumps(payload), encoding="utf-8")


def test_pending_followup_annotates_job_whose_experiment_is_already_certified(
    tmp_path: Path,
    monkeypatch,
) -> None:
    # k1711-mcs-eval sat pending for two days asking a fire to split and re-run an
    # evaluation codex had already merged and certified. Surface that, don't hide it.
    monkeypatch.setattr(module, "ROOT", tmp_path)
    _write_verdict(
        tmp_path,
        "k1711",
        {
            "kid": "k1711",
            "verdict": "PASS",
            "reviewer": "codex/gpt-5 independent full-surface review",
            "reviewed_at": "2026-07-16T02:46:31+08:00",
            "reviewed_commit": "63520b4dae8b62d55650904ed51fab1739386f65",
        },
    )
    job = {
        "id": "k1711-mcs-eval",
        "title": "K1711 evaluation: MCS + DM over cached forecasts",
        "status": "failed",
        "exit_code": -1,
        "timeout_seconds": 3600,
        "followup_dispatched": False,
        "claude_followup": {"brief": "collect", "task_type": "experiment", "priority": 2},
    }

    view = module._pending_followup_view(job)

    assert view is not None, "annotation must never drop the row"
    assert view["followup_mode"] == "split_required"
    superseded = view["possibly_superseded"]
    assert superseded["experiment"] == "k1711"
    assert superseded["certified_at"] == "2026-07-16T02:46:31+08:00"
    assert superseded["reviewed_commit"] == "63520b4dae8b62d55650904ed51fab1739386f65"
    assert superseded["kid"] == "k1711"
    assert "BEFORE" in superseded["advice"]


def test_pending_followup_annotates_completed_collection_row(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(module, "ROOT", tmp_path)
    _write_verdict(
        tmp_path,
        "k1704",
        {"kid": "k1704", "verdict": "PASS", "reviewer": "codex/gpt-5", "reviewed_at": "2026-07-16T05:56:19Z"},
    )
    job = {
        "id": "k1704-primary-prerun-review-20260716",
        "title": "K1704 primary pre-run Codex review",
        "status": "completed",
        "followup_dispatched": False,
        "claude_followup": {"brief": "collect review", "task_type": "experiment", "priority": 3},
    }

    view = module._pending_followup_view(job)

    assert view is not None
    assert view["followup_mode"] == "collect_completed"
    assert view["possibly_superseded"]["experiment"] == "k1704"


def test_pending_followup_does_not_annotate_without_a_pass_verdict(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(module, "ROOT", tmp_path)
    _write_verdict(
        tmp_path,
        "k1799",
        {"kid": "k1799", "verdict": "FAIL", "reviewer": "codex/gpt-5", "reviewed_at": "2026-07-16T05:56:19Z"},
    )
    job = {
        "id": "k1799-eval",
        "title": "K1799 evaluation",
        "status": "completed",
        "followup_dispatched": False,
        "claude_followup": {"brief": "collect", "task_type": "experiment", "priority": 3},
    }

    view = module._pending_followup_view(job)

    assert view is not None
    assert "possibly_superseded" not in view


def test_pending_followup_without_experiment_id_or_verdict_is_unannotated(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(module, "ROOT", tmp_path)
    job = {
        "id": "refresh-market-panel",
        "title": "nightly data refresh",
        "status": "completed",
        "followup_dispatched": False,
        "claude_followup": {"brief": "collect", "task_type": "platform_ops", "priority": 3},
    }

    view = module._pending_followup_view(job)

    assert view is not None
    assert "possibly_superseded" not in view


def test_unreadable_verdict_warns_instead_of_silently_skipping(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(module, "ROOT", tmp_path)
    d = tmp_path / "experiments" / "k1650"
    d.mkdir(parents=True)
    (d / "review_verdict.json").write_text("{truncated", encoding="utf-8")
    job = {
        "id": "k1650-eval",
        "title": "K1650 evaluation",
        "status": "completed",
        "followup_dispatched": False,
        "claude_followup": {"brief": "collect", "task_type": "experiment", "priority": 3},
    }

    view = module._pending_followup_view(job)

    assert view is not None
    assert "possibly_superseded" not in view
    assert "review_verdict unreadable" in capsys.readouterr().err
