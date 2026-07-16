"""The dirty-guard must distinguish uncommitted machine output from a live writer.

Regression suite for the latch described in ``docs/fix_56ddf72b_dirty_guard.md``:
a declared output that was dirty at run start was excluded from the write set AND
from the commit set, so the only job that would ever have committed it was the one
refusing to touch it. ``frontend-v2-fix/data/strategy_metrics.json`` sat that way
for 11 days without a commit and without an alert.

Every repo here is a throwaway built by ``_init_repo``; nothing touches the real
checkout (feedback_hermetic_git_in_tests).
"""
from __future__ import annotations

import fcntl
import json
import subprocess
from pathlib import Path

import pytest

from volpred.ops.scheduled_writer_commit import (
    adoptable_churn,
    dirty_paths_before_write,
    probe_dirty_outputs,
    writable_output_paths,
)

LABEL = "test_writer"


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    )


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "storage").mkdir(parents=True)
    _git(repo.parent, "init", "-b", "main", repo.name)
    _git(repo, "config", "user.email", "dirty-guard-test@example.com")
    _git(repo, "config", "user.name", "Dirty Guard Test")
    out = repo / "storage" / "feed.json"
    out.write_text(json.dumps([{"id": "committed"}]), encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "seed")
    return repo


def _make_dirty(repo: Path, rel: str = "storage/feed.json") -> str:
    (repo / rel).write_text(json.dumps([{"id": "written-but-never-committed"}]),
                            encoding="utf-8")
    return rel


def _classify(repo: Path, rels: list[str]) -> tuple[frozenset[str], frozenset[str]]:
    dirty, unprobed = probe_dirty_outputs(repo, rels, label=LABEL)
    return adoptable_churn(repo, dirty, unprobed, label=LABEL)


# ── the bug: uncommitted machine output is not a conflict ────────────────────


def test_uncommitted_machine_output_is_churn_not_conflict(tmp_path: Path) -> None:
    """A sibling daemon's uncommitted write must not read as someone's live edit."""
    repo = _init_repo(tmp_path)
    rel = _make_dirty(repo)

    churn, conflict = _classify(repo, [rel])

    assert churn == {rel}
    assert conflict == frozenset()


def test_churn_stays_in_the_write_set(tmp_path: Path) -> None:
    """The whole point: the run that would clean the path is allowed to write it."""
    repo = _init_repo(tmp_path)
    rel = _make_dirty(repo)

    _churn, conflict = _classify(repo, [rel])

    assert writable_output_paths(repo, [rel], dirty_before=conflict, label=LABEL) == [rel]


def test_old_behaviour_would_have_excluded_it(tmp_path: Path) -> None:
    """Pin the contrast, so a revert to "dirty means excluded" fails here.

    ``dirty_paths_before_write`` is the pre-2026-07-16 answer and still the right
    default for callers that never establish authorship — it must keep excluding.
    """
    repo = _init_repo(tmp_path)
    rel = _make_dirty(repo)

    conservative = dirty_paths_before_write(repo, [rel], label=LABEL)

    assert conservative == {rel}
    assert writable_output_paths(repo, [rel], dirty_before=conservative, label=LABEL) == []


# ── the guard must still hold for the thing it was built for ────────────────


def test_live_writer_holds_the_guard(tmp_path: Path) -> None:
    """Someone is mid-write right now → conflict, not churn.

    flock is per open-file-description, so an exclusive lock on one fd blocks the
    classifier's LOCK_SH|LOCK_NB on another even inside this process.
    """
    repo = _init_repo(tmp_path)
    rel = _make_dirty(repo)

    with open(repo / rel, "r+", encoding="utf-8") as holder:
        fcntl.flock(holder.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            churn, conflict = _classify(repo, [rel])
        finally:
            fcntl.flock(holder.fileno(), fcntl.LOCK_UN)

    assert conflict == {rel}, "a held lock must block adoption"
    assert churn == frozenset()
    assert writable_output_paths(repo, [rel], dirty_before=conflict, label=LABEL) == []


def test_truncated_content_is_never_adopted(tmp_path: Path) -> None:
    """Committing a half-written control file is how a truncated queue became history."""
    repo = _init_repo(tmp_path)
    rel = "storage/feed.json"
    (repo / rel).write_text('[{"id": "cut-off"', encoding="utf-8")  # writer killed mid-write

    churn, conflict = _classify(repo, [rel])

    assert conflict == {rel}
    assert churn == frozenset()


def test_unresolved_git_probe_fails_closed(tmp_path: Path) -> None:
    """Git could not answer → the absence of a fact must not become permission."""
    repo = _init_repo(tmp_path)
    rel = _make_dirty(repo)
    not_a_repo = tmp_path / "bare"
    (not_a_repo / "storage").mkdir(parents=True)
    (not_a_repo / rel).write_text("{}", encoding="utf-8")

    dirty, unprobed = probe_dirty_outputs(not_a_repo, [rel], label=LABEL)
    churn, conflict = adoptable_churn(not_a_repo, dirty, unprobed, label=LABEL)

    assert unprobed == {rel}, "git status outside a repo must report as unprobed"
    assert conflict == {rel}, "unprobed must never be adopted, however well it parses"
    assert churn == frozenset()


# ── the latch itself ────────────────────────────────────────────────────────


def test_a_deletion_is_adoptable(tmp_path: Path) -> None:
    """Machine state garbage-collects itself; staging the deletion is the point."""
    repo = _init_repo(tmp_path)
    rel = "storage/feed.json"
    (repo / rel).unlink()

    churn, conflict = _classify(repo, [rel])

    assert churn == {rel}
    assert conflict == frozenset()


def test_mixed_set_holds_only_on_the_real_conflict(tmp_path: Path) -> None:
    """One locked path must not condemn the clean-but-uncommitted ones beside it.

    The module was always documented per-path ("a pre-existing edit to one FRED
    series must not prevent the job from committing the other clean series"); it
    was daily_update that collapsed it to all-or-nothing.
    """
    repo = _init_repo(tmp_path)
    locked_rel = "storage/metrics.json"
    (repo / locked_rel).write_text("{}", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "add metrics")
    # Dirty both only after the seed commit, or `git add -A` above adopts them.
    churn_rel = _make_dirty(repo, "storage/feed.json")
    (repo / locked_rel).write_text('{"v": 2}', encoding="utf-8")

    with open(repo / locked_rel, "r+", encoding="utf-8") as holder:
        fcntl.flock(holder.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            churn, conflict = _classify(repo, [churn_rel, locked_rel])
        finally:
            fcntl.flock(holder.fileno(), fcntl.LOCK_UN)

    assert churn == {churn_rel}
    assert conflict == {locked_rel}


def test_latch_releases_after_one_run(tmp_path: Path) -> None:
    """End-to-end: adopt → commit → next run starts clean.

    Under the old rule this file could never reach a commit: excluded from the
    write set for being dirty, excluded from the commit set by the same flag, and
    nothing else in the system commits it.
    """
    from volpred.ops.scheduled_writer_commit import commit_owned_outputs

    repo = _init_repo(tmp_path)
    rel = _make_dirty(repo)

    _churn, conflict = _classify(repo, [rel])
    staged = commit_owned_outputs(
        repo, [rel], dirty_before=conflict, message="adopt churn", label=LABEL
    )

    assert staged == [rel], "the churn path must actually reach a commit"
    assert probe_dirty_outputs(repo, [rel], label=LABEL) == (frozenset(), frozenset()), (
        "after the run commits, the next run must see a clean tree — this is the latch releasing"
    )
