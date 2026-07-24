"""Change and Effect Delivery interfaces.

The package owns immutable ChangeSet proposal validation, payload-bound
EffectRequest identity, and narrow authority-fenced provider adapters.
Ownership remains capability-specific: callers may use only the effect
families whose production cutover gate is recorded in
``operations_core_module_design.md``.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
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
from ._publisher_article_sync import (
    PublisherArticleProjection,
    PublisherArticleProjectionReadback,
    PublisherArticleSyncEffectAdapter,
    SupabaseArticleProjectionAdapter,
    encode_publisher_article_sync_payload,
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
    work_lease_token: str
    primary_fencing_token: str
    repository: str
    message: str
    actor: str


@dataclass(frozen=True)
class DeliveryReceipt:
    schema_version: str
    change_set_id: str
    proposal_sha256: str
    work_item_id: str
    work_item_version: int
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
    ) -> None:
        self._clock = clock
        self._id_factory = id_factory
        self._actuator = actuator
        self._settlement = settlement
        self._lock = RLock()
        self._by_id: dict[str, ChangeSetView] = {}
        self._id_by_idempotency_key: dict[str, str] = {}
        self._land_command_sha_by_id: dict[str, str] = {}
        self._actuation_by_id: dict[str, object] = {}
        self._delivery_by_id: dict[str, DeliveryReceipt] = {}

    def propose(self, proposal: ChangeSetProposal) -> ChangeSetView:
        normalized = _normalize_proposal(proposal)
        proposal_sha256 = _proposal_sha256(normalized)

        with self._lock:
            existing_id = self._id_by_idempotency_key.get(
                normalized.idempotency_key
            )
            if existing_id is not None:
                existing = self._by_id[existing_id]
                if existing.proposal_sha256 != proposal_sha256:
                    raise ChangeSetConflict(
                        "ChangeSet idempotency key conflicts with its original payload"
                    )
                return existing

            _validate_workspace(normalized)
            change_set_id = self._id_factory()
            if not change_set_id:
                raise ValueError("ChangeSet id is required")
            if change_set_id in self._by_id:
                raise ValueError(f"duplicate ChangeSet id: {change_set_id}")
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
            self._by_id[view.id] = view
            self._id_by_idempotency_key[view.idempotency_key] = view.id
            return view

    def inspect(self, change_set_id: str) -> ChangeSetView:
        with self._lock:
            try:
                return self._by_id[change_set_id]
            except KeyError as exc:
                raise ValueError(f"unknown ChangeSet: {change_set_id}") from exc

    def land(self, command: LandChangeSet) -> DeliveryReceipt:
        """Land one immutable proposal and durably settle its verified commit.

        Once the actuator reports a commit, retries never invoke the Git writer
        again. They resume only the settlement phase, preventing a transient
        database failure from creating a second commit.
        """

        if self._actuator is None or self._settlement is None:
            raise RuntimeError("Change Delivery landing is not configured")
        normalized = _normalize_land_command(command)
        land_command_sha256 = _land_command_sha256(normalized)

        from ._change_settlement import CommitSettlement
        from ._git_actuator import CommitActuation

        with self._lock:
            try:
                change_set = self._by_id[normalized.change_set_id]
            except KeyError as exc:
                raise ValueError(
                    f"unknown ChangeSet: {normalized.change_set_id}"
                ) from exc

            existing_command_sha = self._land_command_sha_by_id.get(change_set.id)
            if (
                existing_command_sha is not None
                and existing_command_sha != land_command_sha256
            ):
                raise ChangeSetConflict(
                    "ChangeSet landing command conflicts with its original payload"
                )
            existing_delivery = self._delivery_by_id.get(change_set.id)
            if existing_delivery is not None:
                return existing_delivery

            actuation = self._actuation_by_id.get(change_set.id)
            if actuation is None:
                actuation = self._actuator.commit(
                    CommitActuation(
                        proposal_sha256=change_set.proposal_sha256,
                        work_item_id=change_set.work_item_id,
                        work_item_version=change_set.work_item_version,
                        work_lease_token=normalized.work_lease_token,
                        primary_fencing_token=normalized.primary_fencing_token,
                        repository=normalized.repository,
                        expected_head=change_set.base_commit,
                        exact_paths=change_set.exact_paths,
                        content_hashes=change_set.content_hashes,
                        message=normalized.message,
                        actor=normalized.actor,
                    )
                )
                actuation = _validate_actuation_receipt(
                    actuation,
                    change_set=change_set,
                    command=normalized,
                )
                self._land_command_sha_by_id[change_set.id] = land_command_sha256
                self._actuation_by_id[change_set.id] = actuation
                self._by_id[change_set.id] = replace(
                    change_set,
                    status="commit_unsettled",
                )

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
            )
            self._delivery_by_id[change_set.id] = delivery
            self._by_id[change_set.id] = replace(change_set, status="landed")
            return delivery


def _required_text(value: str, *, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} is required")
    return normalized


def _normalize_land_command(command: LandChangeSet) -> LandChangeSet:
    if not isinstance(command, LandChangeSet):
        raise TypeError("LandChangeSet is required")
    repository = Path(command.repository).expanduser()
    if not repository.is_absolute():
        raise ValueError("Change Delivery repository must be an absolute path")
    actor = _required_text(command.actor, field="commit actor")
    if not actor.startswith("commit-worker:"):
        raise ValueError("commit actor must use the commit-worker identity")
    return LandChangeSet(
        change_set_id=_required_text(
            command.change_set_id,
            field="change_set_id",
        ),
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
        actor=actor,
    )


def _land_command_sha256(command: LandChangeSet) -> str:
    encoded = json.dumps(
        {
            "schema_version": "land-change-set.v1",
            "change_set_id": command.change_set_id,
            "work_lease_token": command.work_lease_token,
            "primary_fencing_token": command.primary_fencing_token,
            "repository": command.repository,
            "message": command.message,
            "actor": command.actor,
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
        or receipt.parent_sha != change_set.base_commit
        or receipt.exact_paths != change_set.exact_paths
        or receipt.actor != command.actor
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
) -> DeliveryReceipt:
    if not isinstance(receipt, DeliveryReceipt):
        raise RuntimeError("commit settlement returned an invalid delivery receipt")
    if (
        receipt.schema_version != "change-delivery-receipt.v1"
        or receipt.change_set_id != change_set.id
        or receipt.proposal_sha256 != change_set.proposal_sha256
        or receipt.work_item_id != change_set.work_item_id
        or receipt.work_item_version != change_set.work_item_version
        or receipt.authority_request_sha256
        != actuation.authority_request_sha256
        or receipt.work_lease_ref != actuation.work_lease_ref
        or receipt.primary_authority_ref != actuation.primary_authority_ref
        or receipt.repository != command.repository
        or receipt.commit_sha != actuation.commit_sha
        or receipt.parent_sha != actuation.parent_sha
        or receipt.exact_paths != actuation.exact_paths
        or receipt.actor != command.actor
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
    if proposal.work_item_version <= 0:
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
    "ContentHash",
    "DeliveryReceipt",
    "EffectAttemptOutcome",
    "EffectDelivery",
    "EffectRequest",
    "EffectRequestConflict",
    "EffectView",
    "FailedEffect",
    "LandChangeSet",
    "PublisherArticleProjection",
    "PublisherArticleProjectionReadback",
    "PublisherArticleSyncEffectAdapter",
    "SupabaseArticleProjectionAdapter",
    "encode_publisher_article_sync_payload",
]
