"""dispatch_state.json — supervisor persistent state with fcntl lock.

Schema (version 1)::

    {
      "version": 1,
      "supervisor_started_at": "<ISO>",          # supervisor process boot time
      "supervisor_pid": int | null,              # os.getpid() of the live daemon
      "last_heartbeat_at": "<ISO>",              # liveness heartbeat (health_loop, every 30s)
      "last_fire_at": "<ISO|null>",              # last time a worker was actually spawned
      "current_jobs": [                          # canonical in-flight workers (one per slot)
        {
          "job_id": str,                         # immutable CAS identity for this logical fire
          "cohort_id": str,                      # immutable fire cohort (stable across retries)
          "slot_id": int,                        # 1..max_slots, stable across retries
          "phase": "reserved|running|classifying|retry_wait|codex_failover|restart_cleanup|kill_failed_orphan|timeout_unverified",
          "pid": int | null,                     # null while reserved / between retry attempts
          "pgid": int | null,
          "started_wall": str | null,
          "schedule_id": "hourly_dispatch",
          "started_at": "<ISO>",                 # logical-fire start (stable across retries)
          "attempt_started_at": "<ISO>",         # current attempt start
          "attempt": int,
          "model": "opus",
          "log_path": str,
          "scheduled_for": "<ISO|null>",
          "fire_reason": "cron|requested:*|cron+requested:*",
          "fire_key": str | null,                 # atomic cron-slot dedup identity
          "restart_cleanup_pending": true,
          "cleanup_recorded": true,
          "cleanup_outcome": str
        }
      ],
      "current_job": null | {                    # deprecated projection: lowest current_jobs slot
        "job_id": str,                           # same object shape as current_jobs[]
        "cohort_id": str,
        "slot_id": int,
        "phase": "reserved|running|classifying|retry_wait|codex_failover|restart_cleanup|kill_failed_orphan|timeout_unverified",
        "pid": int | null,                       # null during the reserve_fire()..attach_process() window
        "pgid": int | null,
        "started_wall": str | null,               # `ps -o lstart=` fingerprint (may lag pid/pgid — see update_started_wall)
        "schedule_id": "hourly_dispatch",
        "started_at": "<ISO>",
        "attempt_started_at": "<ISO>",
        "attempt": int,                          # 1..3
        "model": "opus",                         # all attempts opus (2026-07-05 all-opus directive)
        "log_path": str,
        "scheduled_for": "<ISO|null>",            # cron slot this fire services (naive local ISO)
        "fire_reason": "cron|requested:*|cron+requested:*",
        "fire_key": str | null,
        "restart_cleanup_pending": true,          # only present while a restart-orphan investigation is in flight
        "cleanup_recorded": true,                 # append_completion_entry() stamped this orphan's entry
        "cleanup_outcome": str                    # …and which outcome, so a crash-before-finalize retry
      },                                          #    knows whether to re-alert without re-appending
      "phase_z_pending": [                       # released workers whose slot still drains PHASE-Z
        {
          "job_id": str, "cohort_id": str, "slot_id": int,
          "created_at": "<ISO>"
        }
      ],
      "completions": [                           # ring buffer (max 100 entries)
        {
          "fire_at": "<ISO>", "completed_at": "<ISO>",
          "job_id": str, "cohort_id": str, "slot_id": int,
          "scheduled_for": "<ISO|null>", "fire_reason": str, "fire_key": str | null,
          "exit_code": int, "duration_s": float,
          "attempts": int, "final_model": str,
          # 下三者只在 orphan 路徑（append_completion_entry 且 job 有 pid）出現，
          # 供事後人工核對是哪個行程 — 一般 record_completion() 的 entry 沒有。
          "pid": int, "pgid": int, "started_wall": str,
          "outcome": "success" | "failure" | "killed_timeout" | "kill_failed_orphan" |
                     "silent_death" |
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
import hashlib
import json
import logging
import os
import tempfile
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from volpred.canonical_write import guard_canonical_write

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
_IMPLICIT_JOB_ID: ContextVar[str | None] = ContextVar("dispatch_job_id", default=None)


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
        "current_jobs": [],
        # Backward-compatible reader projection. All writers use current_jobs;
        # _normalise_state refreshes this from the lowest occupied slot.
        "current_job": None,
        "phase_z_pending": [],
        "completions": [],
        "auth_blocked": False,
        "auth_blocked_at": None,
        # 宣告即存在 — 與幽靈欄位可區分（同 supervisor_pid 2026-07-10 的修法）。
        # `request_fire()` 是 writer；fresh state 缺這兩個 key 會讓 reader 讀到的
        # null 再度分不清「沒有 pending request」與「這欄位根本沒實作」。
        "fire_requested_at": None,
        "fire_request_reason": None,
        "alerts_dedup": {},
    }


def _legacy_job_id(job: dict[str, Any], index: int) -> str:
    """Deterministic identity for a pre-multislot current_job.

    read_state() is intentionally read-only, so a random migration id there
    would change on every read until the next writer happened to persist it.
    A digest makes repeated reads stable and the next locked write durable.
    """
    raw = json.dumps(job, sort_keys=True, ensure_ascii=False, default=str)
    digest = hashlib.sha256(f"{index}:{raw}".encode("utf-8")).hexdigest()[:24]
    return f"legacy-{digest}"


def _normalise_state(data: dict[str, Any]) -> dict[str, Any]:
    """Migrate v1 single-slot state in memory without resetting live workers.

    `current_jobs` is canonical. `current_job` remains a compatibility
    projection for old readers during the rollout and is never consulted when
    a canonical list is present. The schema version deliberately stays at 1:
    bumping it would erase a live legacy worker before orphan cleanup can see it.
    """
    raw_jobs = data.get("current_jobs")
    legacy_projection_present = "current_job" in data
    legacy = data.get("current_job")
    if not isinstance(raw_jobs, list):
        raw_jobs = [legacy] if isinstance(legacy, dict) else []
    elif legacy_projection_present:
        # Mixed-version rollout safety. A still-running old daemon only knows
        # current_job and preserves the unknown current_jobs key. Therefore
        # [] + dict means old reserve/attach just created a live worker, while
        # [job] + None means old completion just cleared it. New writers always
        # call _sync_projection, so a consistent projection equals slot 1.
        first = raw_jobs[0] if raw_jobs else None
        if legacy is None and raw_jobs:
            # An old daemon completed the projected (lowest-slot) legacy job.
            # Preserve any siblings a new daemon admitted meanwhile.
            raw_jobs = raw_jobs[1:]
        elif isinstance(legacy, dict) and (
            first is None
            or any(legacy.get(key) != first.get(key) for key in ("job_id", "pid", "attempt", "log_path"))
        ):
            # Old reserve/attach mutated the projected job but knows nothing
            # about later siblings. Replace only slot 1, never drop the tail.
            raw_jobs = [legacy, *raw_jobs[1:]]

    jobs: list[dict[str, Any]] = []
    occupied_slots: set[int] = set()
    for index, raw in enumerate(raw_jobs, start=1):
        if not isinstance(raw, dict):
            LOG.warning("ignoring malformed current_jobs[%d]: %r", index - 1, raw)
            continue
        job = dict(raw)
        try:
            slot_id = int(job.get("slot_id", index))
        except (TypeError, ValueError):
            slot_id = index
        if slot_id < 1 or slot_id in occupied_slots:
            slot_id = 1
            while slot_id in occupied_slots:
                slot_id += 1
        occupied_slots.add(slot_id)
        job["slot_id"] = slot_id
        job_id = str(job.get("job_id") or _legacy_job_id(job, index))
        job["job_id"] = job_id
        job["cohort_id"] = str(job.get("cohort_id") or job_id)
        job["phase"] = str(job.get("phase") or ("running" if job.get("pid") else "reserved"))
        job["attempt_started_at"] = job.get("attempt_started_at") or job.get("started_at")
        jobs.append(job)

    jobs.sort(key=lambda item: (int(item["slot_id"]), str(item["job_id"])))
    data["current_jobs"] = jobs
    data["current_job"] = jobs[0] if jobs else None
    if not isinstance(data.get("phase_z_pending"), list):
        data["phase_z_pending"] = []
    return data


def _sync_projection(data: dict[str, Any]) -> None:
    """Refresh the deprecated single-job view after a canonical mutation."""
    jobs = data.get("current_jobs") or []
    jobs.sort(key=lambda item: (int(item["slot_id"]), str(item["job_id"])))
    data["current_jobs"] = jobs
    data["current_job"] = jobs[0] if jobs else None


def _resolve_job_id(job_id: str | None) -> str | None:
    """Resolve a deprecated implicit handle only within its creating context.

    Never infer identity from "the only remaining job": after A exits, a stale
    A callback could otherwise clear the sole surviving sibling B.
    """
    return str(job_id) if job_id is not None else _IMPLICIT_JOB_ID.get()


def _find_job(data: dict[str, Any], job_id: str | None) -> tuple[int, dict[str, Any]] | None:
    """Find an exact logical job. Missing identity never falls back by count."""
    jobs = data.get("current_jobs") or []
    job_id = _resolve_job_id(job_id)
    if job_id is None:
        return None
    for index, job in enumerate(jobs):
        if str(job.get("job_id")) == str(job_id):
            return index, job
    return None


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


# Backward-compatible probe constant; path classification is owned centrally by
# volpred.canonical_write rather than a dispatch-specific equality check.
_CANONICAL_STATE_PATH = STATE_PATH


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    """Write JSON atomically: temp file in same dir → fsync → os.replace.

    Codex review fix #4 (2026-06-15): the previous seek/truncate/dump/fsync
    pattern was non-atomic — a crash between truncate() and dump() leaves
    the canonical state file empty, and a crash mid-dump leaves a partial
    JSON that fails to parse on next boot (the `_empty_state()` fallback
    would silently nuke completion history / auth_blocked flag / dedup).
    os.replace() is POSIX-atomic on same filesystem; downstream readers
    never observe a partially-written file.

    The shared writer-level gate is precise where the former per-test mtime
    fingerprint was not: it identifies the attempted writer and permits tmp
    paths while the live daemon independently updates its own state.
    """
    guard_canonical_write(path)
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
    if not path.parent.exists():
        guard_canonical_write(path.parent)
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
            _normalise_state(data)
            yield lock_fh, data
            _sync_projection(data)
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
            return _normalise_state(data)
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


def mark_restart_orphans_pending(path: Path = STATE_PATH) -> list[dict[str, Any]]:
    """Flag every occupied slot for restart-orphan investigation atomically.

    Returns immutable snapshots ordered by slot. Nothing is cleared here: a
    second supervisor crash must be able to rediscover every sibling.

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
        result: list[dict[str, Any]] = []
        for job in data.get("current_jobs") or []:
            job["restart_cleanup_pending"] = True
            job["phase"] = "restart_cleanup"
            result.append(dict(job))
        _sync_projection(data)
        return result


def mark_restart_orphan_pending(path: Path = STATE_PATH) -> dict[str, Any] | None:
    """Deprecated single-slot wrapper for `mark_restart_orphans_pending()`."""
    jobs = mark_restart_orphans_pending(path)
    if not jobs:
        return None
    _IMPLICIT_JOB_ID.set(str(jobs[0]["job_id"]))
    return jobs[0]


def finalize_restart_orphan_cleanup(
    path: Path = STATE_PATH, *, job_id: str | None = None,
) -> bool:
    """CAS-clear exactly one orphan after identity-check, kill, and record.

    `job_id` is mandatory when more than one slot is occupied. Returning False
    means another cleanup actor already won the transition.
    """
    with _locked_state(path) as (_fh, data):
        found = _find_job(data, job_id)
        if found is None:
            return False
        index, _job = found
        del data["current_jobs"][index]
        _sync_projection(data)
        return True


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
            "job_id": job.get("job_id"),
            "cohort_id": job.get("cohort_id"),
            "slot_id": job.get("slot_id"),
            "scheduled_for": job.get("scheduled_for"),
            "fire_reason": job.get("fire_reason") or "cron",
            "fire_key": job.get("fire_key"),
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
        if mark_cleanup_recorded:
            found = _find_job(data, job.get("job_id"))
            if found is not None:
                _index, current = found
                current["cleanup_recorded"] = True
            # Record the outcome so a crash-before-finalize retry knows whether
            # to re-alert (Codex review round-3 #1) without re-appending.
                current["cleanup_outcome"] = outcome
                pending = data.get("phase_z_pending") or []
                if not any(item.get("job_id") == job.get("job_id") for item in pending):
                    pending.append({
                        "job_id": job.get("job_id"),
                        "cohort_id": job.get("cohort_id"),
                        "slot_id": job.get("slot_id"),
                        "created_at": _now(),
                    })
                data["phase_z_pending"] = pending
                _sync_projection(data)
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


@dataclass(frozen=True)
class JobHandle:
    """Immutable identity returned by the atomic slot reservation."""

    job_id: str
    cohort_id: str
    slot_id: int


def reserve_fire(
    *,
    schedule_id: str,
    attempt: int,
    model: str,
    log_path: str,
    scheduled_for: str | None = None,
    fire_reason: str = "cron",
    fire_key: str | None = None,
    max_slots: int = 2,
    cohort_id: str | None = None,
    path: Path = STATE_PATH,
) -> JobHandle:
    """Atomically claim the lowest free slot BEFORE spawning the child.

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
    try:
        max_slots = int(max_slots)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"max_slots must be an integer, got {max_slots!r}") from exc
    if max_slots < 1:
        raise ValueError(f"max_slots must be >= 1, got {max_slots}")

    with _locked_state(path) as (_fh, data):
        jobs = data.get("current_jobs") or []
        pending = data.get("phase_z_pending") or []
        if pending:
            raise RuntimeError(
                "reserve_fire while PHASE-Z drain is pending: "
                f"current_jobs={jobs} phase_z_pending={pending}"
            )
        if fire_key:
            duplicate = next(
                (
                    item for item in [*jobs, *(data.get("completions") or [])]
                    if item.get("fire_key") == fire_key
                ),
                None,
            )
            if duplicate is not None:
                raise RuntimeError(f"reserve_fire duplicate fire_key={fire_key}")
        occupied = {int(job["slot_id"]) for job in jobs}
        occupied.update(
            int(item["slot_id"]) for item in pending
            if isinstance(item, dict) and item.get("slot_id") is not None
        )
        if len(occupied) >= max_slots:
            raise RuntimeError(
                f"reserve_fire while slots at max_slots={max_slots}: "
                f"current_jobs={jobs} phase_z_pending={pending}"
            )
        slot_id = next((slot for slot in range(1, max_slots + 1) if slot not in occupied), None)
        if slot_id is None:
            raise RuntimeError(
                f"reserve_fire while current_jobs at max_slots={max_slots}: {jobs}"
            )
        active_ids = {str(job.get("job_id")) for job in jobs}
        job_id = uuid.uuid4().hex
        while job_id in active_ids:  # defensive against a monkeypatched UUID source
            job_id = uuid.uuid4().hex
        cohort = str(cohort_id or uuid.uuid4().hex)
        started_at = _now()
        job = {
            "job_id": job_id,
            "cohort_id": cohort,
            "slot_id": slot_id,
            "phase": "reserved",
            "pid": None,
            "pgid": None,
            "started_wall": None,
            "schedule_id": schedule_id,
            "started_at": started_at,
            "attempt_started_at": started_at,
            "attempt": attempt,
            "model": model,
            "log_path": log_path,
            "scheduled_for": scheduled_for,
            "fire_reason": fire_reason,
            "fire_key": fire_key,
        }
        jobs.append(job)
        data["current_jobs"] = jobs
        data["last_fire_at"] = started_at
        _sync_projection(data)
    _IMPLICIT_JOB_ID.set(job_id)
    return JobHandle(job_id=job_id, cohort_id=cohort, slot_id=slot_id)


def begin_attempt(
    *, job_id: str, attempt: int, model: str, log_path: str,
    expected_previous_attempt: int | None = None,
    path: Path = STATE_PATH,
) -> JobHandle | None:
    """CAS-start a retry attempt while retaining the logical fire's slot."""
    with _locked_state(path) as (_fh, data):
        found = _find_job(data, job_id)
        if found is None:
            return None
        _index, job = found
        if expected_previous_attempt is not None and int(job.get("attempt", 0)) != int(expected_previous_attempt):
            return None
        if job.get("pid") is not None:
            raise RuntimeError(f"begin_attempt while process still attached: job_id={job_id}")
        attempt_started_at = _now()
        job.update({
            "phase": "reserved",
            "pid": None,
            "pgid": None,
            "started_wall": None,
            "attempt_started_at": attempt_started_at,
            "attempt": int(attempt),
            "model": model,
            "log_path": log_path,
        })
        _sync_projection(data)
        handle = JobHandle(
            job_id=str(job["job_id"]), cohort_id=str(job["cohort_id"]),
            slot_id=int(job["slot_id"]),
        )
    _IMPLICIT_JOB_ID.set(handle.job_id)
    return handle


def mark_job_phase(
    *, job_id: str, phase: str, expected_phase: str | None = None,
    expected_attempt: int | None = None, expected_pid: int | None = None,
    detach_process: bool = False, path: Path = STATE_PATH,
) -> bool:
    """CAS-update phase and optionally detach an exited attempt process.

    Detach before a long failover/backoff so the health watchdog cannot mistake
    the intentionally exited Claude pid for a silent death. pid/attempt CAS
    prevents a stale callback from detaching a newer retry attempt.
    """
    with _locked_state(path) as (_fh, data):
        found = _find_job(data, job_id)
        if found is None:
            return False
        _index, job = found
        if expected_phase is not None and job.get("phase") != expected_phase:
            return False
        if expected_attempt is not None and int(job.get("attempt", 0)) != int(expected_attempt):
            return False
        if expected_pid is not None and job.get("pid") != expected_pid:
            return False
        job["phase"] = str(phase)
        if detach_process:
            job["pid"] = None
            job["pgid"] = None
            job["started_wall"] = None
        _sync_projection(data)
        return True


def attach_process(
    *, pid: int, pgid: int, started_wall: str | None,
    job_id: str | None = None, expected_attempt: int | None = None,
    path: Path = STATE_PATH,
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
        found = _find_job(data, job_id)
        if found is None:
            raise RuntimeError("attach_process called with no active reservation")
        _index, job = found
        if expected_attempt is not None and int(job.get("attempt", 0)) != int(expected_attempt):
            raise RuntimeError(
                f"attach_process attempt CAS failed: job_id={job.get('job_id')} "
                f"expected={expected_attempt} actual={job.get('attempt')}"
            )
        if job.get("pid") is not None:
            raise RuntimeError(f"attach_process called twice: job_id={job.get('job_id')}")
        job["pid"] = pid
        job["pgid"] = pgid
        job["started_wall"] = started_wall
        job["phase"] = "running"
        _sync_projection(data)


def update_started_wall(
    *, pid: int, started_wall: str, job_id: str | None = None,
    expected_attempt: int | None = None, path: Path = STATE_PATH,
) -> None:
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
        found = _find_job(data, job_id)
        if found is None:
            # Safe legacy fallback: pid identifies a currently attached OS
            # process; unlike list length it cannot select an arbitrary sibling.
            matches = [job for job in data.get("current_jobs") or [] if job.get("pid") == pid]
            if len(matches) != 1:
                return
            job = matches[0]
        else:
            _index, job = found
        if job.get("pid") != pid:
            return
        if expected_attempt is not None and int(job.get("attempt", 0)) != int(expected_attempt):
            return
        job["started_wall"] = started_wall
        _sync_projection(data)


def release_reservation(
    path: Path = STATE_PATH, *, job_id: str | None = None,
    expected_attempt: int | None = None,
) -> bool:
    """Free the slot when spawn itself failed after `reserve_fire()` succeeded
    (e.g. `claude_bin` missing → `FileNotFoundError` before a pid ever existed).
    Without this the slot would wedge forever (current_job set, no process)."""
    with _locked_state(path) as (_fh, data):
        found = _find_job(data, job_id)
        if found is None:
            return False
        index, job = found
        if expected_attempt is not None and int(job.get("attempt", 0)) != int(expected_attempt):
            return False
        if job.get("pid") is not None:
            raise RuntimeError(f"release_reservation with attached process: job_id={job.get('job_id')}")
        del data["current_jobs"][index]
        _sync_projection(data)
        if _IMPLICIT_JOB_ID.get() == str(job.get("job_id")):
            _IMPLICIT_JOB_ID.set(None)
        return True


def record_completion(
    *,
    exit_code: int,
    outcome: str,
    final_model: str,
    job_id: str | None = None,
    expected_attempt: int | None = None,
    expected_pid: int | None = None,
    expected_phase: str | None = None,
    release_slot: bool = True,
    path: Path = STATE_PATH,
) -> dict[str, Any] | None:
    """Move current_job → completions ring buffer. Returns the completion entry,
    or None if the slot was already empty.

    The return value is also the **race-winner token**, and callers must treat it
    as such. Hang detection has two independent triggers (the worker's own
    subprocess timeout in worker.py, and the max-age watchdog in health.py) and
    on a real hang both fire within ~1s of each other. This function is the
    single atomic transition between them: it runs under `_locked_state`, so
    exactly one caller sees the job and clears it; the loser sees None.

    Whoever gets a non-None entry OWNS the incident and is the one that must
    alert. The loser must stay silent — it no longer has the job to describe.
    Ignoring that, and re-reading `current_job` after the transition to build the
    alert, is what produced the blind "pid=-1 / pgid=-1 / started_at=None /
    log=(unknown) / tail=(empty)" hang mails the owner kept receiving (2026-07-12
    00:57): the loser won the alert-dedup lottery and mailed a job it could no
    longer see. Hence `job` — the snapshot as it was at the moment of the
    transition — rides along in the returned dict so the winner never has to look
    it up again. It is deliberately NOT persisted into the completions ring.
    """
    managed_phase_z = job_id is not None
    with _locked_state(path) as (_fh, data):
        found = _find_job(data, job_id)
        if found is None:
            return None
        index, job = found
        if expected_attempt is not None and int(job.get("attempt", 0)) != int(expected_attempt):
            return None
        if expected_pid is not None and job.get("pid") != expected_pid:
            return None
        if expected_phase is not None and job.get("phase") != expected_phase:
            return None
        job_snapshot = dict(job)
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
            "job_id": job.get("job_id"),
            "cohort_id": job.get("cohort_id"),
            "slot_id": job.get("slot_id"),
            "scheduled_for": job.get("scheduled_for"),
            "fire_reason": job.get("fire_reason") or "cron",
            "fire_key": job.get("fire_key"),
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
        cohort_drained = False
        if release_slot:
            del data["current_jobs"][index]
            if managed_phase_z:
                pending = data.get("phase_z_pending") or []
                if not any(item.get("job_id") == job.get("job_id") for item in pending):
                    pending.append({
                        "job_id": job.get("job_id"),
                        "cohort_id": job.get("cohort_id"),
                        "slot_id": job.get("slot_id"),
                        "created_at": _now(),
                    })
                data["phase_z_pending"] = pending
            cohort_drained = not any(
                sibling.get("cohort_id") == job.get("cohort_id")
                for sibling in data.get("current_jobs") or []
            )
        else:
            # Retain ownership while waiting to retry. pid=None means health
            # has no process to inspect, but the occupied slot still blocks a
            # scheduler from stealing it.
            job.update({
                "phase": "retry_wait",
                "pid": None,
                "pgid": None,
                "started_wall": None,
            })
        _sync_projection(data)
        if release_slot and _IMPLICIT_JOB_ID.get() == str(job.get("job_id")):
            _IMPLICIT_JOB_ID.set(None)
        # `job` is returned but never persisted — the ring buffer keeps its
        # existing shape (see test_every_written_field_is_declared_in_empty_state).
        return {
            **entry,
            "job": job_snapshot,
            "phase_z_pending": bool(release_slot and managed_phase_z),
            "cohort_drained": cohort_drained,
        }


def finish_phase_z(*, cohort_id: str, path: Path = STATE_PATH) -> int:
    """Release every drained slot for one cohort after PHASE-Z finishes.

    Returns the number of pending slot records removed. The exact cohort CAS
    makes a duplicate finally callback harmless and cannot release another
    concurrently draining cohort.
    """
    with _locked_state(path) as (_fh, data):
        pending = data.get("phase_z_pending") or []
        kept = [item for item in pending if str(item.get("cohort_id")) != str(cohort_id)]
        removed = len(pending) - len(kept)
        data["phase_z_pending"] = kept
        return removed


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
# Planned-restart marker (deploy-aware restart-alert suppression, 2026-07-10)
#
# A restart under launchd KeepAlive is normally worth an INFO breadcrumb to the
# owner — an *unexpected* KeepAlive respawn means the daemon crashed. But a
# restart caused by a *deliberate* `launchctl kickstart -k` after editing the
# supervisor's own code (its memory image is frozen at boot, so a code change
# only takes effect on reload) is pure deploy noise. On 2026-07-10 a dev session
# reloaded the daemon 5× in 80min while fixing supervisor bugs → 5 INFO restart
# emails (Telegram msg 352 complaint).
#
# The reloader drops a short-lived marker BEFORE kickstart; the fresh boot
# consumes it and downgrades its restart alert to a log-only breadcrumb. The
# marker lives in its OWN file (not `dispatch_state.json`) so it never contends
# for the hot state lock and a schema-version bump can never wipe it. It is
# consume-once: a crash *right after* a planned reload has no marker on the
# KeepAlive respawn → that (genuinely unexpected) restart still alerts.
# ---------------------------------------------------------------------------
RESTART_MARKER_PATH = ROOT / "storage" / "ops" / "supervisor_restart_marker.json"
_RESTART_MARKER_DEFAULT_TTL_S = 120


def write_planned_restart_marker(
    reason: str = "deploy",
    ttl_s: int = _RESTART_MARKER_DEFAULT_TTL_S,
    path: Path = RESTART_MARKER_PATH,
) -> str:
    """Record that the *next* supervisor boot is a planned reload, not a crash.

    Called by the reload wrapper immediately before `launchctl kickstart -k`.
    Returns the ISO `expires_at` so the caller can log it. The marker is a
    single small JSON written atomically; TTL bounds how long a stale marker
    can mask a real crash (default 120s covers kickstart + boot comfortably).
    """
    now = datetime.now(timezone.utc)
    expires_at = (now + timedelta(seconds=max(1, int(ttl_s)))).isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(
        path,
        {"reason": str(reason), "written_at": now.isoformat(), "expires_at": expires_at},
    )
    return expires_at


def consume_planned_restart_marker(path: Path = RESTART_MARKER_PATH) -> str | None:
    """Return the planned-restart reason if a FRESH marker exists, else None.

    Consume-once: the marker file is always removed after being read, whether
    fresh or stale, so it can only suppress the single boot it was written for.
    A corrupt or expired marker returns None (→ the restart alert fires as an
    unexpected event) and is logged, never silently swallowed."""
    if not path.exists():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
        marker = json.loads(raw)
    except (OSError, ValueError) as exc:
        LOG.warning(
            "planned_restart_marker unreadable — treating restart as unexpected: %s (%s)",
            exc, path,
        )
        _unlink_quiet(path)
        return None
    _unlink_quiet(path)  # consume-once regardless of freshness
    try:
        expires_at = _parse_state_timestamp(marker.get("expires_at"))
    except (TypeError, ValueError) as exc:
        LOG.warning("planned_restart_marker bad expires_at %r (%s)", marker.get("expires_at"), exc)
        return None
    if datetime.now(timezone.utc) >= expires_at:
        LOG.info(
            "planned_restart_marker expired (expires_at=%s) — restart treated as unexpected",
            marker.get("expires_at"),
        )
        return None
    return str(marker.get("reason") or "deploy")


def _unlink_quiet(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass  # silent-ok: consume-once race — another boot already removed it
    except OSError as exc:
        LOG.warning("planned_restart_marker unlink failed: %s (%s)", exc, path)


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
    job_id: str = ""
    cohort_id: str = ""
    slot_id: int = 1
    phase: str = "running"
    started_wall: str | None = None
    age_seconds: float = 0.0


def get_current_jobs(path: Path = STATE_PATH) -> list[CurrentJob]:
    """Return every inspectable process, ordered by stable slot id.

    Reserved/retry-wait jobs with pid=None still occupy capacity in raw state,
    but are omitted because a watchdog has no OS process to inspect.
    """
    snap = read_state(path)
    result: list[CurrentJob] = []
    for job in snap.get("current_jobs") or []:
        if job.get("pid") is None or job.get("phase") == "classifying":
            continue
        age = -1.0
        try:
            started_dt = _parse_state_timestamp(job["attempt_started_at"] or job["started_at"])
            age = (datetime.now(timezone.utc) - started_dt).total_seconds()
        except (KeyError, TypeError, ValueError) as exc:
            LOG.warning(
                "invalid current_job.started_at in %s: %r (%s: %s)",
                path,
                job.get("attempt_started_at") or job.get("started_at"),
                type(exc).__name__,
                exc,
            )
        result.append(CurrentJob(
            job_id=str(job.get("job_id", "")),
            cohort_id=str(job.get("cohort_id", "")),
            slot_id=int(job.get("slot_id", 0)),
            pid=int(job["pid"]),
            pgid=int(job.get("pgid") or job["pid"]),
            schedule_id=str(job.get("schedule_id", "")),
            started_at=str(job.get("started_at", "")),
            attempt=int(job.get("attempt", 1)),
            model=str(job.get("model", "")),
            log_path=str(job.get("log_path", "")),
            phase=str(job.get("phase", "running")),
            started_wall=job.get("started_wall"),
            age_seconds=age,
        ))
    return result


def get_current_job(path: Path = STATE_PATH) -> CurrentJob | None:
    """Deprecated lowest-slot projection; use get_current_jobs()."""
    jobs = get_current_jobs(path)
    return jobs[0] if jobs else None


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
