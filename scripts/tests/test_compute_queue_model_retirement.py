"""Retired agent-model admission, pre-spawn remap, and safe retry contracts."""

from __future__ import annotations

import argparse
import json
import threading
from pathlib import Path
from types import SimpleNamespace

from scripts import compute_queue


def _patch_queue_paths(tmp_path: Path, monkeypatch) -> Path:
    queue_dir = tmp_path / "compute_queue"
    log_dir = tmp_path / "logs"
    queue_dir.mkdir(parents=True)
    log_dir.mkdir(parents=True)
    monkeypatch.setattr(compute_queue, "QUEUE_DIR", queue_dir)
    monkeypatch.setattr(compute_queue, "LOG_DIR", log_dir)
    monkeypatch.setattr(compute_queue, "LOCK_FILE", queue_dir / ".worker.lock")
    return queue_dir


def test_enqueue_agent_rejects_retired_model_before_writing_artifacts(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    """A stale model must fail at admission, not after hours in the queue."""
    queue_dir = _patch_queue_paths(tmp_path, monkeypatch)
    monkeypatch.setattr(compute_queue, "ROOT", tmp_path)
    monkeypatch.setattr(
        compute_queue,
        "AGENT_BRIEF_DIR",
        tmp_path / "briefs",
    )
    monkeypatch.setattr(
        compute_queue,
        "is_registered_linked_worktree",
        lambda *_a, **_k: True,
    )
    monkeypatch.setattr(
        compute_queue,
        "_find_task_dispatch_collision",
        lambda **_k: None,
    )
    brief = tmp_path / "brief.md"
    brief.write_text("do the thing", encoding="utf-8")
    workdir = tmp_path / "wt"
    workdir.mkdir()

    rc = compute_queue.enqueue_agent(
        SimpleNamespace(
            id="retired-model-job",
            title=None,
            brief_file=str(brief),
            model="claude-opus-4-8",
            effort="xhigh",
            cwd=str(workdir),
            result_artifact=None,
            followup_brief=None,
            followup_task_type="experiment",
            followup_priority=2,
            timeout=None,
            timeout_parent_job_id=None,
            split_stage=None,
            source_task_id="assign-retired",
        )
    )

    assert rc == 2
    assert "not allowed by the canonical model router/provider registry" in (
        capsys.readouterr().err
    )
    assert not (queue_dir / "retired-model-job.json").exists()
    assert not (tmp_path / "briefs" / "retired-model-job.md").exists()


def test_spawn_preflight_remaps_retired_model_from_canonical_router(
    monkeypatch,
) -> None:
    """A queued immutable spec may only change through an auditable remap."""
    monkeypatch.setattr(
        compute_queue,
        "_agent_model_policy",
        lambda task_type: {
            "allowed_models": frozenset(
                {"claude-opus-5", "claude-sonnet-5"}
            ),
            "canonical_model": "claude-opus-5",
            "registry_sha256": "a" * 64,
            "task_type": task_type,
        },
    )
    job = {
        "id": "old-job",
        "kind": "agent",
        "script_path": "scripts/run_agent_job.py",
        "args": [
            "--brief-file",
            "/tmp/brief.md",
            "--model",
            "claude-opus-4-8",
        ],
        "claude_followup": {"task_type": "experiment"},
    }

    receipt = compute_queue._remap_retired_agent_model(job)

    assert (
        compute_queue._arg_value(job["args"], "--model")
        == "claude-opus-5"
    )
    assert receipt == {
        "from_model": "claude-opus-4-8",
        "to_model": "claude-opus-5",
        "reason": "frozen_model_retired_before_spawn",
        "task_type": "experiment",
        "registry_sha256": "a" * 64,
        "remapped_at": receipt["remapped_at"],
    }
    assert job["model_remap_receipts"] == [receipt]


def test_enqueue_agent_blocks_same_live_worktree_with_different_source_task(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    """Worktree identity is an owner key independent of source task id."""
    queue_dir = _patch_queue_paths(tmp_path, monkeypatch)
    monkeypatch.setattr(compute_queue, "ROOT", tmp_path)
    monkeypatch.setattr(
        compute_queue,
        "AGENT_BRIEF_DIR",
        tmp_path / "briefs",
    )
    monkeypatch.setattr(
        compute_queue,
        "is_registered_linked_worktree",
        lambda *_a, **_k: True,
    )
    monkeypatch.setattr(
        compute_queue,
        "_find_task_dispatch_collision",
        lambda **_k: None,
    )
    brief = tmp_path / "brief.md"
    brief.write_text("do the thing", encoding="utf-8")
    workdir = tmp_path / "wt"
    workdir.mkdir()
    (queue_dir / "existing-job.json").write_text(
        json.dumps(
            {
                "id": "existing-job",
                "kind": "agent",
                "status": "queued",
                "cwd": str(workdir),
                "source_task_id": "assign-first",
            }
        ),
        encoding="utf-8",
    )

    rc = compute_queue.enqueue_agent(
        SimpleNamespace(
            id="second-job",
            title=None,
            brief_file=str(brief),
            model="claude-opus-5",
            effort="xhigh",
            cwd=str(workdir),
            result_artifact=None,
            followup_brief=None,
            followup_task_type="experiment",
            followup_priority=2,
            timeout=None,
            timeout_parent_job_id=None,
            split_stage=None,
            source_task_id="assign-second",
        )
    )

    assert rc == 2
    error = capsys.readouterr().err
    assert "worktree collision" in error
    assert "existing-job" in error
    assert not (queue_dir / "second-job.json").exists()
    assert not (tmp_path / "briefs" / "second-job.md").exists()


def test_enqueue_agent_fails_closed_on_unreadable_collision_receipt(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    """A corrupt owner receipt cannot be treated as an empty worktree lane."""
    queue_dir = _patch_queue_paths(tmp_path, monkeypatch)
    monkeypatch.setattr(compute_queue, "ROOT", tmp_path)
    monkeypatch.setattr(
        compute_queue,
        "AGENT_BRIEF_DIR",
        tmp_path / "briefs",
    )
    monkeypatch.setattr(
        compute_queue,
        "is_registered_linked_worktree",
        lambda *_a, **_k: True,
    )
    monkeypatch.setattr(
        compute_queue,
        "_find_task_dispatch_collision",
        lambda **_k: None,
    )
    (queue_dir / "unknown-owner.json").write_text(
        "{not-json",
        encoding="utf-8",
    )
    brief = tmp_path / "brief.md"
    brief.write_text("do the thing", encoding="utf-8")
    workdir = tmp_path / "wt"
    workdir.mkdir()

    rc = compute_queue.enqueue_agent(
        SimpleNamespace(
            id="must-not-enqueue",
            title=None,
            brief_file=str(brief),
            model="claude-opus-5",
            effort="xhigh",
            cwd=str(workdir),
            result_artifact=None,
            followup_brief=None,
            followup_task_type="experiment",
            followup_priority=2,
            timeout=None,
            timeout_parent_job_id=None,
            split_stage=None,
            source_task_id="assign-corrupt-owner",
        )
    )

    assert rc == 2
    assert "worktree collision scan failed closed" in capsys.readouterr().err
    assert not (queue_dir / "must-not-enqueue.json").exists()
    assert not (tmp_path / "briefs" / "must-not-enqueue.md").exists()


def test_parallel_enqueue_agent_admits_only_one_owner_per_worktree(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """The final receipt CAS closes the gap after two clean prechecks."""
    queue_dir = _patch_queue_paths(tmp_path, monkeypatch)
    monkeypatch.setattr(compute_queue, "ROOT", tmp_path)
    monkeypatch.setattr(
        compute_queue,
        "AGENT_BRIEF_DIR",
        tmp_path / "briefs",
    )
    monkeypatch.setattr(
        compute_queue,
        "AGENT_JOB_DIR",
        tmp_path / "agent_jobs",
    )
    monkeypatch.setattr(
        compute_queue,
        "is_registered_linked_worktree",
        lambda *_a, **_k: True,
    )
    monkeypatch.setattr(
        compute_queue,
        "_agent_model_policy",
        lambda task_type: {
            "allowed_models": frozenset({"claude-opus-5"}),
            "canonical_model": "claude-opus-5",
            "registry_sha256": "c" * 64,
            "task_type": task_type,
        },
    )
    monkeypatch.setattr(
        compute_queue,
        "_link_source_task",
        lambda *_a, **_k: None,
    )
    both_prechecks_passed = threading.Barrier(2)

    def no_task_collision(**_kwargs):
        both_prechecks_passed.wait(timeout=5)
        return None

    monkeypatch.setattr(
        compute_queue,
        "_find_task_dispatch_collision",
        no_task_collision,
    )
    brief = tmp_path / "brief.md"
    brief.write_text("do the thing", encoding="utf-8")
    workdir = tmp_path / "wt"
    workdir.mkdir()
    results: list[int] = []

    def enqueue_one(index: int) -> None:
        results.append(
            compute_queue.enqueue_agent(
                SimpleNamespace(
                    id=f"parallel-{index}",
                    title=None,
                    brief_file=str(brief),
                    model="claude-opus-5",
                    effort="xhigh",
                    cwd=str(workdir),
                    result_artifact=None,
                    followup_brief=None,
                    followup_task_type="experiment",
                    followup_priority=2,
                    timeout=None,
                    timeout_parent_job_id=None,
                    split_stage=None,
                    source_task_id=f"assign-parallel-{index}",
                )
            )
        )

    threads = [
        threading.Thread(target=enqueue_one, args=(index,))
        for index in (1, 2)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()

    assert sorted(results) == [0, 2]
    receipts = [
        path
        for path in queue_dir.glob("parallel-*.json")
        if path.is_file()
    ]
    assert len(receipts) == 1
    assert json.loads(receipts[0].read_text())["cwd"] == str(workdir)
    assert len(list((tmp_path / "briefs").glob("parallel-*.md"))) == 1


def test_execute_job_persists_model_remap_before_agent_spawn(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """The child command and durable running receipt must agree before Popen."""
    queue_dir = _patch_queue_paths(tmp_path, monkeypatch)
    job_path = queue_dir / "retired-model.json"
    job = {
        "id": "retired-model",
        "kind": "agent",
        "status": "running",
        "queued_at": "2026-07-29T00:00:00Z",
        "script_path": "scripts/run_agent_job.py",
        "interpreter": "uv run python",
        "args": [
            "--brief-file",
            str(tmp_path / "brief.md"),
            "--model",
            "claude-opus-4-8",
            "--cwd",
            str(tmp_path),
        ],
        "env": {},
        "stdout_file": str(compute_queue.LOG_DIR / "retired-model.stdout"),
        "stderr_file": str(compute_queue.LOG_DIR / "retired-model.stderr"),
        "result_artifact": None,
        "timeout_seconds": 30,
        "claude_followup": {"task_type": "experiment"},
    }
    job_path.write_text(json.dumps(job), encoding="utf-8")
    monkeypatch.setattr(
        compute_queue,
        "_agent_model_policy",
        lambda task_type: {
            "allowed_models": frozenset(
                {"claude-opus-5", "claude-sonnet-5"}
            ),
            "canonical_model": "claude-opus-5",
            "registry_sha256": "b" * 64,
            "task_type": task_type,
        },
    )

    def fake_spawn(command, **_kwargs):
        running_receipt = json.loads(job_path.read_text(encoding="utf-8"))
        assert compute_queue._arg_value(
            running_receipt["args"], "--model"
        ) == "claude-opus-5"
        assert running_receipt["model_remap_receipts"][0]["from_model"] == (
            "claude-opus-4-8"
        )
        assert compute_queue._arg_value(command, "--model") == "claude-opus-5"
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(compute_queue, "_run_job_subprocess", fake_spawn)

    compute_queue._execute_job(job_path, job)

    terminal_receipt = json.loads(job_path.read_text(encoding="utf-8"))
    assert terminal_receipt["status"] == "completed"
    assert terminal_receipt["model_remap_receipts"][0] == {
        "from_model": "claude-opus-4-8",
        "to_model": "claude-opus-5",
        "reason": "frozen_model_retired_before_spawn",
        "task_type": "experiment",
        "registry_sha256": "b" * 64,
        "remapped_at": terminal_receipt["model_remap_receipts"][0][
            "remapped_at"
        ],
    }


def test_requeue_refuses_policy_denial_after_agent_spawn(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    """The typed class cannot launder a job that already touched its worktree."""
    queue_dir = _patch_queue_paths(tmp_path, monkeypatch)
    metadata_path = tmp_path / "metadata.json"
    metadata_path.write_text(
        json.dumps(
            {
                "failure_class": "policy_denial_pre_spawn",
                "agent_spawned": True,
                "agent_spawn_attempts": 1,
            }
        ),
        encoding="utf-8",
    )
    job_path = queue_dir / "unsafe-policy-denial.json"
    job_path.write_text(
        json.dumps(
            {
                "id": "unsafe-policy-denial",
                "kind": "agent",
                "status": "failed",
                "failure_reason": "agent_runner_failed",
                "job_metadata": str(metadata_path),
                "source_task_id": None,
                "followup_dispatched": False,
            }
        ),
        encoding="utf-8",
    )

    assert (
        compute_queue.requeue(argparse.Namespace(id="unsafe-policy-denial"))
        == 2
    )
    assert "agent_spawned=false" in capsys.readouterr().err
    assert json.loads(job_path.read_text(encoding="utf-8"))["status"] == "failed"
