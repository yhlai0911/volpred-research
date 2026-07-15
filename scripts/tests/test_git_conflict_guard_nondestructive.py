"""The conflict watchdog preserves evidence and never overwrites author bytes."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from scripts import git_conflict_guard as guard


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(args), cwd=repo, capture_output=True, text=True, check=True)


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(repo, "git", "init", "-b", "main", "-q")
    _run(repo, "git", "config", "user.name", "Guard Test")
    _run(repo, "git", "config", "user.email", "guard@example.invalid")
    (repo / "state.json").write_text('{"ok":true}\n')
    (repo / "foreign.txt").write_text("base\n")
    _run(repo, "git", "add", ".")
    _run(repo, "git", "commit", "-qm", "seed")
    return repo


def _git_dir(repo: Path) -> Path:
    return Path(_run(repo, "git", "rev-parse", "--absolute-git-dir").stdout.strip())


def test_marker_state_is_reported_without_reset_or_checkout(
    monkeypatch, tmp_path: Path
) -> None:
    repo = _repo(tmp_path)
    marker_bytes = b"<<<<<<< Updated upstream\nours\n=======\ntheirs\n>>>>>>> Stashed changes\n"
    (repo / "state.json").write_bytes(marker_bytes)
    (repo / "foreign.txt").write_text("foreign staged\n")
    _run(repo, "git", "add", "foreign.txt")
    staged = _run(repo, "git", "show", ":foreign.txt").stdout
    auto_merge = _git_dir(repo) / "AUTO_MERGE"
    auto_merge.write_text(_run(repo, "git", "write-tree").stdout.strip() + "\n")

    monkeypatch.setattr(guard, "ROOT", repo)
    monkeypatch.setattr(guard, "_send_alert", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(sys, "argv", ["git_conflict_guard.py", "--quiet"])
    assert guard.main() == 0

    assert (repo / "state.json").read_bytes() == marker_bytes
    assert _run(repo, "git", "show", ":foreign.txt").stdout == staged
    assert auto_merge.exists(), "ambiguous evidence must be preserved"


def test_empty_orphan_can_be_removed_without_touching_foreign_index(
    monkeypatch, tmp_path: Path
) -> None:
    repo = _repo(tmp_path)
    (repo / "foreign.txt").write_text("foreign staged\n")
    _run(repo, "git", "add", "foreign.txt")
    staged = _run(repo, "git", "show", ":foreign.txt").stdout
    auto_merge = _git_dir(repo) / "AUTO_MERGE"
    auto_merge.write_text(_run(repo, "git", "write-tree").stdout.strip() + "\n")

    monkeypatch.setattr(guard, "ROOT", repo)
    monkeypatch.setattr(guard, "_send_alert", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(sys, "argv", ["git_conflict_guard.py", "--quiet"])
    assert guard.main() == 0

    assert not auto_merge.exists()
    assert _run(repo, "git", "show", ":foreign.txt").stdout == staged
