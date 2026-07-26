"""Change and Effect Delivery interfaces.

The package owns immutable ChangeSet proposal validation, payload-bound
EffectRequest identity, and narrow authority-fenced provider adapters.
Ownership remains capability-specific: callers may use only the effect
families whose production cutover gate is recorded in
``operations_core_module_design.md``.
"""

from __future__ import annotations

import hashlib
import json
import re
import stat
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from threading import RLock
from typing import Callable

from ._effect import (
    AcknowledgedEffect,
    AcknowledgementExpectation,
    EffectAttemptOutcome,
    EffectDelivery,
    EffectRequest,
    EffectRequestConflict,
    EffectView,
    FailedEffect,
)
from ._publisher_article_reconcile import (
    PreparedPublisherArticleReconcile,
    PublisherArticleReconcileEffectAdapter,
    PublisherArticleReconcilePlan,
    encode_publisher_article_reconcile_payload,
    prepare_publisher_article_reconcile,
)
from ._publisher_article_delete import (
    PUBLISHER_ARTICLE_DELETE_CASCADE_COLUMNS,
    PreparedPublisherArticleDelete,
    PublisherArticleDeleteApprovalReadback,
    PublisherArticleDeleteAuthorization,
    PublisherArticleDeleteCandidateReadback,
    PublisherArticleDeleteEffectAdapter,
    PublisherArticleDeletePlan,
    PublisherArticleDeleteRestoreError,
    PublisherArticleDeleteRestoreExecutor,
    PublisherArticleDeleteRestoreReceipt,
    PublisherArticleDeleteRestoreRequest,
    plan_publisher_article_delete,
    prepare_publisher_article_delete,
)
from ._publisher_article_sync import (
    PublisherArticleProjection,
    PublisherArticleProjectionReadback,
    PublisherArticleSyncEffectAdapter,
    SupabaseArticleProjectionAdapter,
    encode_publisher_article_sync_payload,
)
from .owned_publisher_reconcile import (
    OwnedPublisherArticleReconcile,
    OwnedPublisherReconcileAttempt,
    OwnedPublisherReconcileCommand,
    OwnedPublisherReconcileReceipt,
    OwnedPublisherReconcileRequest,
    PublisherArticleReconcileOwner,
    PublisherArticleReconcileOwnershipLost,
    SupabaseOwnedPublisherReconcileStore,
)
from .owned_publisher_delete import (
    OwnedPublisherArticleDelete,
    OwnedPublisherDeleteAttempt,
    OwnedPublisherDeleteCommand,
    OwnedPublisherDeleteReconciliation,
    OwnedPublisherDeleteReconciliationReceipt,
    OwnedPublisherDeleteReconciliationSummary,
    OwnedPublisherDeleteReceipt,
    OwnedPublisherDeleteRequest,
    PublisherArticleDeleteOwner,
    PublisherArticleDeleteOwnershipLost,
    SupabaseOwnedPublisherDeleteStore,
    SupabasePublisherArticleDeleteApprovalVerifier,
    SupabasePublisherArticleDeleteProjection,
    SupabasePublisherArticleDeleteRestoreProjection,
    SupabasePublisherDeleteProviderFactory,
)
from .owned_publisher_article import (
    OwnedPublisherArticleAttempt,
    OwnedPublisherArticleCommand,
    OwnedPublisherArticleRecovery,
    OwnedPublisherArticleRecoverySummary,
    OwnedPublisherArticleReceipt,
    OwnedPublisherArticleRequest,
    OwnedPublisherArticleSync,
    PublisherArticleSyncOwner,
    PublisherArticleSyncOwnershipLost,
    SupabaseOwnedPublisherArticleStore,
)

_GIT_OBJECT_ID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_SCHEMA_VERSION = "changeset.v1"


@dataclass(frozen=True)
class ContentHash:
    path: str
    sha256: str


@dataclass(frozen=True)
class CheckEvidence:
    name: str
    status: str
    evidence_ref: str


@dataclass(frozen=True)
class CommitWorkerPrincipal:
    """Trusted runtime principal used by the formal commit caller."""

    ref: str


@dataclass(frozen=True)
class ChangeSetProposal:
    idempotency_key: str
    work_item_id: str
    work_item_version: int
    base_commit: str
    workspace_ref: str
    exact_paths: tuple[str, ...]
    content_hashes: tuple[ContentHash, ...]
    required_checks: tuple[CheckEvidence, ...]
    author_ref: str
    author_evidence_ref: str


@dataclass(frozen=True)
class ChangeSetView:
    schema_version: str
    id: str
    idempotency_key: str
    work_item_id: str
    work_item_version: int
    base_commit: str
    workspace_ref: str
    exact_paths: tuple[str, ...]
    content_hashes: tuple[ContentHash, ...]
    required_checks: tuple[CheckEvidence, ...]
    author_ref: str
    author_evidence_ref: str
    proposal_sha256: str
    status: str
    created_at: str


@dataclass(frozen=True)
class LandChangeSet:
    change_set_id: str
    commit_owner_generation: int
    work_lease_token: str
    primary_fencing_token: str
    repository: str
    message: str


@dataclass(frozen=True)
class DeliveryReceipt:
    schema_version: str
    change_set_id: str
    proposal_sha256: str
    work_item_id: str
    work_item_version: int
    commit_owner_generation: int
    commit_owner_ref: str
    authority_request_sha256: str
    work_lease_ref: str
    primary_authority_ref: str
    repository: str
    commit_sha: str
    parent_sha: str
    exact_paths: tuple[str, ...]
    actor: str
    status: str
    actuation_observed_at: str
    settled_at: str
    settlement_ref: str
    settlement_sha256: str


class ChangeSetConflict(ValueError):
    """An idempotency key was replayed with a different proposal payload."""


class ChangeDelivery:
    """Validate and retain immutable candidate ChangeSets.

    ``land`` coordinates the authority-fenced Git actuator with a durable
    post-commit settlement adapter. The adapters remain injected so proposing
    and inspecting ChangeSets stays side-effect free.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], datetime],
        id_factory: Callable[[], str],
        actuator=None,
        settlement=None,
        store=None,
        check_verifier=None,
        commit_worker: CommitWorkerPrincipal | None = None,
    ) -> None:
        from ._change_store import InMemoryChangeSetStore

        self._clock = clock
        self._id_factory = id_factory
        self._actuator = actuator
        self._settlement = settlement
        self._check_verifier = check_verifier
        self._commit_worker = (
            _normalize_commit_worker(commit_worker)
            if commit_worker is not None
            else None
        )
        self._store = (
            store if store is not None else InMemoryChangeSetStore()
        )
        self._lock = RLock()

    def propose(self, proposal: ChangeSetProposal) -> ChangeSetView:
        normalized = _normalize_proposal(proposal)
        proposal_sha256 = _proposal_sha256(normalized)

        with self._lock:
            existing = self._store.load_by_idempotency_key(
                normalized.idempotency_key
            )
            if existing is not None:
                if existing.view.proposal_sha256 != proposal_sha256:
                    raise ChangeSetConflict(
                        "ChangeSet idempotency key conflicts with its original payload"
                    )
                return existing.view

            _validate_workspace(normalized)
            change_set_id = self._id_factory()
            if not change_set_id:
                raise ValueError("ChangeSet id is required")
            observed_at = self._clock()
            if observed_at.tzinfo is None:
                raise ValueError("ChangeSet clock must return a timezone-aware value")
            created_at = observed_at.isoformat()
            view = ChangeSetView(
                schema_version=_SCHEMA_VERSION,
                id=change_set_id,
                idempotency_key=normalized.idempotency_key,
                work_item_id=normalized.work_item_id,
                work_item_version=normalized.work_item_version,
                base_commit=normalized.base_commit,
                workspace_ref=normalized.workspace_ref,
                exact_paths=normalized.exact_paths,
                content_hashes=normalized.content_hashes,
                required_checks=normalized.required_checks,
                author_ref=normalized.author_ref,
                author_evidence_ref=normalized.author_evidence_ref,
                proposal_sha256=proposal_sha256,
                status="proposed",
                created_at=created_at,
            )
            return self._store.create(view).view

    def inspect(self, change_set_id: str) -> ChangeSetView:
        with self._lock:
            return self._store.load(change_set_id).view

    def land(self, command: LandChangeSet) -> DeliveryReceipt:
        """Land one immutable proposal and durably settle its verified commit.

        Once the actuator reports a commit, retries never invoke the Git writer
        again. They resume only the settlement phase, preventing a transient
        database failure from creating a second commit.
        """

        if (
            self._actuator is None
            or self._settlement is None
            or self._check_verifier is None
            or self._commit_worker is None
        ):
            raise RuntimeError("Change Delivery landing is not configured")
        normalized = _normalize_land_command(command)
        commit_worker_ref = self._commit_worker.ref
        land_command_sha256 = _land_command_sha256(
            normalized,
            commit_worker_ref=commit_worker_ref,
        )

        from ._change_settlement import CommitSettlement
        from ._git_actuator import CommitActuation

        with self._lock:
            record = self._store.load(normalized.change_set_id)
            change_set = record.view
            existing_command_sha = record.land_command_sha256
            if (
                existing_command_sha is not None
                and existing_command_sha != land_command_sha256
            ):
                raise ChangeSetConflict(
                    "ChangeSet landing command conflicts with its original payload"
                )
            existing_delivery = record.delivery
            if existing_delivery is not None:
                return existing_delivery

            actuation = record.actuation
            if actuation is None:
                actuation_command = CommitActuation(
                    proposal_sha256=change_set.proposal_sha256,
                    work_item_id=change_set.work_item_id,
                    work_item_version=change_set.work_item_version,
                    commit_owner_generation=(
                        normalized.commit_owner_generation
                    ),
                    work_lease_token=normalized.work_lease_token,
                    primary_fencing_token=normalized.primary_fencing_token,
                    repository=normalized.repository,
                    expected_head=change_set.base_commit,
                    exact_paths=change_set.exact_paths,
                    content_hashes=change_set.content_hashes,
                    message=normalized.message,
                    actor=commit_worker_ref,
                    workspace_ref=change_set.workspace_ref,
                )
                actuation = self._actuator.recover(actuation_command)
                if actuation is None:
                    self._check_verifier.verify(change_set)
                    actuation = self._actuator.commit(actuation_command)
                actuation = _validate_actuation_receipt(
                    actuation,
                    change_set=change_set,
                    command=normalized,
                    commit_worker_ref=commit_worker_ref,
                )
                record = self._store.checkpoint_actuation(
                    change_set_id=change_set.id,
                    proposal_sha256=change_set.proposal_sha256,
                    land_command_sha256=land_command_sha256,
                    actuation=actuation,
                )
                change_set = record.view

            delivery = self._settlement.settle(
                CommitSettlement(
                    change_set_id=change_set.id,
                    repository=normalized.repository,
                    work_lease_token=normalized.work_lease_token,
                    primary_fencing_token=normalized.primary_fencing_token,
                    actuation=actuation,
                )
            )
            delivery = _validate_delivery_receipt(
                delivery,
                change_set=change_set,
                command=normalized,
                actuation=actuation,
                commit_worker_ref=commit_worker_ref,
            )
            landed = self._store.mark_landed(
                change_set_id=change_set.id,
                proposal_sha256=change_set.proposal_sha256,
                land_command_sha256=land_command_sha256,
                delivery=delivery,
            )
            if landed.delivery is None:
                raise RuntimeError(
                    "ChangeSet store omitted the durable delivery receipt"
                )
            return landed.delivery


def _required_text(value: str, *, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} is required")
    return normalized


def _normalize_commit_worker(
    principal: CommitWorkerPrincipal,
) -> CommitWorkerPrincipal:
    if not isinstance(principal, CommitWorkerPrincipal):
        raise TypeError("CommitWorkerPrincipal is required")
    ref = _required_text(principal.ref, field="commit worker principal")
    if not ref.startswith("commit-worker:"):
        raise ValueError(
            "commit worker principal must use the commit-worker identity"
        )
    return CommitWorkerPrincipal(ref=ref)


def _normalize_land_command(command: LandChangeSet) -> LandChangeSet:
    if not isinstance(command, LandChangeSet):
        raise TypeError("LandChangeSet is required")
    repository = Path(command.repository).expanduser()
    if not repository.is_absolute():
        raise ValueError("Change Delivery repository must be an absolute path")
    if (
        isinstance(command.commit_owner_generation, bool)
        or command.commit_owner_generation <= 0
    ):
        raise ValueError("commit_owner_generation must be positive")
    return LandChangeSet(
        change_set_id=_required_text(
            command.change_set_id,
            field="change_set_id",
        ),
        commit_owner_generation=command.commit_owner_generation,
        work_lease_token=_required_text(
            command.work_lease_token,
            field="work_lease_token",
        ),
        primary_fencing_token=_required_text(
            command.primary_fencing_token,
            field="primary_fencing_token",
        ),
        repository=str(repository.resolve()),
        message=_required_text(command.message, field="commit message"),
    )


def _land_command_sha256(
    command: LandChangeSet,
    *,
    commit_worker_ref: str,
) -> str:
    encoded = json.dumps(
        {
            "schema_version": "land-change-set.v1",
            "change_set_id": command.change_set_id,
            "commit_owner_generation": command.commit_owner_generation,
            "work_lease_token": command.work_lease_token,
            "primary_fencing_token": command.primary_fencing_token,
            "repository": command.repository,
            "message": command.message,
            "actor": commit_worker_ref,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_actuation_receipt(
    receipt,
    *,
    change_set: ChangeSetView,
    command: LandChangeSet,
    commit_worker_ref: str,
):
    from ._git_actuator import CommitActuationReceipt, CommitActuatorBlocked

    if not isinstance(receipt, CommitActuationReceipt):
        raise CommitActuatorBlocked(
            "commit actuator returned an invalid actuation receipt"
        )
    try:
        observed_at = datetime.fromisoformat(receipt.observed_at)
    except (TypeError, ValueError):
        observed_at = None
    if (
        observed_at is None
        or observed_at.tzinfo is None
        or observed_at.utcoffset() is None
    ):
        raise CommitActuatorBlocked(
            "commit actuator observed_at must be a timezone-aware timestamp"
        )
    if (
        receipt.schema_version != "commit-actuation.v1"
        or receipt.proposal_sha256 != change_set.proposal_sha256
        or receipt.work_item_id != change_set.work_item_id
        or receipt.work_item_version != change_set.work_item_version
        or receipt.commit_owner_generation
        != command.commit_owner_generation
        or not receipt.commit_owner_ref.strip()
        or receipt.parent_sha != change_set.base_commit
        or receipt.exact_paths != change_set.exact_paths
        or receipt.actor != commit_worker_ref
        or receipt.status != "committed"
        or _SHA256.fullmatch(receipt.authority_request_sha256) is None
        or _GIT_OBJECT_ID.fullmatch(receipt.commit_sha) is None
        or not receipt.work_lease_ref.strip()
        or not receipt.primary_authority_ref.strip()
    ):
        raise CommitActuatorBlocked(
            "commit actuator receipt does not match the immutable ChangeSet"
        )
    return receipt


def _validate_delivery_receipt(
    receipt,
    *,
    change_set: ChangeSetView,
    command: LandChangeSet,
    actuation,
    commit_worker_ref: str,
) -> DeliveryReceipt:
    if not isinstance(receipt, DeliveryReceipt):
        raise RuntimeError("commit settlement returned an invalid delivery receipt")
    if (
        receipt.schema_version != "change-delivery-receipt.v1"
        or receipt.change_set_id != change_set.id
        or receipt.proposal_sha256 != change_set.proposal_sha256
        or receipt.work_item_id != change_set.work_item_id
        or receipt.work_item_version != change_set.work_item_version
        or receipt.commit_owner_generation
        != command.commit_owner_generation
        or receipt.commit_owner_ref != actuation.commit_owner_ref
        or receipt.authority_request_sha256
        != actuation.authority_request_sha256
        or receipt.work_lease_ref != actuation.work_lease_ref
        or receipt.primary_authority_ref != actuation.primary_authority_ref
        or receipt.repository != command.repository
        or receipt.commit_sha != actuation.commit_sha
        or receipt.parent_sha != actuation.parent_sha
        or receipt.exact_paths != actuation.exact_paths
        or receipt.actor != commit_worker_ref
        or receipt.status != "landed"
        or receipt.actuation_observed_at != actuation.observed_at
        or not receipt.settled_at.strip()
        or not receipt.settlement_ref.strip()
        or _SHA256.fullmatch(receipt.settlement_sha256) is None
    ):
        raise RuntimeError(
            "durable commit settlement read-back does not match its actuation"
        )
    return receipt


def _normalize_exact_path(raw: str) -> str:
    if not raw or "\0" in raw or "\\" in raw:
        raise ValueError(f"unsafe ChangeSet path: {raw!r}")
    path = PurePosixPath(raw)
    if (
        path.is_absolute()
        or raw != path.as_posix()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.parts[0] == ".git"
    ):
        raise ValueError(
            "ChangeSet path must be one normalized repo-relative file: "
            f"{raw!r}"
        )
    return path.as_posix()


def _normalize_proposal(proposal: ChangeSetProposal) -> ChangeSetProposal:
    idempotency_key = _required_text(
        proposal.idempotency_key, field="idempotency_key"
    )
    work_item_id = _required_text(proposal.work_item_id, field="work_item_id")
    if (
        isinstance(proposal.work_item_version, bool)
        or not isinstance(proposal.work_item_version, int)
        or proposal.work_item_version <= 0
    ):
        raise ValueError("work_item_version must be positive")
    if _GIT_OBJECT_ID.fullmatch(proposal.base_commit) is None:
        raise ValueError("base_commit must be a lowercase Git object id")

    workspace = Path(proposal.workspace_ref).expanduser()
    if not workspace.is_absolute():
        raise ValueError("workspace_ref must be an absolute path")
    workspace_ref = str(workspace.resolve())

    paths = tuple(_normalize_exact_path(path) for path in proposal.exact_paths)
    if not paths:
        raise ValueError("ChangeSet must name at least one exact path")
    if len(paths) != len(set(paths)):
        raise ValueError("ChangeSet exact paths must be unique")
    paths = tuple(sorted(paths))

    hashes_by_path: dict[str, ContentHash] = {}
    for entry in proposal.content_hashes:
        path = _normalize_exact_path(entry.path)
        if path in hashes_by_path:
            raise ValueError(f"duplicate content hash path: {path}")
        if _SHA256.fullmatch(entry.sha256) is None:
            raise ValueError(
                f"content hash for {path} must be 64 lowercase hex characters"
            )
        hashes_by_path[path] = ContentHash(path=path, sha256=entry.sha256)
    if set(hashes_by_path) != set(paths):
        raise ValueError("content hashes must match the exact path set")
    content_hashes = tuple(hashes_by_path[path] for path in paths)

    if not proposal.required_checks:
        raise ValueError("ChangeSet must include required check evidence")
    checks_by_name: dict[str, CheckEvidence] = {}
    for check in proposal.required_checks:
        name = _required_text(check.name, field="check name")
        if name in checks_by_name:
            raise ValueError(f"duplicate required check: {name}")
        if check.status != "passed":
            raise ValueError(f"required check did not pass: {name}")
        evidence_ref = _required_text(
            check.evidence_ref, field=f"evidence for check {name}"
        )
        checks_by_name[name] = CheckEvidence(
            name=name,
            status="passed",
            evidence_ref=evidence_ref,
        )

    return ChangeSetProposal(
        idempotency_key=idempotency_key,
        work_item_id=work_item_id,
        work_item_version=proposal.work_item_version,
        base_commit=proposal.base_commit,
        workspace_ref=workspace_ref,
        exact_paths=paths,
        content_hashes=content_hashes,
        required_checks=tuple(
            checks_by_name[name] for name in sorted(checks_by_name)
        ),
        author_ref=_required_text(proposal.author_ref, field="author_ref"),
        author_evidence_ref=_required_text(
            proposal.author_evidence_ref, field="author_evidence_ref"
        ),
    )


def _proposal_sha256(proposal: ChangeSetProposal) -> str:
    payload = {
        "schema_version": _SCHEMA_VERSION,
        "idempotency_key": proposal.idempotency_key,
        "work_item_id": proposal.work_item_id,
        "work_item_version": proposal.work_item_version,
        "base_commit": proposal.base_commit,
        "workspace_ref": proposal.workspace_ref,
        "exact_paths": list(proposal.exact_paths),
        "content_hashes": [
            {"path": item.path, "sha256": item.sha256}
            for item in proposal.content_hashes
        ],
        "required_checks": [
            {
                "name": item.name,
                "status": item.status,
                "evidence_ref": item.evidence_ref,
            }
            for item in proposal.required_checks
        ],
        "author_ref": proposal.author_ref,
        "author_evidence_ref": proposal.author_evidence_ref,
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _run_git(workspace: Path, *args: str) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(workspace), *args],
            capture_output=True,
            check=False,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError(f"cannot inspect ChangeSet workspace: {exc}") from exc
    if proc.returncode != 0:
        detail = (
            (proc.stderr or proc.stdout)
            .decode("utf-8", errors="replace")
            .strip()
        )
        raise ValueError(f"cannot inspect ChangeSet workspace: {detail[:300]}")
    return proc.stdout.decode("utf-8", errors="surrogateescape")


def _dirty_paths(workspace: Path) -> tuple[str, ...]:
    raw = _run_git(
        workspace,
        "-c",
        "core.quotepath=false",
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
    )
    entries = raw.split("\0")
    dirty: list[str] = []
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if not entry:
            continue
        if len(entry) < 4 or entry[2] != " ":
            raise ValueError("unrecognized Git status entry in ChangeSet workspace")
        state = entry[:2]
        path = entry[3:]
        if "R" in state or "C" in state:
            if index < len(entries):
                index += 1
            raise ValueError(
                "renamed or copied paths are not supported in this ChangeSet slice"
            )
        if state[0] not in {" ", "?"}:
            raise ValueError("ChangeSet workspace index must be clean")
        if "D" in state:
            raise ValueError(
                "deleted paths are not supported in this ChangeSet slice"
            )
        dirty.append(_normalize_exact_path(path))
    if len(dirty) != len(set(dirty)):
        raise ValueError("Git reported duplicate dirty paths")
    return tuple(sorted(dirty))


def _tree_git_mode(workspace: Path, revision: str, path: str) -> str | None:
    raw = _run_git(
        workspace,
        "--literal-pathspecs",
        "ls-tree",
        "-z",
        revision,
        "--",
        path,
    )
    entries = [entry for entry in raw.split("\0") if entry]
    if not entries:
        return None
    if len(entries) != 1:
        raise ValueError(f"cannot resolve exact Git tree mode for ChangeSet path: {path}")
    metadata, separator, observed_path = entries[0].partition("\t")
    fields = metadata.split()
    if (
        separator != "\t"
        or observed_path != path
        or len(fields) != 3
        or fields[1] != "blob"
    ):
        raise ValueError(f"unsupported Git tree entry for ChangeSet path: {path}")
    return fields[0]


def _regular_file_git_mode(mode: int) -> str:
    return "100755" if stat.S_IMODE(mode) & 0o111 else "100644"


def _validate_workspace(proposal: ChangeSetProposal) -> None:
    workspace = Path(proposal.workspace_ref)
    if not workspace.is_dir():
        raise ValueError("ChangeSet workspace does not exist or is not a directory")

    top = Path(
        _run_git(
            workspace,
            "rev-parse",
            "--path-format=absolute",
            "--show-toplevel",
        ).strip()
    ).resolve()
    if top != workspace:
        raise ValueError("workspace_ref must name the linked worktree root")
    common_dir = Path(
        _run_git(
            workspace,
            "rev-parse",
            "--path-format=absolute",
            "--git-common-dir",
        ).strip()
    ).resolve()
    if common_dir.parent.resolve() == workspace:
        raise ValueError("canonical checkout cannot be used as a ChangeSet workspace")

    head = _run_git(workspace, "rev-parse", "--verify", "HEAD").strip()
    if head != proposal.base_commit:
        raise ValueError(
            f"ChangeSet base commit drifted: expected {proposal.base_commit}, found {head}"
        )
    observed_paths = _dirty_paths(workspace)
    if observed_paths != proposal.exact_paths:
        raise ValueError(
            "ChangeSet exact paths do not match the complete workspace dirty set"
        )

    expected_hashes = {
        entry.path: entry.sha256 for entry in proposal.content_hashes
    }
    for relative in proposal.exact_paths:
        candidate = workspace / relative
        if candidate.is_symlink():
            raise ValueError(f"ChangeSet path may not be a symlink: {relative}")
        resolved = candidate.resolve()
        try:
            resolved.relative_to(workspace)
        except ValueError as exc:
            raise ValueError(
                f"ChangeSet path escapes its workspace: {relative}"
            ) from exc
        if not resolved.is_file():
            raise ValueError(f"ChangeSet path is not a regular file: {relative}")
        base_mode = _tree_git_mode(workspace, proposal.base_commit, relative)
        expected_mode = base_mode or "100644"
        if expected_mode not in {"100644", "100755"}:
            raise ValueError(
                f"unsupported base Git file mode for ChangeSet path: {relative}"
            )
        observed_mode = _regular_file_git_mode(resolved.stat().st_mode)
        if observed_mode != expected_mode:
            raise ValueError(
                "Git file mode changes are outside ChangeSet content identity: "
                f"{relative}"
            )
        try:
            payload = resolved.read_bytes()
        except OSError as exc:
            raise ValueError(
                f"cannot read ChangeSet path {relative}: {exc}"
            ) from exc
        observed_hash = hashlib.sha256(payload).hexdigest()
        if observed_hash != expected_hashes[relative]:
            raise ValueError(f"content hash drift for ChangeSet path: {relative}")


__all__ = [
    "AcknowledgedEffect",
    "AcknowledgementExpectation",
    "ChangeDelivery",
    "ChangeSetConflict",
    "ChangeSetProposal",
    "ChangeSetView",
    "CheckEvidence",
    "CommitWorkerPrincipal",
    "ContentHash",
    "DeliveryReceipt",
    "EffectAttemptOutcome",
    "EffectDelivery",
    "EffectRequest",
    "EffectRequestConflict",
    "EffectView",
    "FailedEffect",
    "LandChangeSet",
    "OwnedPublisherArticleAttempt",
    "OwnedPublisherArticleCommand",
    "OwnedPublisherArticleRecovery",
    "OwnedPublisherArticleRecoverySummary",
    "OwnedPublisherArticleReceipt",
    "OwnedPublisherArticleRequest",
    "OwnedPublisherArticleSync",
    "OwnedPublisherArticleDelete",
    "OwnedPublisherArticleReconcile",
    "OwnedPublisherDeleteAttempt",
    "OwnedPublisherDeleteCommand",
    "OwnedPublisherDeleteReconciliation",
    "OwnedPublisherDeleteReconciliationReceipt",
    "OwnedPublisherDeleteReconciliationSummary",
    "OwnedPublisherDeleteReceipt",
    "OwnedPublisherDeleteRequest",
    "OwnedPublisherReconcileAttempt",
    "OwnedPublisherReconcileCommand",
    "OwnedPublisherReconcileReceipt",
    "OwnedPublisherReconcileRequest",
    "PUBLISHER_ARTICLE_DELETE_CASCADE_COLUMNS",
    "PreparedPublisherArticleDelete",
    "PreparedPublisherArticleReconcile",
    "PublisherArticleDeleteApprovalReadback",
    "PublisherArticleDeleteAuthorization",
    "PublisherArticleDeleteCandidateReadback",
    "PublisherArticleDeleteEffectAdapter",
    "PublisherArticleDeleteOwner",
    "PublisherArticleDeleteOwnershipLost",
    "PublisherArticleDeletePlan",
    "PublisherArticleDeleteRestoreError",
    "PublisherArticleDeleteRestoreExecutor",
    "PublisherArticleDeleteRestoreReceipt",
    "PublisherArticleDeleteRestoreRequest",
    "PublisherArticleProjection",
    "PublisherArticleProjectionReadback",
    "PublisherArticleReconcileEffectAdapter",
    "PublisherArticleReconcileOwner",
    "PublisherArticleReconcileOwnershipLost",
    "PublisherArticleReconcilePlan",
    "PublisherArticleSyncEffectAdapter",
    "PublisherArticleSyncOwner",
    "PublisherArticleSyncOwnershipLost",
    "SupabaseArticleProjectionAdapter",
    "SupabaseOwnedPublisherArticleStore",
    "SupabaseOwnedPublisherDeleteStore",
    "SupabaseOwnedPublisherReconcileStore",
    "SupabasePublisherArticleDeleteApprovalVerifier",
    "SupabasePublisherArticleDeleteProjection",
    "SupabasePublisherArticleDeleteRestoreProjection",
    "SupabasePublisherDeleteProviderFactory",
    "encode_publisher_article_reconcile_payload",
    "encode_publisher_article_sync_payload",
    "prepare_publisher_article_reconcile",
    "plan_publisher_article_delete",
    "prepare_publisher_article_delete",
]
