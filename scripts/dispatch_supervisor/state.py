"""dispatch_state.json — supervisor persistent state with fcntl lock.

Schema (version 1)::

    {
      "version": 1,
      "supervisor_started_at": "<ISO>",          # supervisor process boot time
      "last_heartbeat_at": "<ISO>",              # scheduler tick heartbeat (every 60s)
      "last_fire_at": "<ISO|null>",              # last time a worker was actually spawned
      "current_job": null | {                    # in-flight worker (None when idle)
        "pid": int,
        "pgid": int,
        "schedule_id": "hourly_dispatch",
        "started_at": "<ISO>",
        "attempt": int,                          # 1..3
        "model": "opus" | "sonnet",
        "log_path": str
      },
      "completions": [                           # ring buffer (max 100 entries)
        {
          "fire_at": "<ISO>", "completed_at": "<ISO>",
          "exit_code": int, "duration_s": float,
          "attempts": int, "final_model": str,
          "outcome": "success" | "failure" | "killed_timeout" | "killed_supervisor"
        }
      ],
      "auth_blocked": false,                      # set true on 'Not logged in' — halts ticks
      "auth_blocked_at": "<ISO|null>",
      "alerts_dedup": {                           # alert_key -> last_sent_at (for dedup window)
        "auth_blocked": "<ISO>"
      }
    }

Lock semantics mirror `scripts/task_pool_claim.py`: `fcntl.LOCK_EX` for the
duration of any read-modify-write cycle. Atomic rename on persist.

Used by:
  - supervisor.py  (scheduler tick, fire decision, completion record)
  - health.py      (read current_job to verify worker liveness)
  - check_alerts.py (read last_heartbeat_at to detect supervisor death)
"""
from __future__ import annotations

import fcntl
import json
import logging
import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parents[2]
STATE_PATH = ROOT / "storage" / "ops" / "dispatch_state.json"

SCHEMA_VERSION = 1
COMPLETIONS_MAX = 100  # ring buffer cap
LOG = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_state_timestamp(value: Any) -> datetime:
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _empty_state() -> dict[str, Any]:
    return {
        "version": SCHEMA_VERSION,
        "supervisor_started_at": None,
        "last_heartbeat_at": None,
        "last_fire_at": None,
        "current_job": None,
        "completions": [],
        "auth_blocked": False,
        "auth_blocked_at": None,
        "alerts_dedup": {},
    }


def _warn_state_reset(path: Path, reason: str, detail: str) -> None:
    LOG.warning(
        "dispatch state reset to empty: path=%s reason=%s detail=%s",
        path,
        reason,
        detail,
    )


def _state_schema_detail(data: Any) -> str:
    version = data.get("version") if isinstance(data, dict) else None
    return f"type={type(data).__name__} version={version!r}"


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    """Write JSON atomically: temp file in same dir → fsync → os.replace.

    Codex review fix #4 (2026-06-15): the previous seek/truncate/dump/fsync
    pattern was non-atomic — a crash between truncate() and dump() leaves
    the canonical state file empty, and a crash mid-dump leaves a partial
    JSON that fails to parse on next boot (the `_empty_state()` fallback
    would silently nuke completion history / auth_blocked flag / dedup).
    os.replace() is POSIX-atomic on same filesystem; downstream readers
    never observe a partially-written file.
    """
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.tmp.",
        dir=str(path.parent),
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp_fh:
            json.dump(data, tmp_fh, indent=2, ensure_ascii=False)
            tmp_fh.flush()
            os.fsync(tmp_fh.fileno())
        os.replace(tmp_path, path)
    except Exception:
        # Best-effort cleanup; never mask the original error.
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        raise


@contextmanager
def _locked_state(path: Path = STATE_PATH) -> Iterator[tuple[Any, dict[str, Any]]]:
    """Open state file under LOCK_EX, yield (fh, data). Writes atomically on context exit.

    Lock is held on the original inode for the full read-modify-write cycle so
    concurrent _locked_state() / read_state() callers serialize correctly. The
    persist step goes through `_atomic_write_json` (temp file + os.replace) so
    a crash mid-write never leaves a partial/empty canonical file. After
    os.replace() the path points at a new inode — the next _locked_state()
    call will open & lock that new inode, which is the intended semantics.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        _atomic_write_json(path, _empty_state())
    fh = path.open("r+", encoding="utf-8")
    fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
    try:
        try:
            data = json.load(fh)
        except json.JSONDecodeError as exc:
            _warn_state_reset(path, "json_decode_failed", f"{type(exc).__name__}: {exc}")
            data = _empty_state()
        if not isinstance(data, dict) or data.get("version") != SCHEMA_VERSION:
            _warn_state_reset(
                path,
                "schema_invalid",
                _state_schema_detail(data),
            )
            data = _empty_state()
        yield fh, data
        _atomic_write_json(path, data)
    finally:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        fh.close()


def read_state(path: Path = STATE_PATH) -> dict[str, Any]:
    """Snapshot read (no write). Safe under concurrent writers (LOCK_SH)."""
    if not path.exists():
        return _empty_state()
    fh = path.open("r", encoding="utf-8")
    fcntl.flock(fh.fileno(), fcntl.LOCK_SH)
    try:
        try:
            data = json.load(fh)
        except json.JSONDecodeError as exc:
            _warn_state_reset(path, "json_decode_failed", f"{type(exc).__name__}: {exc}")
            return _empty_state()
        if not isinstance(data, dict) or data.get("version") != SCHEMA_VERSION:
            _warn_state_reset(
                path,
                "schema_invalid",
                _state_schema_detail(data),
            )
            return _empty_state()
        return data
    finally:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        fh.close()


def mark_supervisor_started(path: Path = STATE_PATH) -> None:
    """Called once at supervisor boot. Sets timestamps only.

    Codex review §10 #3 fix (2026-06-15): this function used to also silently
    discard a stale `current_job` on restart. Workers spawn with
    `start_new_session=True` so they do NOT die when the supervisor crashes —
    a stale `current_job` on boot can be a REAL orphan still running. Blindly
    clearing it here meant the next tick would spawn a brand-new worker on
    top of the still-alive orphan (double execution) with zero record of what
    happened to the old one. Orphan detection/kill/recording is now the
    caller's job via `claim_and_clear_current_job()` (needs `procutil` identity
    checks that this module deliberately does not depend on).
    """
    with _locked_state(path) as (_fh, data):
        data["supervisor_started_at"] = _now()
        data["last_heartbeat_at"] = _now()


def claim_and_clear_current_job(path: Path = STATE_PATH) -> dict[str, Any] | None:
    """Atomically pop `current_job` (used at supervisor boot for orphan handling).

    Returns the popped dict (or None if there was none) so the caller can
    identity-check the pid, kill it if still alive, and record a completion
    entry via `append_completion_entry()`. See `mark_supervisor_started` for
    why this is a separate step (Codex review §10 #3).
    """
    with _locked_state(path) as (_fh, data):
        job = data.get("current_job")
        data["current_job"] = None
        return job


def append_completion_entry(
    job: dict[str, Any], *, exit_code: int, outcome: str, final_model: str,
    path: Path = STATE_PATH,
) -> dict[str, Any]:
    """Append a completion entry for a job dict that is no longer `current_job`.

    Mirrors `record_completion`'s ring-buffer append but takes the job
    explicitly — used for orphans claimed via `claim_and_clear_current_job()`,
    where `current_job` has already been cleared by the time we know the
    outcome (kill succeeded / pid already gone / identity mismatch).
    """
    with _locked_state(path) as (_fh, data):
        started_at = job.get("started_at")
        try:
            started_dt = _parse_state_timestamp(started_at)
            duration_s = (datetime.now(timezone.utc) - started_dt).total_seconds()
        except (TypeError, ValueError) as exc:
            LOG.warning(
                "invalid job.started_at for append_completion_entry in %s: %r (%s: %s)",
                path, started_at, type(exc).__name__, exc,
            )
            duration_s = -1.0
        entry = {
            "fire_at": started_at,
            "completed_at": _now(),
            "exit_code": exit_code,
            "duration_s": round(duration_s, 2),
            "attempts": job.get("attempt", 1),
            "final_model": final_model,
            "outcome": outcome,
        }
        completions = data.get("completions") or []
        completions.append(entry)
        if len(completions) > COMPLETIONS_MAX:
            completions = completions[-COMPLETIONS_MAX:]
        data["completions"] = completions
        return entry


def heartbeat(path: Path = STATE_PATH) -> None:
    """Called every scheduler tick (~60s) to prove supervisor alive."""
    with _locked_state(path) as (_fh, data):
        data["last_heartbeat_at"] = _now()


def reserve_fire(
    *,
    schedule_id: str,
    attempt: int,
    model: str,
    log_path: str,
    path: Path = STATE_PATH,
) -> None:
    """Atomically claim the job slot BEFORE spawning the child process.

    Codex review §10 #5 fix (2026-06-15): the previous flow spawned the Popen
    child THEN called begin_fire(). Between "scheduler observed current_job is
    None" and "state records the new job", two overlapping callers (e.g. a
    botched double-launch of the supervisor, or the legacy shell wrapper
    racing the new supervisor mid-migration) could both pass the None check
    and both spawn — doubling dispatch with no lock ever preventing it.
    Reserving the slot under the state lock BEFORE Popen closes that window:
    whichever caller's `reserve_fire()` wins the lock first writes a
    placeholder (`pid=None`) current_job; the loser's call raises and MUST
    NOT spawn a child.
    """
    with _locked_state(path) as (_fh, data):
        if data.get("current_job") is not None:
            raise RuntimeError(
                f"reserve_fire while current_job in-flight: {data['current_job']}"
            )
        data["current_job"] = {
            "pid": None,
            "pgid": None,
            "started_wall": None,
            "schedule_id": schedule_id,
            "started_at": _now(),
            "attempt": attempt,
            "model": model,
            "log_path": log_path,
        }
        data["last_fire_at"] = _now()


def attach_process(
    *, pid: int, pgid: int, started_wall: str | None, path: Path = STATE_PATH,
) -> None:
    """Fill in real pid/pgid/identity fingerprint after a successful spawn
    following `reserve_fire()`. Raises if the reservation is missing (should
    be unreachable under correct single-writer-per-slot discipline; guards
    against a supervisor bug silently corrupting job identity)."""
    with _locked_state(path) as (_fh, data):
        job = data.get("current_job")
        if job is None:
            raise RuntimeError("attach_process called with no active reservation")
        job["pid"] = pid
        job["pgid"] = pgid
        job["started_wall"] = started_wall
        data["current_job"] = job


def release_reservation(path: Path = STATE_PATH) -> None:
    """Free the slot when spawn itself failed after `reserve_fire()` succeeded
    (e.g. `claude_bin` missing → `FileNotFoundError` before a pid ever existed).
    Without this the slot would wedge forever (current_job set, no process)."""
    with _locked_state(path) as (_fh, data):
        data["current_job"] = None


def record_completion(
    *,
    exit_code: int,
    outcome: str,
    final_model: str,
    path: Path = STATE_PATH,
) -> dict[str, Any] | None:
    """Move current_job → completions ring buffer. Returns the completion entry."""
    with _locked_state(path) as (_fh, data):
        job = data.get("current_job")
        if job is None:
            return None
        started_at = job.get("started_at")
        try:
            started_dt = _parse_state_timestamp(started_at)
            duration_s = (datetime.now(timezone.utc) - started_dt).total_seconds()
        except (TypeError, ValueError) as exc:
            LOG.warning(
                "invalid current_job.started_at for completion in %s: %r (%s: %s)",
                path,
                started_at,
                type(exc).__name__,
                exc,
            )
            duration_s = -1.0
        entry = {
            "fire_at": started_at,
            "completed_at": _now(),
            "exit_code": exit_code,
            "duration_s": round(duration_s, 2),
            "attempts": job.get("attempt", 1),
            "final_model": final_model,
            "outcome": outcome,
        }
        completions = data.get("completions") or []
        completions.append(entry)
        if len(completions) > COMPLETIONS_MAX:
            completions = completions[-COMPLETIONS_MAX:]
        data["completions"] = completions
        data["current_job"] = None
        return entry


def set_auth_blocked(blocked: bool, path: Path = STATE_PATH) -> None:
    """Toggle auth_blocked flag. When true, scheduler halts new fires."""
    with _locked_state(path) as (_fh, data):
        data["auth_blocked"] = bool(blocked)
        data["auth_blocked_at"] = _now() if blocked else None


def should_dedup_alert(alert_key: str, window_s: int, path: Path = STATE_PATH) -> bool:
    """Return True if alert was sent within last `window_s` seconds (suppress new send)."""
    snap = read_state(path)
    last = (snap.get("alerts_dedup") or {}).get(alert_key)
    if not last:
        return False
    try:
        last_dt = _parse_state_timestamp(last)
        age = (datetime.now(timezone.utc) - last_dt).total_seconds()
        return age < window_s
    except (TypeError, ValueError) as exc:
        LOG.warning(
            "invalid alerts_dedup timestamp for %s in %s: %r (%s: %s)",
            alert_key,
            path,
            last,
            type(exc).__name__,
            exc,
        )
        return False


def mark_alert_sent(alert_key: str, path: Path = STATE_PATH) -> None:
    with _locked_state(path) as (_fh, data):
        dedup = data.get("alerts_dedup") or {}
        dedup[alert_key] = _now()
        data["alerts_dedup"] = dedup


# ---------------------------------------------------------------------------
# Convenience accessors (read-only, used by CLI / health checks)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CurrentJob:
    pid: int
    pgid: int
    schedule_id: str
    started_at: str
    attempt: int
    model: str
    log_path: str
    started_wall: str | None = None
    age_seconds: float = 0.0


def get_current_job(path: Path = STATE_PATH) -> CurrentJob | None:
    snap = read_state(path)
    job = snap.get("current_job")
    if not job:
        return None
    if job.get("pid") is None:
        # Reservation window (reserve_fire() ran, attach_process() has not yet
        # — normally sub-millisecond, spanning only the Popen() call itself).
        # No real pid to identity-check yet; treat as "no job to inspect" for
        # this tick rather than crash on int(None) — reserve_fire()'s own
        # non-null current_job already prevents a second concurrent fire.
        return None
    age = -1.0
    try:
        started_dt = _parse_state_timestamp(job["started_at"])
        age = (datetime.now(timezone.utc) - started_dt).total_seconds()
    except (KeyError, TypeError, ValueError) as exc:
        LOG.warning(
            "invalid current_job.started_at in %s: %r (%s: %s)",
            path,
            job.get("started_at"),
            type(exc).__name__,
            exc,
        )
    return CurrentJob(
        pid=int(job["pid"]),
        pgid=int(job.get("pgid") or job["pid"]),
        schedule_id=str(job.get("schedule_id", "")),
        started_at=str(job.get("started_at", "")),
        attempt=int(job.get("attempt", 1)),
        model=str(job.get("model", "")),
        log_path=str(job.get("log_path", "")),
        started_wall=job.get("started_wall"),
        age_seconds=age,
    )


def get_supervisor_age_seconds(path: Path = STATE_PATH) -> float | None:
    """Seconds since last_heartbeat_at — used by external monitor to flag dead supervisor."""
    snap = read_state(path)
    last = snap.get("last_heartbeat_at")
    if not last:
        return None
    try:
        last_dt = _parse_state_timestamp(last)
        return (datetime.now(timezone.utc) - last_dt).total_seconds()
    except (TypeError, ValueError) as exc:
        LOG.warning(
            "invalid last_heartbeat_at in %s: %r (%s: %s)",
            path,
            last,
            type(exc).__name__,
            exc,
        )
        return None
