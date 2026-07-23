"""Atomic legacy task-pool suspension for direct-execution cutovers.

This module owns one narrow policy: while direct execution is enabled, the
legacy ``next_tasks.json`` queue may finish or remove rows that already exist,
but no writer may introduce a new task identity.  The low-level queue writer
enforces that rule, so producer-specific prompts and refill scripts cannot
silently bypass it.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from volpred.canonical_write import guard_canonical_write


class TaskPoolAdmissionClosed(RuntimeError):
    """A write tried to admit new work while the legacy pool is suspended."""


class TaskPoolModeConflict(RuntimeError):
    """The queue owner state changed before a requested transition committed."""


@dataclass(frozen=True)
class TaskPoolMode:
    enabled: bool
    mode: str
    activated_at: str | None = None
    activated_by: str | None = None
    reason: str | None = None
    backup_path: str | None = None
    backup_sha256: str | None = None
    backup_bytes: int | None = None
    backup_task_count: int | None = None
    preserve_task_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class TaskPoolModeEvidence:
    mode: TaskPoolMode
    state_path: str
    sha256: str
    byte_count: int


@dataclass(frozen=True)
class DirectModeReceipt:
    queue_path: str
    state_path: str
    backup_path: str
    backup_sha256: str
    backup_bytes: int
    backup_task_count: int
    preserved_task_ids: tuple[str, ...]
    cleared_task_count: int
    activated_at: str


@dataclass(frozen=True)
class DirectModeReconcileReceipt:
    queue_path: str
    state_path: str
    removed_task_ids: tuple[str, ...]
    retained_task_ids: tuple[str, ...]
    reconciled_at: str
    reconciled_by: str
    reason: str


@dataclass(frozen=True)
class RestoreReceipt:
    queue_path: str
    state_path: str
    backup_path: str
    restored_task_count: int
    restored_at: str


def task_pool_mode_path(queue_path: str | Path) -> Path:
    """Return the mode state paired with a legacy queue path."""

    queue = Path(queue_path)
    return queue.parent / "ops" / "task_pool_mode.json"


def _mode_from_payload(payload: Any) -> TaskPoolMode:
    if not isinstance(payload, dict):
        raise ValueError("task-pool mode state must be an object")
    enabled = payload.get("enabled", False)
    mode = payload.get("mode", "queued_execution")
    if not isinstance(enabled, bool):
        raise ValueError("task-pool mode 'enabled' must be boolean")
    if not isinstance(mode, str) or not mode:
        raise ValueError("task-pool mode 'mode' must be a non-empty string")
    preserve = payload.get("preserve_task_ids", [])
    if not isinstance(preserve, list) or not all(
        isinstance(item, str) and item for item in preserve
    ):
        raise ValueError("task-pool mode 'preserve_task_ids' must be string ids")
    return TaskPoolMode(
        enabled=enabled,
        mode=mode,
        activated_at=_optional_string(payload, "activated_at"),
        activated_by=_optional_string(payload, "activated_by"),
        reason=_optional_string(payload, "reason"),
        backup_path=_optional_string(payload, "backup_path"),
        backup_sha256=_optional_string(payload, "backup_sha256"),
        backup_bytes=_optional_int(payload, "backup_bytes"),
        backup_task_count=_optional_int(payload, "backup_task_count"),
        preserve_task_ids=tuple(preserve),
    )


def _optional_string(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"task-pool mode {key!r} must be a string")
    return value


def _optional_int(payload: dict[str, Any], key: str) -> int | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"task-pool mode {key!r} must be a non-negative integer")
    return value


def load_task_pool_mode(state_path: str | Path) -> TaskPoolMode:
    """Read the direct-execution gate; a missing state means queued execution."""

    path = Path(state_path)
    if not path.exists():
        return TaskPoolMode(enabled=False, mode="queued_execution")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"task-pool mode state unreadable: {exc}") from exc
    return _mode_from_payload(payload)


def load_task_pool_mode_evidence(
    state_path: str | Path,
) -> TaskPoolModeEvidence:
    """Parse mode and evidence identity from one immutable byte snapshot."""
    path = Path(state_path)
    try:
        payload = path.read_bytes()
        decoded = json.loads(payload)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"task-pool mode evidence unreadable: {exc}") from exc
    return TaskPoolModeEvidence(
        mode=_mode_from_payload(decoded),
        state_path=str(path.resolve()),
        sha256=hashlib.sha256(payload).hexdigest(),
        byte_count=len(payload),
    )


def _load_expected_mode_evidence(
    state_path: Path,
    *,
    expected_state_sha256: str,
) -> TaskPoolModeEvidence:
    if not isinstance(expected_state_sha256, str) or not all(
        ch in "0123456789abcdef" for ch in expected_state_sha256
    ) or len(expected_state_sha256) != 64:
        raise ValueError(
            "expected_state_sha256 must be 64 lowercase hexadecimal characters"
        )
    evidence = load_task_pool_mode_evidence(state_path)
    if evidence.sha256 != expected_state_sha256:
        raise TaskPoolModeConflict(
            "task-pool owner compare-and-set failed: "
            f"expected {expected_state_sha256}, observed {evidence.sha256}"
        )
    return evidence


def _task_ids(rows: Iterable[Any]) -> tuple[set[str], int]:
    ids: set[str] = set()
    anonymous = 0
    for row in rows:
        if not isinstance(row, dict):
            anonymous += 1
            continue
        task_id = row.get("id")
        if not isinstance(task_id, str) or not task_id:
            anonymous += 1
            continue
        ids.add(task_id)
    return ids, anonymous


def enforce_task_pool_write(
    *,
    state_path: str | Path,
    existing_tasks: list[Any],
    proposed_tasks: list[Any],
) -> None:
    """Reject new task identities while allowing lifecycle updates/removals."""

    try:
        mode = load_task_pool_mode(state_path)
    except ValueError as exc:
        raise TaskPoolAdmissionClosed(str(exc)) from exc
    if not mode.enabled:
        return
    if mode.mode != "direct_execution":
        raise TaskPoolAdmissionClosed(
            f"unsupported enabled task-pool mode {mode.mode!r}; failing closed"
        )
    existing_ids, existing_anonymous = _task_ids(existing_tasks)
    proposed_ids, proposed_anonymous = _task_ids(proposed_tasks)
    added = sorted(proposed_ids - existing_ids)
    anonymous_growth = max(0, proposed_anonymous - existing_anonymous)
    if added or anonymous_growth:
        details = []
        if added:
            details.append(f"new task id(s): {', '.join(added[:8])}")
        if anonymous_growth:
            details.append(f"new anonymous row(s): {anonymous_growth}")
        raise TaskPoolAdmissionClosed(
            "legacy task-pool admission is closed for direct execution; "
            + "; ".join(details)
        )


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    guard_canonical_write(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode()
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temp_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def _validate_identity(value: str, *, field: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field} must not be empty")
    return cleaned


def _backup_name(now: str, digest: str) -> str:
    stamp = "".join(ch for ch in now if ch.isdigit())[:14]
    if len(stamp) != 14:
        raise ValueError("now must contain a full ISO date and time")
    return f"{stamp}Z_next_tasks_{digest[:12]}.json"


def enter_direct_execution_mode(
    *,
    queue_path: str | Path,
    state_path: str | Path,
    backup_dir: str | Path,
    activated_by: str,
    reason: str,
    preserve_task_ids: Iterable[str] = (),
    expected_state_sha256: str | None,
    now: str,
) -> DirectModeReceipt:
    """Back up exact queue bytes, enable admission denial, then clear the pool.

    All three actions happen while holding the queue's exclusive lock.  The
    state is enabled before the queue is rewritten, so a crash can leave a
    safely closed full queue but never an open empty queue without a backup.
    """

    queue = Path(queue_path)
    state = Path(state_path)
    backups = Path(backup_dir)
    actor = _validate_identity(activated_by, field="activated_by")
    rationale = _validate_identity(reason, field="reason")
    preserve = tuple(
        dict.fromkeys(
            _validate_identity(x, field="preserve_task_id")
            for x in preserve_task_ids
        )
    )

    guard_canonical_write(queue)
    guard_canonical_write(state)
    guard_canonical_write(backups)
    if not queue.exists():
        if expected_state_sha256 is None:
            if state.exists():
                observed = load_task_pool_mode_evidence(state).sha256
                raise TaskPoolModeConflict(
                    "task-pool owner compare-and-set failed: "
                    f"expected absent state, observed {observed}"
                )
        else:
            _load_expected_mode_evidence(
                state,
                expected_state_sha256=expected_state_sha256,
            )
        raise ValueError("next_tasks queue does not exist")

    with queue.open("r+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            if expected_state_sha256 is None:
                if state.exists():
                    observed = load_task_pool_mode_evidence(state).sha256
                    raise TaskPoolModeConflict(
                        "task-pool owner compare-and-set failed: "
                        f"expected absent state, observed {observed}"
                    )
            else:
                evidence = _load_expected_mode_evidence(
                    state,
                    expected_state_sha256=expected_state_sha256,
                )
                source_mode = evidence.mode
                if source_mode.enabled and source_mode.mode == "direct_execution":
                    raise ValueError("task pool is already in direct-execution mode")
                if source_mode.enabled or source_mode.mode != "queued_execution":
                    raise ValueError(
                        "enter-direct requires disabled queued-execution owner state"
                    )
            original = queue.read_bytes()
            try:
                tasks = json.loads(original.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise ValueError(f"next_tasks queue is unreadable: {exc}") from exc
            if not isinstance(tasks, list):
                raise ValueError("next_tasks queue root must be a list")
            task_ids, anonymous = _task_ids(tasks)
            if anonymous:
                raise ValueError(
                    f"next_tasks queue has {anonymous} row(s) without a valid id"
                )
            missing = sorted(set(preserve) - task_ids)
            if missing:
                raise ValueError(f"preserved task id(s) not found: {', '.join(missing)}")

            digest = hashlib.sha256(original).hexdigest()
            backups.mkdir(parents=True, exist_ok=True)
            backup = backups / _backup_name(now, digest)
            try:
                with backup.open("xb") as backup_handle:
                    backup_handle.write(original)
                    backup_handle.flush()
                    os.fsync(backup_handle.fileno())
            except FileExistsError:
                if backup.read_bytes() != original:
                    raise ValueError(f"backup collision with different bytes: {backup}")
            verified = backup.read_bytes()
            if verified != original or hashlib.sha256(verified).hexdigest() != digest:
                raise RuntimeError("task-pool backup read-back verification failed")

            retained = [
                task
                for task in tasks
                if isinstance(task, dict) and task.get("id") in set(preserve)
            ]
            state_payload: dict[str, Any] = {
                "schema": 1,
                "enabled": True,
                "mode": "direct_execution",
                "activated_at": now,
                "activated_by": actor,
                "reason": rationale,
                "queue_path": str(queue.resolve()),
                "backup_path": str(backup.resolve()),
                "backup_sha256": digest,
                "backup_bytes": len(original),
                "backup_task_count": len(tasks),
                "preserve_task_ids": list(preserve),
                "cleared_task_count": len(tasks) - len(retained),
            }
            _atomic_write_json(state, state_payload)

            from volpred.ops.next_tasks import write_tasks_to_handle

            write_tasks_to_handle(handle, retained)
            handle.flush()
            os.fsync(handle.fileno())
            if json.loads(queue.read_text(encoding="utf-8")) != retained:
                raise RuntimeError("task-pool clear read-back verification failed")
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    return DirectModeReceipt(
        queue_path=str(queue.resolve()),
        state_path=str(state.resolve()),
        backup_path=str(backup.resolve()),
        backup_sha256=digest,
        backup_bytes=len(original),
        backup_task_count=len(tasks),
        preserved_task_ids=preserve,
        cleared_task_count=len(tasks) - len(retained),
        activated_at=now,
    )


def reconcile_direct_execution_pool(
    *,
    queue_path: str | Path,
    state_path: str | Path,
    reconciled_by: str,
    reason: str,
    expected_state_sha256: str,
    now: str,
) -> DirectModeReconcileReceipt:
    """Remove rows outside the active direct-mode receipt's preserve set.

    This is the recovery path for a writer process that was already running
    before the admission guard shipped and therefore retained an old append
    function in memory. It deliberately does not replace the activation state
    or its verified backup pointer.
    """

    queue = Path(queue_path)
    state = Path(state_path)
    actor = _validate_identity(reconciled_by, field="reconciled_by")
    rationale = _validate_identity(reason, field="reason")

    guard_canonical_write(queue)
    if not queue.exists():
        raise ValueError("next_tasks queue does not exist")

    retained: list[Any] = []
    removed_ids: list[str] = []
    with queue.open("r+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            evidence = _load_expected_mode_evidence(
                state,
                expected_state_sha256=expected_state_sha256,
            )
            mode = evidence.mode
            if not mode.enabled or mode.mode != "direct_execution":
                raise ValueError("task pool is not in direct-execution mode")
            preserve = set(mode.preserve_task_ids)
            raw = handle.read()
            try:
                tasks = json.loads(raw) if raw.strip() else []
            except json.JSONDecodeError as exc:
                raise ValueError(f"next_tasks queue is unreadable: {exc}") from exc
            if not isinstance(tasks, list):
                raise ValueError("next_tasks queue root must be a list")
            _, anonymous = _task_ids(tasks)
            if anonymous:
                raise ValueError(
                    f"next_tasks queue has {anonymous} row(s) without a valid id"
                )
            for task in tasks:
                task_id = str(task["id"])
                if task_id in preserve:
                    retained.append(task)
                else:
                    removed_ids.append(task_id)
            if removed_ids:
                from volpred.ops.next_tasks import write_tasks_to_handle

                write_tasks_to_handle(handle, retained)
                handle.flush()
                os.fsync(handle.fileno())
                handle.seek(0)
                if json.load(handle) != retained:
                    raise RuntimeError("task-pool reconcile read-back verification failed")
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    return DirectModeReconcileReceipt(
        queue_path=str(queue.resolve()),
        state_path=str(state.resolve()),
        removed_task_ids=tuple(removed_ids),
        retained_task_ids=tuple(str(task["id"]) for task in retained),
        reconciled_at=now,
        reconciled_by=actor,
        reason=rationale,
    )


def restore_task_pool_backup(
    *,
    queue_path: str | Path,
    state_path: str | Path,
    backup_path: str | Path,
    restored_by: str,
    reason: str,
    expected_state_sha256: str,
    now: str,
) -> RestoreReceipt:
    """Restore the verified cutover backup when the live pool is empty."""

    queue = Path(queue_path)
    state = Path(state_path)
    backup = Path(backup_path)
    actor = _validate_identity(restored_by, field="restored_by")
    rationale = _validate_identity(reason, field="reason")

    guard_canonical_write(queue)
    if not queue.exists():
        _load_expected_mode_evidence(
            state,
            expected_state_sha256=expected_state_sha256,
        )
        raise ValueError("next_tasks queue does not exist")
    with queue.open("r+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            evidence = _load_expected_mode_evidence(
                state,
                expected_state_sha256=expected_state_sha256,
            )
            mode = evidence.mode
            if not mode.enabled or mode.mode != "direct_execution":
                raise ValueError("task pool is not in direct-execution mode")
            if (
                mode.backup_path is None
                or backup.resolve() != Path(mode.backup_path).resolve()
            ):
                raise ValueError(
                    "backup path does not match the active direct-mode receipt"
                )
            payload = backup.read_bytes()
            digest = hashlib.sha256(payload).hexdigest()
            if digest != mode.backup_sha256:
                raise ValueError(
                    "backup sha256 does not match the active direct-mode receipt"
                )
            try:
                restored = json.loads(payload.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise ValueError(f"backup is unreadable: {exc}") from exc
            if not isinstance(restored, list):
                raise ValueError("backup root must be a list")
            current = json.load(handle)
            if not isinstance(current, list):
                raise ValueError("next_tasks queue root must be a list")
            if current:
                raise ValueError("refusing restore while the live task pool is non-empty")
            disabled_payload = {
                "schema": 1,
                "enabled": False,
                "mode": "queued_execution",
                "restored_at": now,
                "restored_by": actor,
                "reason": rationale,
                "restored_backup_path": str(backup.resolve()),
                "restored_backup_sha256": digest,
                "restored_task_count": len(restored),
            }
            _atomic_write_json(state, disabled_payload)
            try:
                from volpred.ops.next_tasks import write_tasks_to_handle

                write_tasks_to_handle(handle, restored)
                handle.flush()
                os.fsync(handle.fileno())
            except Exception:
                _atomic_write_json(
                    state,
                    {
                        "schema": 1,
                        "enabled": True,
                        "mode": "direct_execution",
                        "activated_at": mode.activated_at,
                        "activated_by": mode.activated_by,
                        "reason": mode.reason,
                        "backup_path": mode.backup_path,
                        "backup_sha256": mode.backup_sha256,
                        "backup_bytes": mode.backup_bytes,
                        "backup_task_count": mode.backup_task_count,
                        "preserve_task_ids": list(mode.preserve_task_ids),
                    },
                )
                raise
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    return RestoreReceipt(
        queue_path=str(queue.resolve()),
        state_path=str(state.resolve()),
        backup_path=str(backup.resolve()),
        restored_task_count=len(restored),
        restored_at=now,
    )
