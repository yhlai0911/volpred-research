from __future__ import annotations

import subprocess
from pathlib import Path

from volpred.ops.task_dispatch_collision import (
    find_task_dispatch_collision,
    find_task_dispatch_collisions,
)


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def test_batch_collision_query_matches_single_enqueue_gate(tmp_path: Path) -> None:
    canonical = tmp_path / "canonical"
    canonical.mkdir()
    _git(canonical, "init", "-b", "main")
    _git(canonical, "config", "user.email", "test@example.com")
    _git(canonical, "config", "user.name", "Test")
    (canonical / "seed.txt").write_text("seed", encoding="utf-8")
    _git(canonical, "add", "seed.txt")
    _git(canonical, "commit", "-m", "seed")

    existing = tmp_path / "existing"
    target = tmp_path / "target"
    _git(canonical, "worktree", "add", "-b", "existing-task", str(existing))
    (existing / "result.txt").write_text("result", encoding="utf-8")
    _git(existing, "add", "result.txt")
    _git(existing, "commit", "-m", "[agent] implement K1730 and K1731")
    _git(canonical, "worktree", "add", "-b", "target-task", str(target), "main")

    collisions = find_task_dispatch_collisions(
        repo_root=canonical,
        task_ids=("K1730", "K1731", "K1735"),
        target_workdir=target,
    )

    assert sorted(collisions) == ["K1730", "K1731"]
    assert collisions["K1730"]["branch"] == "existing-task"
    assert collisions["K1731"]["worktree"] == str(existing)
    assert find_task_dispatch_collision(
        repo_root=canonical,
        task_id="K1730",
        target_workdir=target,
    ) == collisions["K1730"]

    _git(canonical, "merge", "--no-ff", "existing-task", "-m", "merge tasks")
    assert (
        find_task_dispatch_collisions(
            repo_root=canonical,
            task_ids=("K1730", "K1731"),
            target_workdir=target,
        )
        == {}
    )
