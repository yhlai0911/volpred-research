"""Durable event sources for the physical legacy-retirement gate.

Legacy execution must be observable even when the retired entrypoint is
accidentally re-enabled.  The entrypoint therefore appends an immutable event
before doing business work.  Operations Core later converts the verified event
chain into the typed interval signal consumed by ``legacy_retirement``.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import socket
import stat
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from volpred.ops.delivery.supabase_rpc import (
    ServiceRoleRpcClient,
    runtime_environment,
)
from volpred.ops.legacy_retirement import (
    LegacyRetirementInputError,
    load_verified_retirement_observations,
)

_DIMENSION = "legacy_business_fire"
_ORPHAN_DIMENSION = "orphan_work"
_EVENT_SCHEMA = "legacy-retirement-event.v1"
_ORPHAN_EVENT_SCHEMA = "orphan-work-retirement-event.v1"
_HEAD_SCHEMA = "legacy-retirement-event-head.v1"
_SIGNAL_SCHEMA = "legacy-retirement-signal.v1"
_EVENT_KEYS = frozenset(
    {
        "schema_version",
        "dimension",
        "producer",
        "event_id",
        "sequence",
        "previous_event_sha256",
        "occurred_at",
        "host",
        "pid",
        "event_sha256",
    }
)
_HEX_32 = re.compile(r"[0-9a-f]{32}")
_HEX_64 = re.compile(r"[0-9a-f]{64}")
_SAFE_IDENTITY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,255}")
_ORPHAN_EVENT_KEYS = frozenset(
    {
        "schema_version",
        "dimension",
        "producer",
        "event_id",
        "sequence",
        "previous_event_sha256",
        "occurred_at",
        "workspace",
        "branch",
        "job_id",
        "event_sha256",
    }
)


def _canonical_bytes(payload: Mapping[str, object]) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _utc(value: datetime, *, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise LegacyRetirementInputError(f"{field} must be timezone-aware")
    return value.astimezone(UTC)


def _timestamp(value: object, *, field: str) -> datetime:
    if not isinstance(value, str):
        raise LegacyRetirementInputError(f"{field} must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise LegacyRetirementInputError(f"{field} is invalid") from error
    return _utc(parsed, field=field)


def _reject_symlink_components(root: Path, path: Path) -> None:
    root = root.absolute()
    target = path.absolute()
    try:
        relative = target.relative_to(root)
    except ValueError as error:
        raise LegacyRetirementInputError(
            f"legacy retirement event path escapes root: {path}"
        ) from error
    cursor = root
    for part in relative.parts:
        cursor /= part
        if os.path.lexists(cursor) and cursor.is_symlink():
            raise LegacyRetirementInputError(
                f"legacy retirement event path traverses symlink: {cursor}"
            )


def _read_regular_nofollow(path: Path) -> bytes:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise LegacyRetirementInputError(f"unsafe event ledger file: {path}") from error
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise LegacyRetirementInputError(f"event ledger entry is not a file: {path}")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            return handle.read()
    finally:
        os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _event_sha(event: Mapping[str, object]) -> str:
    unsigned = dict(event)
    unsigned.pop("event_sha256", None)
    return _sha256(_canonical_bytes(unsigned))


def _event_directory(root: Path) -> Path:
    return root / "storage" / "ops" / "legacy_retirement_events" / _DIMENSION


def _head_path(root: Path) -> Path:
    return (
        root
        / "storage"
        / "ops"
        / "legacy_retirement_event_heads"
        / f"{_DIMENSION}.json"
    )


def _dimension_event_directory(root: Path, dimension: str) -> Path:
    return root / "storage" / "ops" / "legacy_retirement_events" / dimension


def _dimension_head_path(root: Path, dimension: str) -> Path:
    return (
        root
        / "storage"
        / "ops"
        / "legacy_retirement_event_heads"
        / f"{dimension}.json"
    )


def _secure_directory(path: Path) -> bool:
    existed = path.exists()
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path, 0o700)
    return existed


def load_verified_legacy_business_fire_events(root: Path) -> list[dict[str, object]]:
    """Verify the complete gap-free event chain; reject deletions and tampering."""

    repo_root = Path(root)
    directory = _event_directory(repo_root)
    head_path = _head_path(repo_root)
    _reject_symlink_components(repo_root, directory)
    _reject_symlink_components(repo_root, head_path)
    if not directory.exists():
        if head_path.exists():
            raise LegacyRetirementInputError(
                "legacy business-fire event ledger was removed behind its durable head"
            )
        return []
    if not directory.is_dir() or directory.is_symlink():
        raise LegacyRetirementInputError("legacy business-fire ledger is unsafe")
    unexpected = [
        path.name
        for path in directory.iterdir()
        if path.name != ".append.lock" and path.suffix != ".json"
    ]
    if unexpected:
        raise LegacyRetirementInputError(
            "legacy business-fire ledger contains unexpected entries"
        )
    events: list[dict[str, object]] = []
    previous_sha: str | None = None
    for expected_sequence, path in enumerate(
        sorted(directory.glob("*.json")),
        start=1,
    ):
        try:
            decoded = json.loads(_read_regular_nofollow(path))
        except (UnicodeError, json.JSONDecodeError) as error:
            raise LegacyRetirementInputError(
                f"legacy business-fire event is invalid: {path.name}"
            ) from error
        if not isinstance(decoded, dict):
            raise LegacyRetirementInputError(
                f"legacy business-fire event is not an object: {path.name}"
            )
        event: dict[str, object] = decoded
        event_id = event.get("event_id")
        event_sha256 = event.get("event_sha256")
        prior = event.get("previous_event_sha256")
        pid = event.get("pid")
        host = event.get("host")
        if (
            set(event) != _EVENT_KEYS
            or event.get("schema_version") != _EVENT_SCHEMA
            or event.get("dimension") != _DIMENSION
            or event.get("producer") != "legacy_entry_tripwire"
            or not isinstance(event_id, str)
            or _HEX_32.fullmatch(event_id) is None
            or event.get("sequence") != expected_sequence
            or event.get("previous_event_sha256") != previous_sha
            or (
                prior is not None
                and (not isinstance(prior, str) or _HEX_64.fullmatch(prior) is None)
            )
            or not isinstance(event_sha256, str)
            or _HEX_64.fullmatch(event_sha256) is None
            or event_sha256 != _event_sha(event)
            or isinstance(pid, bool)
            or not isinstance(pid, int)
            or pid < 1
            or not isinstance(host, str)
            or not host.strip()
            or host != host.strip()
            or path.name != f"{expected_sequence:012d}-{event_id}.json"
        ):
            raise LegacyRetirementInputError(
                f"legacy business-fire event chain is invalid: {path.name}"
            )
        occurred_at = _timestamp(
            event.get("occurred_at"),
            field=f"{path.name}.occurred_at",
        )
        if events and occurred_at < _timestamp(
            events[-1]["occurred_at"],
            field="previous occurred_at",
        ):
            raise LegacyRetirementInputError(
                "legacy business-fire event time regressed"
            )
        previous_sha = str(event["event_sha256"])
        events.append(event)
    if not events:
        if head_path.exists():
            raise LegacyRetirementInputError(
                "legacy business-fire event chain was truncated"
            )
        return []
    if not head_path.exists():
        raise LegacyRetirementInputError(
            "legacy business-fire durable head is missing"
        )
    try:
        decoded_head = json.loads(_read_regular_nofollow(head_path))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise LegacyRetirementInputError(
            "legacy business-fire durable head is invalid"
        ) from error
    if not isinstance(decoded_head, dict):
        raise LegacyRetirementInputError(
            "legacy business-fire durable head is not an object"
        )
    head = decoded_head
    if (
        set(head)
        != {
            "schema_version",
            "dimension",
            "high_watermark",
            "last_event_sha256",
            "updated_at",
            "head_sha256",
        }
        or head.get("schema_version") != _HEAD_SCHEMA
        or head.get("dimension") != _DIMENSION
        or head.get("high_watermark") != len(events)
        or head.get("last_event_sha256") != previous_sha
        or not isinstance(head.get("head_sha256"), str)
        or _HEX_64.fullmatch(str(head["head_sha256"])) is None
    ):
        raise LegacyRetirementInputError(
            "legacy business-fire durable head does not match the event chain"
        )
    unsigned_head = dict(head)
    unsigned_head.pop("head_sha256")
    if head["head_sha256"] != _sha256(_canonical_bytes(unsigned_head)):
        raise LegacyRetirementInputError(
            "legacy business-fire durable head hash is invalid"
        )
    _timestamp(head.get("updated_at"), field="durable head updated_at")
    return events


def append_legacy_business_fire(
    root: Path,
    *,
    occurred_at: datetime | None = None,
) -> Path:
    """Append one unavoidable legacy-entry tripwire event.

    ``occurred_at`` exists for deterministic tests; production CLI callers do
    not expose it and always use the local UTC clock.
    """

    repo_root = Path(root)
    directory = _event_directory(repo_root)
    _reject_symlink_components(repo_root, directory)
    event_root = directory.parent
    event_root_existed = _secure_directory(event_root)
    directory_existed = _secure_directory(directory)
    if not event_root_existed:
        _fsync_directory(event_root.parent)
    if not directory_existed:
        _fsync_directory(directory.parent)
    lock_path = directory / ".append.lock"
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError as error:
        raise LegacyRetirementInputError(
            "legacy business-fire append lock is unsafe"
        ) from error
    with os.fdopen(descriptor, "a+b") as lock:
        os.fchmod(lock.fileno(), 0o600)
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        now = _utc(occurred_at or datetime.now(UTC), field="occurred_at")
        events = load_verified_legacy_business_fire_events(repo_root)
        sequence = len(events) + 1
        event_id = uuid4().hex
        event: dict[str, object] = {
            "schema_version": _EVENT_SCHEMA,
            "dimension": _DIMENSION,
            "producer": "legacy_entry_tripwire",
            "event_id": event_id,
            "sequence": sequence,
            "previous_event_sha256": (
                events[-1]["event_sha256"] if events else None
            ),
            "occurred_at": now.isoformat(),
            "host": socket.gethostname(),
            "pid": os.getpid(),
        }
        event["event_sha256"] = _event_sha(event)
        path = directory / f"{sequence:012d}-{event_id}.json"
        with path.open("xb") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(_canonical_bytes(event))
            handle.flush()
            os.fsync(handle.fileno())
        _fsync_directory(directory)
        head_path = _head_path(repo_root)
        _reject_symlink_components(repo_root, head_path)
        head_directory_existed = _secure_directory(head_path.parent)
        if not head_directory_existed:
            _fsync_directory(head_path.parent.parent)
        head: dict[str, object] = {
            "schema_version": _HEAD_SCHEMA,
            "dimension": _DIMENSION,
            "high_watermark": sequence,
            "last_event_sha256": event["event_sha256"],
            "updated_at": now.isoformat(),
        }
        head["head_sha256"] = _sha256(_canonical_bytes(head))
        temporary_head = head_path.with_name(f".{head_path.name}.{uuid4().hex}.tmp")
        try:
            with temporary_head.open("xb") as handle:
                os.fchmod(handle.fileno(), 0o600)
                handle.write(_canonical_bytes(head))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_head, head_path)
            _fsync_directory(head_path.parent)
        except BaseException:
            temporary_head.unlink(missing_ok=True)
            raise
        return path


def load_verified_orphan_work_events(root: Path) -> list[dict[str, object]]:
    """Verify the complete orphan-work chain and its independent durable head."""

    repo_root = Path(root)
    directory = _dimension_event_directory(repo_root, _ORPHAN_DIMENSION)
    head_path = _dimension_head_path(repo_root, _ORPHAN_DIMENSION)
    _reject_symlink_components(repo_root, directory)
    _reject_symlink_components(repo_root, head_path)
    if not directory.exists():
        if head_path.exists():
            raise LegacyRetirementInputError(
                "orphan-work event ledger was removed behind its durable head"
            )
        return []
    if not directory.is_dir() or directory.is_symlink():
        raise LegacyRetirementInputError("orphan-work event ledger is unsafe")
    unexpected = [
        path.name
        for path in directory.iterdir()
        if path.name != ".append.lock" and path.suffix != ".json"
    ]
    if unexpected:
        raise LegacyRetirementInputError(
            "orphan-work event ledger contains unexpected entries"
        )
    events: list[dict[str, object]] = []
    previous_sha: str | None = None
    for expected_sequence, path in enumerate(
        sorted(directory.glob("*.json")),
        start=1,
    ):
        try:
            decoded = json.loads(_read_regular_nofollow(path))
        except (UnicodeError, json.JSONDecodeError) as error:
            raise LegacyRetirementInputError(
                f"orphan-work event is invalid: {path.name}"
            ) from error
        if not isinstance(decoded, dict):
            raise LegacyRetirementInputError(
                f"orphan-work event is not an object: {path.name}"
            )
        event: dict[str, object] = decoded
        event_id = event.get("event_id")
        event_sha256 = event.get("event_sha256")
        prior = event.get("previous_event_sha256")
        workspace = event.get("workspace")
        branch = event.get("branch")
        job_id = event.get("job_id")
        if (
            set(event) != _ORPHAN_EVENT_KEYS
            or event.get("schema_version") != _ORPHAN_EVENT_SCHEMA
            or event.get("dimension") != _ORPHAN_DIMENSION
            or event.get("producer") != "dispatch_supervisor_orphan_sweep"
            or not isinstance(event_id, str)
            or _HEX_32.fullmatch(event_id) is None
            or event.get("sequence") != expected_sequence
            or prior != previous_sha
            or (
                prior is not None
                and (not isinstance(prior, str) or _HEX_64.fullmatch(prior) is None)
            )
            or not isinstance(event_sha256, str)
            or _HEX_64.fullmatch(event_sha256) is None
            or event_sha256 != _event_sha(event)
            or not isinstance(workspace, str)
            or _SAFE_IDENTITY.fullmatch(workspace) is None
            or not isinstance(branch, str)
            or _SAFE_IDENTITY.fullmatch(branch) is None
            or not isinstance(job_id, str)
            or re.fullmatch(r"[0-9a-f]{8}", job_id) is None
            or path.name != f"{expected_sequence:012d}-{event_id}.json"
        ):
            raise LegacyRetirementInputError(
                f"orphan-work event chain is invalid: {path.name}"
            )
        occurred_at = _timestamp(
            event.get("occurred_at"),
            field=f"{path.name}.occurred_at",
        )
        if events and occurred_at < _timestamp(
            events[-1]["occurred_at"],
            field="previous orphan-work occurred_at",
        ):
            raise LegacyRetirementInputError("orphan-work event time regressed")
        previous_sha = event_sha256
        events.append(event)
    if not events:
        if head_path.exists():
            raise LegacyRetirementInputError("orphan-work event chain was truncated")
        return []
    if not head_path.exists():
        raise LegacyRetirementInputError("orphan-work durable head is missing")
    try:
        decoded_head = json.loads(_read_regular_nofollow(head_path))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise LegacyRetirementInputError("orphan-work durable head is invalid") from error
    if not isinstance(decoded_head, dict):
        raise LegacyRetirementInputError(
            "orphan-work durable head is not an object"
        )
    head = decoded_head
    if (
        set(head)
        != {
            "schema_version",
            "dimension",
            "high_watermark",
            "last_event_sha256",
            "updated_at",
            "head_sha256",
        }
        or head.get("schema_version") != _HEAD_SCHEMA
        or head.get("dimension") != _ORPHAN_DIMENSION
        or head.get("high_watermark") != len(events)
        or head.get("last_event_sha256") != previous_sha
        or not isinstance(head.get("head_sha256"), str)
        or _HEX_64.fullmatch(str(head["head_sha256"])) is None
    ):
        raise LegacyRetirementInputError(
            "orphan-work durable head does not match the event chain"
        )
    unsigned_head = dict(head)
    unsigned_head.pop("head_sha256")
    if head["head_sha256"] != _sha256(_canonical_bytes(unsigned_head)):
        raise LegacyRetirementInputError("orphan-work durable head hash is invalid")
    _timestamp(head.get("updated_at"), field="orphan-work durable head updated_at")
    return events


def append_orphan_work_event(
    root: Path,
    *,
    workspace: str,
    branch: str,
    job_id: str,
    occurred_at: datetime | None = None,
) -> Path:
    """Append one idempotent orphan detection before workspace finalization."""

    for field, value in (
        ("workspace", workspace),
        ("branch", branch),
    ):
        if not isinstance(value, str) or _SAFE_IDENTITY.fullmatch(value) is None:
            raise LegacyRetirementInputError(
                f"orphan-work {field} identity is invalid"
            )
    if not isinstance(job_id, str) or re.fullmatch(r"[0-9a-f]{8}", job_id) is None:
        raise LegacyRetirementInputError("orphan-work job identity is invalid")
    repo_root = Path(root)
    directory = _dimension_event_directory(repo_root, _ORPHAN_DIMENSION)
    _reject_symlink_components(repo_root, directory)
    event_root = directory.parent
    event_root_existed = _secure_directory(event_root)
    directory_existed = _secure_directory(directory)
    if not event_root_existed:
        _fsync_directory(event_root.parent)
    if not directory_existed:
        _fsync_directory(directory.parent)
    lock_path = directory / ".append.lock"
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError as error:
        raise LegacyRetirementInputError(
            "orphan-work append lock is unsafe"
        ) from error
    with os.fdopen(descriptor, "a+b") as lock:
        os.fchmod(lock.fileno(), 0o600)
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        events = load_verified_orphan_work_events(repo_root)
        for existing in events:
            if existing.get("workspace") != workspace:
                continue
            if (
                existing.get("branch") != branch
                or existing.get("job_id") != job_id
            ):
                raise LegacyRetirementInputError(
                    "orphan-work workspace identity drifted"
                )
            return directory / (
                f"{int(existing['sequence']):012d}-{existing['event_id']}.json"
            )
        now = _utc(occurred_at or datetime.now(UTC), field="occurred_at")
        sequence = len(events) + 1
        event_id = uuid4().hex
        event: dict[str, object] = {
            "schema_version": _ORPHAN_EVENT_SCHEMA,
            "dimension": _ORPHAN_DIMENSION,
            "producer": "dispatch_supervisor_orphan_sweep",
            "event_id": event_id,
            "sequence": sequence,
            "previous_event_sha256": (
                events[-1]["event_sha256"] if events else None
            ),
            "occurred_at": now.isoformat(),
            "workspace": workspace,
            "branch": branch,
            "job_id": job_id,
        }
        event["event_sha256"] = _event_sha(event)
        path = directory / f"{sequence:012d}-{event_id}.json"
        with path.open("xb") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(_canonical_bytes(event))
            handle.flush()
            os.fsync(handle.fileno())
        _fsync_directory(directory)
        head_path = _dimension_head_path(repo_root, _ORPHAN_DIMENSION)
        _reject_symlink_components(repo_root, head_path)
        head_directory_existed = _secure_directory(head_path.parent)
        if not head_directory_existed:
            _fsync_directory(head_path.parent.parent)
        head: dict[str, object] = {
            "schema_version": _HEAD_SCHEMA,
            "dimension": _ORPHAN_DIMENSION,
            "high_watermark": sequence,
            "last_event_sha256": event["event_sha256"],
            "updated_at": now.isoformat(),
        }
        head["head_sha256"] = _sha256(_canonical_bytes(head))
        temporary_head = head_path.with_name(
            f".{head_path.name}.{uuid4().hex}.tmp"
        )
        try:
            with temporary_head.open("xb") as handle:
                os.fchmod(handle.fileno(), 0o600)
                handle.write(_canonical_bytes(head))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_head, head_path)
            _fsync_directory(head_path.parent)
        except BaseException:
            temporary_head.unlink(missing_ok=True)
            raise
        return path


def _previous_signal(root: Path) -> Mapping[str, Any] | None:
    return _previous_dimension_signal(root, _DIMENSION)


def _previous_dimension_signal(
    root: Path,
    dimension: str,
) -> Mapping[str, Any] | None:
    observations = load_verified_retirement_observations(root)
    if not observations:
        return None
    latest = observations[-1]
    receipt_id = latest.get("receipt_id")
    if not isinstance(receipt_id, str):
        raise LegacyRetirementInputError("previous observation has no receipt id")
    path = (
        Path(root)
        / "storage"
        / "ops"
        / "legacy_retirement_observations"
        / receipt_id
        / "sources"
        / f"{dimension}.json"
    )
    try:
        decoded = json.loads(_read_regular_nofollow(path))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise LegacyRetirementInputError(
            "previous legacy business-fire signal is invalid"
        ) from error
    if not isinstance(decoded, dict):
        raise LegacyRetirementInputError(
            "previous legacy business-fire signal is not an object"
        )
    return decoded


def _write_typed_signal(
    root: Path,
    *,
    dimension: str,
    signal: Mapping[str, object],
) -> Path:
    signal_dir = root / "storage" / "ops" / "legacy_retirement_signals"
    path = signal_dir / f"{dimension}.json"
    _reject_symlink_components(root, signal_dir)
    signal_dir_existed = _secure_directory(signal_dir)
    if not signal_dir_existed:
        _fsync_directory(signal_dir.parent)
    lock_path = signal_dir / ".materialize.lock"
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError as error:
        raise LegacyRetirementInputError(
            f"{dimension} materializer lock is unsafe"
        ) from error
    with os.fdopen(descriptor, "a+b") as lock:
        os.fchmod(lock.fileno(), 0o600)
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        temporary = signal_dir / f".{path.name}.{uuid4().hex}.tmp"
        try:
            with temporary.open("xb") as handle:
                os.fchmod(handle.fileno(), 0o600)
                handle.write(_canonical_bytes(signal))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            _fsync_directory(signal_dir)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    return path


@contextmanager
def _dimension_materialization_lock(
    root: Path,
    dimension: str,
) -> Iterator[None]:
    signal_dir = root / "storage" / "ops" / "legacy_retirement_signals"
    _reject_symlink_components(root, signal_dir)
    signal_dir_existed = _secure_directory(signal_dir)
    if not signal_dir_existed:
        _fsync_directory(signal_dir.parent)
    lock_path = signal_dir / f".{dimension}.transaction.lock"
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError as error:
        raise LegacyRetirementInputError(
            f"{dimension} transaction lock is unsafe"
        ) from error
    with os.fdopen(descriptor, "a+b") as lock:
        os.fchmod(lock.fileno(), 0o600)
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        yield


@contextmanager
def _dimension_event_append_lock(
    root: Path,
    dimension: str,
) -> Iterator[None]:
    directory = _dimension_event_directory(root, dimension)
    _reject_symlink_components(root, directory)
    event_root = directory.parent
    event_root_existed = _secure_directory(event_root)
    directory_existed = _secure_directory(directory)
    if not event_root_existed:
        _fsync_directory(event_root.parent)
    if not directory_existed:
        _fsync_directory(directory.parent)
    lock_path = directory / ".append.lock"
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError as error:
        raise LegacyRetirementInputError(
            f"{dimension} append lock is unsafe"
        ) from error
    with os.fdopen(descriptor, "a+b") as lock:
        os.fchmod(lock.fileno(), 0o600)
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        yield


def _materialize_local_event_signal_locked(
    root: Path,
    *,
    dimension: str,
    events: list[dict[str, object]],
    observed_at: datetime,
) -> Path:
    if events and _timestamp(
        events[-1]["occurred_at"],
        field=f"{dimension} occurred_at",
    ) > observed_at:
        raise LegacyRetirementInputError(
            f"{dimension} event ledger is from the future"
        )
    previous = _previous_dimension_signal(root, dimension)
    first_signal = previous is None
    if first_signal:
        window_from = (
            _timestamp(
                events[0]["occurred_at"],
                field=f"{dimension} occurred_at",
            )
            if events
            else observed_at
        )
        previous_watermark = 0
    else:
        if (
            previous.get("schema_version") != _SIGNAL_SCHEMA
            or previous.get("dimension") != dimension
            or previous.get("producer") != "operations_core"
        ):
            raise LegacyRetirementInputError(
                f"previous {dimension} signal identity drifted"
            )
        window_from = _timestamp(
            previous.get("window_to"),
            field=f"{dimension} previous window_to",
        )
        previous_watermark = previous.get("high_watermark")
        if (
            isinstance(previous_watermark, bool)
            or not isinstance(previous_watermark, int)
            or previous_watermark < 0
        ):
            raise LegacyRetirementInputError(
                f"previous {dimension} watermark is invalid"
            )
    if window_from > observed_at:
        raise LegacyRetirementInputError(
            f"{dimension} signal interval regressed"
        )
    covered: list[dict[str, object]] = []
    for event in events:
        sequence = event.get("sequence")
        occurred = _timestamp(
            event.get("occurred_at"),
            field=f"{dimension} occurred_at",
        )
        if (
            isinstance(sequence, bool)
            or not isinstance(sequence, int)
            or sequence < 1
        ):
            raise LegacyRetirementInputError(
                f"{dimension} event sequence is invalid"
            )
        if (first_signal or sequence > previous_watermark) and occurred <= observed_at:
            covered.append(event)
    high_watermark = len(events)
    if high_watermark < previous_watermark:
        raise LegacyRetirementInputError(
            f"{dimension} event watermark regressed"
        )
    evidence_refs = [
        f"legacy-retirement-event://{dimension}/{event['event_sha256']}"
        for event in covered
    ] or [
        (
            "legacy-retirement-event-ledger://"
            f"{dimension}/high-watermark/{high_watermark}"
        )
    ]
    signal: dict[str, object] = {
        "schema_version": _SIGNAL_SCHEMA,
        "dimension": dimension,
        "producer": "operations_core",
        "observed_at": observed_at.isoformat(),
        "window_from": window_from.isoformat(),
        "window_to": observed_at.isoformat(),
        "count": len(covered),
        "high_watermark": high_watermark,
        "evidence_refs": evidence_refs,
    }
    return _write_typed_signal(
        root,
        dimension=dimension,
        signal=signal,
    )


def materialize_orphan_work_signal(
    root: Path,
    *,
    observed_at: datetime | None = None,
) -> Path:
    """Advance the orphan-work signal only from the verified sweep ledger."""

    repo_root = Path(root)
    now = _utc(observed_at or datetime.now(UTC), field="observed_at")
    with (
        _dimension_materialization_lock(repo_root, _ORPHAN_DIMENSION),
        _dimension_event_append_lock(repo_root, _ORPHAN_DIMENSION),
    ):
        events = load_verified_orphan_work_events(repo_root)
        return _materialize_local_event_signal_locked(
            repo_root,
            dimension=_ORPHAN_DIMENSION,
            events=events,
            observed_at=now,
        )


def _materialize_duplicate_effect_signal_locked(
    root: Path,
    *,
    rpc_client: ServiceRoleRpcClient | None = None,
) -> Path:
    """Derive duplicate-effect violations from the private DB trigger ledger."""

    repo_root = Path(root)
    previous = _previous_dimension_signal(repo_root, "duplicate_effect")
    after_sequence = 0
    window_from: datetime | None = None
    if previous is not None:
        if (
            previous.get("schema_version") != _SIGNAL_SCHEMA
            or previous.get("dimension") != "duplicate_effect"
            or previous.get("producer") != "operations_core"
        ):
            raise LegacyRetirementInputError(
                "previous duplicate-effect signal identity drifted"
            )
        watermark = previous.get("high_watermark")
        if isinstance(watermark, bool) or not isinstance(watermark, int):
            raise LegacyRetirementInputError(
                "previous duplicate-effect watermark is invalid"
            )
        after_sequence = watermark
        window_from = _timestamp(
            previous.get("window_to"),
            field="duplicate-effect previous window_to",
        )
    client = rpc_client
    if client is None:
        environment = runtime_environment()
        client = ServiceRoleRpcClient(
            supabase_url=environment.get("SUPABASE_URL", ""),
            service_role_key=environment.get("SUPABASE_SERVICE_ROLE_KEY", ""),
        )
    raw = client.call(
        "volpred_read_duplicate_effect_retirement_events",
        {"p_after_sequence": after_sequence},
    )
    if not isinstance(raw, Mapping) or set(raw) != {
        "schema_version",
        "observed_at",
        "after_sequence",
        "high_watermark",
        "events",
    }:
        raise LegacyRetirementInputError(
            "duplicate-effect RPC response schema is invalid"
        )
    if (
        raw.get("schema_version")
        != "duplicate-effect-retirement-events.v1"
        or raw.get("after_sequence") != after_sequence
    ):
        raise LegacyRetirementInputError(
            "duplicate-effect RPC cursor identity drifted"
        )
    observed_at = _timestamp(
        raw.get("observed_at"),
        field="duplicate-effect observed_at",
    )
    high_watermark = raw.get("high_watermark")
    events = raw.get("events")
    if (
        isinstance(high_watermark, bool)
        or not isinstance(high_watermark, int)
        or high_watermark < after_sequence
        or not isinstance(events, list)
        or len(events) != high_watermark - after_sequence
    ):
        raise LegacyRetirementInputError(
            "duplicate-effect RPC sequence coverage is invalid"
        )
    expected_sequence = after_sequence + 1
    evidence_refs: list[str] = []
    earliest_event: datetime | None = None
    for event in events:
        if not isinstance(event, Mapping) or set(event) != {
            "sequence",
            "effect_id",
            "first_delivered_attempt_count",
            "offending_attempt_count",
            "offending_evidence_sha256",
            "detected_at",
        }:
            raise LegacyRetirementInputError(
                "duplicate-effect RPC event schema is invalid"
            )
        effect_id = event.get("effect_id")
        first_attempt = event.get("first_delivered_attempt_count")
        offending_attempt = event.get("offending_attempt_count")
        evidence_sha = event.get("offending_evidence_sha256")
        detected_at = _timestamp(
            event.get("detected_at"),
            field="duplicate-effect detected_at",
        )
        if (
            event.get("sequence") != expected_sequence
            or not isinstance(effect_id, str)
            or not effect_id.strip()
            or isinstance(first_attempt, bool)
            or not isinstance(first_attempt, int)
            or first_attempt < 1
            or isinstance(offending_attempt, bool)
            or not isinstance(offending_attempt, int)
            or offending_attempt < 1
            or offending_attempt == first_attempt
            or not isinstance(evidence_sha, str)
            or _HEX_64.fullmatch(evidence_sha) is None
            or detected_at > observed_at
        ):
            raise LegacyRetirementInputError(
                "duplicate-effect RPC event identity is invalid"
            )
        earliest_event = min(
            detected_at,
            earliest_event or detected_at,
        )
        evidence_refs.append(
            "supabase-effect-delivery://duplicate-effect/"
            f"{expected_sequence}/{effect_id}/{evidence_sha}"
        )
        expected_sequence += 1
    if window_from is None:
        window_from = earliest_event or observed_at
    if window_from > observed_at:
        raise LegacyRetirementInputError(
            "duplicate-effect signal interval regressed"
        )
    if not evidence_refs:
        evidence_refs = [
            (
                "supabase-effect-delivery://duplicate-effect/high-watermark/"
                f"{high_watermark}/backend/{client.backend_sha256}"
            )
        ]
    signal: dict[str, object] = {
        "schema_version": _SIGNAL_SCHEMA,
        "dimension": "duplicate_effect",
        "producer": "operations_core",
        "observed_at": observed_at.isoformat(),
        "window_from": window_from.isoformat(),
        "window_to": observed_at.isoformat(),
        "count": len(events),
        "high_watermark": high_watermark,
        "evidence_refs": evidence_refs,
    }
    return _write_typed_signal(
        repo_root,
        dimension="duplicate_effect",
        signal=signal,
    )


def materialize_duplicate_effect_signal(
    root: Path,
    *,
    rpc_client: ServiceRoleRpcClient | None = None,
) -> Path:
    """Atomically advance the duplicate-effect evidence cursor and signal."""

    repo_root = Path(root)
    with _dimension_materialization_lock(repo_root, "duplicate_effect"):
        return _materialize_duplicate_effect_signal_locked(
            repo_root,
            rpc_client=rpc_client,
        )


def materialize_legacy_business_fire_signal(
    root: Path,
    *,
    observed_at: datetime | None = None,
) -> Path:
    """Derive the canonical interval signal from verified immutable events."""

    repo_root = Path(root)
    now = _utc(observed_at or datetime.now(UTC), field="observed_at")
    signal_dir = repo_root / "storage" / "ops" / "legacy_retirement_signals"
    path = signal_dir / f"{_DIMENSION}.json"
    _reject_symlink_components(repo_root, signal_dir)
    signal_dir_existed = _secure_directory(signal_dir)
    if not signal_dir_existed:
        _fsync_directory(signal_dir.parent)
    lock_path = signal_dir / ".materialize.lock"
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError as error:
        raise LegacyRetirementInputError(
            "legacy business-fire materializer lock is unsafe"
        ) from error
    with os.fdopen(descriptor, "a+b") as lock:
        os.fchmod(lock.fileno(), 0o600)
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        event_directory = _event_directory(repo_root)
        event_root = event_directory.parent
        event_root_existed = _secure_directory(event_root)
        event_directory_existed = _secure_directory(event_directory)
        if not event_root_existed:
            _fsync_directory(event_root.parent)
        if not event_directory_existed:
            _fsync_directory(event_directory.parent)
        event_lock_path = event_directory / ".append.lock"
        event_lock_flags = os.O_CREAT | os.O_RDWR
        if hasattr(os, "O_NOFOLLOW"):
            event_lock_flags |= os.O_NOFOLLOW
        try:
            event_descriptor = os.open(event_lock_path, event_lock_flags, 0o600)
        except OSError as error:
            raise LegacyRetirementInputError(
                "legacy business-fire append lock is unsafe"
            ) from error
        with os.fdopen(event_descriptor, "a+b") as event_lock:
            os.fchmod(event_lock.fileno(), 0o600)
            fcntl.flock(event_lock.fileno(), fcntl.LOCK_EX)
            events = load_verified_legacy_business_fire_events(repo_root)
            if events and _timestamp(
                events[-1]["occurred_at"],
                field="occurred_at",
            ) > now:
                raise LegacyRetirementInputError(
                    "legacy business-fire ledger is from the future"
                )
            previous = _previous_signal(repo_root)
            first_signal = previous is None
            if first_signal:
                window_from = (
                    _timestamp(events[0]["occurred_at"], field="occurred_at")
                    if events
                    else now
                )
                previous_watermark = 0
            else:
                if (
                    previous.get("schema_version") != _SIGNAL_SCHEMA
                    or previous.get("dimension") != _DIMENSION
                    or previous.get("producer") != "operations_core"
                ):
                    raise LegacyRetirementInputError(
                        "previous legacy business-fire signal identity drifted"
                    )
                window_from = _timestamp(
                    previous.get("window_to"),
                    field="window_from",
                )
                previous_watermark = previous.get("high_watermark")
                if isinstance(previous_watermark, bool) or not isinstance(
                    previous_watermark,
                    int,
                ):
                    raise LegacyRetirementInputError(
                        "previous legacy business-fire watermark is invalid"
                    )
            if window_from > now:
                raise LegacyRetirementInputError(
                    "legacy business-fire signal interval regressed"
                )
            covered: list[dict[str, object]] = []
            for event in events:
                occurred = _timestamp(event["occurred_at"], field="occurred_at")
                sequence = event["sequence"]
                if not isinstance(sequence, int):
                    raise LegacyRetirementInputError(
                        "legacy business-fire event sequence is invalid"
                    )
                sequence_is_new = first_signal or sequence > previous_watermark
                if sequence_is_new and occurred <= now:
                    covered.append(event)
            high_watermark = len(events)
            if high_watermark < previous_watermark:
                raise LegacyRetirementInputError(
                    "legacy business-fire event watermark regressed"
                )
            evidence_refs = [
                f"legacy-retirement-event://{_DIMENSION}/{event['event_sha256']}"
                for event in covered
            ] or [
                (
                    "legacy-retirement-event-ledger://"
                    f"{_DIMENSION}/high-watermark/{high_watermark}"
                )
            ]
            signal: dict[str, object] = {
                "schema_version": _SIGNAL_SCHEMA,
                "dimension": _DIMENSION,
                "producer": "operations_core",
                "observed_at": now.isoformat(),
                "window_from": window_from.isoformat(),
                "window_to": now.isoformat(),
                "count": len(covered),
                "high_watermark": high_watermark,
                "evidence_refs": evidence_refs,
            }
            temporary = signal_dir / f".{path.name}.{uuid4().hex}.tmp"
            try:
                with temporary.open("xb") as handle:
                    os.fchmod(handle.fileno(), 0o600)
                    handle.write(_canonical_bytes(signal))
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, path)
                _fsync_directory(signal_dir)
            except BaseException:
                temporary.unlink(missing_ok=True)
                raise
    return path
