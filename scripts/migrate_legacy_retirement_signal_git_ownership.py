#!/usr/bin/env python3
"""Retire legacy-retirement runtime signals from Git without deleting them.

The migration is deliberately restartable.  It acquires the repository's one
Git-writer lease first, then the signal batch lock, and delegates the deletion
commit to ``git_writer_lock.py untrack-preserve``.  This ordering prevents a
materializer/observer refresh from racing the byte-and-mode identity checks.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

from volpred.ops.git_writer_lock import (
    DEFAULT_TIMEOUT_S,
    git_writer_lock,
    require_canonical_main_checkout,
)
from volpred.ops.legacy_retirement import retirement_signal_batch_lock

ROOT = Path(__file__).resolve().parents[1]
SIGNAL_DIRECTORY = Path("storage/ops/legacy_retirement_signals")
GIT_WRITER_CLI = ROOT / "scripts" / "git_writer_lock.py"


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "--literal-pathspecs", *args],
        cwd=repo,
        capture_output=True,
        check=False,
    )


def _head(repo: Path) -> str:
    resolved = _git(repo, "rev-parse", "--verify", "HEAD^{commit}")
    if resolved.returncode != 0:
        raise RuntimeError("cannot resolve canonical HEAD")
    return resolved.stdout.decode("ascii").strip()


def _tracked_signal_paths(repo: Path) -> list[str]:
    listed = _git(repo, "ls-files", "-z", "--", SIGNAL_DIRECTORY.as_posix())
    if listed.returncode != 0:
        raise RuntimeError("cannot enumerate tracked retirement signal paths")
    return sorted(
        raw.decode("utf-8", errors="surrogateescape")
        for raw in listed.stdout.split(b"\0")
        if raw
    )


def _identity(target: Path) -> tuple[str, int, int]:
    if target.is_symlink():
        raise RuntimeError(f"runtime signal path is a symlink: {target}")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(target, flags)
    except OSError as exc:
        raise RuntimeError(f"cannot open runtime signal: {target}") from exc
    try:
        file_stat = os.fstat(descriptor)
        if not stat.S_ISREG(file_stat.st_mode):
            raise RuntimeError(
                f"runtime signal is not a regular file: {target}"
            )
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            payload = handle.read()
        return (
            hashlib.sha256(payload).hexdigest(),
            len(payload),
            stat.S_IMODE(file_stat.st_mode),
        )
    finally:
        os.close(descriptor)


def _identities(repo: Path, paths: list[str]) -> dict[str, tuple[str, int, int]]:
    return {path: _identity(repo / path) for path in paths}


def _assert_ignored(repo: Path, paths: list[str]) -> None:
    for path in paths:
        ignored = subprocess.run(
            ["git", "check-ignore", "--no-index", "-q", "--", path],
            cwd=repo,
            check=False,
        )
        if ignored.returncode != 0:
            raise RuntimeError(
                f"runtime signal is not covered by Git ignore policy: {path}"
            )


def migrate(
    *,
    repo: Path,
    actor: str,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> dict[str, object]:
    repo = Path(repo).expanduser().resolve()
    with git_writer_lock(repo, actor=actor, timeout_s=timeout_s) as lease:
        require_canonical_main_checkout(repo)
        with retirement_signal_batch_lock(repo):
            head_before = _head(repo)
            tracked_before = _tracked_signal_paths(repo)
            if not tracked_before:
                live_paths = sorted(
                    target.relative_to(repo).as_posix()
                    for target in (repo / SIGNAL_DIRECTORY).iterdir()
                    if target.is_file() and not target.is_symlink()
                )
                _assert_ignored(repo, live_paths)
                return {
                    "schema_version": (
                        "legacy-retirement-signal-git-migration.v1"
                    ),
                    "status": "already_migrated",
                    "head_before": head_before,
                    "head_after": head_before,
                    "tracked_before": [],
                    "tracked_after": [],
                    "live_identities": _identities(repo, live_paths),
                }

            before = _identities(repo, tracked_before)
            command = [
                sys.executable,
                str(GIT_WRITER_CLI),
                "untrack-preserve",
                "--repo",
                str(repo),
                "--actor",
                actor,
                "--timeout",
                str(timeout_s),
                "--expected-head",
                head_before,
                "--message",
                "[codex] retire legacy retirement runtime signals from Git",
                "--",
                *tracked_before,
            ]
            committed = subprocess.run(
                command,
                cwd=repo,
                env=lease.child_env(),
                pass_fds=lease.child_pass_fds(),
                capture_output=True,
                text=True,
                check=False,
            )
            if committed.returncode != 0:
                raise RuntimeError(
                    "Git ownership migration failed: "
                    f"{committed.stderr.strip() or committed.stdout.strip()}"
                )

            tracked_after = _tracked_signal_paths(repo)
            after = _identities(repo, tracked_before)
            if tracked_after:
                raise RuntimeError(
                    "Git ownership migration left tracked signal paths"
                )
            if after != before:
                raise RuntimeError(
                    "Git ownership migration changed runtime bytes or modes"
                )
            _assert_ignored(repo, tracked_before)
            return {
                "schema_version": (
                    "legacy-retirement-signal-git-migration.v1"
                ),
                "status": "migrated",
                "head_before": head_before,
                "head_after": _head(repo),
                "tracked_before": tracked_before,
                "tracked_after": tracked_after,
                "live_identities": after,
            }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        report = migrate(
            repo=args.repo,
            actor=args.actor,
            timeout_s=args.timeout,
        )
    except (RuntimeError, ValueError) as exc:
        print(f"migration blocked: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
