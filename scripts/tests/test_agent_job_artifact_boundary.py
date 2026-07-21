"""Regression tests for agent-job result/metadata ownership boundaries.

The runner owns lifecycle metadata in the main repo. The agent owns research
artifacts in its worktree. A relative ``--result-artifact`` therefore resolves
from ``--cwd`` and is verification-only; treating it as the runner summary path
silently creates plausible fake experiment results in main.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from scripts import compute_queue, run_agent_job


def _fake_agent(path: Path, body: str) -> Path:
    path.write_text("#!/bin/sh\nset -eu\n" + body)
    path.chmod(0o755)
    return path


def _runner_argv(
    brief: Path,
    worktree: Path,
    metadata: Path,
    result_artifact: str,
) -> list[str]:
    return [
        "run_agent_job.py",
        "--brief-file",
        str(brief),
        "--cwd",
        str(worktree),
        "--result-artifact",
        result_artifact,
        "--job-metadata",
        str(metadata),
        "--timeout",
        "10",
    ]


def test_runner_verifies_worktree_result_without_writing_main(monkeypatch, tmp_path: Path) -> None:
    main = tmp_path / "main"
    worktree = tmp_path / "worktree"
    main.mkdir()
    worktree.mkdir()
    brief = main / "brief.md"
    brief.write_text("produce the result")

    rel_artifact = "experiments/k-test/k-test_results.json"
    real_artifact = worktree / rel_artifact
    fake = _fake_agent(
        tmp_path / "fake-claude",
        f'mkdir -p "{real_artifact.parent}"\n'
        f'printf \'{{"source":"agent"}}\' > "{real_artifact}"\n',
    )
    metadata = main / "storage/ops/agent_jobs/job-test.json"

    monkeypatch.setattr(run_agent_job, "ROOT", main)
    monkeypatch.setattr(run_agent_job, "CLAUDE_BIN", str(fake))
    monkeypatch.setattr(
        sys,
        "argv",
        _runner_argv(brief, worktree, metadata, rel_artifact),
    )

    assert run_agent_job.main() == 0
    assert json.loads(real_artifact.read_text()) == {"source": "agent"}
    assert not (main / rel_artifact).exists()

    receipt = json.loads(metadata.read_text())
    assert receipt["result_artifact"] == str(real_artifact)
    assert receipt["result_artifact_exists"] is True
    assert receipt["validation_ok"] is True
    assert receipt["runner_exit_code"] == 0


def test_runner_fails_when_successful_agent_omits_declared_result(
    monkeypatch,
    tmp_path: Path,
) -> None:
    main = tmp_path / "main"
    worktree = tmp_path / "worktree"
    main.mkdir()
    worktree.mkdir()
    brief = main / "brief.md"
    brief.write_text("forget the result")
    fake = _fake_agent(tmp_path / "fake-claude", "exit 0\n")
    metadata = main / "storage/ops/agent_jobs/job-missing.json"
    rel_artifact = "experiments/k-missing/k-missing_results.json"

    monkeypatch.setattr(run_agent_job, "ROOT", main)
    monkeypatch.setattr(run_agent_job, "CLAUDE_BIN", str(fake))
    monkeypatch.setattr(
        sys,
        "argv",
        _runner_argv(brief, worktree, metadata, rel_artifact),
    )

    assert run_agent_job.main() == 1
    assert not (worktree / rel_artifact).exists()
    assert not (main / rel_artifact).exists()

    receipt = json.loads(metadata.read_text())
    assert receipt["exit_code"] == 0
    assert receipt["result_artifact_exists"] is False
    assert receipt["validation_ok"] is False
    assert receipt["runner_exit_code"] == 1


def test_runner_never_overwrites_absolute_worktree_result(monkeypatch, tmp_path: Path) -> None:
    main = tmp_path / "main"
    worktree = tmp_path / "worktree"
    main.mkdir()
    worktree.mkdir()
    brief = main / "brief.md"
    brief.write_text("preserve an existing result")
    result_artifact = worktree / "experiments/k-absolute/k-absolute_results.json"
    result_artifact.parent.mkdir(parents=True)
    result_artifact.write_text('{"source":"agent","rows":42}')
    fake = _fake_agent(tmp_path / "fake-claude", "exit 0\n")
    metadata = main / "storage/ops/agent_jobs/job-absolute.json"

    monkeypatch.setattr(run_agent_job, "ROOT", main)
    monkeypatch.setattr(run_agent_job, "CLAUDE_BIN", str(fake))
    monkeypatch.setattr(
        sys,
        "argv",
        _runner_argv(brief, worktree, metadata, str(result_artifact)),
    )

    assert run_agent_job.main() == 0
    assert json.loads(result_artifact.read_text()) == {"source": "agent", "rows": 42}
    assert json.loads(metadata.read_text())["result_artifact_exists"] is True


def _enqueue_args(
    *,
    brief: Path,
    cwd: str,
    result_artifact: str | None,
    job_id: str,
) -> argparse.Namespace:
    return argparse.Namespace(
        id=job_id,
        title="agent artifact boundary",
        brief_file=str(brief),
        model="claude-opus-4-8",
        effort="xhigh",
        cwd=cwd,
        result_artifact=result_artifact,
        followup_brief="verify the real result",
        followup_task_type="experiment",
        followup_priority=1,
        timeout=5400,
    )


def _patch_queue_paths(monkeypatch, root: Path) -> None:
    monkeypatch.setattr(compute_queue, "ROOT", root)
    monkeypatch.setattr(compute_queue, "QUEUE_DIR", root / "storage/ops/compute_queue")
    monkeypatch.setattr(compute_queue, "LOCK_FILE", root / "storage/ops/compute_queue/.worker.lock")
    monkeypatch.setattr(compute_queue, "LOG_DIR", root / "storage/logs/compute")
    monkeypatch.setattr(compute_queue, "AGENT_JOB_DIR", root / "storage/ops/agent_jobs")


def test_enqueue_agent_resolves_result_from_worktree_and_separates_metadata(
    monkeypatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "main"
    worktree = root / ".claude/worktrees/k-test"
    worktree.mkdir(parents=True)
    brief = root / "brief.md"
    brief.write_text("produce a canonical experiment result")
    _patch_queue_paths(monkeypatch, root)

    rel_artifact = "experiments/k-test/k-test_results.json"
    args = _enqueue_args(
        brief=brief,
        cwd=".claude/worktrees/k-test",
        result_artifact=rel_artifact,
        job_id="agent-artifact-test",
    )

    assert compute_queue.enqueue_agent(args) == 0
    job = json.loads(
        (root / "storage/ops/compute_queue/agent-artifact-test.json").read_text()
    )
    expected_result = worktree / rel_artifact
    expected_metadata = root / "storage/ops/agent_jobs/agent-artifact-test.json"

    assert job["result_artifact"] == str(expected_result)
    assert job["output_paths"] == []  # worktree artifact is not main-repo Git ownership
    assert job["job_metadata"] == str(expected_metadata)
    assert job["kind"] == "agent"
    assert job["cwd"] == str(worktree)
    result_index = job["args"].index("--result-artifact")
    metadata_index = job["args"].index("--job-metadata")
    assert job["args"][result_index + 1] == str(expected_result)
    assert job["args"][metadata_index + 1] == str(expected_metadata)
    assert not (root / rel_artifact).exists()

    # The frozen brief must land under the tmp root like every other write. It did
    # not until 2026-07-15: AGENT_BRIEF_DIR was bound at import from the real ROOT,
    # so this test wrote a brief into the live checkout on every run and only CI's
    # repo-state assert noticed. Assert the destination, not just the queue record.
    assert (root / "storage/ops/agent_briefs/agent-artifact-test.md").exists()


def test_enqueue_agent_without_result_does_not_invent_a_fake_artifact(
    monkeypatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "main"
    worktree = root / ".claude/worktrees/code-only"
    worktree.mkdir(parents=True)
    brief = root / "brief.md"
    brief.write_text("commit a code-only change")
    _patch_queue_paths(monkeypatch, root)

    args = _enqueue_args(
        brief=brief,
        cwd=".claude/worktrees/code-only",
        result_artifact=None,
        job_id="agent-code-only",
    )

    assert compute_queue.enqueue_agent(args) == 0
    job = json.loads(
        (root / "storage/ops/compute_queue/agent-code-only.json").read_text()
    )
    assert job["result_artifact"] is None
    assert job["output_paths"] == []
    assert job["kind"] == "agent"
    assert job["cwd"] == str(worktree)
    assert "--result-artifact" not in job["args"]
    assert job["job_metadata"].endswith("storage/ops/agent_jobs/agent-code-only.json")
