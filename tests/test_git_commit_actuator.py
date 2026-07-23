from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import subprocess

import pytest

from volpred.ops.delivery import ContentHash
from volpred.ops.delivery._git_actuator import (
    CommitActuation,
    CommitActuatorBlocked,
    GitCommitActuator,
)


NOW = datetime(2026, 7, 23, 16, 30, tzinfo=timezone.utc)


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


@pytest.fixture
def repository(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Commit Actuator Test")
    _git(repo, "config", "user.email", "commit-actuator@example.invalid")
    (repo / "tracked.txt").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-m", "base")
    return repo, _git(repo, "rev-parse", "HEAD")


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _command(repo: Path, expected_head: str) -> CommitActuation:
    return CommitActuation(
        proposal_sha256="a" * 64,
        repository=str(repo),
        expected_head=expected_head,
        exact_paths=("new.txt", "tracked.txt"),
        content_hashes=(
            ContentHash("new.txt", _hash(repo / "new.txt")),
            ContentHash("tracked.txt", _hash(repo / "tracked.txt")),
        ),
        message="[change-delivery] land changeset-1",
        actor="commit-worker:test",
    )


def _actuator() -> GitCommitActuator:
    return GitCommitActuator(clock=lambda: NOW)


def test_actuator_lands_and_reads_back_exact_changeset(
    repository: tuple[Path, str],
) -> None:
    repo, base_commit = repository
    (repo / "tracked.txt").write_text("candidate\n", encoding="utf-8")
    (repo / "new.txt").write_text("new\n", encoding="utf-8")

    receipt = _actuator().commit(_command(repo, base_commit))

    assert receipt.schema_version == "commit-actuation.v1"
    assert receipt.proposal_sha256 == "a" * 64
    assert receipt.parent_sha == base_commit
    assert receipt.commit_sha == _git(repo, "rev-parse", "HEAD")
    assert receipt.exact_paths == ("new.txt", "tracked.txt")
    assert receipt.actor == "commit-worker:test"
    assert receipt.status == "committed"
    assert receipt.observed_at == NOW.isoformat()
    assert _git(repo, "show", "--format=", "--name-only", "HEAD").splitlines() == [
        "new.txt",
        "tracked.txt",
    ]


def test_actuator_preserves_unrelated_index_and_worktree_state(
    repository: tuple[Path, str],
) -> None:
    repo, base_commit = repository
    (repo / "foreign.txt").write_text("foreign base\n", encoding="utf-8")
    _git(repo, "add", "foreign.txt")
    _git(repo, "commit", "-m", "foreign base")
    base_commit = _git(repo, "rev-parse", "HEAD")

    (repo / "foreign.txt").write_text("foreign staged\n", encoding="utf-8")
    _git(repo, "add", "foreign.txt")
    staged_foreign = _git(repo, "show", ":foreign.txt")
    (repo / "foreign.txt").write_text("foreign working\n", encoding="utf-8")
    (repo / "tracked.txt").write_text("candidate\n", encoding="utf-8")
    (repo / "new.txt").write_text("new\n", encoding="utf-8")

    _actuator().commit(_command(repo, base_commit))

    assert _git(repo, "show", ":foreign.txt") == staged_foreign
    assert (repo / "foreign.txt").read_text(encoding="utf-8") == "foreign working\n"
    assert _git(repo, "show", "--format=", "--name-only", "HEAD").splitlines() == [
        "new.txt",
        "tracked.txt",
    ]


def test_actuator_rejects_stale_head_before_touching_index(
    repository: tuple[Path, str],
) -> None:
    repo, stale_head = repository
    (repo / "concurrent.txt").write_text("concurrent\n", encoding="utf-8")
    _git(repo, "add", "concurrent.txt")
    _git(repo, "commit", "-m", "concurrent")
    observed_head = _git(repo, "rev-parse", "HEAD")
    (repo / "tracked.txt").write_text("candidate\n", encoding="utf-8")
    (repo / "new.txt").write_text("new\n", encoding="utf-8")
    before_status = _git(repo, "status", "--porcelain=v1", "--untracked-files=all")

    with pytest.raises(CommitActuatorBlocked, match="expected HEAD fence failed"):
        _actuator().commit(_command(repo, stale_head))

    assert _git(repo, "rev-parse", "HEAD") == observed_head
    assert _git(repo, "status", "--porcelain=v1", "--untracked-files=all") == before_status
    assert _git(repo, "diff", "--cached", "--name-only") == ""


def test_actuator_rejects_content_drift_and_restores_index(
    repository: tuple[Path, str],
) -> None:
    repo, base_commit = repository
    (repo / "tracked.txt").write_text("candidate\n", encoding="utf-8")
    (repo / "new.txt").write_text("new\n", encoding="utf-8")
    command = _command(repo, base_commit)
    drifted = replace(
        command,
        content_hashes=(
            ContentHash("new.txt", "0" * 64),
            command.content_hashes[1],
        ),
    )
    before_status = _git(repo, "status", "--porcelain=v1", "--untracked-files=all")

    with pytest.raises(CommitActuatorBlocked, match="expected content hash failed"):
        _actuator().commit(drifted)

    assert _git(repo, "rev-parse", "HEAD") == base_commit
    assert _git(repo, "status", "--porcelain=v1", "--untracked-files=all") == before_status
    assert _git(repo, "diff", "--cached", "--name-only") == ""


def test_actuator_rejects_writer_success_without_new_commit(
    repository: tuple[Path, str],
) -> None:
    repo, base_commit = repository
    command = CommitActuation(
        proposal_sha256="a" * 64,
        repository=str(repo),
        expected_head=base_commit,
        exact_paths=("tracked.txt",),
        content_hashes=(ContentHash("tracked.txt", _hash(repo / "tracked.txt")),),
        message="[change-delivery] no-op",
        actor="commit-worker:test",
    )

    with pytest.raises(CommitActuatorBlocked, match="without creating a commit"):
        _actuator().commit(command)


def test_actuator_validates_complete_hash_scope(
    repository: tuple[Path, str],
) -> None:
    repo, base_commit = repository
    (repo / "tracked.txt").write_text("candidate\n", encoding="utf-8")
    (repo / "new.txt").write_text("new\n", encoding="utf-8")
    command = _command(repo, base_commit)

    with pytest.raises(ValueError, match="exactly match"):
        _actuator().commit(
            replace(command, content_hashes=command.content_hashes[:1])
        )
