"""Realigning `main` after history surgery must be incapable of losing work.

The helper exists because four hand-run `git update-ref` attempts on
2026-08-04 were silently rejected by a reference-transaction hook (a terminal
holds no writer lease), while the supervisor kept committing onto the stale
chain. These lock the two properties that make the automated version safe:

* the rewrite base is found by TREE equality, not reachability or patch-id --
  both of which misread a rewrite and would re-apply work the target already
  has;
* the ref is never moved unless the replayed tree is byte-identical to the tree
  `main` has now.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import align_local_main as align  # noqa: E402


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()


@pytest.fixture()
def repo(tmp_path: Path, monkeypatch) -> Path:
    r = tmp_path / "r"
    r.mkdir()
    _git(r, "init", "-b", "main")
    _git(r, "config", "user.email", "t@example.com")
    _git(r, "config", "user.name", "T")
    monkeypatch.setattr(align, "REPO_ROOT", r)
    return r


def _commit(repo: Path, name: str, body: str) -> str:
    (repo / name).write_text(body, encoding="utf-8")
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", f"add {name}")
    return _git(repo, "rev-parse", "HEAD")


def test_rewrite_base_is_found_by_tree_not_by_ancestry(repo: Path) -> None:
    """The target shares no ancestry with main, yet must still be recognised."""
    _commit(repo, "a.txt", "a")
    base = _commit(repo, "b.txt", "b")
    new_work = _commit(repo, "c.txt", "c")

    # Build an unrelated chain whose head has the SAME tree as `base` --
    # exactly what a content-preserving history rewrite produces.
    _git(repo, "checkout", "-q", "--orphan", "rewritten")
    _git(repo, "reset", "-q", "--hard")
    (repo / "a.txt").write_text("a", encoding="utf-8")
    (repo / "b.txt").write_text("b", encoding="utf-8")
    _git(repo, "add", "a.txt", "b.txt")
    _git(repo, "commit", "-q", "-m", "rewritten base")
    target = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "main")

    assert _git(repo, "rev-parse", f"{target}^{{tree}}") == _git(
        repo, "rev-parse", f"{base}^{{tree}}"
    )

    plan = align.plan(target)

    assert plan["rewrite_base"] == base
    # Only the genuinely new commit is carried over; the pre-rewrite ones are
    # already represented in the target and must not be replayed.
    assert plan["local_only"] == [new_work]


def test_refuses_a_target_that_is_not_a_content_preserving_rewrite(
    repo: Path,
) -> None:
    """No commit on main has the target's tree -> realigning could drop work."""
    _commit(repo, "a.txt", "a")
    _git(repo, "checkout", "-q", "--orphan", "other")
    _git(repo, "reset", "-q", "--hard")
    (repo / "z.txt").write_text("totally different", encoding="utf-8")
    _git(repo, "add", "z.txt")
    _git(repo, "commit", "-q", "-m", "unrelated")
    target = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "main")

    with pytest.raises(RuntimeError, match="not a content-preserving rewrite"):
        align.plan(target)


def test_replay_refuses_to_move_the_ref_when_the_tree_would_change(
    repo: Path,
) -> None:
    """The one invariant that makes work-loss structurally impossible."""
    _commit(repo, "a.txt", "a")
    target = _git(repo, "rev-parse", "HEAD")
    new_work = _commit(repo, "b.txt", "b")

    with pytest.raises(RuntimeError, match="does not match the current main tree"):
        align._replay(target, [new_work], expected_tree="0" * 40)


def test_already_aligned_is_a_noop(repo: Path) -> None:
    head = _commit(repo, "a.txt", "a")

    result = align.align(head, actor="test", apply=False)

    assert result["action"] == "noop_already_aligned"
    assert result["applied"] is False


def test_plan_never_writes_anything(repo: Path) -> None:
    _commit(repo, "a.txt", "a")
    base = _commit(repo, "b.txt", "b")
    _commit(repo, "c.txt", "c")
    before = _git(repo, "rev-parse", "refs/heads/main")

    align.plan(base)

    assert _git(repo, "rev-parse", "refs/heads/main") == before
