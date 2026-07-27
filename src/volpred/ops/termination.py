"""Durable intent receipts for every system-owned process termination.

POSIX wait status says *which* signal ended a process, but not who sent it.
Without a receipt written before the syscall, a supervisor-owned timeout and an
unknown external SIGTERM are observationally identical after the fact.

This module is the only production owner of ``os.kill`` / ``os.killpg``. Callers
first arm an exact target + signal sequence, then pass the returned capability
to a send function. Each append is protected by a stable flock and fsynced.
Only a ``signal_result(status=sent)`` is attribution evidence; an armed intent
alone never turns a later external signal into a system-owned one.
"""
from __future__ import annotations

import fcntl
import json
import os
import signal
import stat
import subprocess
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal

from volpred.ops.diagnostics import warn

TargetKind = Literal["pid", "pgid"]
DEFAULT_LEDGER_PATH = (
    Path(__file__).resolve().parents[3]
    / "storage"
    / "ops"
    / "termination_intents.jsonl"
)
DEFAULT_MATCH_MAX_AGE_S = 6 * 60 * 60
LEDGER_PATH_ENV = "VOLPRED_TERMINATION_LEDGER_PATH"


class TerminationIntentError(RuntimeError):
    """Base class for fail-closed termination contract violations."""


class TerminationIntentRequired(TerminationIntentError):
    """A production signal path was called without an armed intent."""


class TerminationIntentMismatch(TerminationIntentError):
    """The requested target or signal is outside the armed capability."""


def ledger_for_state(state_path: Path | str) -> Path:
    """Keep termination evidence beside the supervisor state it explains."""
    return Path(state_path).with_name("termination_intents.jsonl")


@dataclass(frozen=True)
class TerminationIntent:
    intent_id: str
    target_kind: TargetKind
    target_id: int
    reason: str
    actor: str
    signal_sequence: tuple[int, ...]
    armed_at: str
    target_identity: str
    job_id: str | None = None
    attempt: int | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_signal_sequence(values: list[int] | tuple[int, ...]) -> tuple[int, ...]:
    normalized = tuple(int(value) for value in values)
    if not normalized or any(value <= 0 for value in normalized):
        raise ValueError("signal_sequence must contain one or more terminating signals")
    return normalized


def _target_identity(target_kind: TargetKind, target_id: int) -> str:
    """Start-time fingerprint for the pid that pins this pid/pgid generation."""
    try:
        result = subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(target_id)],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise TerminationIntentError(
            f"cannot fingerprint {target_kind}={target_id}: {exc}"
        ) from exc
    value = result.stdout.strip()
    return value if result.returncode == 0 and value else f"absent:{target_kind}:{target_id}"


def _pgid_has_members(pgid: int) -> bool:
    try:
        result = subprocess.run(
            ["ps", "-o", "pid=", "-g", str(pgid)],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise TerminationIntentError(
            f"cannot verify pgid={pgid} membership: {exc}"
        ) from exc
    return result.returncode == 0 and bool(result.stdout.strip())


def _root_identity_matches(intent: TerminationIntent) -> bool:
    current = _target_identity(intent.target_kind, intent.target_id)
    if current == intent.target_identity:
        return True
    if (
        intent.target_kind == "pgid"
        and current == f"absent:pgid:{intent.target_id}"
        and not intent.target_identity.startswith("absent:")
    ):
        # The leader may exit on TERM while descendants keep the original PGID
        # alive. A PGID cannot be reused until that group drains.
        return _pgid_has_members(intent.target_id)
    return False


def _ledger_path(path: Path | str | None) -> Path:
    override = os.environ.get(LEDGER_PATH_ENV)
    if override and (path is None or Path(path) == DEFAULT_LEDGER_PATH):
        return Path(override)
    return Path(path) if path is not None else DEFAULT_LEDGER_PATH


def _append_event(
    path: Path, event: dict, *, reject_duplicate_attempt: bool = False,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(path.name + ".lock")
    if path.is_symlink() or lock_path.is_symlink():
        raise TerminationIntentError("termination ledger/lock must not be a symlink")
    lock_flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    ledger_flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_APPEND
        | getattr(os, "O_NOFOLLOW", 0)
    )
    encoded = (
        json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    lock_fd = os.open(lock_path, lock_flags, 0o600)
    try:
        _validate_ledger_fd(lock_fd)
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        ledger_fd = os.open(path, ledger_flags, 0o600)
        end = 0
        write_started = False
        try:
            _validate_ledger_fd(ledger_fd)
            end = os.lseek(ledger_fd, 0, os.SEEK_END)
            previous = b""
            if end:
                read_fd = os.open(
                    path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                )
                try:
                    os.lseek(read_fd, end - 1, os.SEEK_SET)
                    last = os.read(read_fd, 1)
                    if last != b"\n" or reject_duplicate_attempt:
                        os.lseek(read_fd, 0, os.SEEK_SET)
                        previous = os.read(read_fd, end)
                    if last != b"\n":
                        newline = previous.rfind(b"\n")
                        os.ftruncate(ledger_fd, newline + 1)
                        end = newline + 1
                        previous = previous[:end]
                finally:
                    os.close(read_fd)
            if reject_duplicate_attempt:
                for line in previous.splitlines():
                    try:
                        prior = json.loads(line)
                    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                        warn(
                            "termination_intent",
                            "ignored malformed row while enforcing one-use intent",
                            err=str(exc),
                            ledger=str(path),
                        )
                        continue
                    if (
                        isinstance(prior, dict)
                        and prior.get("event") == "signal_attempted"
                        and prior.get("intent_id") == event.get("intent_id")
                        and prior.get("actual_target_kind")
                        == event.get("actual_target_kind")
                        and _event_int(prior, "actual_target_id")
                        == _event_int(event, "actual_target_id")
                        and _event_int(prior, "signum")
                        == _event_int(event, "signum")
                    ):
                        raise TerminationIntentMismatch(
                            "intent already attempted this exact target and signal"
                        )
            written = os.write(ledger_fd, encoded)
            write_started = True
            if written != len(encoded):
                raise OSError(
                    f"short termination-ledger write {written}/{len(encoded)}"
                )
            os.fsync(ledger_fd)
            # Repeat the parent barrier on every committed row. If an earlier
            # first-creation barrier failed, the files still exist, so an
            # existence-based shortcut could otherwise skip the only barrier
            # that makes those directory entries crash-durable.
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except BaseException:
            if write_started:
                # A complete newline is not attribution evidence until every
                # durability barrier succeeds. Roll it back while the append
                # lock is still held so readers can never observe a false
                # signal_attempted/signal_result event.
                os.ftruncate(ledger_fd, end)
                os.fsync(ledger_fd)
            raise
        finally:
            os.close(ledger_fd)
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


def _validate_ledger_fd(fd: int) -> None:
    details = os.fstat(fd)
    if not stat.S_ISREG(details.st_mode):
        raise TerminationIntentError("termination ledger must be a regular file")
    if details.st_uid != os.getuid():
        raise TerminationIntentError("termination ledger must be owned by current uid")
    if details.st_mode & 0o022:
        raise TerminationIntentError(
            "termination ledger must not be group/other writable"
        )


def _intent_fields(intent: TerminationIntent) -> dict:
    return {
        "intent_id": intent.intent_id,
        "target_kind": intent.target_kind,
        "target_id": intent.target_id,
        "reason": intent.reason,
        "actor": intent.actor,
        "signal_sequence": list(intent.signal_sequence),
        "armed_at": intent.armed_at,
        "target_identity": intent.target_identity,
        "job_id": intent.job_id,
        "attempt": intent.attempt,
    }


def arm(
    *,
    target_kind: TargetKind,
    target_id: int,
    reason: str,
    actor: str,
    signal_sequence: list[int] | tuple[int, ...],
    job_id: str | None = None,
    attempt: int | None = None,
    ledger_path: Path | str | None = None,
    target_identity: str | None = None,
) -> TerminationIntent:
    if target_kind not in {"pid", "pgid"}:
        raise ValueError(f"unsupported target_kind: {target_kind}")
    if int(target_id) <= 0:
        raise ValueError("target_id must be positive")
    if not str(reason).strip() or not str(actor).strip():
        raise ValueError("reason and actor are required")
    armed_at = _now_iso()
    intent = TerminationIntent(
        intent_id=uuid.uuid4().hex,
        target_kind=target_kind,
        target_id=int(target_id),
        reason=str(reason).strip(),
        actor=str(actor).strip(),
        signal_sequence=_validate_signal_sequence(signal_sequence),
        armed_at=armed_at,
        target_identity=(
            str(target_identity)
            if target_identity is not None
            else _target_identity(target_kind, int(target_id))
        ),
        job_id=str(job_id) if job_id else None,
        attempt=int(attempt) if attempt is not None else None,
    )
    _append_event(
        _ledger_path(ledger_path),
        {"event": "intent_armed", "observed_at": armed_at, **_intent_fields(intent)},
    )
    return intent


def _send(
    intent: TerminationIntent | None,
    *,
    actual_kind: TargetKind,
    actual_id: int,
    signum: int,
    ledger_path: Path | str | None,
    sender: Callable[[int, int], None],
    require_root_kind: TargetKind | None,
    identity_verifier: Callable[[TerminationIntent], bool] | None,
) -> str:
    if intent is None:
        raise TerminationIntentRequired("termination requires a durable intent")
    if require_root_kind is not None and intent.target_kind != require_root_kind:
        raise TerminationIntentMismatch(
            f"intent targets {intent.target_kind}, not {require_root_kind}"
        )
    if actual_id <= 0 or int(signum) not in intent.signal_sequence:
        raise TerminationIntentMismatch("target or signal is outside armed intent")
    if require_root_kind is not None and actual_id != intent.target_id:
        raise TerminationIntentMismatch("signal target differs from armed target")
    if identity_verifier is not None and not identity_verifier(intent):
        raise TerminationIntentMismatch(
            "root target identity changed after intent was armed"
        )

    path = _ledger_path(ledger_path)
    base = {
        **_intent_fields(intent),
        "actual_target_kind": actual_kind,
        "actual_target_id": int(actual_id),
        "signum": int(signum),
    }
    _append_event(
        path,
        {"event": "signal_attempted", "observed_at": _now_iso(), **base},
        reject_duplicate_attempt=True,
    )
    try:
        sender(int(actual_id), int(signum))
    except ProcessLookupError:
        _append_event(
            path,
            {
                "event": "signal_result",
                "observed_at": _now_iso(),
                "status": "gone",
                **base,
            },
        )
        return "gone"
    except BaseException as exc:
        _append_event(
            path,
            {
                "event": "signal_result",
                "observed_at": _now_iso(),
                "status": "error",
                "error": f"{type(exc).__name__}: {exc}",
                **base,
            },
        )
        raise
    _append_event(
        path,
        {
            "event": "signal_result",
            "observed_at": _now_iso(),
            "status": "sent",
            **base,
        },
    )
    return "sent"


def send_pgid(
    intent: TerminationIntent | None,
    signum: int,
    *,
    ledger_path: Path | str | None = None,
    sender: Callable[[int, int], None] | None = None,
) -> str:
    return _send(
        intent,
        actual_kind="pgid",
        actual_id=int(intent.target_id) if intent is not None else -1,
        signum=signum,
        ledger_path=ledger_path,
        sender=sender or os.killpg,
        require_root_kind="pgid",
        identity_verifier=_root_identity_matches,
    )


def send_pid(
    intent: TerminationIntent | None,
    signum: int,
    *,
    ledger_path: Path | str | None = None,
    sender: Callable[[int, int], None] | None = None,
) -> str:
    return _send(
        intent,
        actual_kind="pid",
        actual_id=int(intent.target_id) if intent is not None else -1,
        signum=signum,
        ledger_path=ledger_path,
        sender=sender or os.kill,
        require_root_kind="pid",
        identity_verifier=_root_identity_matches,
    )


def send_member_pid(
    intent: TerminationIntent | None,
    pid: int,
    signum: int,
    *,
    ledger_path: Path | str | None = None,
    sender: Callable[[int, int], None] | None = None,
    identity_verifier: Callable[[int], bool] | None = None,
) -> str:
    """Signal one member while retaining the root pid/pgid intent identity."""
    if identity_verifier is None or not identity_verifier(int(pid)):
        raise TerminationIntentMismatch(
            "member pid identity was not verified immediately before signal"
        )
    return _send(
        intent,
        actual_kind="pid",
        actual_id=int(pid),
        signum=signum,
        ledger_path=ledger_path,
        sender=sender or os.kill,
        require_root_kind=None,
        identity_verifier=None,
    )


def _read_events(path: Path) -> list[dict]:
    lock_path = path.with_name(path.name + ".lock")
    if path.is_symlink() or lock_path.is_symlink():
        warn(
            "termination_intent",
            "refused symlinked termination ledger",
            ledger=str(path),
        )
        return []
    if not path.exists():
        return []
    lock_flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    try:
        lock_fd = os.open(lock_path, lock_flags, 0o600)
    except FileNotFoundError as exc:
        warn(
            "termination_intent",
            "ledger parent disappeared before read lock",
            err=str(exc),
            ledger=str(path),
        )
        return []
    try:
        _validate_ledger_fd(lock_fd)
        fcntl.flock(lock_fd, fcntl.LOCK_SH)
        try:
            ledger_fd = os.open(
                path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            )
        except FileNotFoundError as exc:
            warn(
                "termination_intent",
                "ledger disappeared after read lock",
                err=str(exc),
                ledger=str(path),
            )
            return []
        try:
            _validate_ledger_fd(ledger_fd)
            chunks: list[bytes] = []
            while True:
                chunk = os.read(ledger_fd, 64 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            lines = b"".join(chunks).decode("utf-8").splitlines()
        except (OSError, UnicodeDecodeError, TerminationIntentError) as exc:
            warn(
                "termination_intent",
                "termination ledger read failed closed",
                err=str(exc),
                ledger=str(path),
            )
            return []
        finally:
            os.close(ledger_fd)
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)
    events: list[dict] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            warn(
                "termination_intent",
                "ignored malformed termination ledger row",
                err=str(exc),
                ledger=str(path),
                row_head=line[:120],
            )
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def _event_int(event: dict, key: str) -> int | None:
    try:
        return int(event.get(key))
    except (TypeError, ValueError) as exc:
        warn(
            "termination_intent",
            "invalid integer field rejected",
            err=str(exc),
            field=key,
            value=repr(event.get(key))[:120],
        )
        return None


def _valid_armed_event(event: dict) -> bool:
    sequence = event.get("signal_sequence")
    attempt = event.get("attempt")
    return (
        event.get("event") == "intent_armed"
        and isinstance(event.get("intent_id"), str)
        and bool(event["intent_id"])
        and event.get("target_kind") in {"pid", "pgid"}
        and (_event_int(event, "target_id") or 0) > 0
        and isinstance(event.get("reason"), str)
        and bool(event["reason"])
        and isinstance(event.get("actor"), str)
        and bool(event["actor"])
        and isinstance(event.get("target_identity"), str)
        and bool(event["target_identity"])
        and isinstance(sequence, list)
        and bool(sequence)
        and all(isinstance(value, int) and value > 0 for value in sequence)
        and isinstance(event.get("armed_at"), str)
        and bool(event["armed_at"])
        and (event.get("job_id") is None or isinstance(event["job_id"], str))
        and (
            attempt is None
            or (isinstance(attempt, int) and not isinstance(attempt, bool) and attempt > 0)
        )
        and isinstance(event.get("observed_at"), str)
    )


def _matches_armed_lineage(event: dict, armed: dict) -> bool:
    return all(
        event.get(key) == armed.get(key)
        for key in (
            "intent_id", "target_kind", "target_id", "reason", "actor",
            "signal_sequence", "armed_at", "target_identity", "job_id", "attempt",
        )
    )


def _signal_event_key(event: dict) -> tuple[str, str, int, int] | None:
    intent_id = event.get("intent_id")
    actual_kind = event.get("actual_target_kind")
    actual_id = _event_int(event, "actual_target_id")
    signum = _event_int(event, "signum")
    if (
        not isinstance(intent_id, str)
        or actual_kind not in {"pid", "pgid"}
        or actual_id is None
        or actual_id <= 0
        or signum is None
        or signum <= 0
    ):
        return None
    return intent_id, actual_kind, actual_id, signum


def _lineaged_signal_events(path: Path) -> tuple[list[dict], list[dict], set[tuple]]:
    armed_by_id: dict[str, dict] = {}
    attempts: dict[tuple, dict] = {}
    sent: list[dict] = []
    terminal: set[tuple] = set()
    for event in _read_events(path):
        if _valid_armed_event(event):
            armed_by_id[event["intent_id"]] = event
            continue
        key = _signal_event_key(event)
        if key is None:
            continue
        armed = armed_by_id.get(key[0])
        if armed is None or not _matches_armed_lineage(event, armed):
            continue
        if key[3] not in armed["signal_sequence"]:
            continue
        if event.get("event") == "signal_attempted":
            attempts[key] = event
        elif event.get("event") == "signal_result" and key in attempts:
            if event.get("status") not in {"sent", "gone", "error"}:
                continue
            terminal.add(key)
            if event.get("status") == "sent":
                sent.append(event)
    return sent, list(attempts.values()), terminal


def match_sent_signal(
    *,
    target_kind: TargetKind,
    target_id: int,
    signum: int,
    job_id: str | None,
    attempt: int | None,
    ledger_path: Path | str | None = None,
    max_age_s: float = DEFAULT_MATCH_MAX_AGE_S,
) -> dict | None:
    """Return the newest exact sent receipt, never an armed/failed attempt."""
    now = datetime.now(timezone.utc)
    sent_events, _attempts, _terminal = _lineaged_signal_events(
        _ledger_path(ledger_path)
    )
    for event in reversed(sent_events):
        if (
            event.get("event") != "signal_result"
            or event.get("status") != "sent"
            or event.get("target_kind") != target_kind
            or _event_int(event, "target_id") != int(target_id)
            or _event_int(event, "signum") != int(signum)
            or (job_id is not None and event.get("job_id") != job_id)
            or (
                attempt is not None
                and _event_int(event, "attempt") != int(attempt)
            )
        ):
            continue
        try:
            observed = datetime.fromisoformat(str(event["observed_at"]))
            if observed.tzinfo is None:
                observed = observed.replace(tzinfo=timezone.utc)
        except (KeyError, ValueError) as exc:
            warn(
                "termination_intent",
                "sent receipt has invalid observed_at",
                err=str(exc),
                intent_id=event.get("intent_id"),
            )
            continue
        age = (now - observed).total_seconds()
        if 0 <= age <= max_age_s:
            return event
    return None


def match_sent_signal_for_job(
    *,
    target_kind: TargetKind,
    signum: int,
    job_id: str,
    attempt: int,
    ledger_path: Path | str | None = None,
    max_age_s: float = DEFAULT_MATCH_MAX_AGE_S,
) -> dict | None:
    """Match a unique exact WorkItem attempt after its state row was released.

    A health watchdog may win the completion CAS and remove ``current_jobs``
    before the worker observes wait status. The durable job+attempt identity is
    still available here. Multiple eligible target ids fail closed rather than
    guessing across a PID/PGID reuse or duplicate intent.
    """
    now = datetime.now(timezone.utc)
    eligible: list[dict] = []
    sent_events, _attempts, _terminal = _lineaged_signal_events(
        _ledger_path(ledger_path)
    )
    for event in reversed(sent_events):
        if (
            event.get("event") != "signal_result"
            or event.get("status") != "sent"
            or event.get("target_kind") != target_kind
            or _event_int(event, "signum") != int(signum)
            or event.get("job_id") != job_id
            or _event_int(event, "attempt") != int(attempt)
        ):
            continue
        try:
            observed = datetime.fromisoformat(str(event["observed_at"]))
            if observed.tzinfo is None:
                observed = observed.replace(tzinfo=timezone.utc)
        except (KeyError, ValueError) as exc:
            warn(
                "termination_intent",
                "job receipt has invalid observed_at",
                err=str(exc),
                intent_id=event.get("intent_id"),
            )
            continue
        age = (now - observed).total_seconds()
        if 0 <= age <= max_age_s:
            eligible.append(event)
    target_ids = {
        target
        for event in eligible
        if (target := _event_int(event, "target_id")) is not None
    }
    if len(target_ids) != 1:
        return None
    return eligible[0]


def wait_for_sent_signal(
    *,
    target_kind: TargetKind,
    target_id: int,
    signum: int,
    job_id: str,
    attempt: int,
    ledger_path: Path | str | None = None,
    wait_s: float = 1.0,
    poll_s: float = 0.01,
) -> dict | None:
    """Bound the syscall→sent-receipt publication race before external attribution."""
    deadline = time.monotonic() + max(0.0, wait_s)
    while True:
        match = match_sent_signal(
            target_kind=target_kind,
            target_id=target_id,
            signum=signum,
            job_id=job_id,
            attempt=attempt,
            ledger_path=ledger_path,
        )
        if match is not None or time.monotonic() >= deadline:
            return match
        time.sleep(max(0.001, poll_s))


def match_unresolved_signal_attempt(
    *,
    target_kind: TargetKind,
    target_id: int,
    signum: int,
    job_id: str,
    attempt: int,
    ledger_path: Path | str | None = None,
) -> dict | None:
    """Return an exact attempted syscall only when no result was durably published."""
    _sent, attempts, terminal = _lineaged_signal_events(
        _ledger_path(ledger_path)
    )
    for event in reversed(attempts):
        key = _signal_event_key(event)
        if (
            key is not None
            and key not in terminal
            and event.get("target_kind") == target_kind
            and _event_int(event, "target_id") == int(target_id)
            and _event_int(event, "signum") == int(signum)
            and event.get("job_id") == job_id
            and _event_int(event, "attempt") == int(attempt)
        ):
            return event
    return None


def terminating_signals() -> tuple[int, int]:
    return (signal.SIGTERM, signal.SIGKILL)
