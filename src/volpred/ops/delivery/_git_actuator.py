"""Private adapter from Change Delivery to the canonical Git writer.

This module does not grant landing authority.  It asks an injected authority
adapter to verify the current WorkLease and Primary Authority fencing token,
then translates the authorized, materialized exact-path request into the
existing ``scripts/git_writer_lock.py commit`` transaction and verifies the
resulting commit object.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Callable, Protocol

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
    work_item_id: str
    work_item_version: int
    work_lease_token: str
    primary_fencing_token: str
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
    work_item_id: str
    work_item_version: int
    authority_request_sha256: str
    work_lease_ref: str
    primary_authority_ref: str
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


@dataclass(frozen=True)
class CommitAuthorityRequest:
    request_sha256: str
    proposal_sha256: str
    work_item_id: str
    work_item_version: int
    work_lease_token: str
    primary_fencing_token: str
    repository: str
    expected_head: str
    exact_paths: tuple[str, ...]
    content_hashes: tuple[ContentHash, ...]
    message: str
    actor: str


@dataclass(frozen=True)
class CommitAuthorityGrant:
    request_sha256: str
    work_lease_ref: str
    primary_authority_ref: str


class CommitAuthority(Protocol):
    """Verify both delivery fences against canonical coordination state."""

    def authorize(self, request: CommitAuthorityRequest) -> CommitAuthorityGrant: ...


class GitCommitActuator:
    """Invoke and read back the existing exact-path Git writer transaction."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime],
        authority: CommitAuthority,
        writer_cli: Path = _DEFAULT_WRITER_CLI,
        python_executable: str = sys.executable,
        timeout_s: float = 120.0,
    ) -> None:
        self._clock = clock
        self._authority = authority
        self._writer_cli = writer_cli.resolve()
        self._python_executable = python_executable
        self._timeout_s = timeout_s

    def commit(self, command: CommitActuation) -> CommitActuationReceipt:
        normalized = _normalize_command(command)
        repository = Path(normalized.repository)
        authority_request = _authority_request(normalized)
        try:
            authority_grant = self._authority.authorize(authority_request)
        except CommitActuatorError:
            raise
        except Exception as exc:
            raise CommitActuatorBlocked(
                "commit authority could not authorize the request"
            ) from exc
        authority_grant = _validate_authority_grant(
            authority_grant,
            request=authority_request,
        )

        observed_head = _git_text(
            repository,
            "rev-parse",
            "--verify",
            "HEAD^{commit}",
        )
        if observed_head != normalized.expected_head:
            recovered = _recover_prior_commit(
                repository,
                command=normalized,
                authority_request=authority_request,
                authority_grant=authority_grant,
                observed_head=observed_head,
            )
            if recovered is not None:
                return recovered
            raise CommitActuatorBlocked(
                "expected HEAD fence failed and no exact prior ChangeSet "
                "commit was found"
            )

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
        parent_sha = _verify_commit(
            repository,
            command=normalized,
            commit_sha=commit_sha,
        )

        observed_at = self._clock()
        if observed_at.tzinfo is None:
            raise CommitActuatorBlocked(
                "commit actuator clock must return a timezone-aware value"
            )
        return CommitActuationReceipt(
            schema_version=_RECEIPT_SCHEMA,
            proposal_sha256=normalized.proposal_sha256,
            work_item_id=normalized.work_item_id,
            work_item_version=normalized.work_item_version,
            authority_request_sha256=authority_request.request_sha256,
            work_lease_ref=authority_grant.work_lease_ref,
            primary_authority_ref=authority_grant.primary_authority_ref,
            commit_sha=commit_sha,
            parent_sha=parent_sha,
            exact_paths=normalized.exact_paths,
            actor=normalized.actor,
            status="committed",
            observed_at=observed_at.isoformat(),
        )


def _recover_prior_commit(
    repository: Path,
    *,
    command: CommitActuation,
    authority_request: CommitAuthorityRequest,
    authority_grant: CommitAuthorityGrant,
    observed_head: str,
) -> CommitActuationReceipt | None:
    """Recover an exact writer commit whose process return was lost.

    The canonical writer can only have created the first mainline child of the
    fenced expected HEAD. Later commits may already be on top when a restarted
    worker retries, so inspect that historical child rather than accepting an
    arbitrary matching commit from repository history.
    """

    candidates = _git_text(
        repository,
        "rev-list",
        "--first-parent",
        "--reverse",
        f"{command.expected_head}..{observed_head}",
    ).splitlines()
    if not candidates:
        return None
    commit_sha = candidates[0]
    try:
        parent_sha = _verify_commit(
            repository,
            command=command,
            commit_sha=commit_sha,
        )
        observed_at = datetime.fromisoformat(
            _git_text(
                repository,
                "show",
                "--no-patch",
                "--format=%cI",
                commit_sha,
            )
        )
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            return None
    except (  # silent-ok: caller raises an explicit stale-HEAD recovery miss
        CommitActuatorBlocked,
        TypeError,
        ValueError,
    ):
        return None

    return CommitActuationReceipt(
        schema_version=_RECEIPT_SCHEMA,
        proposal_sha256=command.proposal_sha256,
        work_item_id=command.work_item_id,
        work_item_version=command.work_item_version,
        authority_request_sha256=authority_request.request_sha256,
        work_lease_ref=authority_grant.work_lease_ref,
        primary_authority_ref=authority_grant.primary_authority_ref,
        commit_sha=commit_sha,
        parent_sha=parent_sha,
        exact_paths=command.exact_paths,
        actor=command.actor,
        status="committed",
        observed_at=observed_at.isoformat(),
    )


def _verify_commit(
    repository: Path,
    *,
    command: CommitActuation,
    commit_sha: str,
) -> str:
    parent_sha = _git_text(
        repository,
        "rev-parse",
        "--verify",
        f"{commit_sha}^{{commit}}^",
    )
    if parent_sha != command.expected_head:
        raise CommitActuatorBlocked(
            "canonical Git writer produced a commit with an unexpected parent"
        )
    message = _git_text(
        repository,
        "show",
        "--no-patch",
        "--format=%B",
        commit_sha,
    )
    if message != command.message:
        raise CommitActuatorBlocked(
            "canonical Git writer commit message differs from the ChangeSet"
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
    if changed_paths != command.exact_paths:
        raise CommitActuatorBlocked(
            "canonical Git writer commit paths differ from the ChangeSet"
        )
    for item in command.content_hashes:
        blob = _git_bytes(repository, "show", f"{commit_sha}:{item.path}")
        observed = hashlib.sha256(blob).hexdigest()
        if observed != item.sha256:
            raise CommitActuatorBlocked(
                f"committed content hash differs from the ChangeSet: {item.path}"
            )
    return parent_sha


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
    work_item_id = _required_text(command.work_item_id, field="work_item_id")
    if command.work_item_version <= 0:
        raise ValueError("work_item_version must be positive")
    work_lease_token = _required_text(
        command.work_lease_token,
        field="work_lease_token",
    )
    primary_fencing_token = _required_text(
        command.primary_fencing_token,
        field="primary_fencing_token",
    )

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

    actor = _required_text(command.actor, field="commit actor")
    if not actor.startswith("commit-worker:"):
        raise ValueError("commit actor must use the commit-worker identity")

    return CommitActuation(
        proposal_sha256=command.proposal_sha256,
        work_item_id=work_item_id,
        work_item_version=command.work_item_version,
        work_lease_token=work_lease_token,
        primary_fencing_token=primary_fencing_token,
        repository=str(repository),
        expected_head=command.expected_head,
        exact_paths=paths,
        content_hashes=tuple(hashes[path] for path in paths),
        message=_required_text(command.message, field="commit message"),
        actor=actor,
    )


def _authority_request(command: CommitActuation) -> CommitAuthorityRequest:
    request = CommitAuthorityRequest(
        request_sha256="",
        proposal_sha256=command.proposal_sha256,
        work_item_id=command.work_item_id,
        work_item_version=command.work_item_version,
        work_lease_token=command.work_lease_token,
        primary_fencing_token=command.primary_fencing_token,
        repository=command.repository,
        expected_head=command.expected_head,
        exact_paths=command.exact_paths,
        content_hashes=command.content_hashes,
        message=command.message,
        actor=command.actor,
    )
    return replace(
        request,
        request_sha256=_authority_request_sha256(request),
    )


def _authority_request_sha256(request: CommitAuthorityRequest) -> str:
    """Recompute the complete write-intent identity for authority adapters."""

    payload = {
        "schema_version": "commit-authority-request.v1",
        "proposal_sha256": request.proposal_sha256,
        "work_item_id": request.work_item_id,
        "work_item_version": request.work_item_version,
        "work_lease_token": request.work_lease_token,
        "primary_fencing_token": request.primary_fencing_token,
        "repository": request.repository,
        "expected_head": request.expected_head,
        "exact_paths": list(request.exact_paths),
        "content_hashes": [
            {"path": item.path, "sha256": item.sha256}
            for item in request.content_hashes
        ],
        "message": request.message,
        "actor": request.actor,
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_authority_grant(
    grant: CommitAuthorityGrant,
    *,
    request: CommitAuthorityRequest,
) -> CommitAuthorityGrant:
    try:
        if grant.request_sha256 != request.request_sha256:
            raise CommitActuatorBlocked(
                "commit authority grant does not match the requested write intent"
            )
        return CommitAuthorityGrant(
            request_sha256=grant.request_sha256,
            work_lease_ref=_required_text(
                grant.work_lease_ref,
                field="authority WorkLease reference",
            ),
            primary_authority_ref=_required_text(
                grant.primary_authority_ref,
                field="Primary Authority reference",
            ),
        )
    except CommitActuatorBlocked:
        raise
    except (AttributeError, TypeError, ValueError) as exc:
        raise CommitActuatorBlocked(
            "commit authority returned an invalid grant"
        ) from exc


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
    "CommitAuthority",
    "CommitAuthorityGrant",
    "CommitAuthorityRequest",
    "CommitActuatorBlocked",
    "CommitActuatorBusy",
    "CommitActuatorError",
    "GitCommitActuator",
]
