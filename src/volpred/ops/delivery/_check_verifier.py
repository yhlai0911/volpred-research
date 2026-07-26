"""Trusted isolated-workspace verification for immutable ChangeSets."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
import subprocess

from . import (
    ChangeSetProposal,
    ChangeSetView,
    _normalize_proposal,
    _proposal_sha256,
    _validate_workspace,
)


class CheckVerificationFailed(RuntimeError):
    """A required ChangeSet check could not be independently verified."""


class IsolatedCheckVerifier:
    """Execute operator-configured checks inside the candidate worktree.

    The ChangeSet supplies only check names and author evidence. Commands come
    from this trusted composition object, so an author cannot turn a fabricated
    ``status="passed"`` field into commit authority.
    """

    def __init__(
        self,
        commands: Mapping[str, Sequence[str]],
        *,
        timeout_seconds: float = 900.0,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("check timeout must be positive")
        normalized: dict[str, tuple[str, ...]] = {}
        for raw_name, raw_command in commands.items():
            name = raw_name.strip()
            command = tuple(raw_command)
            if (
                not name
                or not command
                or any(not isinstance(arg, str) or not arg for arg in command)
            ):
                raise ValueError(
                    "isolated check registry requires names and argv"
                )
            normalized[name] = command
        self._commands = normalized
        self._timeout_seconds = timeout_seconds

    def verify(self, change_set: ChangeSetView) -> None:
        proposal = _proposal_from_view(change_set)
        _validate_workspace(proposal)
        workspace = Path(proposal.workspace_ref)

        for check in proposal.required_checks:
            command = self._commands.get(check.name)
            if command is None:
                raise CheckVerificationFailed(
                    f"required check is not configured: {check.name}"
                )
            try:
                completed = subprocess.run(
                    command,
                    cwd=workspace,
                    capture_output=True,
                    check=False,
                    timeout=self._timeout_seconds,
                )
            except (OSError, subprocess.TimeoutExpired) as error:
                raise CheckVerificationFailed(
                    f"required check could not run: {check.name}: {error}"
                ) from error
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout).decode(
                    "utf-8",
                    errors="replace",
                ).strip()
                raise CheckVerificationFailed(
                    f"required check failed: {check.name}: {detail[:300]}"
                )

        # Checks are read-only from the delivery contract's perspective. A
        # command that changes HEAD, scope, file bytes, modes, or index state
        # invalidates the candidate before the Git actuator can run.
        _validate_workspace(proposal)


def _proposal_from_view(change_set: ChangeSetView) -> ChangeSetProposal:
    if not isinstance(change_set, ChangeSetView):
        raise CheckVerificationFailed(
            "required check verifier received an invalid ChangeSet"
        )
    proposal = _normalize_proposal(
        ChangeSetProposal(
            idempotency_key=change_set.idempotency_key,
            work_item_id=change_set.work_item_id,
            work_item_version=change_set.work_item_version,
            base_commit=change_set.base_commit,
            workspace_ref=change_set.workspace_ref,
            exact_paths=change_set.exact_paths,
            content_hashes=change_set.content_hashes,
            required_checks=change_set.required_checks,
            author_ref=change_set.author_ref,
            author_evidence_ref=change_set.author_evidence_ref,
        )
    )
    if (
        change_set.schema_version != "changeset.v1"
        or change_set.status != "proposed"
        or _proposal_sha256(proposal) != change_set.proposal_sha256
    ):
        raise CheckVerificationFailed(
            "required check ChangeSet identity is invalid"
        )
    return proposal


__all__ = ["CheckVerificationFailed", "IsolatedCheckVerifier"]
