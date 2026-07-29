from __future__ import annotations

import subprocess
from contextlib import contextmanager
from pathlib import Path

import pytest

from scripts.dispatch_supervisor import workspace


def test_merge_script_preserves_writer_lease_without_private_supervisor_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = tmp_path / workspace.MERGE_SCRIPT_RELPATH
    script.parent.mkdir(parents=True)
    script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    worktree = tmp_path / "dispatch-worktree"
    worktree.mkdir()
    expected_main = "a" * 40
    expected_candidate = "b" * 40
    child_calls: list[dict] = []

    class Lease:
        def child_env(self):
            return {
                "PATH": "/volpred-merge-path",
                "VOLPRED_ACTOR": "dispatch-workspace-integrator",
                "VOLPRED_GIT_WRITER_LOCK_TOKEN": "writer-token",
                "VOLPRED_GIT_WRITER_LOCK_FD": "19",
                "VOLPRED_SUPERVISOR_RELEASE_ID": "private-release",
                "VOLPRED_DEFERRED_RELOAD_ROOT": "/private/reload",
                "VOLPRED_CANONICAL_REPO_ROOT": "/private/canonical",
            }

        def child_pass_fds(self):
            return (19,)

    @contextmanager
    def fake_writer_lock(*_args, **_kwargs):
        yield Lease()

    def fake_git(repo: Path, *args: str, **_kwargs):
        sha = expected_main if Path(repo) == tmp_path else expected_candidate
        return subprocess.CompletedProcess(args, 0, f"{sha}\n", "")

    def runner(argv, **kwargs):
        child_calls.append({"argv": argv, **kwargs})
        return subprocess.CompletedProcess(argv, 0, "merged\n", "")

    monkeypatch.setattr(workspace, "git_writer_lock", fake_writer_lock)
    monkeypatch.setattr(workspace, "_git", fake_git)

    outcome = workspace._run_merge_script(
        repo_root=tmp_path,
        workspace={
            "name": "dispatch-slot-1-aaaaaaaa",
            "path": str(worktree),
        },
        runner=runner,
        expected_main_sha=expected_main,
        expected_candidate_sha=expected_candidate,
    )

    assert outcome["ok"] is True
    assert len(child_calls) == 1
    call = child_calls[0]
    assert call["pass_fds"] == (19,)
    child_env = call["env"]
    assert child_env["PATH"] == "/volpred-merge-path"
    assert child_env["VOLPRED_ACTOR"] == "dispatch-workspace-integrator"
    assert child_env["VOLPRED_GIT_WRITER_LOCK_TOKEN"] == "writer-token"
    assert child_env["VOLPRED_GIT_WRITER_LOCK_FD"] == "19"
    assert "VOLPRED_SUPERVISOR_RELEASE_ID" not in child_env
    assert "VOLPRED_DEFERRED_RELOAD_ROOT" not in child_env
    assert "VOLPRED_CANONICAL_REPO_ROOT" not in child_env
