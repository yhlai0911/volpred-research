"""Single-source task/worktree collision query for dispatch admission.

The enqueue boundary and every upstream candidate selector must ask this module
the same question: does an unmerged registered worktree already carry a commit
whose message names this canonical task id?  The batch API scans the git graph
and worktree registry once, so a starvation menu can validate all candidates
before truncating them to the available slot count.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Iterable
from pathlib import Path

Collision = dict[str, str]
Runner = Callable[..., subprocess.CompletedProcess[str]]


def find_task_dispatch_collisions(
    *,
    repo_root: Path,
    task_ids: Iterable[str],
    target_workdir: Path,
    runner: Runner = subprocess.run,
) -> dict[str, Collision]:
    """Return live unmerged worktree collisions keyed by canonical task id.

    A commit already reachable from canonical ``HEAD`` is historical and safe.
    A matching commit reachable only from another registered worktree branch is
    live ownership and must prevent a second agent dispatch.
    """

    normalized_ids = tuple(
        dict.fromkeys(str(task_id or "").strip() for task_id in task_ids)
    )
    normalized_ids = tuple(task_id for task_id in normalized_ids if task_id)
    if not normalized_ids:
        return {}

    def git(*args: str) -> subprocess.CompletedProcess[str]:
        try:
            return runner(
                ["git", "-C", str(repo_root), *args],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(
                f"git {' '.join(args[:2])} failed: {exc}"
            ) from exc

    matches = git(
        "log",
        "--all",
        "--fixed-strings",
        *(f"--grep={task_id}" for task_id in normalized_ids),
        "--format=%H%x1f%B%x1e",
    )
    if matches.returncode != 0:
        raise RuntimeError(
            f"git log collision scan failed rc={matches.returncode}: "
            f"{(matches.stderr or '').strip()[-240:]}"
        )

    matching_shas: dict[str, list[str]] = {
        task_id: [] for task_id in normalized_ids
    }
    for raw_record in (matches.stdout or "").split("\x1e"):
        record = raw_record.strip("\n")
        if "\x1f" not in record:
            continue
        sha, message = record.split("\x1f", 1)
        sha = sha.strip()
        if not sha:
            continue
        for task_id in normalized_ids:
            if task_id in message:
                matching_shas[task_id].append(sha)
    if not any(matching_shas.values()):
        return {}

    worktrees = git("worktree", "list", "--porcelain")
    if worktrees.returncode != 0:
        raise RuntimeError(
            f"git worktree collision scan failed rc={worktrees.returncode}: "
            f"{(worktrees.stderr or '').strip()[-240:]}"
        )

    records: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in [*(worktrees.stdout or "").splitlines(), ""]:
        if not line:
            if current:
                records.append(current)
                current = {}
            continue
        key, _, value = line.partition(" ")
        if key in {"worktree", "branch"} and value:
            current[key] = (
                value.removeprefix("refs/heads/")
                if key == "branch"
                else value
            )

    target = target_workdir.resolve()
    head_ancestry: dict[str, bool] = {}
    branch_ancestry: dict[tuple[str, str], bool] = {}
    collisions: dict[str, Collision] = {}
    for task_id in normalized_ids:
        for record in records:
            raw_path = record.get("worktree")
            branch = record.get("branch")
            if (
                not raw_path
                or not branch
                or Path(raw_path).resolve() == target
            ):
                continue
            for sha in matching_shas[task_id]:
                if sha not in head_ancestry:
                    merged = git("merge-base", "--is-ancestor", sha, "HEAD")
                    if merged.returncode not in {0, 1}:
                        raise RuntimeError(
                            "cannot determine whether task commit "
                            f"{sha[:12]} is merged into HEAD"
                        )
                    head_ancestry[sha] = merged.returncode == 0
                if head_ancestry[sha]:
                    continue
                ancestry_key = (sha, branch)
                if ancestry_key not in branch_ancestry:
                    on_branch = git(
                        "merge-base",
                        "--is-ancestor",
                        sha,
                        branch,
                    )
                    if on_branch.returncode not in {0, 1}:
                        raise RuntimeError(
                            f"cannot inspect task commit {sha[:12]} "
                            f"on branch {branch}"
                        )
                    branch_ancestry[ancestry_key] = (
                        on_branch.returncode == 0
                    )
                if branch_ancestry[ancestry_key]:
                    collisions[task_id] = {
                        "worktree": raw_path,
                        "branch": branch,
                        "commit": sha,
                    }
                    break
            if task_id in collisions:
                break
    return collisions


def find_task_dispatch_collision(
    *,
    repo_root: Path,
    task_id: str,
    target_workdir: Path,
    runner: Runner = subprocess.run,
) -> Collision | None:
    """Single-task compatibility wrapper used by ``enqueue-agent``."""

    return find_task_dispatch_collisions(
        repo_root=repo_root,
        task_ids=(task_id,),
        target_workdir=target_workdir,
        runner=runner,
    ).get(str(task_id or "").strip())
