"""dispatch_state.json — supervisor persistent state with fcntl lock.

Schema (version 1)::

    {
      "version": 1,
      "supervisor_started_at": "<ISO>",          # supervisor process boot time
      "supervisor_pid": int | null,              # os.getpid() of the live daemon
      "last_heartbeat_at": "<ISO>",              # liveness heartbeat (health_loop, every 30s)
      "last_fire_at": "<ISO|null>",              # last time a worker was actually spawned
      "current_job": null | {                    # in-flight worker (None when idle)
        "pid": int | null,                       # null during the reserve_fire()..attach_process() window
        "pgid": int | null,
        "started_wall": str | null,               # `ps -o lstart=` fingerprint (may lag pid/pgid — see update_started_wall)
        "schedule_id": "hourly_dispatch",
        "started_at": "<ISO>",
        "attempt": int,                          # 1..3
        "model": "opus",                         # all attempts opus (2026-07-05 all-opus directive)
        "log_path": str,
        "restart_cleanup_pending": true           # only present while a restart-orphan investigation is in flight
      },
      "completions": [                           # ring buffer (max 100 entries)
        {
          "fire_at": "<ISO>", "completed_at": "<ISO>",
          "exit_code": int, "duration_s": float,
          "attempts": int, "final_model": str,
          "outcome": "success" | "failure" | "killed_timeout" | "silent_death" |
                     "timeout_unverified" | "killed_supervisor_restart" |
                     "orphan_gone_or_reused" | "orphan_unverified_not_killed" |
                     "reservation_abandoned_no_pid" | "quota_blocked" | "auth_blocked"
        }
      ],
      "auth_blocked": false,                      # set true on 'Not logged in' — halts ticks
      "auth_blocked_at": "<ISO|null>",
      "fire_requested_at": "<ISO|null>",          # pending out-of-band fire request (request_fire)
      "fire_request_reason": "<str|null>",        # why; both cleared by consume_fire_request()
      "alerts_dedup": {                           # alert_key -> last_sent_at (for dedup window)
        "auth_blocked": "<ISO>"
      }
    }

Lock semantics: `fcntl.LOCK_EX` on a dedicated sibling lockfile
(`_lock_path()`) for the duration of any read-modify-write cycle — NOT on
`dispatch_state.json` itself, which is replaced (new inode) on every persist
(Codex review fix #1, 2026-07-04, gate-blocking: locking the replaced file
directly is a TOCTOU race — see `_lock_path()`'s docstring). Persist is an
atomic `os.replace()` via `_atomic_write_json()`.

Used by:
  - supervisor.py  (scheduler tick, fire decision, completion record, restart-orphan cleanup)
  - health.py      (heartbeat + read current_job to verify worker liveness)
  - volpred.ops.alerts._parse_dispatch_supervisor_heartbeat_state
                   (reads last_heartbeat_at as a wedged-daemon dead-man switch;
                    this docstring claimed check_alerts.py did so long before
                    any reader actually existed — wired 2026-07-10)
  - scripts/cron_review.py (daemon liveness + last completed run, for boss report)

Reader's field map — `jq` against a key that was never implemented returns
`null`, which is indistinguishable from "declared but not set yet". Every
field an outside reader needs is listed in the schema above; anything else is
a phantom. Known misreads that have cost real debugging time:

  - `last_dispatch_at` → does not exist. Use `last_fire_at` (set under the
    state lock inside `reserve_fire()`, i.e. per worker-spawn ATTEMPT, and it
    doubles as the cron cursor `scheduler._due_to_fire()` reads).
  - `last_completion`  → not written by anything, and since 2026-07-10 not read
    by anything either. Use `completions[-1]`, the append-only ring buffer that
    `record_completion()` owns and that is the single source of "last finished
    run". To ask "is a run in flight?", read `current_job`, not the freshness of
    that buffer.
  - `supervisor_pid` vs `launchctl list` → these legitimately DIFFER by one.
    The plist runs `uv run python -m ...`, so launchd tracks the `uv` wrapper
    while this field holds its Python child — the process that actually runs
    the loops and owns this file. A mismatch is expected; check liveness with
    `ps -p <supervisor_pid>` (or a fresh `last_heartbeat_at`), not by diffing
    the two numbers.

Prefer `uv run python -m scripts.dispatch_supervisor.cli status` over
hand-rolled `jq` — it prints the whole normalized state, so a key that is
absent from the output is a key that does not exist.
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


def _lock_path(state_path: Path) -> Path:
    """Stable sibling lockfile — NEVER replaced/renamed, unlike `state_path` itself.

    Codex review fix #1 (2026-07-04, gate-blocking finding): the previous
    design flocked the canonical state file's own inode and then persisted
    via `os.replace()`. That is a TOCTOU race — process B can `open()` the
    canonical path (getting the OLD inode) *before* process A's
    `os.replace()` swaps in a new inode; B then blocks on `flock` against
    that old inode until A closes its fd, acquires the lock on the
    now-detached old inode, reads A's pre-write content, and on its own
    `os.replace()` clobbers whatever A just wrote. Reproduced with two
    overlapping `_locked_state()` writers; the first writer's `current_job`
    was silently lost — this reopens the exact double-dispatch race
    `reserve_fire()` was built to close. Locking a lockfile that is opened
    in append mode and NEVER unlinked/replaced guarantees every contender
    flocks the same inode, so the mutex is real regardless of what happens
    to the data file underneath it.
    """
    return state_path.with_name(state_path.name + ".lock")

SCHEMA_VERSION = 1
# Adding an OPTIONAL key to `_empty_state()` must NOT bump SCHEMA_VERSION:
# `_locked_state()` / `read_state()` reset the file to empty whenever the
# on-disk `version` differs, so a bump would wipe `current_job` (orphaning a
# live worker) and the whole `completions` ring on the very next heartbeat of
# the running daemon. New keys read back as `None` on a pre-existing file until
# their first write; only a change that INVALIDATES existing values earns a bump.
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
        "supervisor_pid": None,
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
            pass  # silent-ok: temp file already gone — cleanup race-safe
        raise


def _acquire_lock(lock_path: Path, *, shared: bool = False, max_attempts: int = 5):
    """Open + flock the sibling lockfile, then verify the locked fd still
    refers to the inode currently at `lock_path`; retry on mismatch.

    Codex review round-2 hardening (2026-07-04): the lockfile scheme is only
    sound while every contender flocks the SAME inode. If an external cleanup
    process (or a stray `rm *.lock`) deletes and recreates the lockfile
    between our `open()` and `flock()`, we hold a lock on a detached inode
    that serializes nothing — the TOCTOU race the lockfile was built to close
    quietly reopens. Post-flock fstat-vs-stat inode comparison detects this
    and retries against the file currently at the path. No VolPred process
    deletes `*.lock` today (and `storage/ops/*.lock` is gitignored), so this
    is belt-and-suspenders — but the failure mode is silent lost updates, so
    it warrants the two extra syscalls per acquisition.
    """
    op = fcntl.LOCK_SH if shared else fcntl.LOCK_EX
    for attempt in range(1, max_attempts + 1):
        fh = lock_path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(fh.fileno(), op)
        except Exception:
            fh.close()
            raise
        try:
            path_ino = os.stat(lock_path).st_ino
        except FileNotFoundError:
            path_ino = None  # lockfile deleted after we opened it — fd is detached
        if path_ino is not None and os.fstat(fh.fileno()).st_ino == path_ino:
            return fh
        LOG.warning(
            "lockfile inode changed under us (attempt %d/%d) path=%s — releasing and retrying",
            attempt, max_attempts, lock_path,
        )
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        fh.close()
    raise RuntimeError(
        f"could not acquire a stable lock on {lock_path} after {max_attempts} attempts "
        "(lockfile keeps being deleted/recreated underneath us)"
    )


@contextmanager
def _locked_state(path: Path = STATE_PATH) -> Iterator[tuple[Any, dict[str, Any]]]:
    """Lock the sibling lockfile under LOCK_EX, yield (lock_fh, data). Writes
    atomically on context exit.

    The lock is held on `_lock_path(path)` — a file that is opened in append
    mode and never unlinked or replaced — for the full read-modify-write
    cycle, so concurrent `_locked_state()` / `read_state()` callers actually
    serialize (see `_lock_path()` docstring for why locking `path` itself,
    which DOES get replaced, was unsafe; `_acquire_lock()` for the
    deleted-lockfile inode check). The persist step still goes through
    `_atomic_write_json` (temp file + os.replace) so a crash mid-write never
    leaves a partial/empty canonical file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_fh = _acquire_lock(_lock_path(path), shared=False)
    try:
        try:
            if not path.exists():
                _atomic_write_json(path, _empty_state())
            with path.open("r", encoding="utf-8") as data_fh:
                try:
                    data = json.load(data_fh)
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
            yield lock_fh, data
            _atomic_write_json(path, data)
        finally:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)
    finally:
        lock_fh.close()


def read_state(path: Path = STATE_PATH) -> dict[str, Any]:
    """Snapshot read (no write). Takes LOCK_SH on the sibling lockfile so a
    read can never observe a writer's data file mid read-modify-write cycle
    (belt-and-suspenders — `os.replace()` already makes any plain read of
    `path` atomic on its own, but this keeps read/write serialization
    reasoning in one place)."""
    if not path.exists():
        return _empty_state()
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_fh = _acquire_lock(_lock_path(path), shared=True)
    try:
        try:
            if not path.exists():
                return _empty_state()
            with path.open("r", encoding="utf-8") as data_fh:
                try:
                    data = json.load(data_fh)
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
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)
    finally:
        lock_fh.close()


def mark_supervisor_started(path: Path = STATE_PATH) -> None:
    """Called once at supervisor boot. Sets timestamps + owning pid.

    `supervisor_pid` is the daemon's own `os.getpid()`, not a worker's — a
    reader that wants "is the daemon alive" needs BOTH this and a fresh
    `last_heartbeat_at`, since a bare pid can be stale or OS-reused. The two
    are always written together (here and in `heartbeat()`), so they never
    disagree about which process last proved itself alive.

    Codex review §10 #3 fix (2026-06-15): this function used to also silently
    discard a stale `current_job` on restart. Workers spawn with
    `start_new_session=True` so they do NOT die when the supervisor crashes —
    a stale `current_job` on boot can be a REAL orphan still running. Blindly
    clearing it here meant the next tick would spawn a brand-new worker on
    top of the still-alive orphan (double execution) with zero record of what
    happened to the old one. Orphan detection/kill/recording is now the
    caller's job via `mark_restart_orphan_pending()` (needs `procutil`
    identity checks that this module deliberately does not depend on).
    """
    with _locked_state(path) as (_fh, data):
        data["supervisor_started_at"] = _now()
        data["supervisor_pid"] = os.getpid()
        data["last_heartbeat_at"] = _now()


def mark_restart_orphan_pending(path: Path = STATE_PATH) -> dict[str, Any] | None:
    """Read `current_job` at boot and flag it for orphan investigation —
    WITHOUT clearing it. Returns a copy of the job dict (or None if idle).

    Codex review fix #3 (2026-07-04, gate-blocking finding): the prior
    `claim_and_clear_current_job()` popped `current_job` to `None` in the
    same atomic step as handing it to the caller, *before* the caller had
    actually killed/recorded anything. A second supervisor crash between
    that pop and `_handle_restart_orphan()` finishing lost the orphan's
    record entirely — and worse, if the orphan was still alive and not yet
    killed, the *next* restart would see `current_job=None` and never look
    for it again, permanently losing track of a live untracked process.

    Marking (not clearing) means: while `restart_cleanup_pending` is set,
    `current_job` stays non-null, so (a) `reserve_fire()` still correctly
    refuses new dispatches during cleanup, and (b) if THIS restart crashes
    mid-cleanup too, the next restart calls this again, sees the same job
    still present, and retries the identical cleanup — idempotently. Only
    `finalize_restart_orphan_cleanup()` (called after kill + record are both
    done) actually clears the slot.
    """
    with _locked_state(path) as (_fh, data):
        job = data.get("current_job")
        if job is None:
            return None
        job["restart_cleanup_pending"] = True
        data["current_job"] = job
        return dict(job)


def finalize_restart_orphan_cleanup(path: Path = STATE_PATH) -> None:
    """Clear `current_job` — call ONLY after the orphan flagged by
    `mark_restart_orphan_pending()` has been identity-checked, killed (if
    warranted), and its outcome recorded via `append_completion_entry()`.
    This is the sole point a restart-orphan's slot transitions back to None;
    see `mark_restart_orphan_pending()` for why clearing is deferred this far."""
    with _locked_state(path) as (_fh, data):
        data["current_job"] = None


def append_completion_entry(
    job: dict[str, Any], *, exit_code: int, outcome: str, final_model: str,
    path: Path = STATE_PATH, mark_cleanup_recorded: bool = False,
) -> dict[str, Any]:
    """Append a completion entry for a job dict that is no longer `current_job`.

    Mirrors `record_completion`'s ring-buffer append but takes the job
    explicitly — used for orphans flagged via `mark_restart_orphan_pending()`,
    where `current_job` is not cleared until `finalize_restart_orphan_cleanup()`
    runs, so this call happens *before* the slot is actually freed.

    `mark_cleanup_recorded=True` (Codex review round-2 low finding, 2026-07-04:
    completion-entry idempotency): in the SAME locked transaction as the
    append, also set `current_job["cleanup_recorded"] = True`. If the
    supervisor crashes after this transaction but before
    `finalize_restart_orphan_cleanup()`, the next restart's
    `mark_restart_orphan_pending()` returns a job carrying that flag, and
    `_handle_restart_orphan()` skips straight to finalize instead of
    appending a duplicate completion entry for the same orphan.
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
        # Codex review round-3 medium #2 (2026-07-04): persist pid/pgid/fingerprint
        # for orphan/unverified outcomes so the unverified-orphan runbook's
        # `jq '.completions[-5:]'` actually yields the pid/pgid the operator
        # needs to check by hand (current_job is cleared right after this).
        if job.get("pid") is not None:
            entry["pid"] = job.get("pid")
            entry["pgid"] = job.get("pgid")
            entry["started_wall"] = job.get("started_wall")
        completions = data.get("completions") or []
        completions.append(entry)
        if len(completions) > COMPLETIONS_MAX:
            completions = completions[-COMPLETIONS_MAX:]
        data["completions"] = completions
        if mark_cleanup_recorded and data.get("current_job") is not None:
            data["current_job"]["cleanup_recorded"] = True
            # Record the outcome so a crash-before-finalize retry knows whether
            # to re-alert (Codex review round-3 #1) without re-appending.
            data["current_job"]["cleanup_outcome"] = outcome
        return entry


def heartbeat(path: Path = STATE_PATH) -> None:
    """Prove the supervisor process is alive. Owner: `health.health_loop()`
    (every 30s); `scheduler._tick_once()` also calls it so `--once` smoke runs
    still stamp one.

    2026-07-10: liveness used to be stamped ONLY from the scheduler tick,
    which `await`s `worker.run_worker()` to completion — so `last_heartbeat_at`
    froze for the entire run (up to 3×50min with the retry ladder), i.e. the
    field went stale exactly while the daemon was busiest, and a reader had to
    fall back to launchd logs to tell a working daemon from a dead one. The
    health loop never blocks, so it is the correct owner.

    Re-stamps `supervisor_pid` on every beat rather than trusting the boot
    write: that self-heals both a state-file reset (corrupt JSON / schema drift
    → `_empty_state()`) and a hand-run `--once` process having stamped its own
    short-lived pid, within one beat. Safe because every caller runs inside the
    supervisor process itself — workers are `Popen` children and never import
    this module.
    """
    with _locked_state(path) as (_fh, data):
        data["last_heartbeat_at"] = _now()
        data["supervisor_pid"] = os.getpid()


def request_fire(reason: str, path: Path = STATE_PATH) -> None:
    """Ask the supervisor to fire ASAP (next 60s tick), outside the cron cadence.

    2026-07-05 cutover follow-up: external triggers (e.g. gmail_inbox_poll's
    boss-reply immediate dispatch) used to Popen the LEGACY shell wrapper
    directly — after cutover that was a live double-dispatch race (its pgrep
    guard couldn't see the supervisor's in-flight job, and the legacy wrapper
    spawns its own claude + retry ladder outside dispatch_state control).
    Writing a flag under the state lock and letting the scheduler consume it
    keeps ALL fires on the single reserve_fire() slot path. If a job is
    already in flight the request simply stays pending and fires right after —
    "as soon as possible", never "in parallel".
    """
    with _locked_state(path) as (_fh, data):
        data["fire_requested_at"] = _now()
        data["fire_request_reason"] = str(reason)[:200]


def consume_fire_request(path: Path = STATE_PATH) -> str | None:
    """Atomically read-and-clear a pending fire request. Returns the reason
    string if one was pending, else None. Scheduler-side counterpart of
    `request_fire()` — called only when the tick is actually about to fire."""
    with _locked_state(path) as (_fh, data):
        if not data.get("fire_requested_at"):
            return None
        reason = str(data.get("fire_request_reason") or "unspecified")
        data["fire_requested_at"] = None
        data["fire_request_reason"] = None
        return reason


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
    """Fill in real pid/pgid (and identity fingerprint, if already known)
    after a successful spawn following `reserve_fire()`. Raises if the
    reservation is missing (should be unreachable under correct
    single-writer-per-slot discipline; guards against a supervisor bug
    silently corrupting job identity).

    Callers should pass `started_wall=None` and call this IMMEDIATELY after
    `Popen()` returns (before the slower `ps`-based fingerprint lookup), then
    fill the fingerprint in separately via `update_started_wall()` once it's
    available. See that function's docstring for why (Codex review fix #2,
    2026-07-04) — this narrows the "current_job.pid is None" crash-recovery
    blind spot in `mark_restart_orphan_pending()` down to just the `Popen()`
    syscall itself, rather than spanning the whole fingerprint subprocess call.
    """
    with _locked_state(path) as (_fh, data):
        job = data.get("current_job")
        if job is None:
            raise RuntimeError("attach_process called with no active reservation")
        job["pid"] = pid
        job["pgid"] = pgid
        job["started_wall"] = started_wall
        data["current_job"] = job


def update_started_wall(*, pid: int, started_wall: str, path: Path = STATE_PATH) -> None:
    """Fill in the identity fingerprint after `attach_process()` already
    recorded pid/pgid without one (Codex review fix #2, 2026-07-04).

    Fingerprinting requires a `ps` subprocess call — slower than the pid/pgid
    attach itself — so it is captured in this separate follow-up step to keep
    the "reservation has a pid but no fingerprint yet" window as small as
    possible. No-ops (does not raise) if `current_job`'s pid no longer
    matches `pid` — the job may have already completed (or been replaced by
    a subsequent fire) by the time the `ps` call returned.
    """
    with _locked_state(path) as (_fh, data):
        job = data.get("current_job")
        if job is None or job.get("pid") != pid:
            return
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


def clear_alert_dedup(alert_key: str, path: Path = STATE_PATH) -> None:
    """Reset one alert's dedup window (e.g. quota outage ended → the NEXT
    outage must email again even if the fixed window hasn't elapsed)."""
    with _locked_state(path) as (_fh, data):
        dedup = data.get("alerts_dedup") or {}
        if alert_key in dedup:
            del dedup[alert_key]
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
