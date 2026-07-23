"""A test half without its source half must never reach the candidate index.

The deadlock (2026-07-21/22, task assign_b802db4f): a refactor's new test file
went dirty *during* a fire (owned) while its new source module was already dirty
at fire start (foreign, excluded). PHASE-Z staged the test alone, the
audit-test-imports gate rejected the candidate exactly as designed, the whole
commit rolled back, every path stayed dirty — and the next fire rebuilt the
identical doomed candidate. 21 paths stuck >=3 fires; ~13 hours of output lost.

Nothing here was a bug in isolation. Ownership classification is keyed on *when*
a path went dirty; the import gate is keyed on *what* paths mean to each other.
Neither knows the other's key, so a refactor split across the ownership line
produces a candidate that cannot pass, forever.

The invariant these tests pin: PHASE-Z detects the split before staging and
defers the TEST half, never adopting the foreign source (that would be stealing
in-flight bytes). The exception is narrow on purpose — only an untracked test
whose missing half is itself untracked and present on disk. A tracked test that
breaks is a real break and must still block the commit.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.dispatch_supervisor import phase_z


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                          text=True, check=True).stdout


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "src" / "volpred" / "ops").mkdir(parents=True)
    (root / "scripts" / "tests").mkdir(parents=True)
    (root / "tests").mkdir()
    _git_init = ["init", "-q", "-b", "main"]
    subprocess.run(["git", "-C", str(root), *_git_init], check=True)
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")

    # HEAD ships one source module and one test for it — both tracked.
    (root / "src" / "volpred" / "ops" / "__init__.py").write_text("", encoding="utf-8")
    (root / "src" / "volpred" / "ops" / "settled.py").write_text("X = 1\n", encoding="utf-8")
    (root / "tests" / "test_settled.py").write_text(
        "from volpred.ops.settled import X\n", encoding="utf-8"
    )
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    return root


def _head(repo: Path) -> str:
    return _git(repo, "rev-parse", "HEAD").strip()


def test_untracked_test_without_its_source_is_deferred(repo: Path) -> None:
    """The exact deadlock: new test staged, new source left foreign."""
    (repo / "src" / "volpred" / "ops" / "task_signature.py").write_text(
        "def sign(): ...\n", encoding="utf-8"
    )
    (repo / "tests" / "test_task_signature.py").write_text(
        "from volpred.ops.task_signature import sign\n", encoding="utf-8"
    )

    deferred = phase_z._split_pair_deferrals(
        repo, ["tests/test_task_signature.py"], _head(repo), runner=subprocess.run,
    )

    assert deferred == {
        "tests/test_task_signature.py": ["src/volpred/ops/task_signature.py"],
    }


def test_both_halves_staged_together_is_not_a_split(repo: Path) -> None:
    """Deferring is about the *candidate*, not about being untracked."""
    (repo / "src" / "volpred" / "ops" / "task_signature.py").write_text(
        "def sign(): ...\n", encoding="utf-8"
    )
    (repo / "tests" / "test_task_signature.py").write_text(
        "from volpred.ops.task_signature import sign\n", encoding="utf-8"
    )

    deferred = phase_z._split_pair_deferrals(
        repo,
        ["tests/test_task_signature.py", "src/volpred/ops/task_signature.py"],
        _head(repo),
        runner=subprocess.run,
    )

    assert deferred == {}


def test_tracked_test_is_never_deferred(repo: Path) -> None:
    """A test HEAD already ships breaking is a real break — it must still block.

    Deferring it would silently drop regression coverage, which is the failure
    mode the import gate exists to catch.
    """
    (repo / "tests" / "test_settled.py").write_text(
        "from volpred.ops.brand_new import Y\n", encoding="utf-8"
    )
    (repo / "src" / "volpred" / "ops" / "brand_new.py").write_text("Y = 2\n", encoding="utf-8")

    deferred = phase_z._split_pair_deferrals(
        repo, ["tests/test_settled.py"], _head(repo), runner=subprocess.run,
    )

    assert deferred == {}


def test_missing_half_absent_from_disk_is_not_deferred(repo: Path) -> None:
    """No source on disk ⇒ not a split, just a broken test. Let the gate speak."""
    (repo / "tests" / "test_ghost.py").write_text(
        "from volpred.ops.never_written import Z\n", encoding="utf-8"
    )

    deferred = phase_z._split_pair_deferrals(
        repo, ["tests/test_ghost.py"], _head(repo), runner=subprocess.run,
    )

    assert deferred == {}


def test_submodule_import_from_package_resolves(repo: Path) -> None:
    """``from volpred.ops import fire_manifest`` — the package is tracked, the
    submodule is the half that goes missing. Resolving only ``volpred.ops``
    would miss this, which is one of the three paths that actually deadlocked."""
    (repo / "src" / "volpred" / "ops" / "fire_manifest.py").write_text("M = 1\n", encoding="utf-8")
    (repo / "scripts" / "tests" / "test_fire_manifest.py").write_text(
        "from volpred.ops import fire_manifest\n", encoding="utf-8"
    )

    deferred = phase_z._split_pair_deferrals(
        repo, ["scripts/tests/test_fire_manifest.py"], _head(repo), runner=subprocess.run,
    )

    assert deferred == {
        "scripts/tests/test_fire_manifest.py": ["src/volpred/ops/fire_manifest.py"],
    }


def test_script_path_literal_reference_resolves(repo: Path) -> None:
    """``tests/test_worktree_gc.py`` referenced ``scripts/worktree_gc.py`` by path
    literal, not by import — the gate flags it the same way, so must the guard."""
    (repo / "scripts" / "worktree_gc.py").write_text("# gc\n", encoding="utf-8")
    (repo / "tests" / "test_worktree_gc.py").write_text(
        'SCRIPT = "scripts/worktree_gc.py"\n', encoding="utf-8"
    )

    deferred = phase_z._split_pair_deferrals(
        repo, ["tests/test_worktree_gc.py"], _head(repo), runner=subprocess.run,
    )

    assert deferred == {"tests/test_worktree_gc.py": ["scripts/worktree_gc.py"]}


def test_non_test_paths_are_left_alone(repo: Path) -> None:
    """The guard defers test halves only; source paths are never dropped."""
    (repo / "src" / "volpred" / "ops" / "lonely.py").write_text(
        "from volpred.ops.absent_half import Q\n", encoding="utf-8"
    )
    (repo / "src" / "volpred" / "ops" / "absent_half.py").write_text("Q = 1\n", encoding="utf-8")

    deferred = phase_z._split_pair_deferrals(
        repo, ["src/volpred/ops/lonely.py"], _head(repo), runner=subprocess.run,
    )

    assert deferred == {}


def test_real_phase_z_commits_other_output_without_splitting_pair(repo: Path) -> None:
    """Full incident shape: the fire lands, while both refactor halves stay out."""
    source = repo / "src" / "volpred" / "ops" / "task_signature.py"
    source.write_text("def sign(): ...\n", encoding="utf-8")
    pre_fire_dirty = {"src/volpred/ops/task_signature.py"}

    test = repo / "tests" / "test_task_signature.py"
    test.write_text("from volpred.ops.task_signature import sign\n", encoding="utf-8")
    (repo / "fire_output.txt").write_text("useful output\n", encoding="utf-8")
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    hook.chmod(0o755)

    outcome = phase_z.run_phase_z(
        repo_root=repo,
        pre_fire_dirty=pre_fire_dirty,
        runner=subprocess.run,
        test_runner=subprocess.run,
        alert_fn=lambda **_kwargs: {"sent": False},
    )

    assert outcome["committed"] is True
    assert outcome.get("rolled_back") is not True
    committed = set(_git(repo, "show", "--name-only", "--pretty=format:", "HEAD").split())
    assert "fire_output.txt" in committed
    assert "tests/test_task_signature.py" not in committed
    assert "src/volpred/ops/task_signature.py" not in committed
