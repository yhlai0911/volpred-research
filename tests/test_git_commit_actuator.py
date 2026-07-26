from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import subprocess
import sys
import time

import pytest

from volpred.ops.delivery import ContentHash
from volpred.ops.delivery._git_actuator import (
    CommitActuation,
    CommitAuthorityAbandonment,
    CommitAuthorityGrant,
    CommitAuthorityRequest,
    CommitActuatorBlocked,
    CommitActuatorBusy,
    GitCommitActuator,
    _authority_bound_message,
    _authority_request,
)


NOW = datetime(2026, 7, 23, 16, 30, tzinfo=timezone.utc)


class _Authority:
    def __init__(
        self,
        *,
        work_lease_token: str = "work-lease-current",
        primary_fencing_token: str = "primary-fence-current",
    ) -> None:
        self._work_lease_token = work_lease_token
        self._primary_fencing_token = primary_fencing_token
        self.requests: list[CommitAuthorityRequest] = []
        self.grants: dict[str, CommitAuthorityGrant] = {}
        self.abandonments: list[CommitAuthorityAbandonment] = []

    def authorize(self, request: CommitAuthorityRequest) -> CommitAuthorityGrant:
        self.requests.append(request)
        if request.work_lease_token != self._work_lease_token:
            raise CommitActuatorBlocked("stale WorkLease token")
        if request.primary_fencing_token != self._primary_fencing_token:
            raise CommitActuatorBlocked("stale Primary Authority fencing token")
        grant = CommitAuthorityGrant(
            request_sha256=request.request_sha256,
            commit_owner_generation=request.commit_owner_generation,
            commit_owner_ref="commit-owner:git.commit:generation-3",
            work_lease_ref="work-lease:work-1:v7",
            primary_authority_ref="primary-authority:epoch-42",
        )
        self.grants[request.request_sha256] = grant
        return grant

    def recover(
        self,
        request: CommitAuthorityRequest,
    ) -> CommitAuthorityGrant | None:
        return self.grants.get(request.request_sha256)

    def abandon(
        self,
        request: CommitAuthorityRequest,
        grant: CommitAuthorityGrant,
        *,
        reason: str,
    ) -> CommitAuthorityAbandonment:
        abandonment = CommitAuthorityAbandonment(
            schema_version="commit-authority-abandonment.v1",
            request_sha256=request.request_sha256,
            reason=reason,
            abandoned_at=NOW.isoformat(),
        )
        self.abandonments.append(abandonment)
        return abandonment


class _MalformedGrantAuthority(_Authority):
    def authorize(self, request: CommitAuthorityRequest) -> CommitAuthorityGrant:
        return CommitAuthorityGrant(
            request_sha256=request.request_sha256,
            commit_owner_generation=request.commit_owner_generation,
            commit_owner_ref="commit-owner:git.commit:generation-3",
            work_lease_ref="",
            primary_authority_ref="primary-authority:epoch-42",
        )


class _MismatchedGrantAuthority(_Authority):
    def authorize(self, request: CommitAuthorityRequest) -> CommitAuthorityGrant:
        return CommitAuthorityGrant(
            request_sha256="0" * 64,
            commit_owner_generation=request.commit_owner_generation,
            commit_owner_ref="commit-owner:git.commit:generation-3",
            work_lease_ref="work-lease:work-1:v7",
            primary_authority_ref="primary-authority:epoch-42",
        )


class _MismatchedOwnerAuthority(_Authority):
    def authorize(
        self,
        request: CommitAuthorityRequest,
    ) -> CommitAuthorityGrant:
        return replace(
            super().authorize(request),
            commit_owner_ref="commit-owner:git.commit:generation-99",
        )


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


@pytest.fixture
def repository(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Commit Actuator Test")
    _git(repo, "config", "user.email", "commit-actuator@example.invalid")
    (repo / "tracked.txt").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-m", "base")
    return repo, _git(repo, "rev-parse", "HEAD")


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _command(repo: Path, expected_head: str) -> CommitActuation:
    return CommitActuation(
        proposal_sha256="a" * 64,
        work_item_id="work-1",
        work_item_version=7,
        commit_owner_generation=3,
        work_lease_token="work-lease-current",
        primary_fencing_token="primary-fence-current",
        repository=str(repo),
        expected_head=expected_head,
        exact_paths=("new.txt", "tracked.txt"),
        content_hashes=(
            ContentHash("new.txt", _hash(repo / "new.txt")),
            ContentHash("tracked.txt", _hash(repo / "tracked.txt")),
        ),
        message="[change-delivery] land changeset-1",
        actor="commit-worker:test",
    )


def _actuator(authority: _Authority | None = None) -> GitCommitActuator:
    return GitCommitActuator(
        clock=lambda: NOW,
        authority=authority or _Authority(),
    )


def test_actuator_lands_and_reads_back_exact_changeset(
    repository: tuple[Path, str],
) -> None:
    repo, base_commit = repository
    (repo / "tracked.txt").write_text("candidate\n", encoding="utf-8")
    (repo / "new.txt").write_text("new\n", encoding="utf-8")

    receipt = _actuator().commit(_command(repo, base_commit))

    assert receipt.schema_version == "commit-actuation.v1"
    assert receipt.proposal_sha256 == "a" * 64
    assert receipt.work_item_id == "work-1"
    assert receipt.work_item_version == 7
    assert receipt.commit_owner_generation == 3
    assert receipt.commit_owner_ref == "commit-owner:git.commit:generation-3"
    assert len(receipt.authority_request_sha256) == 64
    assert receipt.work_lease_ref == "work-lease:work-1:v7"
    assert receipt.primary_authority_ref == "primary-authority:epoch-42"
    assert receipt.parent_sha == base_commit
    assert receipt.commit_sha == _git(repo, "rev-parse", "HEAD")
    assert receipt.exact_paths == ("new.txt", "tracked.txt")
    assert receipt.actor == "commit-worker:test"
    assert receipt.status == "committed"
    assert receipt.observed_at == NOW.isoformat()
    assert _git(repo, "show", "--no-patch", "--format=%B", "HEAD") == (
        f"{_command(repo, base_commit).message}\n\n"
        "Volpred-Commit-Authority-Request: "
        f"{receipt.authority_request_sha256}"
    )
    assert _git(repo, "show", "--format=", "--name-only", "HEAD").splitlines() == [
        "new.txt",
        "tracked.txt",
    ]


def test_actuator_recovers_exact_commit_after_process_return_is_lost(
    repository: tuple[Path, str],
    tmp_path: Path,
) -> None:
    repo, base_commit = repository
    (repo / "tracked.txt").write_text("candidate\n", encoding="utf-8")
    (repo / "new.txt").write_text("new\n", encoding="utf-8")
    command = _command(repo, base_commit)
    authority = _Authority()
    committed = _actuator(authority).commit(command)

    (repo / "later.txt").write_text("later\n", encoding="utf-8")
    _git(repo, "add", "later.txt")
    _git(repo, "commit", "-m", "later commit")
    head_after_later_commit = _git(repo, "rev-parse", "HEAD")
    restarted = GitCommitActuator(
        clock=lambda: NOW,
        authority=authority,
        writer_cli=tmp_path / "writer-must-not-run",
    )

    recovered = restarted.commit(command)

    assert recovered.commit_sha == committed.commit_sha
    assert recovered.parent_sha == base_commit
    assert recovered.exact_paths == command.exact_paths
    assert recovered.actor == command.actor
    assert recovered.status == "committed"
    assert datetime.fromisoformat(recovered.observed_at).utcoffset() is not None
    assert len(authority.requests) == 1
    assert _git(repo, "rev-parse", "HEAD") == head_after_later_commit


def test_actuator_recovery_requires_preexisting_authority_grant(
    repository: tuple[Path, str],
) -> None:
    repo, base_commit = repository
    (repo / "tracked.txt").write_text("candidate\n", encoding="utf-8")
    (repo / "new.txt").write_text("new\n", encoding="utf-8")
    command = _command(repo, base_commit)
    request = _authority_request(command)
    _git(repo, "add", "new.txt", "tracked.txt")
    _git(
        repo,
        "commit",
        "-m",
        _authority_bound_message(
            command.message,
            request.request_sha256,
        ),
    )
    authority = _Authority()

    with pytest.raises(
        CommitActuatorBlocked,
        match="no existing grant",
    ):
        _actuator(authority).recover(command)

    assert authority.requests == []


def test_authority_bound_non_exact_commit_keeps_grant_active(
    repository: tuple[Path, str],
) -> None:
    repo, base_commit = repository
    (repo / "tracked.txt").write_text("candidate\n", encoding="utf-8")
    (repo / "new.txt").write_text("new\n", encoding="utf-8")
    command = _command(repo, base_commit)
    request = _authority_request(command)
    authority = _Authority()
    authority.authorize(request)
    _git(repo, "add", "tracked.txt")
    _git(
        repo,
        "commit",
        "-m",
        _authority_bound_message(command.message, request.request_sha256),
    )

    with pytest.raises(
        CommitActuatorBlocked,
        match="authority-bound non-exact mutation",
    ):
        _actuator(authority).commit(command)

    assert authority.abandonments == []
    assert request.request_sha256 in authority.grants


def test_unexpected_head_mutation_retains_grant_and_blocks_rollback(
    repository: tuple[Path, str],
) -> None:
    repo, base_commit = repository
    (repo / "tracked.txt").write_text("candidate\n", encoding="utf-8")
    (repo / "new.txt").write_text("new\n", encoding="utf-8")

    class _RacingAuthority(_Authority):
        def authorize(
            self,
            request: CommitAuthorityRequest,
        ) -> CommitAuthorityGrant:
            grant = super().authorize(request)
            (repo / "unrelated.txt").write_text(
                "concurrent\n",
                encoding="utf-8",
            )
            _git(repo, "add", "unrelated.txt")
            _git(repo, "commit", "-m", "concurrent unrelated commit")
            return grant

    authority = _RacingAuthority()

    with pytest.raises(
        CommitActuatorBlocked,
        match="expected HEAD",
    ):
        _actuator(authority).commit(_command(repo, base_commit))

    assert authority.abandonments == []
    assert len(authority.grants) == 1


def test_busy_writer_preserves_active_grant_for_exact_retry(
    repository: tuple[Path, str],
    tmp_path: Path,
) -> None:
    repo, base_commit = repository
    (repo / "tracked.txt").write_text("candidate\n", encoding="utf-8")
    (repo / "new.txt").write_text("new\n", encoding="utf-8")
    busy_writer = tmp_path / "busy_writer.py"
    busy_writer.write_text(
        "import sys\n"
        "sys.stderr.write('canonical writer lock is busy')\n"
        "raise SystemExit(75)\n",
        encoding="utf-8",
    )
    authority = _Authority()
    actuator = GitCommitActuator(
        clock=lambda: NOW,
        authority=authority,
        writer_cli=busy_writer,
    )

    with pytest.raises(CommitActuatorBusy, match="lock is busy"):
        actuator.commit(_command(repo, base_commit))

    assert len(authority.grants) == 1
    assert authority.abandonments == []
    assert _git(repo, "rev-parse", "HEAD") == base_commit


def test_external_writer_lock_blocks_before_authority_grant(
    repository: tuple[Path, str],
    tmp_path: Path,
) -> None:
    repo, base_commit = repository
    (repo / "tracked.txt").write_text("candidate\n", encoding="utf-8")
    (repo / "new.txt").write_text("new\n", encoding="utf-8")
    marker = tmp_path / "holder-ready"
    release = tmp_path / "holder-release"
    cli = Path(__file__).resolve().parents[1] / "scripts" / "git_writer_lock.py"
    holder_code = (
        "from pathlib import Path\n"
        "import sys, time\n"
        "marker, release = map(Path, sys.argv[1:3])\n"
        "marker.write_text('held', encoding='utf-8')\n"
        "deadline = time.monotonic() + 10\n"
        "while not release.exists() and time.monotonic() < deadline:\n"
        "    time.sleep(0.01)\n"
        "raise SystemExit(0 if release.exists() else 3)\n"
    )
    holder = subprocess.Popen(
        [
            sys.executable,
            str(cli),
            "run",
            "--repo",
            str(repo),
            "--actor",
            "external-holder",
            "--timeout",
            "0",
            "--command-timeout",
            "15",
            "--",
            sys.executable,
            "-c",
            holder_code,
            str(marker),
            str(release),
        ],
        cwd=repo,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert marker.exists(), holder.communicate(timeout=1)
        authority = _Authority()

        with pytest.raises(CommitActuatorBusy, match="lock busy"):
            _actuator(authority).commit(_command(repo, base_commit))

        assert authority.requests == []
        assert authority.grants == {}
    finally:
        release.write_text("release\n", encoding="utf-8")
        stdout, stderr = holder.communicate(timeout=5)
        assert holder.returncode == 0, (stdout, stderr)


def test_timeout_then_unrelated_commit_terminally_abandons_old_grant(
    repository: tuple[Path, str],
    tmp_path: Path,
) -> None:
    repo, base_commit = repository
    (repo / "tracked.txt").write_text("candidate\n", encoding="utf-8")
    (repo / "new.txt").write_text("new\n", encoding="utf-8")
    timeout_writer = tmp_path / "timeout_writer.py"
    timeout_writer.write_text(
        "import time\n"
        "time.sleep(5)\n",
        encoding="utf-8",
    )
    authority = _Authority()
    first = GitCommitActuator(
        clock=lambda: NOW,
        authority=authority,
        writer_cli=timeout_writer,
        timeout_s=0.05,
    )

    with pytest.raises(CommitActuatorBusy, match="timed out"):
        first.commit(_command(repo, base_commit))
    assert len(authority.grants) == 1
    assert authority.abandonments == []

    (repo / "unrelated.txt").write_text("other request\n", encoding="utf-8")
    _git(repo, "add", "unrelated.txt")
    _git(
        repo,
        "commit",
        "-m",
        _authority_bound_message("unrelated request", "d" * 64),
    )
    with pytest.raises(CommitActuatorBlocked, match="expected HEAD"):
        _actuator(authority).commit(_command(repo, base_commit))

    assert len(authority.abandonments) == 1
    assert authority.abandonments[0].request_sha256 == (
        _authority_request(_command(repo, base_commit)).request_sha256
    )


def test_timeout_with_staged_residue_keeps_grant_active_on_retry(
    repository: tuple[Path, str],
    tmp_path: Path,
) -> None:
    repo, base_commit = repository
    (repo / "tracked.txt").write_text("candidate\n", encoding="utf-8")
    (repo / "new.txt").write_text("new\n", encoding="utf-8")
    residue_writer = tmp_path / "residue_writer.py"
    residue_writer.write_text(
        "import subprocess, time\n"
        "subprocess.run(\n"
        "    ['git', 'add', '--', 'new.txt', 'tracked.txt'],\n"
        "    check=True,\n"
        ")\n"
        "time.sleep(5)\n",
        encoding="utf-8",
    )
    authority = _Authority()
    first = GitCommitActuator(
        clock=lambda: NOW,
        authority=authority,
        writer_cli=residue_writer,
        timeout_s=0.15,
    )
    command = _command(repo, base_commit)

    with pytest.raises(CommitActuatorBusy, match="timed out"):
        first.commit(command)
    assert _git(repo, "diff", "--cached", "--name-only").splitlines() == [
        "new.txt",
        "tracked.txt",
    ]
    assert len(authority.requests) == 1
    assert authority.abandonments == []

    with pytest.raises(CommitActuatorBlocked, match="already staged"):
        _actuator(authority).commit(command)

    assert len(authority.requests) == 1
    assert authority.abandonments == []
    assert _authority_request(command).request_sha256 in authority.grants


def test_missing_authority_trailer_keeps_existing_grant_active(
    repository: tuple[Path, str],
) -> None:
    repo, base_commit = repository
    (repo / "tracked.txt").write_text("candidate\n", encoding="utf-8")
    (repo / "new.txt").write_text("new\n", encoding="utf-8")
    command = _command(repo, base_commit)
    request = _authority_request(command)
    authority = _Authority()
    authority.authorize(request)
    _git(repo, "add", "new.txt", "tracked.txt")
    _git(repo, "commit", "-m", command.message)

    with pytest.raises(
        CommitActuatorBlocked,
        match="ambiguous or authority-bound",
    ):
        _actuator(authority).commit(command)

    assert authority.abandonments == []
    assert request.request_sha256 in authority.grants


def test_actuator_does_not_recover_lookalike_commit_with_different_message(
    repository: tuple[Path, str],
) -> None:
    repo, base_commit = repository
    (repo / "tracked.txt").write_text("candidate\n", encoding="utf-8")
    (repo / "new.txt").write_text("new\n", encoding="utf-8")
    command = _command(repo, base_commit)
    _git(repo, "add", "new.txt", "tracked.txt")
    _git(
        repo,
        "commit",
        "-m",
        _authority_bound_message(
            "different intent",
            _authority_request(command).request_sha256,
        ),
    )
    lookalike_commit = _git(repo, "rev-parse", "HEAD")

    with pytest.raises(
        CommitActuatorBlocked,
        match="expected HEAD fence failed",
    ):
        _actuator().commit(command)

    assert _git(repo, "rev-parse", "HEAD") == lookalike_commit


def test_actuator_does_not_recover_unbound_bitwise_lookalike_commit(
    repository: tuple[Path, str],
) -> None:
    repo, base_commit = repository
    (repo / "tracked.txt").write_text("candidate\n", encoding="utf-8")
    (repo / "new.txt").write_text("new\n", encoding="utf-8")
    command = _command(repo, base_commit)
    _git(repo, "add", "new.txt", "tracked.txt")
    _git(repo, "commit", "-m", command.message)
    lookalike_commit = _git(repo, "rev-parse", "HEAD")

    with pytest.raises(
        CommitActuatorBlocked,
        match="expected HEAD fence failed",
    ):
        _actuator().commit(command)

    assert _git(repo, "rev-parse", "HEAD") == lookalike_commit


def test_actuator_does_not_recover_commit_from_prior_owner_generation(
    repository: tuple[Path, str],
) -> None:
    repo, base_commit = repository
    (repo / "tracked.txt").write_text("candidate\n", encoding="utf-8")
    (repo / "new.txt").write_text("new\n", encoding="utf-8")
    command = _command(repo, base_commit)
    prior_owner_command = replace(command, commit_owner_generation=2)
    _git(repo, "add", "new.txt", "tracked.txt")
    _git(
        repo,
        "commit",
        "-m",
        _authority_bound_message(
            command.message,
            _authority_request(prior_owner_command).request_sha256,
        ),
    )
    prior_owner_commit = _git(repo, "rev-parse", "HEAD")

    with pytest.raises(
        CommitActuatorBlocked,
        match="expected HEAD fence failed",
    ):
        _actuator().commit(command)

    assert _git(repo, "rev-parse", "HEAD") == prior_owner_commit


def test_actuator_does_not_recover_lookalike_commit_with_different_file_mode(
    repository: tuple[Path, str],
) -> None:
    repo, base_commit = repository
    (repo / "tracked.txt").write_text("candidate\n", encoding="utf-8")
    new_path = repo / "new.txt"
    new_path.write_text("new\n", encoding="utf-8")
    command = _command(repo, base_commit)
    new_path.chmod(0o755)
    _git(repo, "add", "new.txt", "tracked.txt")
    _git(
        repo,
        "commit",
        "-m",
        _authority_bound_message(
            command.message,
            _authority_request(command).request_sha256,
        ),
    )
    lookalike_commit = _git(repo, "rev-parse", "HEAD")

    with pytest.raises(
        CommitActuatorBlocked,
        match="expected HEAD fence failed",
    ):
        _actuator().commit(command)

    assert _git(repo, "rev-parse", "HEAD") == lookalike_commit


def test_actuator_preserves_unrelated_index_and_worktree_state(
    repository: tuple[Path, str],
) -> None:
    repo, base_commit = repository
    (repo / "foreign.txt").write_text("foreign base\n", encoding="utf-8")
    _git(repo, "add", "foreign.txt")
    _git(repo, "commit", "-m", "foreign base")
    base_commit = _git(repo, "rev-parse", "HEAD")

    (repo / "foreign.txt").write_text("foreign staged\n", encoding="utf-8")
    _git(repo, "add", "foreign.txt")
    staged_foreign = _git(repo, "show", ":foreign.txt")
    (repo / "foreign.txt").write_text("foreign working\n", encoding="utf-8")
    (repo / "tracked.txt").write_text("candidate\n", encoding="utf-8")
    (repo / "new.txt").write_text("new\n", encoding="utf-8")

    _actuator().commit(_command(repo, base_commit))

    assert _git(repo, "show", ":foreign.txt") == staged_foreign
    assert (repo / "foreign.txt").read_text(encoding="utf-8") == "foreign working\n"
    assert _git(repo, "show", "--format=", "--name-only", "HEAD").splitlines() == [
        "new.txt",
        "tracked.txt",
    ]


def test_actuator_rejects_stale_head_before_touching_index(
    repository: tuple[Path, str],
) -> None:
    repo, stale_head = repository
    (repo / "concurrent.txt").write_text("concurrent\n", encoding="utf-8")
    _git(repo, "add", "concurrent.txt")
    _git(repo, "commit", "-m", "concurrent")
    observed_head = _git(repo, "rev-parse", "HEAD")
    (repo / "tracked.txt").write_text("candidate\n", encoding="utf-8")
    (repo / "new.txt").write_text("new\n", encoding="utf-8")
    before_status = _git(repo, "status", "--porcelain=v1", "--untracked-files=all")

    with pytest.raises(CommitActuatorBlocked, match="expected HEAD fence failed"):
        _actuator().commit(_command(repo, stale_head))

    assert _git(repo, "rev-parse", "HEAD") == observed_head
    assert _git(repo, "status", "--porcelain=v1", "--untracked-files=all") == before_status
    assert _git(repo, "diff", "--cached", "--name-only") == ""


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("work_lease_token", "work-lease-stale", "stale WorkLease token"),
        (
            "primary_fencing_token",
            "primary-fence-stale",
            "stale Primary Authority fencing token",
        ),
    ],
)
def test_actuator_rejects_stale_authority_before_touching_git_writer(
    repository: tuple[Path, str],
    field: str,
    value: str,
    message: str,
) -> None:
    repo, base_commit = repository
    (repo / "tracked.txt").write_text("candidate\n", encoding="utf-8")
    (repo / "new.txt").write_text("new\n", encoding="utf-8")
    before_status = _git(repo, "status", "--porcelain=v1", "--untracked-files=all")
    authority = _Authority()
    command = replace(_command(repo, base_commit), **{field: value})

    with pytest.raises(CommitActuatorBlocked, match=message):
        _actuator(authority).commit(command)

    assert len(authority.requests) == 1
    assert _git(repo, "rev-parse", "HEAD") == base_commit
    assert _git(repo, "status", "--porcelain=v1", "--untracked-files=all") == before_status
    assert _git(repo, "diff", "--cached", "--name-only") == ""


def test_actuator_rejects_malformed_authority_grant_before_touching_git_writer(
    repository: tuple[Path, str],
) -> None:
    repo, base_commit = repository
    (repo / "tracked.txt").write_text("candidate\n", encoding="utf-8")
    (repo / "new.txt").write_text("new\n", encoding="utf-8")
    before_status = _git(repo, "status", "--porcelain=v1", "--untracked-files=all")

    with pytest.raises(CommitActuatorBlocked, match="invalid grant"):
        _actuator(_MalformedGrantAuthority()).commit(_command(repo, base_commit))

    assert _git(repo, "rev-parse", "HEAD") == base_commit
    assert _git(repo, "status", "--porcelain=v1", "--untracked-files=all") == before_status
    assert _git(repo, "diff", "--cached", "--name-only") == ""


def test_actuator_rejects_grant_for_a_different_write_intent(
    repository: tuple[Path, str],
) -> None:
    repo, base_commit = repository
    (repo / "tracked.txt").write_text("candidate\n", encoding="utf-8")
    (repo / "new.txt").write_text("new\n", encoding="utf-8")

    with pytest.raises(CommitActuatorBlocked, match="requested write intent"):
        _actuator(_MismatchedGrantAuthority()).commit(_command(repo, base_commit))

    assert _git(repo, "rev-parse", "HEAD") == base_commit
    assert _git(repo, "diff", "--cached", "--name-only") == ""


def test_actuator_rejects_grant_for_a_different_owner_generation_ref(
    repository: tuple[Path, str],
) -> None:
    repo, base_commit = repository
    (repo / "tracked.txt").write_text("candidate\n", encoding="utf-8")
    (repo / "new.txt").write_text("new\n", encoding="utf-8")

    with pytest.raises(CommitActuatorBlocked, match="owner reference"):
        _actuator(_MismatchedOwnerAuthority()).commit(
            _command(repo, base_commit)
        )

    assert _git(repo, "rev-parse", "HEAD") == base_commit
    assert _git(repo, "diff", "--cached", "--name-only") == ""


def test_actuator_rejects_content_drift_and_restores_index(
    repository: tuple[Path, str],
) -> None:
    repo, base_commit = repository
    (repo / "tracked.txt").write_text("candidate\n", encoding="utf-8")
    (repo / "new.txt").write_text("new\n", encoding="utf-8")
    command = _command(repo, base_commit)
    drifted = replace(
        command,
        content_hashes=(
            ContentHash("new.txt", "0" * 64),
            command.content_hashes[1],
        ),
    )
    before_status = _git(repo, "status", "--porcelain=v1", "--untracked-files=all")

    with pytest.raises(
        CommitActuatorBlocked,
        match="content drifted before writer",
    ):
        _actuator().commit(drifted)

    assert _git(repo, "rev-parse", "HEAD") == base_commit
    assert _git(repo, "status", "--porcelain=v1", "--untracked-files=all") == before_status
    assert _git(repo, "diff", "--cached", "--name-only") == ""


def test_actuator_rejects_writer_success_without_new_commit(
    repository: tuple[Path, str],
) -> None:
    repo, base_commit = repository
    command = CommitActuation(
        proposal_sha256="a" * 64,
        work_item_id="work-1",
        work_item_version=7,
        commit_owner_generation=3,
        work_lease_token="work-lease-current",
        primary_fencing_token="primary-fence-current",
        repository=str(repo),
        expected_head=base_commit,
        exact_paths=("tracked.txt",),
        content_hashes=(ContentHash("tracked.txt", _hash(repo / "tracked.txt")),),
        message="[change-delivery] no-op",
        actor="commit-worker:test",
    )
    authority = _Authority()

    with pytest.raises(CommitActuatorBlocked, match="without creating a commit"):
        _actuator(authority).commit(command)

    assert len(authority.abandonments) == 1


def test_actuator_validates_complete_hash_scope(
    repository: tuple[Path, str],
) -> None:
    repo, base_commit = repository
    (repo / "tracked.txt").write_text("candidate\n", encoding="utf-8")
    (repo / "new.txt").write_text("new\n", encoding="utf-8")
    command = _command(repo, base_commit)

    with pytest.raises(ValueError, match="exactly match"):
        _actuator().commit(
            replace(command, content_hashes=command.content_hashes[:1])
        )
