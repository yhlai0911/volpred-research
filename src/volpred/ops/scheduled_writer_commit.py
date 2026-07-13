"""Ownership-safe commits for unattended writers of tracked repository files.

Scheduled jobs have no interactive author to return and commit their output.  A
plain ``git add -A`` is nevertheless unsafe in the shared checkout: it can adopt
another session's work.  This module gives those jobs one narrow contract:

1. snapshot whether each declared output path was dirty *before* the write;
2. exclude dirty paths from the producer's write set;
3. after a successful write, commit only paths that were clean at the snapshot;
3. fail closed when Git cannot establish ownership.

Callers remain responsible for declaring their complete output population.  The
ratchet for that declaration lives in
``scripts/tests/test_scheduled_writer_commit_policy.py``.
"""
from __future__ import annotations

import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path


def _relative_paths(repo_root: Path, paths: Iterable[str | Path]) -> list[str]:
    root = repo_root.resolve()
    relative: list[str] = []
    for raw in paths:
        path = Path(raw)
        absolute = path.resolve() if path.is_absolute() else (root / path).resolve()
        try:
            rel = absolute.relative_to(root).as_posix()
        except ValueError as exc:
            raise ValueError(f"scheduled output escapes repository: {raw}") from exc
        if rel not in relative:
            relative.append(rel)
    return relative


def dirty_paths_before_write(
    repo_root: Path,
    paths: Iterable[str | Path],
    *,
    label: str,
) -> frozenset[str]:
    """Return declared output paths that are already dirty, failing closed.

    One path per Git probe keeps the ownership decision exact: a pre-existing
    edit to one FRED series must not prevent the job from committing the other
    clean series it refreshed.  ``git status`` covers both index and worktree;
    ``git diff --quiet`` alone would miss a pre-staged edit.
    """
    rels = _relative_paths(repo_root, paths)
    dirty: set[str] = set()
    for rel in rels:
        try:
            proc = subprocess.run(
                [
                    "git",
                    "status",
                    "--porcelain=v1",
                    "--untracked-files=all",
                    "--",
                    rel,
                ],
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            print(
                f"[{label}] WARN: git ownership probe failed for {rel} ({exc}); "
                "self-commit will skip this path",
                file=sys.stderr,
            )
            dirty.add(rel)
            continue
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()[:200]
            print(
                f"[{label}] WARN: git ownership probe rc={proc.returncode} for "
                f"{rel} ({detail}); self-commit will skip this path",
                file=sys.stderr,
            )
            dirty.add(rel)
        elif proc.stdout.strip():
            dirty.add(rel)
    return frozenset(dirty)


def writable_output_paths(
    repo_root: Path,
    paths: Iterable[str | Path],
    *,
    dirty_before: Iterable[str],
    label: str,
) -> list[str]:
    """Return relative output paths the scheduled writer may safely mutate.

    This is the actual pre-write guard, not merely a commit filter.  Callers
    must derive their write set from this return value.  A path that was staged,
    unstaged, untracked, deleted, or could not be probed is excluded so the
    unattended writer cannot overwrite another author's work before later
    deciding not to commit it.
    """
    rels = _relative_paths(repo_root, paths)
    blocked = set(dirty_before)
    unsafe = [rel for rel in rels if rel in blocked]
    if unsafe:
        print(
            f"[{label}] WARN: refusing to overwrite output(s) already dirty "
            f"before this run: {unsafe}",
            file=sys.stderr,
        )
    return [rel for rel in rels if rel not in blocked]


def commit_owned_outputs(
    repo_root: Path,
    paths: Iterable[str | Path],
    *,
    dirty_before: Iterable[str],
    message: str,
    label: str,
) -> list[str]:
    """Path-scope commit outputs that were clean before this writer ran.

    Existing dirty paths are never staged.  Unrelated staged or unstaged work is
    untouched because both ``git add`` and ``git commit --only`` receive literal
    pathspecs.  Commit failure is observable but non-fatal to the producer: the
    output remains on disk for the normal foreign-file alert/recovery path.
    """
    rels = _relative_paths(repo_root, paths)
    blocked = set(dirty_before)
    safe = [rel for rel in rels if rel not in blocked]
    skipped = [rel for rel in rels if rel in blocked]
    if skipped:
        print(
            f"[{label}] WARN: not staging output owned by an earlier author: "
            f"{skipped}",
            file=sys.stderr,
        )
    if not safe:
        return []

    try:
        subprocess.run(
            ["git", "add", "-A", "--", *safe],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        staged_proc = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--", *safe],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=20,
            check=True,
        )
        staged = [line for line in staged_proc.stdout.splitlines() if line]
        if not staged:
            return []
        subprocess.run(
            ["git", "commit", "--only", "-m", message, "--", *staged],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
    except (OSError, subprocess.TimeoutExpired, subprocess.CalledProcessError) as exc:
        detail = ""
        if isinstance(exc, subprocess.CalledProcessError):
            detail = (exc.stderr or exc.stdout or "").strip()[-300:]
        print(
            f"[{label}] WARN: path-scoped self-commit failed ({exc})"
            f"{': ' + detail if detail else ''}; outputs left in working tree: {safe}",
            file=sys.stderr,
        )
        return []

    print(f"[{label}] committed {len(staged)} owned output path(s): {staged}")
    return staged
