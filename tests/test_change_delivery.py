from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import subprocess

import pytest

from volpred.ops.delivery import (
    ChangeDelivery,
    ChangeSetConflict,
    ChangeSetProposal,
    CheckEvidence,
    ContentHash,
    DeliveryReceipt,
    LandChangeSet,
)
from volpred.ops.delivery._git_actuator import (
    CommitActuation,
    CommitActuationReceipt,
    CommitAuthorityGrant,
    CommitActuatorBlocked,
    GitCommitActuator,
)
from volpred.ops.delivery._change_store import InMemoryChangeSetStore


NOW = datetime(2026, 7, 23, 14, 30, tzinfo=timezone.utc)


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


@pytest.fixture
def workspace(tmp_path: Path) -> tuple[Path, Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Change Delivery Test")
    _git(repo, "config", "user.email", "change-delivery@example.invalid")
    (repo / "tracked.txt").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-m", "base")
    base_commit = _git(repo, "rev-parse", "HEAD")

    linked = tmp_path / "linked"
    _git(repo, "worktree", "add", "-b", "candidate", str(linked), base_commit)
    (linked / "tracked.txt").write_text("candidate\n", encoding="utf-8")
    (linked / "new.txt").write_text("new\n", encoding="utf-8")
    return repo, linked, base_commit


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _proposal(linked: Path, base_commit: str) -> ChangeSetProposal:
    return ChangeSetProposal(
        idempotency_key="changeset:work-1:attempt-1",
        work_item_id="work-1",
        work_item_version=7,
        base_commit=base_commit,
        workspace_ref=str(linked),
        exact_paths=("new.txt", "tracked.txt"),
        content_hashes=(
            ContentHash("tracked.txt", _hash(linked / "tracked.txt")),
            ContentHash("new.txt", _hash(linked / "new.txt")),
        ),
        required_checks=(
            CheckEvidence("pytest", "passed", "log:pytest-123"),
            CheckEvidence("ruff", "passed", "log:ruff-123"),
        ),
        author_ref="agent:codex-worker",
        author_evidence_ref="execution:work-1:attempt-1",
    )


def _delivery() -> ChangeDelivery:
    return ChangeDelivery(clock=lambda: NOW, id_factory=lambda: "changeset-1")


class _Actuator:
    def __init__(self) -> None:
        self.commands: list[CommitActuation] = []

    def commit(self, command: CommitActuation) -> CommitActuationReceipt:
        self.commands.append(command)
        return CommitActuationReceipt(
            schema_version="commit-actuation.v1",
            proposal_sha256=command.proposal_sha256,
            work_item_id=command.work_item_id,
            work_item_version=command.work_item_version,
            authority_request_sha256="a" * 64,
            work_lease_ref="work-lease:work-1:v7",
            primary_authority_ref="primary-authority:operations-core-commits:epoch-1",
            commit_sha="2" * 40,
            parent_sha=command.expected_head,
            exact_paths=command.exact_paths,
            actor=command.actor,
            status="committed",
            observed_at=NOW.isoformat(),
        )


class _TimestampActuator(_Actuator):
    def __init__(self, observed_at: str) -> None:
        super().__init__()
        self._observed_at = observed_at

    def commit(self, command: CommitActuation) -> CommitActuationReceipt:
        return replace(
            super().commit(command),
            observed_at=self._observed_at,
        )


class _Authority:
    def authorize(self, request):
        return CommitAuthorityGrant(
            request_sha256=request.request_sha256,
            work_lease_ref="work-lease:work-1:v7",
            primary_authority_ref="primary-authority:epoch-42",
        )


class _LoseFirstReturn:
    def __init__(self, actuator: GitCommitActuator) -> None:
        self._actuator = actuator
        self.calls = 0

    def commit(self, command: CommitActuation) -> CommitActuationReceipt:
        self.calls += 1
        self._actuator.commit(command)
        raise RuntimeError("process exited before actuation checkpoint")


class _Settlement:
    def __init__(self, *, fail_once: bool = False) -> None:
        self.commands = []
        self._fail_once = fail_once

    def settle(self, command):
        self.commands.append(command)
        if self._fail_once:
            self._fail_once = False
            raise RuntimeError("database unavailable")
        receipt = command.actuation
        return DeliveryReceipt(
            schema_version="change-delivery-receipt.v1",
            change_set_id=command.change_set_id,
            proposal_sha256=receipt.proposal_sha256,
            work_item_id=receipt.work_item_id,
            work_item_version=receipt.work_item_version,
            authority_request_sha256=receipt.authority_request_sha256,
            work_lease_ref=receipt.work_lease_ref,
            primary_authority_ref=receipt.primary_authority_ref,
            repository=command.repository,
            commit_sha=receipt.commit_sha,
            parent_sha=receipt.parent_sha,
            exact_paths=receipt.exact_paths,
            actor=receipt.actor,
            status="landed",
            actuation_observed_at=receipt.observed_at,
            settled_at=NOW.isoformat(),
            settlement_ref=f"change-delivery:{command.change_set_id}:{receipt.commit_sha}",
            settlement_sha256="b" * 64,
        )


def _land(change_set_id: str = "changeset-1") -> LandChangeSet:
    return LandChangeSet(
        change_set_id=change_set_id,
        work_lease_token="work-lease-token",
        primary_fencing_token="primary-fencing-token",
        repository="/repo",
        message="[change-delivery] land changeset-1",
        actor="commit-worker:test",
    )


def test_propose_validates_and_exposes_immutable_changeset(
    workspace: tuple[Path, Path, str],
) -> None:
    repo, linked, base_commit = workspace
    head_before = _git(linked, "rev-parse", "HEAD")
    index_before = _git(linked, "diff", "--cached", "--name-only")

    view = _delivery().propose(_proposal(linked, base_commit))

    assert view.schema_version == "changeset.v1"
    assert view.id == "changeset-1"
    assert view.status == "proposed"
    assert view.exact_paths == ("new.txt", "tracked.txt")
    assert tuple(item.path for item in view.content_hashes) == (
        "new.txt",
        "tracked.txt",
    )
    assert tuple(item.name for item in view.required_checks) == ("pytest", "ruff")
    assert len(view.proposal_sha256) == 64
    assert view.created_at == NOW.isoformat()
    assert _git(linked, "rev-parse", "HEAD") == head_before == base_commit
    assert _git(linked, "diff", "--cached", "--name-only") == index_before == ""
    assert _git(repo, "rev-parse", "HEAD") == base_commit


def test_inspect_returns_proposed_changeset(
    workspace: tuple[Path, Path, str],
) -> None:
    _, linked, base_commit = workspace
    delivery = _delivery()
    proposed = delivery.propose(_proposal(linked, base_commit))

    assert delivery.inspect(proposed.id) == proposed
    with pytest.raises(ValueError, match="unknown ChangeSet"):
        delivery.inspect("missing")


def test_idempotent_replay_is_payload_bound(
    workspace: tuple[Path, Path, str],
) -> None:
    _, linked, base_commit = workspace
    delivery = _delivery()
    proposal = _proposal(linked, base_commit)

    first = delivery.propose(proposal)
    reordered = replace(
        proposal,
        exact_paths=tuple(reversed(proposal.exact_paths)),
        content_hashes=tuple(reversed(proposal.content_hashes)),
        required_checks=tuple(reversed(proposal.required_checks)),
    )
    assert delivery.propose(reordered) is first

    conflicting = replace(proposal, author_evidence_ref="execution:different")
    with pytest.raises(ChangeSetConflict, match="original payload"):
        delivery.propose(conflicting)


def test_idempotent_replay_does_not_require_ephemeral_workspace(
    workspace: tuple[Path, Path, str],
) -> None:
    _, linked, base_commit = workspace
    delivery = _delivery()
    proposal = _proposal(linked, base_commit)
    first = delivery.propose(proposal)
    (linked / "tracked.txt").write_text("workspace drifted\n", encoding="utf-8")
    (linked / "new.txt").unlink()

    assert delivery.propose(proposal) is first


@pytest.mark.parametrize(
    "path",
    [
        "/absolute.txt",
        ".",
        "../escape.txt",
        "dir/../tracked.txt",
        ".git/config",
        r"windows\\path.txt",
    ],
)
def test_propose_rejects_non_exact_paths(
    workspace: tuple[Path, Path, str],
    path: str,
) -> None:
    _, linked, base_commit = workspace
    proposal = replace(
        _proposal(linked, base_commit),
        exact_paths=(path,),
        content_hashes=(ContentHash(path, "0" * 64),),
    )

    with pytest.raises(ValueError, match="path"):
        _delivery().propose(proposal)


def test_propose_rejects_hash_scope_and_content_drift(
    workspace: tuple[Path, Path, str],
) -> None:
    _, linked, base_commit = workspace
    proposal = _proposal(linked, base_commit)

    with pytest.raises(ValueError, match="match the exact path set"):
        _delivery().propose(
            replace(proposal, content_hashes=proposal.content_hashes[:1])
        )
    with pytest.raises(ValueError, match="content hash drift"):
        _delivery().propose(
            replace(
                proposal,
                content_hashes=(
                    ContentHash("new.txt", "0" * 64),
                    proposal.content_hashes[0],
                ),
            )
        )


def test_propose_rejects_undeclared_workspace_residue(
    workspace: tuple[Path, Path, str],
) -> None:
    _, linked, base_commit = workspace
    proposal = _proposal(linked, base_commit)
    (linked / "residue.txt").write_text("unowned\n", encoding="utf-8")

    with pytest.raises(ValueError, match="complete workspace dirty set"):
        _delivery().propose(proposal)


def test_propose_rejects_staged_or_deleted_paths(
    workspace: tuple[Path, Path, str],
) -> None:
    _, linked, base_commit = workspace
    proposal = _proposal(linked, base_commit)
    _git(linked, "add", "tracked.txt")
    with pytest.raises(ValueError, match="index must be clean"):
        _delivery().propose(proposal)

    _git(linked, "reset", "HEAD", "--", "tracked.txt")
    (linked / "tracked.txt").unlink()
    proposal = replace(
        proposal,
        exact_paths=("new.txt", "tracked.txt"),
        content_hashes=(
            ContentHash("new.txt", _hash(linked / "new.txt")),
            ContentHash("tracked.txt", "0" * 64),
        ),
    )
    with pytest.raises(ValueError, match="deleted paths"):
        _delivery().propose(proposal)


def test_propose_rejects_symlinks_and_renames(
    workspace: tuple[Path, Path, str],
) -> None:
    _, linked, base_commit = workspace
    (linked / "new.txt").unlink()
    (linked / "new.txt").symlink_to("tracked.txt")
    proposal = _proposal(linked, base_commit)
    with pytest.raises(ValueError, match="symlink"):
        _delivery().propose(proposal)

    (linked / "new.txt").unlink()
    (linked / "new.txt").write_text("new\n", encoding="utf-8")
    _git(linked, "mv", "tracked.txt", "moved.txt")
    proposal = replace(
        proposal,
        exact_paths=("moved.txt", "new.txt"),
        content_hashes=(
            ContentHash("moved.txt", _hash(linked / "moved.txt")),
            ContentHash("new.txt", _hash(linked / "new.txt")),
        ),
    )
    with pytest.raises(ValueError, match="renamed or copied"):
        _delivery().propose(proposal)


def test_propose_rejects_base_drift_and_canonical_checkout(
    workspace: tuple[Path, Path, str],
) -> None:
    repo, linked, base_commit = workspace
    proposal = _proposal(linked, base_commit)

    with pytest.raises(ValueError, match="base commit drifted"):
        _delivery().propose(replace(proposal, base_commit="0" * 40))

    canonical = replace(
        proposal,
        workspace_ref=str(repo),
        exact_paths=("tracked.txt",),
        content_hashes=(ContentHash("tracked.txt", _hash(repo / "tracked.txt")),),
    )
    with pytest.raises(ValueError, match="canonical checkout"):
        _delivery().propose(canonical)


def test_propose_rejects_unverified_checks_and_missing_author_evidence(
    workspace: tuple[Path, Path, str],
) -> None:
    _, linked, base_commit = workspace
    proposal = _proposal(linked, base_commit)

    with pytest.raises(ValueError, match="did not pass"):
        _delivery().propose(
            replace(
                proposal,
                required_checks=(
                    CheckEvidence("pytest", "failed", "log:pytest-123"),
                ),
            )
        )
    with pytest.raises(ValueError, match="author_evidence_ref"):
        _delivery().propose(replace(proposal, author_evidence_ref=" "))


def test_propose_rejects_ambiguous_clock_and_duplicate_generated_id(
    workspace: tuple[Path, Path, str],
) -> None:
    _, linked, base_commit = workspace
    proposal = _proposal(linked, base_commit)
    ambiguous = ChangeDelivery(
        clock=lambda: datetime(2026, 7, 23, 14, 30),
        id_factory=lambda: "changeset-1",
    )
    with pytest.raises(ValueError, match="timezone-aware"):
        ambiguous.propose(proposal)

    delivery = _delivery()
    delivery.propose(proposal)
    with pytest.raises(ValueError, match="duplicate ChangeSet id"):
        delivery.propose(
            replace(
                proposal,
                idempotency_key="changeset:work-1:attempt-2",
            )
        )


def test_land_orchestrates_actuation_and_durable_settlement(
    workspace: tuple[Path, Path, str],
) -> None:
    _, linked, base_commit = workspace
    actuator = _Actuator()
    settlement = _Settlement()
    delivery = ChangeDelivery(
        clock=lambda: NOW,
        id_factory=lambda: "changeset-1",
        actuator=actuator,
        settlement=settlement,
    )
    proposed = delivery.propose(_proposal(linked, base_commit))

    receipt = delivery.land(_land(proposed.id))

    assert receipt.status == "landed"
    assert receipt.change_set_id == proposed.id
    assert receipt.proposal_sha256 == proposed.proposal_sha256
    assert receipt.commit_sha == "2" * 40
    assert delivery.inspect(proposed.id).status == "landed"
    assert len(actuator.commands) == 1
    assert actuator.commands[0] == CommitActuation(
        proposal_sha256=proposed.proposal_sha256,
        work_item_id=proposed.work_item_id,
        work_item_version=proposed.work_item_version,
        work_lease_token="work-lease-token",
        primary_fencing_token="primary-fencing-token",
        repository="/repo",
        expected_head=proposed.base_commit,
        exact_paths=proposed.exact_paths,
        content_hashes=proposed.content_hashes,
        message="[change-delivery] land changeset-1",
        actor="commit-worker:test",
    )
    assert len(settlement.commands) == 1

    assert delivery.land(_land(proposed.id)) == receipt
    assert len(actuator.commands) == 1
    assert len(settlement.commands) == 1


def test_land_retries_only_post_commit_settlement_after_transient_failure(
    workspace: tuple[Path, Path, str],
) -> None:
    _, linked, base_commit = workspace
    actuator = _Actuator()
    settlement = _Settlement(fail_once=True)
    delivery = ChangeDelivery(
        clock=lambda: NOW,
        id_factory=lambda: "changeset-1",
        actuator=actuator,
        settlement=settlement,
    )
    proposed = delivery.propose(_proposal(linked, base_commit))

    with pytest.raises(RuntimeError, match="database unavailable"):
        delivery.land(_land(proposed.id))

    assert delivery.inspect(proposed.id).status == "commit_unsettled"
    receipt = delivery.land(_land(proposed.id))
    assert receipt.status == "landed"
    assert len(actuator.commands) == 1
    assert len(settlement.commands) == 2


def test_restart_resumes_durable_checkpoint_without_second_git_write(
    workspace: tuple[Path, Path, str],
) -> None:
    _, linked, base_commit = workspace
    store = InMemoryChangeSetStore()
    first_actuator = _Actuator()
    settlement = _Settlement(fail_once=True)
    first_process = ChangeDelivery(
        clock=lambda: NOW,
        id_factory=lambda: "changeset-1",
        actuator=first_actuator,
        settlement=settlement,
        store=store,
    )
    proposed = first_process.propose(_proposal(linked, base_commit))

    with pytest.raises(RuntimeError, match="database unavailable"):
        first_process.land(_land(proposed.id))

    second_actuator = _Actuator()
    restarted_process = ChangeDelivery(
        clock=lambda: NOW,
        id_factory=lambda: "unused-after-restart",
        actuator=second_actuator,
        settlement=settlement,
        store=store,
    )
    assert restarted_process.inspect(proposed.id).status == "commit_unsettled"

    receipt = restarted_process.land(_land(proposed.id))

    assert receipt.status == "landed"
    assert len(first_actuator.commands) == 1
    assert second_actuator.commands == []
    assert len(settlement.commands) == 2
    assert restarted_process.inspect(proposed.id).status == "landed"


def test_restart_recovers_git_commit_when_process_dies_before_checkpoint(
    workspace: tuple[Path, Path, str],
) -> None:
    repo, linked, base_commit = workspace
    (repo / "tracked.txt").write_bytes((linked / "tracked.txt").read_bytes())
    (repo / "new.txt").write_bytes((linked / "new.txt").read_bytes())
    store = InMemoryChangeSetStore()
    settlement = _Settlement()
    first_git_actuator = GitCommitActuator(
        clock=lambda: NOW,
        authority=_Authority(),
    )
    lost_return = _LoseFirstReturn(first_git_actuator)
    first_process = ChangeDelivery(
        clock=lambda: NOW,
        id_factory=lambda: "changeset-1",
        actuator=lost_return,
        settlement=settlement,
        store=store,
    )
    proposed = first_process.propose(_proposal(linked, base_commit))
    command = replace(_land(proposed.id), repository=str(repo))

    with pytest.raises(RuntimeError, match="before actuation checkpoint"):
        first_process.land(command)

    committed_sha = _git(repo, "rev-parse", "HEAD")
    assert committed_sha != base_commit
    assert first_process.inspect(proposed.id).status == "proposed"
    restarted_process = ChangeDelivery(
        clock=lambda: NOW,
        id_factory=lambda: "unused-after-restart",
        actuator=GitCommitActuator(
            clock=lambda: NOW,
            authority=_Authority(),
        ),
        settlement=settlement,
        store=store,
    )

    receipt = restarted_process.land(command)

    assert receipt.status == "landed"
    assert receipt.commit_sha == committed_sha
    assert receipt.parent_sha == base_commit
    assert restarted_process.inspect(proposed.id).status == "landed"
    assert lost_return.calls == 1
    assert _git(repo, "rev-list", "--count", f"{base_commit}..HEAD") == "1"


def test_land_rejects_command_drift_after_external_commit(
    workspace: tuple[Path, Path, str],
) -> None:
    _, linked, base_commit = workspace
    actuator = _Actuator()
    settlement = _Settlement(fail_once=True)
    delivery = ChangeDelivery(
        clock=lambda: NOW,
        id_factory=lambda: "changeset-1",
        actuator=actuator,
        settlement=settlement,
    )
    proposed = delivery.propose(_proposal(linked, base_commit))
    command = _land(proposed.id)

    with pytest.raises(RuntimeError, match="database unavailable"):
        delivery.land(command)

    with pytest.raises(ChangeSetConflict, match="landing command"):
        delivery.land(replace(command, message="[change-delivery] changed"))
    assert len(actuator.commands) == 1
    assert len(settlement.commands) == 1


@pytest.mark.parametrize(
    "observed_at",
    [
        "not-a-timestamp",
        "2026-07-23T14:30:00",
    ],
)
def test_land_rejects_unverifiable_actuation_time_before_settlement(
    workspace: tuple[Path, Path, str],
    observed_at: str,
) -> None:
    _, linked, base_commit = workspace
    actuator = _TimestampActuator(observed_at)
    settlement = _Settlement()
    delivery = ChangeDelivery(
        clock=lambda: NOW,
        id_factory=lambda: "changeset-1",
        actuator=actuator,
        settlement=settlement,
    )
    proposed = delivery.propose(_proposal(linked, base_commit))

    with pytest.raises(CommitActuatorBlocked, match="timezone-aware"):
        delivery.land(_land(proposed.id))

    assert delivery.inspect(proposed.id).status == "proposed"
    assert len(actuator.commands) == 1
    assert settlement.commands == []


def test_land_requires_configured_actuator_and_settlement(
    workspace: tuple[Path, Path, str],
) -> None:
    _, linked, base_commit = workspace
    delivery = _delivery()
    proposed = delivery.propose(_proposal(linked, base_commit))

    with pytest.raises(RuntimeError, match="not configured"):
        delivery.land(_land(proposed.id))
    assert delivery.inspect(proposed.id).status == "proposed"
