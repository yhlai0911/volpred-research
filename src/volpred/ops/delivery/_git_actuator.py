"""Private adapter from Change Delivery to the canonical Git writer.

This module does not grant landing authority.  It only translates an already
authorized, materialized exact-path commit request into the existing
``scripts/git_writer_lock.py commit`` transaction and verifies the resulting
commit object.  WorkLease and Primary Authority fencing remain the responsibility
of the later Change Delivery landing service.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
from pathlib import Path
import subprocess
import sys
from typing import Callable

from . import (
    ContentHash,
    _GIT_OBJECT_ID,
    _SHA256,
    _normalize_exact_path,
    _required_text,
)


_RECEIPT_SCHEMA = "commit-actuation.v1"
_DEFAULT_WRITER_CLI = (
    Path(__file__).resolve().parents[4] / "scripts" / "git_writer_lock.py"
)


@dataclass(frozen=True)
class CommitActuation:
    proposal_sha256: str
    repository: str
    expected_head: str
    exact_paths: tuple[str, ...]
    content_hashes: tuple[ContentHash, ...]
    message: str
    actor: str


@dataclass(frozen=True)
class CommitActuationReceipt:
    schema_version: str
    proposal_sha256: str
    commit_sha: str
    parent_sha: str
    exact_paths: tuple[str, ...]
    actor: str
    status: str
    observed_at: str


class CommitActuatorError(RuntimeError):
    """The Git writer did not produce a verified exact-path commit."""


class CommitActuatorBusy(CommitActuatorError):
    """The canonical Git writer lease was busy."""


class CommitActuatorBlocked(CommitActuatorError):
    """The canonical writer rejected the request before a verified commit."""


class GitCommitActuator:
    """Invoke and read back the existing exact-path Git writer transaction."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime],
        writer_cli: Path = _DEFAULT_WRITER_CLI,
        python_executable: str = sys.executable,
        timeout_s: float = 120.0,
    ) -> None:
        self._clock = clock
        self._writer_cli = writer_cli.resolve()
        self._python_executable = python_executable
        self._timeout_s = timeout_s

    def commit(self, command: CommitActuation) -> CommitActuationReceipt:
        normalized = _normalize_command(command)
        repository = Path(normalized.repository)
        if not self._writer_cli.is_file():
            raise CommitActuatorBlocked(
                f"canonical Git writer CLI is unavailable: {self._writer_cli}"
            )

        argv = [
            self._python_executable,
            str(self._writer_cli),
            "commit",
            "--repo",
            str(repository),
            "--actor",
            normalized.actor,
            "--expected-head",
            normalized.expected_head,
            "--message",
            normalized.message,
        ]
        for item in normalized.content_hashes:
            argv.extend(
                ["--expected-content-hash", f"{item.path}={item.sha256}"]
            )
        argv.extend(["--", *normalized.exact_paths])

        try:
            proc = subprocess.run(
                argv,
                cwd=repository,
                capture_output=True,
                text=True,
                check=False,
                timeout=self._timeout_s,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise CommitActuatorBlocked(
                f"canonical Git writer could not complete: {exc}"
            ) from exc
        detail = (proc.stderr or proc.stdout or "").strip()[-600:]
        if proc.returncode == 75:
            raise CommitActuatorBusy(detail or "canonical Git writer is busy")
        if proc.returncode != 0:
            raise CommitActuatorBlocked(
                detail or f"canonical Git writer exited {proc.returncode}"
            )

        commit_sha = _git_text(repository, "rev-parse", "--verify", "HEAD^{commit}")
        if commit_sha == normalized.expected_head:
            raise CommitActuatorBlocked(
                "canonical Git writer returned success without creating a commit"
            )
        parent_sha = _git_text(
            repository,
            "rev-parse",
            "--verify",
            f"{commit_sha}^{{commit}}^",
        )
        if parent_sha != normalized.expected_head:
            raise CommitActuatorBlocked(
                "canonical Git writer produced a commit with an unexpected parent"
            )

        changed_paths = tuple(
            sorted(
                _git_text(
                    repository,
                    "-c",
                    "core.quotepath=false",
                    "diff-tree",
                    "--no-commit-id",
                    "--name-only",
                    "-r",
                    commit_sha,
                ).splitlines()
            )
        )
        if changed_paths != normalized.exact_paths:
            raise CommitActuatorBlocked(
                "canonical Git writer commit paths differ from the ChangeSet"
            )
        for item in normalized.content_hashes:
            blob = _git_bytes(repository, "show", f"{commit_sha}:{item.path}")
            observed = hashlib.sha256(blob).hexdigest()
            if observed != item.sha256:
                raise CommitActuatorBlocked(
                    f"committed content hash differs from the ChangeSet: {item.path}"
                )

        observed_at = self._clock()
        if observed_at.tzinfo is None:
            raise CommitActuatorBlocked(
                "commit actuator clock must return a timezone-aware value"
            )
        return CommitActuationReceipt(
            schema_version=_RECEIPT_SCHEMA,
            proposal_sha256=normalized.proposal_sha256,
            commit_sha=commit_sha,
            parent_sha=parent_sha,
            exact_paths=normalized.exact_paths,
            actor=normalized.actor,
            status="committed",
            observed_at=observed_at.isoformat(),
        )


def _normalize_command(command: CommitActuation) -> CommitActuation:
    repository = Path(command.repository).expanduser()
    if not repository.is_absolute():
        raise ValueError("commit actuator repository must be an absolute path")
    repository = repository.resolve()
    if not repository.is_dir():
        raise ValueError("commit actuator repository does not exist")
    if _GIT_OBJECT_ID.fullmatch(command.expected_head) is None:
        raise ValueError("expected_head must be a lowercase Git object id")
    if _SHA256.fullmatch(command.proposal_sha256) is None:
        raise ValueError("proposal_sha256 must be 64 lowercase hexadecimal characters")

    paths = tuple(sorted(_normalize_exact_path(path) for path in command.exact_paths))
    if not paths or len(paths) != len(set(paths)):
        raise ValueError("commit actuator exact paths must be non-empty and unique")
    hashes: dict[str, ContentHash] = {}
    for item in command.content_hashes:
        path = _normalize_exact_path(item.path)
        if path in hashes:
            raise ValueError(f"duplicate content hash path: {path}")
        if _SHA256.fullmatch(item.sha256) is None:
            raise ValueError(f"invalid content hash for {path}")
        hashes[path] = ContentHash(path=path, sha256=item.sha256)
    if set(hashes) != set(paths):
        raise ValueError("content hashes must exactly match commit actuator paths")

    return CommitActuation(
        proposal_sha256=command.proposal_sha256,
        repository=str(repository),
        expected_head=command.expected_head,
        exact_paths=paths,
        content_hashes=tuple(hashes[path] for path in paths),
        message=_required_text(command.message, field="commit message"),
        actor=_required_text(command.actor, field="commit actor"),
    )


def _git_text(repository: Path, *args: str) -> str:
    return _git_bytes(repository, *args).decode(
        "utf-8",
        errors="surrogateescape",
    ).strip()


def _git_bytes(repository: Path, *args: str) -> bytes:
    try:
        proc = subprocess.run(
            ["git", "--literal-pathspecs", *args],
            cwd=repository,
            capture_output=True,
            check=False,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CommitActuatorBlocked(f"cannot verify committed Git state: {exc}") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).decode(
            "utf-8",
            errors="replace",
        ).strip()
        raise CommitActuatorBlocked(
            f"cannot verify committed Git state: {detail[-400:]}"
        )
    return proc.stdout


__all__ = [
    "CommitActuation",
    "CommitActuationReceipt",
    "CommitActuatorBlocked",
    "CommitActuatorBusy",
    "CommitActuatorError",
    "GitCommitActuator",
]
