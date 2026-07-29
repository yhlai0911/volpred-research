"""Durable global producer-custody bindings for dispatch fires.

The dispatch state and per-workspace receipts are useful projections, but
neither is a global recovery boundary: state can be replaced after a crash and
not every fire owns a workspace.  This append-only ledger binds the kernel
custody captured immediately before ``Popen`` to the immutable
``(job_id, attempt)`` generation.

Readers are deliberately strict.  A missing or unreadable ledger is
*unavailable*, while an existing, valid empty ledger means there is no pending
custody.  Corruption is never skipped in favour of an older event because that
could make a live producer disappear from recovery.
"""

from __future__ import annotations

import fcntl
import json
import os
import signal
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO

from volpred.ops import termination

RECEIPTS_RELPATH = (
    Path("storage") / "ops" / "producer_custody_receipts.jsonl"
)
SCHEMA_VERSION = 1
_BOUND = "producer_custody_bound"
_RELEASED = "producer_custody_released"


class CustodyReceiptError(RuntimeError):
    """Base class for custody-ledger failures."""


class CustodyLedgerUnavailable(CustodyReceiptError):
    """The ledger cannot be observed, so pending custody is unknown."""


class CustodyLedgerInvalid(CustodyReceiptError):
    """The ledger is malformed or violates the append-only state contract."""


class CustodyBindingConflict(CustodyReceiptError):
    """One immutable fire generation was rebound to different custody."""


class CustodyDrainUnconfirmed(CustodyReceiptError):
    """A caller tried to release custody without a positive drain result."""


def initialize_producer_custody_ledger(
    repo_root: Path,
    *,
    migration_confirmed_quiescent: bool,
) -> bool:
    """Create the empty ledger only at an explicitly proven migration boundary.

    Runtime recovery never auto-creates a missing ledger: after activation,
    absence could mean lost custody evidence.  The one-time cutover caller must
    therefore attest that the old supervisor coalition is positively idle.
    """
    if migration_confirmed_quiescent is not True:
        raise CustodyDrainUnconfirmed(
            "custody ledger initialization requires proven quiescence"
        )
    source = _ledger_path(repo_root)
    try:
        parent_created = not source.parent.exists()
        source.parent.mkdir(parents=True, exist_ok=True)
        if parent_created:
            _fsync_directory(source.parent.parent)
        created = not source.exists()
        with source.open("a+b") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                _validated_states(
                    _read_locked(handle, source=source),
                    source=source,
                )
                handle.flush()
                os.fsync(handle.fileno())
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        if created:
            _fsync_directory(source.parent)
        return created
    except CustodyReceiptError:
        raise
    except OSError as exc:
        raise CustodyLedgerUnavailable(
            f"custody ledger cannot be initialized: {source}"
        ) from exc


def _ledger_path(repo_root: Path) -> Path:
    return Path(repo_root) / RECEIPTS_RELPATH


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _timestamp(value: str | None, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty ISO-8601 timestamp")
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must include a timezone")
    return text


def _key(job_id: str, attempt: int) -> tuple[str, int]:
    normalized_job_id = str(job_id or "").strip()
    if not normalized_job_id:
        raise ValueError("job_id must be non-empty")
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt <= 0:
        raise ValueError("attempt must be a positive integer")
    return normalized_job_id, attempt


def _custody_copy(custody: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(custody, dict) or not custody:
        raise ValueError("custody must be a non-empty mapping")
    try:
        encoded = json.dumps(
            custody,
            ensure_ascii=False,
            sort_keys=True,
            allow_nan=False,
        )
        copied = json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise ValueError("custody must be JSON serializable") from exc
    if not isinstance(copied, dict) or not copied:
        raise ValueError("custody must be a non-empty mapping")
    return copied


def _decode_lines(raw: bytes, *, source: Path) -> list[dict[str, Any]]:
    if not raw:
        return []
    if not raw.endswith(b"\n"):
        raise CustodyLedgerInvalid(
            f"custody ledger has a partial final line: {source}"
        )
    try:
        text = raw.decode("utf-8")
    except UnicodeError as exc:
        raise CustodyLedgerInvalid(
            f"custody ledger is not valid UTF-8: {source}"
        ) from exc
    events: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line:
            raise CustodyLedgerInvalid(
                f"custody ledger has a blank line at {source}:{line_number}"
            )
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise CustodyLedgerInvalid(
                f"custody ledger has invalid JSON at {source}:{line_number}"
            ) from exc
        if not isinstance(event, dict):
            raise CustodyLedgerInvalid(
                f"custody event must be an object at {source}:{line_number}"
            )
        events.append(event)
    return events


def _read_locked(handle: BinaryIO, *, source: Path) -> list[dict[str, Any]]:
    handle.seek(0)
    try:
        return _decode_lines(handle.read(), source=source)
    except OSError as exc:
        raise CustodyLedgerUnavailable(
            f"custody ledger cannot be read: {source}"
        ) from exc


def _validated_states(
    events: list[dict[str, Any]],
    *,
    source: Path,
) -> dict[tuple[str, int], dict[str, Any]]:
    states: dict[tuple[str, int], dict[str, Any]] = {}
    bound_fields = {
        "schema_version",
        "event",
        "job_id",
        "attempt",
        "custody",
        "bound_at",
    }
    released_fields = {
        *bound_fields,
        "drain_confirmed",
        "drain_confirmed_at",
        "released_at",
    }
    for line_number, event in enumerate(events, start=1):
        try:
            event_name = event.get("event")
            expected_fields = (
                bound_fields
                if event_name == _BOUND
                else released_fields
                if event_name == _RELEASED
                else None
            )
            if expected_fields is None:
                raise ValueError(f"unknown event {event_name!r}")
            if set(event) != expected_fields:
                raise ValueError(
                    f"fields {sorted(event)} do not match "
                    f"{sorted(expected_fields)}"
                )
            if event.get("schema_version") != SCHEMA_VERSION:
                raise ValueError("unsupported schema_version")
            generation = _key(event.get("job_id"), event.get("attempt"))
            custody = _custody_copy(event.get("custody"))
            bound_at = _timestamp(event.get("bound_at"), field="bound_at")
        except (TypeError, ValueError) as exc:
            raise CustodyLedgerInvalid(
                f"invalid custody event at {source}:{line_number}: {exc}"
            ) from exc

        if event_name == _BOUND:
            if generation in states:
                raise CustodyLedgerInvalid(
                    f"duplicate custody binding at {source}:{line_number}"
                )
            states[generation] = {
                "job_id": generation[0],
                "attempt": generation[1],
                "custody": custody,
                "bound_at": bound_at,
                "released_at": None,
            }
            continue

        state = states.get(generation)
        if state is None:
            raise CustodyLedgerInvalid(
                f"custody release has no matching binding at "
                f"{source}:{line_number}"
            )
        if state["released_at"] is not None:
            raise CustodyLedgerInvalid(
                f"duplicate custody release at {source}:{line_number}"
            )
        if event.get("drain_confirmed") is not True:
            raise CustodyLedgerInvalid(
                f"custody release lacks positive drain at "
                f"{source}:{line_number}"
            )
        try:
            drain_confirmed_at = _timestamp(
                event.get("drain_confirmed_at"),
                field="drain_confirmed_at",
            )
            released_at = _timestamp(
                event.get("released_at"),
                field="released_at",
            )
        except ValueError as exc:
            raise CustodyLedgerInvalid(
                f"invalid custody release timestamp at "
                f"{source}:{line_number}: {exc}"
            ) from exc
        if custody != state["custody"] or bound_at != state["bound_at"]:
            raise CustodyLedgerInvalid(
                f"custody release generation does not match its binding at "
                f"{source}:{line_number}"
            )
        state["drain_confirmed_at"] = drain_confirmed_at
        state["released_at"] = released_at
    return states


def _append_locked(
    handle: BinaryIO,
    *,
    source: Path,
    event: dict[str, Any],
) -> None:
    try:
        encoded = (
            json.dumps(
                event,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
        handle.seek(0, os.SEEK_END)
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    except (OSError, TypeError, ValueError) as exc:
        raise CustodyLedgerUnavailable(
            f"custody ledger append failed: {source}"
        ) from exc


def _fsync_directory(directory: Path) -> None:
    try:
        directory_fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except OSError as exc:
        raise CustodyLedgerUnavailable(
            f"custody ledger directory fsync failed: {directory}"
        ) from exc


def bind_producer_custody(
    repo_root: Path,
    *,
    job_id: str,
    attempt: int,
    custody: dict[str, Any],
    bound_at: str | None = None,
) -> bool:
    """Bind one immutable fire generation before ``Popen``.

    Returns ``True`` when a new event was appended and ``False`` for an
    identical replay.  Rebinding the same ``job_id`` + ``attempt`` to different
    custody raises :class:`CustodyBindingConflict`.
    """

    generation = _key(job_id, attempt)
    normalized_custody = _custody_copy(custody)
    normalized_bound_at = _timestamp(
        bound_at if bound_at is not None else _utc_now(),
        field="bound_at",
    )
    source = _ledger_path(repo_root)
    try:
        # Runtime bind never creates the ledger. Creation is a one-time,
        # explicitly-quiescent migration act; after activation a missing file
        # means custody evidence may have been lost and must fail closed.
        with source.open("r+b") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                states = _validated_states(
                    _read_locked(handle, source=source),
                    source=source,
                )
                current = states.get(generation)
                if current is not None:
                    if current["custody"] != normalized_custody:
                        raise CustodyBindingConflict(
                            "producer custody generation is already bound "
                            f"to different custody: {generation!r}"
                        )
                    if current["released_at"] is not None:
                        raise CustodyBindingConflict(
                            "released producer custody generation is terminal "
                            f"and cannot be rebound: {generation!r}"
                        )
                    return False
                _append_locked(
                    handle,
                    source=source,
                    event={
                        "schema_version": SCHEMA_VERSION,
                        "event": _BOUND,
                        "job_id": generation[0],
                        "attempt": generation[1],
                        "custody": normalized_custody,
                        "bound_at": normalized_bound_at,
                    },
                )
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        return True
    except FileNotFoundError as exc:
        raise CustodyLedgerUnavailable(
            f"custody ledger is absent: {source}"
        ) from exc
    except CustodyReceiptError:
        raise
    except OSError as exc:
        raise CustodyLedgerUnavailable(
            f"custody ledger cannot be bound: {source}"
        ) from exc


def read_pending_producer_custodies(
    repo_root: Path,
) -> list[dict[str, Any]]:
    """Return every bound generation that lacks a confirmed release.

    A missing/unreadable file raises :class:`CustodyLedgerUnavailable`; a
    valid existing empty file returns ``[]``.  Malformed history raises
    :class:`CustodyLedgerInvalid` rather than silently skipping a generation.
    """

    source = _ledger_path(repo_root)
    try:
        with source.open("rb") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_SH)
            try:
                states = _validated_states(
                    _read_locked(handle, source=source),
                    source=source,
                )
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except FileNotFoundError as exc:
        raise CustodyLedgerUnavailable(
            f"custody ledger is absent: {source}"
        ) from exc
    except CustodyReceiptError:
        raise
    except OSError as exc:
        raise CustodyLedgerUnavailable(
            f"custody ledger cannot be read: {source}"
        ) from exc
    return [
        {
            "job_id": state["job_id"],
            "attempt": state["attempt"],
            "custody": dict(state["custody"]),
            "bound_at": state["bound_at"],
        }
        for state in states.values()
        if state["released_at"] is None
    ]


def release_producer_custody(
    repo_root: Path,
    *,
    job_id: str,
    attempt: int,
    drain_confirmed: bool,
    released_at: str | None = None,
) -> bool:
    """Release exact custody only after a positive drain result.

    Returns ``True`` when the release was appended.  An already-released or
    never-bound generation returns ``False`` and cannot affect another
    attempt.  ``drain_confirmed`` must be the literal boolean ``True``.
    """

    if drain_confirmed is not True:
        raise CustodyDrainUnconfirmed(
            "producer custody release requires a positive drain result"
        )
    generation = _key(job_id, attempt)
    normalized_released_at = _timestamp(
        released_at if released_at is not None else _utc_now(),
        field="released_at",
    )
    source = _ledger_path(repo_root)
    try:
        with source.open("r+b") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                states = _validated_states(
                    _read_locked(handle, source=source),
                    source=source,
                )
                current = states.get(generation)
                if current is None or current["released_at"] is not None:
                    return False
                _append_locked(
                    handle,
                    source=source,
                    event={
                        "schema_version": SCHEMA_VERSION,
                        "event": _RELEASED,
                        "job_id": generation[0],
                        "attempt": generation[1],
                        "custody": dict(current["custody"]),
                        "bound_at": current["bound_at"],
                        "drain_confirmed": True,
                        "drain_confirmed_at": normalized_released_at,
                        "released_at": normalized_released_at,
                    },
                )
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        return True
    except FileNotFoundError as exc:
        raise CustodyLedgerUnavailable(
            f"custody ledger is absent: {source}"
        ) from exc
    except CustodyReceiptError:
        raise
    except OSError as exc:
        raise CustodyLedgerUnavailable(
            f"custody ledger cannot be released: {source}"
        ) from exc


def reconcile_pending_producer_custodies(
    repo_root: Path,
) -> dict[str, Any]:
    """Drain and release every nonterminal global custody generation.

    The kernel coalition + unique IDs are the only kill authority.  Any
    unverified probe or failed drain remains pending and makes ``ok=False``;
    callers must not admit a new producer in that state.
    """
    from . import procutil  # local import avoids a module-initialization cycle

    pending = read_pending_producer_custodies(repo_root)
    released: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    ledger_path = (
        Path(repo_root) / "storage" / "ops" / "termination_intents.jsonl"
    )
    for binding in pending:
        custody = binding["custody"]
        members = procutil.producer_cohort_members_checked(
            0,
            job_id=str(binding["job_id"]),
            custody=custody,
        )
        if members:
            intent = termination.arm(
                target_kind="pid",
                target_id=int(members[0]),
                target_identity=(
                    "producer-custody:"
                    f"{custody.get('resource_coalition_id', 'unknown')}"
                ),
                reason="global_producer_custody_recovery",
                actor="dispatch-supervisor.custody-receipt",
                signal_sequence=[signal.SIGTERM, signal.SIGKILL],
                job_id=str(binding["job_id"]),
                attempt=int(binding["attempt"]),
                ledger_path=ledger_path,
            )
            if procutil.kill_producer_cohort(
                custody,
                intent=intent,
                ledger_path=ledger_path,
            ):
                members = []
            else:
                members = procutil.producer_cohort_members_checked(
                    0,
                    job_id=str(binding["job_id"]),
                    custody=custody,
                )
        if members != []:
            unresolved.append(
                {
                    "job_id": binding["job_id"],
                    "attempt": binding["attempt"],
                    "members": members,
                }
            )
            continue
        release_producer_custody(
            repo_root,
            job_id=str(binding["job_id"]),
            attempt=int(binding["attempt"]),
            drain_confirmed=True,
        )
        released.append(
            {
                "job_id": binding["job_id"],
                "attempt": binding["attempt"],
            }
        )
    return {
        "ok": not unresolved,
        "pending_count": len(pending),
        "released": released,
        "unresolved": unresolved,
    }
