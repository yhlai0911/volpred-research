"""Worker — subprocess.Popen wrapper with PGID isolation, timeout, retry ladder.

Replaces all `perl alarm` + watchdog + shell trap layers from
`scripts/cron_hourly_dispatch.sh` with one Python `Popen.wait(timeout=...)`.

Retry ladder (refactor_plan §3 retry policy)::

    attempt 1: opus    → opus exit≠0 + transient (529 / network) → sleep 90s
    attempt 2: opus    → opus exit≠0 + transient → sleep 90s
    attempt 3: sonnet  (final fallback)
    auth-class error  → NO retry; set_auth_blocked(True); send_auth_alert; Codex failover
    quota exhausted   → NO retry; send_quota_alert; Codex failover (separate quota)
    hang (SIGKILL'd)  → NO retry; record killed_timeout; alert

Codex failover (`codex_failover.py`) hands the hourly slot to `codex exec` when
Claude cannot run at all. Ported back in 2026-07-10 after the 2026-07-04
supervisor cutover orphaned it in the retired `cron_hourly_dispatch.sh`.

Each logical fire reserves one state slot before the first Popen and keeps that
same job_id/slot_id through retry backoff and Codex failover.  Attempts only
update that reservation; the final outcome releases it.  This distinction is
required once the scheduler can run more than one fire concurrently: releasing
between attempts lets another fire steal the slot and makes a stale completion
capable of closing the wrong process. Health monitor (health.py)
reads every current_jobs entry from the same state file to independently
detect frozen workers if THIS process itself hangs inside `wait()` (shouldn't
happen with `timeout=` but health is the belt-and-suspenders layer).
"""
from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from volpred.ops import fire_manifest, termination
from volpred.ops.execution.registry import (
    ProviderRegistryError,
    authorize_provider_spawn,
    verify_spawn_receipt,
)

from . import (
    alerts,
    claim_release,
    codex_failover,
    custody_receipt,
    failure_class,
    identity,
    isolation,
    procutil,
    state,
    workspace as workspace_mod,
)
from .child_env import external_child_environment

LOG = logging.getLogger(__name__)

# Default upstream constants (overridable via env for tests + ops)
DEFAULT_TIMEOUT_S = 3000  # 50min — matches CLAUDE.md hourly cap
GRACE_PERIOD_S = 10        # SIGTERM grace before SIGKILL
RETRY_BACKOFF_S = 90        # between transient-failure attempts
MAX_ATTEMPTS = 3

OPUS_MODEL = "claude-opus-5"
# Retired 2026-07-05 (owner all-opus directive): the retry ladder no longer
# drops to sonnet on the final attempt. Kept defined as a valid roster alias so
# any external reference still resolves, but no dispatch path selects it.
SONNET_MODEL = "claude-sonnet-5"

# Recorded as `final_model` when Codex covered the slot — never a Claude model,
# so completion history distinguishes "Claude did it" from "Codex did it".
CODEX_MODEL_LABEL = "codex-failover"

CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "/Users/yhlai0911/.local/bin/claude")
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Reasoning effort for the spawned orchestrator session (2026-07-05: effort was
# previously computed by model_router but NEVER passed to any `claude -p` — it
# was inert metadata. Now wired via `--effort`). This applies to the hourly
# orchestrator session, which does triage/routing/brief-writing + inline
# execution of light tasks; "high" is a strong-but-not-wasteful default (not
# xhigh/max every hour). Heavy research SUBAGENTS the orchestrator spawns should
# carry their own higher effort (xhigh/max per model_router) via their own
# `claude -p --effort` — the Agent/Task tool has no effort knob. The claude CLI
# fail-opens on unknown values (warns + uses default), so this is safe.
# Valid values: low | medium | high | xhigh | max.
DISPATCH_EFFORT = os.environ.get("VOLPRED_DISPATCH_EFFORT", "high")

# Exit codes from `claude -p` that we recognise
HANG_EXIT_CODES = {137, 142, 143}  # SIGKILL / SIGALRM / SIGTERM

# Sentinel value `_run_one_attempt` returns when our own timeout fired and we
# killed the child via _kill_pgid. Distinct from any legitimate POSIX status so
# `_classify` can deterministically map it to "hang" regardless of how the
# child raced with SIGTERM/SIGKILL. Fixes the Codex-review §10 #1 bug where a
# negative wait()-return from a signal-killed child (e.g. -15 SIGTERM, -9
# SIGKILL) was misclassified as `hard_failure` and triggered a retry that
# violated the no-retry-on-hang contract.
TIMEOUT_KILLED_SENTINEL = -1000
OWNERSHIP_LOST_SENTINEL = -1001
TIMEOUT_SURVIVED_SENTINEL = -1002
# The child printed a terse CLI fatal (see failure_class.is_terse_fatal_only)
# and then stopped writing without exiting. We killed it early rather than
# letting the hang cap reap it 16 minutes later. Distinct from the timeout
# sentinels because this is NOT a hang: nothing was running to hang.
FATAL_FASTFAIL_SENTINEL = -1003

# How long a terse-fatal-only log must sit unchanged before we call it dead.
# 60s per the owner's spec: long enough that a CLI which prints the marker and
# then recovers (never observed, but cheap to allow for) survives, short enough
# that the slot loses one minute instead of sixteen.
FATAL_STALL_S = float(os.environ.get("VOLPRED_DISPATCH_FATAL_STALL_S", "60"))
FATAL_POLL_S = float(os.environ.get("VOLPRED_DISPATCH_FATAL_POLL_S", "5"))
# Sidecar-liveness DOA detection (2026-07-21, third Execution-error strike).
# The terse fatal usually never reaches the main log until the process dies —
# the CLI holds it in-process and flushes at kill time (every incident log has
# mtime == kill time), so the marker probe above it is structurally blind to
# the live case; and a HEALTHY agentic run legitimately writes nothing to the
# main log for tens of minutes, so main-log silence alone discriminates
# nothing. The debug sidecar is the one channel with a positive liveness
# signal: a healthy CLI streams debug events from startup on; a dead-on-arrival
# one freezes within its first seconds. Detection therefore keys on "the
# sidecar froze INSIDE the startup window" — a run whose sidecar was still
# growing after that window can never be fast-failed by this path, however
# quiet it goes later (long tool runs are exactly that shape).
SIDECAR_DEAD_S = float(os.environ.get("VOLPRED_DISPATCH_SIDECAR_DEAD_S", "180"))
SIDECAR_STARTUP_WINDOW_S = float(
    os.environ.get("VOLPRED_DISPATCH_SIDECAR_STARTUP_WINDOW_S", "120"))
SIDECAR_STALL_S = float(os.environ.get("VOLPRED_DISPATCH_SIDECAR_STALL_S", "240"))

# Route the CLI's own debug stream to a per-attempt sidecar file (`--debug-file`).
#
# Why this is needed: the 15-byte incident logs carried no diagnostic detail at
# all. stderr is NOT missing — `_spawn` already folds it into the worker log, so
# `Execution error` genuinely WAS everything the CLI emitted — which is exactly
# the problem: the terse fatal names no cause (API? session limit? something
# else?), so the failures are unattributable.
#
# Why only from attempt 2: `--debug-file` implicitly enables debug mode, and we
# have not verified on this host whether debug ALSO reaches stdout. If it does,
# the extra lines land in the worker log, `is_terse_fatal_only` stops matching,
# and the sidecar would silently disable the fast-fail above — the fix breaking
# the more valuable fix. Attempt 1 therefore keeps a pristine log and always
# gets the fast path; by attempt 2 this fire is already known-bad, and knowing
# WHY beats one more clean classification. The first sidecar a real incident
# leaves behind settles whether this can widen to attempt 1.
# 2026-07-21: default 2 → 1. The sidecar is no longer only a post-mortem aid —
# it is the liveness channel the DOA detector reads (see SIDECAR_DEAD_S block),
# and every observed dead-on-arrival happened on attempt 1, exactly the attempt
# that used to run without one. Success still unlinks the sidecar, so the disk
# cost of always-on is one file per FAILED attempt.
DEBUG_SIDECAR_FROM_ATTEMPT = int(os.environ.get("VOLPRED_DISPATCH_DEBUG_FROM_ATTEMPT", "1"))

# stderr/stdout regex classifiers — shared with scripts/run_agent_job.py, the
# other place that spawns `claude -p` and must tell auth/quota/transient apart.
# See failure_class.py for why each class exists and what it obliges the caller
# to do.


@dataclass
class WorkerResult:
    exit_code: int
    # success | failure | killed_timeout | kill_failed_orphan | auth_blocked |
    # quota_blocked | codex_failover_recovered | superseded
    outcome: str
    final_model: str
    attempts: int
    duration_s: float
    log_tail: str            # last ~2KB of combined stdout+stderr


def _normalize_signal_exit(exit_code: int) -> int:
    """`subprocess.Popen.wait()` returns negative N when child died from signal N.

    Normalize to POSIX shell convention (128 + signum) so HANG_EXIT_CODES set
    membership works: -15 SIGTERM → 143, -9 SIGKILL → 137, -14 SIGALRM → 142.
    Positive codes pass through unchanged.
    """
    if exit_code is None:
        return 1
    if exit_code < 0:
        return 128 + abs(exit_code)
    return exit_code


def _classify(exit_code: int, output: str) -> str:
    """Classify one attempt using its private log only."""
    if exit_code == OWNERSHIP_LOST_SENTINEL:
        return "ownership_lost"
    if exit_code == TIMEOUT_SURVIVED_SENTINEL:
        return "hang_survived"
    if exit_code == FATAL_FASTFAIL_SENTINEL:
        return "fatal_fastfail"
    if exit_code == TIMEOUT_KILLED_SENTINEL:
        return "hang"
    if exit_code == 0:
        return "success"
    if exit_code in HANG_EXIT_CODES:
        # A raw signal exit can ONLY be an outside kill: every kill WE initiate
        # returns through a sentinel above (timeout / fatal probes), never as
        # the child's own wait() status. Until 2026-07-21 this fell into "hang"
        # — three healthy fires killed mid-work at ~600s by an unidentified
        # external SIGTERM were mailed to the owner as「卡住」CRITICALs
        # (email-12150, assign_7f15f261).
        return "external_signal"
    return failure_class.classify_output(output) or "hard_failure"


def _read_tail(path: Path, max_bytes: int = 2048) -> str:
    """Read last `max_bytes` of file; tolerate missing file."""
    try:
        with path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - max_bytes))
            return f.read().decode("utf-8", errors="replace")
    except FileNotFoundError:
        return ""  # silent-ok: log not created yet (spawn can fail before any output)
    except OSError as exc:
        LOG.warning("read_tail %s failed: %s", path, exc)
        return ""


def _log_size(path: Path) -> int:
    """Current byte size of the shared worker log (0 if absent)."""
    try:
        return path.stat().st_size
    except FileNotFoundError:
        return 0  # silent-ok: log not created yet — offset 0 is correct
    except OSError as exc:
        LOG.warning("log_size %s failed: %s", path, exc)
        return 0


def _read_since(path: Path, offset: int, max_bytes: int = 2048) -> str:
    """Read what THIS attempt wrote: bytes from `offset` to EOF (tail-capped).

    2026-07-05 (audit finding): the worker log is a shared, append-mode,
    never-rotated file, and `_classify` used to look at the file's global last
    2KB — which can be a PREVIOUS fire's output when the current attempt wrote
    little (e.g. after a quota outage the tail held 15 old quota lines; a
    later unrelated failure would misclassify as quota, or worse, a stale
    'Not logged in' line would misclassify as auth and freeze the whole loop
    behind a manual unblock). Classification must only ever see bytes written
    after the spawn-time offset. Alert bodies may still use `_read_tail` for
    human context.
    """
    try:
        with path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            end = f.tell()
            if end <= offset:
                return ""
            start = max(offset, end - max_bytes)
            f.seek(start)
            return f.read(end - start).decode("utf-8", errors="replace")
    except FileNotFoundError:
        return ""  # silent-ok: log never created — nothing was written
    except OSError as exc:
        LOG.warning("read_since %s failed: %s", path, exc)
        return ""


def _wait_with_fatal_probe(
    proc: subprocess.Popen,
    *,
    log_path: Path,
    log_offset: int,
    timeout_s: float,
    debug_path: Path | None = None,
    stall_s: float | None = None,
    poll_s: float | None = None,
    now_fn=time.monotonic,
) -> tuple[str, int | None]:
    """Wait for the child, watching for the "dead but not exited" shape.

    Returns one of:
      ("exited", raw_wait_status)  child exited on its own — the normal path
      ("timeout", None)            the hang cap expired, caller kills as before
      ("fatal_stall", None)        the child is provably dead-on-arrival —
                                   caller kills now

    Why a poll loop instead of one `proc.wait(timeout=timeout_s)`: the hang cap
    is a last resort, not a detector. On 2026-07-20 five fires printed
    `Execution error` within seconds and then sat there; each burned ~16 minutes
    of its slot before something reaped it, and each mailed a CRITICAL hang
    alert for a process that had never started working.

    TWO detectors feed the fatal_stall verdict, because the main log alone is
    structurally blind (2026-07-21, third strike of the same shape):

    1. Marker probe — the log holds ONLY a terse CLI fatal and has not grown
       for `stall_s`. Stall-gated so a CLI that prints the marker and then
       keeps writing takes itself back out of the verdict. In practice the CLI
       usually flushes the marker only when killed, so this branch catches the
       early-flush minority.
    2. Sidecar liveness — requires `debug_path`. A healthy CLI streams debug
       events from startup on; a DOA one freezes within its first seconds. The
       verdict fires only when the main log is quiet AND the sidecar either
       never wrote a byte (SIDECAR_DEAD_S) or froze at a size it reached inside
       SIDECAR_STARTUP_WINDOW_S and has not grown for SIDECAR_STALL_S. A run
       whose sidecar was still growing after the startup window can never be
       fast-failed here, however quiet it goes later.
    """
    # Resolved at CALL time, not bound as a default: the module globals are the
    # ops knob (env-overridable) and tests tune them by monkeypatching the
    # module, which a default argument captured at import would silently ignore.
    stall_s = FATAL_STALL_S if stall_s is None else stall_s
    poll_s = FATAL_POLL_S if poll_s is None else poll_s
    start = now_fn()
    deadline = start + timeout_s
    marker_since: float | None = None
    marker_size: int | None = None
    sidecar_size = 0
    sidecar_last_growth = start
    while True:
        remaining = deadline - now_fn()
        if remaining <= 0:
            return "timeout", None
        try:
            return "exited", proc.wait(timeout=min(poll_s, remaining))
        except subprocess.TimeoutExpired:
            pass  # silent-ok: poll tick — the timeout IS the loop's clock, not an error
        attempt_output = _read_since(log_path, log_offset)
        # ── detector 2: sidecar liveness (positive proof-of-life channel) ──
        if debug_path is not None:
            now = now_fn()
            size = _log_size(debug_path)
            if size != sidecar_size:
                sidecar_size, sidecar_last_growth = size, now
            main_quiet = (not attempt_output.strip()
                          or failure_class.is_terse_fatal_only(attempt_output))
            if main_quiet:
                if sidecar_size == 0 and now - start >= SIDECAR_DEAD_S:
                    return "fatal_stall", None
                if (sidecar_size > 0
                        and sidecar_last_growth - start <= SIDECAR_STARTUP_WINDOW_S
                        and now - sidecar_last_growth >= SIDECAR_STALL_S):
                    return "fatal_stall", None
        # ── detector 1: terse-fatal marker on the main log ──
        size = _log_size(log_path)
        if not failure_class.is_terse_fatal_only(attempt_output):
            marker_since, marker_size = None, None  # working, or wrote something else
            continue
        if marker_since is None or size != marker_size:
            marker_since, marker_size = now_fn(), size  # (re)start the grace window
            continue
        if now_fn() - marker_since >= stall_s:
            return "fatal_stall", None


def _kill_pgid(
    pgid: int,
    *,
    leader_pid: int | None = None,
    reason: str = "worker_watchdog",
    job_id: str | None = None,
    attempt: int | None = None,
    custody: dict | None = None,
    state_path: Path = state.STATE_PATH,
    grace_s: float = GRACE_PERIOD_S,
) -> bool:
    """Terminate the producer cohort and confirm no known descendant survives.

    Codex review fix #5 (2026-07-04): the actual implementation moved to
    ``procutil``.  When the leader identity is available, use ``kill_tree``:
    a descendant may call ``setsid()`` and escape the original PGID while
    retaining write access to the producer workspace.  The PGID-only fallback
    remains for legacy callers that genuinely lack the leader identity.
    """
    ledger_path = termination.ledger_for_state(state_path)
    intent = termination.arm(
        target_kind="pgid",
        target_id=pgid,
        target_identity=(
            f"producer-custody:{custody.get('resource_coalition_id', 'unknown')}"
            if custody is not None
            else None
        ),
        reason=reason,
        actor="dispatch-supervisor.worker",
        signal_sequence=[signal.SIGTERM, signal.SIGKILL],
        job_id=job_id,
        attempt=attempt,
        ledger_path=ledger_path,
    )
    if custody is not None:
        drained = procutil.kill_producer_cohort(
            custody,
            intent=intent,
            ledger_path=ledger_path,
            grace_s=grace_s,
        )
    elif leader_pid is not None:
        drained = procutil.kill_tree(
            leader_pid,
            intent=intent,
            ledger_path=ledger_path,
            grace_s=grace_s,
        )
    else:
        drained = procutil.kill_pgid(
            pgid, intent=intent, ledger_path=ledger_path, grace_s=grace_s,
        )
    if not drained:
        return False
    cohort = procutil.producer_cohort_members_checked(
        pgid,
        job_id=job_id,
        custody=custody,
    )
    return cohort == []


def _dispatch_actor(
    schedule_id: str,
    *,
    slot_id: str | None = None,
    job_id: str | None = None,
    now: datetime | None = None,
) -> str:
    """VOLPRED_ACTOR stamp injected into the spawned agent's env.

    Until 2026-07-10 no automated dispatch path exported VOLPRED_ACTOR, so every
    shared-state write the agent made (writer_log reads actor off os.environ —
    memory/publisher/control_plane call sites) logged actor="unknown": 197/200
    recent writer_log lines. That unrecoverable attribution stalled the pregate
    enforce-flip evaluation (docs/error_log.md 2026-07-10). The stamp locates the
    exact fire — schedule id plus local HHMM, matching the clock the work_log
    `hourly-<HH>` convention already uses — so a writer_log line traces back to
    the dispatch that produced it instead of the pipeline-wide default.
    """
    stamp = (now or datetime.now()).strftime("%H%M")
    suffix = ""
    if slot_id:
        suffix += f":{slot_id}"
    if job_id:
        suffix += f":{job_id[:8]}"
    return f"dispatch-worker:{schedule_id}:{stamp}{suffix}"


def _spawn(
    *,
    argv: Sequence[str],
    log_path: Path,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
) -> subprocess.Popen:
    """Spawn child in its own process group; redirect combined stdout+stderr to log_path.

    ``env=None`` starts from the parent environment.  In either case the final
    Popen boundary removes immutable-supervisor identity: that identity belongs
    to the daemon and must never reach a provider or any of its descendants.
    Ordinary PATH / auth / HOME / actor values survive.

    Hang-log capture (2026-07-18): a child's stdout to a plain file fd is
    block-buffered by default, so when a hung worker is SIGKILL'd the whole
    in-process buffer dies with it — the log lands 0 bytes and the hang alert's
    `Worker log tail` (see alerts.read_log_tail) is useless exactly for the
    fires that most need diagnosing (evidence: the only two 0-byte worker logs
    were both hang_killed). We force `PYTHONUNBUFFERED=1` into the child env so
    every python child (the worker's helpers and any python the agent spawns)
    flushes each line to the OS page cache, which persists across SIGKILL.

    We must extend the resolved env, never replace it. A bare
    `{"PYTHONUNBUFFERED": "1"}` would wipe PATH/HOME/auth and the
    child could not exec or authenticate.

    Scope honesty: this helps python children only. The real hourly child is the
    `claude` CLI (Node), whose stdout to a regular-file fd is written
    synchronously (libuv SyncWriteStream) and already survives SIGKILL — it does
    not read PYTHONUNBUFFERED and gains nothing here. We deliberately do NOT
    prefix argv with `stdbuf -oL`: verified locally that stdbuf does not unbuffer
    python (python buffers in its own io layer, not libc FILE*) and is inert for
    Node, while its DYLD_INSERT_LIBRARIES/libstdbuf shim is inherited by every
    descendant and can emit dyld warnings that would pollute the 2KB
    classification tail (`_read_since`) — a net negative. A PTY is likewise
    rejected: making isatty() true risks `claude -p` emitting ANSI/TUI output
    that corrupts outcome classification.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_fh = log_path.open("ab")
    child_env = external_child_environment(
        env,
        overrides={"PYTHONUNBUFFERED": "1"},
    )
    return subprocess.Popen(
        list(argv),
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        start_new_session=True,  # new PGID — clean SIGKILL group
        close_fds=True,
        env=child_env,
        cwd=str(cwd) if cwd is not None else None,
    )


def _run_one_attempt(
    *,
    prompt_text: str,
    model: str,
    timeout_s: int,
    log_path: Path,
    attempt: int,
    schedule_id: str,
    scheduled_for: str | None = None,
    fire_reason: str = "cron",
    state_path: Path,
    job_id: str | None = None,
    slot_id: str | None = None,
    claude_bin: str = CLAUDE_BIN,
    effort: str = DISPATCH_EFFORT,
    workdir: Path | None = None,
    isolated_workspace: dict | None = None,
    preselected_task_id: str | None = None,
    process_identity_sink: Callable[[int], None] | None = None,
) -> tuple[int, float]:
    """Single Popen attempt. Returns (exit_code, duration_s, attempt_output).

    `attempt_output` is ONLY the bytes this attempt appended to the shared
    log (spawn-time offset → EOF, tail-capped 2KB) — the classification
    input, immune to previous fires' leftovers (2026-07-05 fix).

    On timeout: SIGKILL whole PGID, return exit_code=-9 (mapped to killed_timeout
    upstream via HANG_EXIT_CODES + outcome classification).
    """
    isolation_receipt = (
        {
            key.removeprefix("isolation_"): value
            for key, value in isolated_workspace.items()
            if key.startswith("isolation_")
        }
        if isinstance(isolated_workspace, dict)
        else None
    )
    custody_repo_root = Path(
        str(
            (
                isolated_workspace.get("isolation_canonical_root")
                if isinstance(isolated_workspace, dict)
                else None
            )
            or PROJECT_ROOT
        )
    )
    producer_custody: dict | None = None
    global_custody_bound = False

    def _release_global_custody() -> None:
        nonlocal global_custody_bound
        if not global_custody_bound:
            return
        custody_receipt.release_producer_custody(
            custody_repo_root,
            job_id=str(job_id),
            attempt=attempt,
            drain_confirmed=True,
        )
        global_custody_bound = False
    debug_root = (
        Path(str(isolation_receipt["run_dir"]))
        if isinstance(isolation_receipt, dict)
        and isolation_receipt.get("run_dir")
        else log_path.parent
    )
    debug_path = debug_root / f"{log_path.stem}.attempt{attempt}.debug.log"
    argv = [
        claude_bin, "-p", "--dangerously-skip-permissions",
        "--effort", effort, "--model", model,
        "--add-dir", str(PROJECT_ROOT),
        "--setting-sources", "",
        "--settings", str(PROJECT_ROOT / ".claude" / "settings.json"),
        *(["--debug-file", str(debug_path)]
          if attempt >= DEBUG_SIDECAR_FROM_ATTEMPT else []),
        prompt_text,
    ]
    managed_state = True
    declare_manifest = job_id is not None
    if job_id is None:
        # Compatibility for direct one-attempt smoke/tests. Production reserves
        # the logical fire in scheduler/run_worker and always supplies job_id.
        handle = state.reserve_fire(
            schedule_id=schedule_id, attempt=attempt, model=model,
            log_path=str(log_path), scheduled_for=scheduled_for,
            fire_reason=fire_reason, path=state_path,
        )
        if handle is None:  # mocked legacy reserve in a unit test
            job_id, slot_id = "direct-smoke", "slot-1"
            managed_state = False
        else:
            job_id, slot_id = handle.job_id, f"slot-{handle.slot_id}"
    else:
        # The logical fire already owns a slot. Retry attempts mutate that exact
        # job_id rather than releasing/re-reserving capacity.
        handle = state.begin_attempt(
            job_id=job_id, attempt=attempt, model=model, log_path=str(log_path),
            expected_previous_attempt=attempt if attempt == 1 else attempt - 1,
            path=state_path,
        )
        if handle is None:
            raise RuntimeError(
                f"begin_attempt CAS lost: job_id={job_id} attempt={attempt}"
            )
    slot_id = slot_id or "slot-1"
    # Record where the shared append-log ends BEFORE we spawn: classification
    # must only ever see THIS attempt's bytes (2026-07-05 cross-fire
    # contamination fix — see _read_since).
    log_offset = _log_size(log_path)
    started = time.time()
    # Stamp the fire onto the agent's env so its shared-state writes are
    # attributable (see _dispatch_actor). Extend the sanitized parent
    # environment — the supervisor boot set VOLPRED_ACTOR=dispatch-supervisor
    # as a process default, which we deliberately override here so AGENT writes
    # carry the fire, not the daemon.
    child_env = external_child_environment(
        overrides={
            "VOLPRED_ACTOR": _dispatch_actor(
                schedule_id, slot_id=slot_id, job_id=job_id,
            ),
            "VOLPRED_DISPATCH_SLOT": slot_id,
            "VOLPRED_DISPATCH_JOB_ID": job_id,
            "VOLPRED_FIRE_ID": job_id,
            "VOLPRED_FIRE_REPO_ROOT": str(PROJECT_ROOT),
            "VOLPRED_TASK_CLAIM_OWNER": identity.task_claim_owner(
                role="hourly", slot_id=slot_id, job_id=job_id,
            ),
            **(
                {"VOLPRED_PRESELECTED_TASK_ID": preselected_task_id}
                if preselected_task_id
                else {}
            ),
        },
    )
    if isolated_workspace is not None:
        expected_workspace = Path(str(isolated_workspace.get("path") or "")).resolve()
        if workdir is None or Path(workdir).resolve() != expected_workspace:
            raise isolation.IsolationUnavailable(
                "worker cwd does not match allocated workspace identity"
            )
        if not isinstance(isolation_receipt, dict):
            raise isolation.IsolationUnavailable(
                "worker isolation was not prepared during admission"
            )
        child_env = isolation.isolated_environment(
            child_env,
            isolation_receipt,
            provider_id="claude-cli",
        )
    # Stage 2 of declared commit ownership: create the change-set before the
    # producer can write.  This remains observability-only; PHASE-Z still uses
    # its fire-start baseline until the seven-day shadow gate passes.
    if declare_manifest:
        try:
            fire_manifest.open_manifest(
                PROJECT_ROOT,
                fire_id=job_id,
                actor=child_env["VOLPRED_ACTOR"],
                job_id=job_id,
                slot_id=slot_id,
            )
        except Exception as exc:  # noqa: BLE001 — attribution must never veto a fire
            LOG.warning("fire manifest open failed for job_id=%s: %s", job_id, exc)
    # Resolve and verify the executable before taking the kernel baseline.  No
    # provider can exist yet, so a policy/wrapper error is a mechanically proven
    # no-spawn outcome rather than a pid=None ambiguity.
    try:
        provider_receipt = authorize_provider_spawn(
            contract_id="dispatch-supervisor.claude",
            model_id=model,
            executable_path=claude_bin,
            environment=child_env,
        )
        child_env = external_child_environment(
            child_env,
            overrides=provider_receipt.environment(),
        )
        argv[0] = provider_receipt.resolved_executable
        if provider_receipt.settings_path is None:
            raise ProviderRegistryError(
                "Claude launch contract requires pinned settings"
            )
        argv[argv.index("--settings") + 1] = provider_receipt.settings_path
        verify_spawn_receipt(provider_receipt)
        # Provider authorization replaces argv[0] with the hash-pinned Claude
        # executable.  Wrap only after that replacement; wrapping first would
        # turn ``sandbox-exec -f profile claude ...`` into
        # ``claude -f profile claude ...`` and every isolated fire would
        # terminate immediately with "unknown option '-f'".
        if isolated_workspace is not None:
            assert isinstance(isolation_receipt, dict)
            argv = isolation.wrap_prepared(argv, isolation_receipt)
        # Capture a kernel-backed producer boundary immediately before Popen,
        # then persist it under the exact attempt CAS.  On macOS this is the
        # launchd resource-coalition id plus process unique IDs for only the
        # trusted supervisor ancestor chain; an existing unknown member makes
        # capture fail closed instead of laundering an orphan into the baseline.
        producer_custody = procutil.capture_producer_custody()
        if producer_custody is None and sys.platform == "darwin":
            raise isolation.IsolationUnavailable(
                "producer custody baseline is unavailable or coalition is not quiescent"
            )
        if producer_custody is not None:
            if managed_state and not state.attach_producer_custody(
                job_id=job_id,
                custody=producer_custody,
                expected_attempt=attempt,
                path=state_path,
            ):
                raise RuntimeError(
                    f"producer custody CAS lost: job_id={job_id} attempt={attempt}"
                )
            custody_receipt.bind_producer_custody(
                custody_repo_root,
                job_id=job_id,
                attempt=attempt,
                custody=producer_custody,
            )
            global_custody_bound = True
            if (
                isinstance(isolated_workspace, dict)
                and not workspace_mod.bind_producer_custody(
                    Path(
                        str(
                            isolated_workspace.get("isolation_canonical_root")
                            or PROJECT_ROOT
                        )
                    ),
                    workspace=isolated_workspace,
                    job_id=job_id,
                    producer_custody=producer_custody,
                    attempt=attempt,
                )
            ):
                raise isolation.IsolationUnavailable(
                    "producer custody receipt was not durably bound before spawn"
                )
        if managed_state and not state.mark_producer_spawn_committed(
            job_id=job_id,
            expected_attempt=attempt,
            path=state_path,
        ):
            raise RuntimeError(
                f"producer spawn-commit CAS lost: job_id={job_id} attempt={attempt}"
            )
        try:
            proc = _spawn(
                argv=argv,
                log_path=log_path,
                env=child_env,
                cwd=workdir,
            )
        except OSError:
            if managed_state:
                state.mark_producer_spawn_aborted(
                    job_id=job_id,
                    expected_attempt=attempt,
                    path=state_path,
                )
            if producer_custody is not None:
                members = procutil.producer_cohort_members_checked(
                    0,
                    job_id=job_id,
                    custody=producer_custody,
                )
                if members == []:
                    _release_global_custody()
            raise
    except BaseException:
        # Keep the exact reservation.  The scheduler records a durable
        # spawn_not_started outcome when no custody was bound, or verifies the
        # bound custody is empty when Popen itself failed.  Releasing here used
        # to erase the only restart/reconciliation identity.
        raise
    # `_spawn` always uses start_new_session=True, so POSIX guarantees the new
    # session leader's PGID equals its PID.  Avoid a fallible extra syscall in
    # the Popen-return→durable-attach crash window.
    pgid = proc.pid
    # Attach pid+pgid IMMEDIATELY (fast — os.getpgid() is a plain syscall) so
    # the pid=None reservation window (a supervisor crash here would strand
    # current_job forever — see supervisor._handle_restart_orphan's
    # pid-is-None branch, Codex review fix #2, 2026-07-04) is narrowed down
    # to the Popen() call itself, not the slower `ps`-based fingerprint call
    # that used to run first and be attached in the same step.
    try:
        state.attach_process(
            job_id=job_id, expected_attempt=attempt, pid=proc.pid, pgid=pgid,
            started_wall=None, path=state_path,
        )
    except BaseException:
        # A child exists but state attachment failed.  Drain by kernel custody
        # before propagating; never let the scheduler classify this as an
        # ordinary pre-spawn failure.
        ledger_path = termination.ledger_for_state(state_path)
        intent = termination.arm(
            target_kind="pid",
            target_id=proc.pid,
            target_identity=(
                "producer-custody:"
                f"{producer_custody.get('resource_coalition_id', 'unknown')}"
                if producer_custody is not None
                else None
            ),
            reason="producer_state_attach_failed",
            actor="dispatch-supervisor.worker",
            signal_sequence=[signal.SIGTERM, signal.SIGKILL],
            job_id=job_id,
            attempt=attempt,
            ledger_path=ledger_path,
        )
        if producer_custody is not None:
            drained = procutil.kill_producer_cohort(
                producer_custody,
                intent=intent,
                ledger_path=ledger_path,
                grace_s=GRACE_PERIOD_S,
            )
        else:
            drained = procutil.kill_tree(
                proc.pid,
                intent=intent,
                ledger_path=ledger_path,
                grace_s=GRACE_PERIOD_S,
            )
        if drained:
            _release_global_custody()
        raise
    if process_identity_sink is not None:
        process_identity_sink(pgid)
    # Codex review §10 #2: fingerprint the process's OS start time so later
    # identity checks (health.py polling, restart orphan cleanup) can detect
    # PID reuse instead of trusting a bare `os.kill(pid, 0)`.
    started_wall = procutil.get_process_start_wall(proc.pid)
    if started_wall:
        state.update_started_wall(
            job_id=job_id, expected_attempt=attempt, pid=proc.pid,
            started_wall=started_wall, path=state_path,
        )
    verdict, raw_exit = _wait_with_fatal_probe(
        proc, log_path=log_path, log_offset=log_offset, timeout_s=timeout_s,
        debug_path=(debug_path
                    if attempt >= DEBUG_SIDECAR_FROM_ATTEMPT else None),
    )
    if verdict == "fatal_stall":
        # Dead-on-arrival CLI: the log holds a terse fatal and nothing else, and
        # has not moved for FATAL_STALL_S. Reap it now — waiting for the hang
        # cap costs the rest of the slot and mails a CRITICAL for a fire that
        # never started (2026-07-20, five occurrences).
        LOG.warning(
            "worker attempt=%d terse CLI fatal + %.0fs stall — killing pgid=%d "
            "instead of waiting out the %ds hang cap",
            attempt, FATAL_STALL_S, pgid, timeout_s,
        )
        killed = bool(_kill_pgid(
            pgid, leader_pid=proc.pid, reason="fatal_stall",
            job_id=job_id, attempt=attempt,
            custody=producer_custody,
            state_path=state_path,
        ))
        try:
            proc.wait(timeout=GRACE_PERIOD_S + 5)
        except subprocess.TimeoutExpired:
            LOG.warning(
                "worker attempt=%d fatal-fastfail child survived SIGKILL grace pgid=%d",
                attempt, pgid,
            )
        duration = time.time() - started
        attempt_output = _read_since(log_path, log_offset)
        if not killed:
            # A group we could not kill is an orphan no matter WHY we killed it;
            # quarantine it exactly like a surviving hang rather than declaring
            # the slot free while something may still be writing.
            return TIMEOUT_SURVIVED_SENTINEL, duration, attempt_output
        _release_global_custody()
        if managed_state and not state.mark_job_phase(
            job_id=job_id, phase="classifying", expected_phase="running",
            expected_attempt=attempt, expected_pid=proc.pid, path=state_path,
        ):
            return OWNERSHIP_LOST_SENTINEL, duration, attempt_output
        return FATAL_FASTFAIL_SENTINEL, duration, attempt_output
    if verdict == "timeout":
        # Codex-review §10 #1 fix: our own watchdog timeout fired. Whatever
        # POSIX signal status we observe next (raw negative wait() return,
        # 137 fallback if SIGKILL also raced), this MUST be classified as
        # "hang" and short-circuit retry. Returning the sentinel makes the
        # classification path single-source and impossible to misread.
        LOG.warning("worker attempt=%d timeout=%ds — SIGTERM→SIGKILL pgid=%d", attempt, timeout_s, pgid)
        killed = bool(_kill_pgid(
            pgid, leader_pid=proc.pid, reason="work_timeout",
            job_id=job_id, attempt=attempt,
            custody=producer_custody,
            state_path=state_path,
        ))
        try:
            proc.wait(timeout=GRACE_PERIOD_S + 5)
        except subprocess.TimeoutExpired:
            LOG.warning(
                "worker attempt=%d still alive after SIGKILL grace pgid=%d",
                attempt,
                pgid,
            )
        duration = time.time() - started
        attempt_output = _read_since(log_path, log_offset)
        if not killed:
            return TIMEOUT_SURVIVED_SENTINEL, duration, attempt_output
        _release_global_custody()
        if managed_state and not state.mark_job_phase(
            job_id=job_id, phase="classifying", expected_phase="running",
            expected_attempt=attempt, expected_pid=proc.pid, path=state_path,
        ):
            return OWNERSHIP_LOST_SENTINEL, duration, attempt_output
        return TIMEOUT_KILLED_SENTINEL, duration, attempt_output
    # Popen.wait() proves only that the process-group leader exited.  A child
    # can keep the inherited sandbox and continue writing the producer
    # workspace after its parent returns.  Finalization must never snapshot and
    # remove that checkout until the whole group is positively empty.
    remaining_members = procutil.producer_cohort_members_checked(
        pgid,
        job_id=job_id,
        custody=producer_custody,
    )
    if remaining_members is None or remaining_members:
        LOG.error(
            "worker attempt=%d leader exited but producer pgid=%d is %s; "
            "retaining workspace and slot",
            attempt,
            pgid,
            (
                "unverifiable"
                if remaining_members is None
                else f"still active: {remaining_members}"
            ),
        )
        duration = time.time() - started
        attempt_output = _read_since(log_path, log_offset)
        return TIMEOUT_SURVIVED_SENTINEL, duration, attempt_output
    exit_code = raw_exit
    duration = time.time() - started
    attempt_output = _read_since(log_path, log_offset)
    # Auth/quota may hand this same immutable attempt to Codex. Keep global
    # custody pending across that handoff; `_attempt_codex_failover` releases it
    # only after probes, alerts and auth cleanup have all left the coalition.
    if _classify(_normalize_signal_exit(exit_code), attempt_output) not in {
        "auth",
        "quota",
    }:
        _release_global_custody()
    if exit_code == 0:
        # Debug sidecars only exist to explain failures; a clean attempt's copy
        # is pure disk cost (a 50-minute opus fire's debug stream is large).
        try:
            debug_path.unlink()
        except FileNotFoundError:
            pass  # silent-ok: sidecar disabled or never written
        except OSError as exc:
            LOG.warning("debug sidecar cleanup %s failed: %s", debug_path, exc)
    normalized_exit = _normalize_signal_exit(exit_code)
    if managed_state and not state.mark_job_phase(
        job_id=job_id, phase="classifying", expected_phase="running",
        expected_attempt=attempt, expected_pid=proc.pid, path=state_path,
    ):
        if _classify(normalized_exit, attempt_output) == "external_signal":
            # Health may have won completion CAS after sending this signal.
            # Preserve the raw exit for durable intent attribution instead of
            # collapsing the exact race into a generic superseded result.
            return normalized_exit, duration, attempt_output
        return OWNERSHIP_LOST_SENTINEL, duration, attempt_output
    return normalized_exit, duration, attempt_output


def _attempt_codex_failover(
    *,
    reason: str,
    attempt: int,
    total_duration: float,
    fallback_exit: int,
    model: str,
    log_tail: str,
    state_path: Path,
    job_id: str,
    slot_id: str,
    workdir: Path | None = None,
    isolated_workspace: dict | None = None,
    preselected_task_id: str | None = None,
) -> WorkerResult | None:
    """Hand this hourly slot to Codex. Returns a WorkerResult only if Codex recovered it.

    Alerts either way — a failover that fired is something the owner must see,
    and one that failed is worse. `None` means the caller should return its own
    Claude-side result (quota_blocked / auth_blocked) unchanged.
    """
    def _track_started(pid: int, pgid: int) -> bool:
        try:
            state.attach_process(
                job_id=job_id, expected_attempt=attempt, pid=pid, pgid=pgid,
                started_wall=None, path=state_path,
            )
            wall = procutil.get_process_start_wall(pid)
            if wall:
                state.update_started_wall(
                    job_id=job_id, expected_attempt=attempt, pid=pid,
                    started_wall=wall, path=state_path,
                )
            return state.mark_job_phase(
                job_id=job_id, phase="codex_failover", expected_phase="running",
                expected_attempt=attempt, expected_pid=pid, path=state_path,
            )
        except RuntimeError as exc:
            LOG.warning("codex failover lost slot before attach job_id=%s: %s", job_id, exc)
            return False

    def _track_finished(pid: int) -> None:
        state.mark_job_phase(
            job_id=job_id, phase="codex_failover", expected_phase="codex_failover",
            expected_attempt=attempt, expected_pid=pid, detach_process=True,
            path=state_path,
        )

    custody_state = state.read_state(state_path)
    producer_custody = next(
        (
            raw.get("producer_custody")
            for raw in (custody_state.get("current_jobs") or [])
            if str(raw.get("job_id") or "") == job_id
            and isinstance(raw.get("producer_custody"), dict)
        ),
        None,
    )
    custody_repo_root = Path(
        str(
            (
                isolated_workspace.get("isolation_canonical_root")
                if isinstance(isolated_workspace, dict)
                else None
            )
            or PROJECT_ROOT
        )
    )

    def _quarantine_unresolved_failover_custody(
        *,
        detail: str,
    ) -> WorkerResult | None:
        """Return a quarantine result unless the full failover cohort drained."""
        if producer_custody is None:
            return None
        members = procutil.producer_cohort_members_checked(
            0,
            job_id=job_id,
            custody=producer_custody,
        )
        if members:
            ledger_path = termination.ledger_for_state(state_path)
            intent = termination.arm(
                target_kind="pid",
                target_id=int(members[0]),
                target_identity=(
                    "producer-custody:"
                    f"{producer_custody.get('resource_coalition_id', 'unknown')}"
                ),
                reason="codex_failover_final_custody_drain",
                actor="dispatch-supervisor.worker",
                signal_sequence=[signal.SIGTERM, signal.SIGKILL],
                job_id=job_id,
                attempt=attempt,
                ledger_path=ledger_path,
            )
            if procutil.kill_producer_cohort(
                producer_custody,
                intent=intent,
                ledger_path=ledger_path,
            ):
                members = []
            else:
                members = procutil.producer_cohort_members_checked(
                    0,
                    job_id=job_id,
                    custody=producer_custody,
                )
        if members == []:
            custody_receipt.release_producer_custody(
                custody_repo_root,
                job_id=job_id,
                attempt=attempt,
                drain_confirmed=True,
            )
            return None

        # Never let a failed/unverifiable failover fall through to the caller's
        # auth/quota completion.  Preserve a representative PID when one is
        # available so health can keep reconciling; kernel custody remains the
        # actual authority even if that representative later exits.
        current = next(
            (
                raw
                for raw in (
                    state.read_state(state_path).get("current_jobs") or []
                )
                if str(raw.get("job_id") or "") == job_id
            ),
            {},
        )
        representative = int(members[0]) if members else None
        if representative is not None and current.get("pid") is None:
            try:
                state.attach_process(
                    job_id=job_id,
                    expected_attempt=attempt,
                    pid=representative,
                    pgid=representative,
                    started_wall=None,
                    path=state_path,
                )
                current = {"phase": "running", "pid": representative}
            except RuntimeError as exc:
                LOG.warning(
                    "codex failover custody representative attach lost: %s",
                    exc,
                )
        phase_owned = state.mark_job_phase(
            job_id=job_id,
            phase="kill_failed_orphan",
            expected_phase=str(current.get("phase") or "codex_failover"),
            expected_attempt=attempt,
            expected_pid=(
                int(current["pid"])
                if current.get("pid") is not None
                else None
            ),
            path=state_path,
        )
        if not phase_owned:
            fresh = next(
                (
                    raw
                    for raw in (
                        state.read_state(state_path).get("current_jobs") or []
                    )
                    if str(raw.get("job_id") or "") == job_id
                ),
                None,
            )
            if fresh is not None:
                phase_owned = state.mark_job_phase(
                    job_id=job_id,
                    phase="kill_failed_orphan",
                    expected_phase=str(fresh.get("phase") or ""),
                    expected_attempt=attempt,
                    expected_pid=(
                        int(fresh["pid"])
                        if fresh.get("pid") is not None
                        else None
                    ),
                    path=state_path,
                )
        if not phase_owned:
            LOG.error(
                "codex failover custody quarantine lost state CAS job_id=%s; "
                "global custody remains pending",
                job_id,
            )
        survivor_text = (
            "unverified" if members is None else ",".join(map(str, members))
        )
        LOG.error(
            "codex failover custody did not drain job_id=%s survivors=%s",
            job_id,
            survivor_text,
        )
        return WorkerResult(
            exit_code=137,
            outcome="kill_failed_orphan",
            final_model=CODEX_MODEL_LABEL,
            attempts=attempt,
            duration_s=total_duration,
            log_tail=(
                f"{detail}\nproducer custody survivors={survivor_text}"
            ).strip(),
        )

    try:
        result = codex_failover.run_codex_failover(
            reason=reason, slot_id=slot_id, job_id=job_id,
            on_process_started=_track_started,
            on_process_finished=_track_finished,
            workdir=workdir,
            isolated_workspace=isolated_workspace,
            preselected_task_id=preselected_task_id,
            producer_custody=producer_custody,
            state_path=state_path,
        )
    except Exception as exc:  # failover must never take the supervisor down
        LOG.exception("codex failover raised unexpectedly reason=%s", reason)
        alerts.send_codex_failover_alert(
            reason=reason, recovered=False, exit_code=-1,
            detail=f"failover 本身拋出例外：{exc}", attempted=True,
            output_tail=log_tail, state_path=state_path,
        )
        return _quarantine_unresolved_failover_custody(
            detail=f"failover exception: {exc}",
        )

    alerts.send_codex_failover_alert(
        reason=reason, recovered=result.recovered, exit_code=result.exit_code,
        detail=result.detail, attempted=result.attempted,
        output_tail=result.output_tail, state_path=state_path,
    )
    custody_quarantine = _quarantine_unresolved_failover_custody(
        detail=result.output_tail or result.detail,
    )
    if custody_quarantine is not None:
        return custody_quarantine
    if result.process_active and producer_custody is None:
        state.mark_job_phase(
            job_id=job_id, phase="kill_failed_orphan",
            expected_phase="codex_failover", expected_attempt=attempt,
            path=state_path,
        )
        return WorkerResult(
            exit_code=137, outcome="kill_failed_orphan", final_model=CODEX_MODEL_LABEL,
            attempts=attempt, duration_s=total_duration + result.duration_s,
            log_tail=result.output_tail or log_tail,
        )
    if not result.recovered:
        return None

    return WorkerResult(
        exit_code=0, outcome="codex_failover_recovered", final_model=CODEX_MODEL_LABEL,
        attempts=attempt, duration_s=total_duration + result.duration_s,
        log_tail=result.output_tail or log_tail,
    )


def run_worker(
    *,
    prompt_text: str,
    schedule_id: str = "hourly_dispatch",
    scheduled_for: str | None = None,
    fire_reason: str = "cron",
    log_path: Path,
    timeout_s: int = DEFAULT_TIMEOUT_S,
    max_attempts: int = MAX_ATTEMPTS,
    state_path: Path = state.STATE_PATH,
    claude_bin: str = CLAUDE_BIN,
    sleep_fn=time.sleep,
    job_id: str | None = None,
    slot_id: str | None = None,
    max_slots: int = 2,
    workdir: Path | None = None,
    isolated_workspace: dict | None = None,
    preselected_task_id: str | None = None,
) -> WorkerResult:
    """Run prompt through claude -p with retry ladder.

    `sleep_fn` injectable for tests (avoid real 90s backoff).
    """
    if state.read_state(state_path).get("auth_blocked"):
        LOG.warning("auth_blocked=true — refusing to spawn worker (manual unblock required)")
        if job_id is not None:
            state.record_completion(
                job_id=job_id, exit_code=-2, outcome="auth_blocked",
                final_model="(none)", path=state_path,
            )
        return WorkerResult(
            exit_code=-2, outcome="auth_blocked", final_model="(none)",
            attempts=0, duration_s=0.0, log_tail="",
        )

    if job_id is None:
        lease = state.reserve_fire(
            schedule_id=schedule_id, attempt=1, model=OPUS_MODEL,
            log_path=str(log_path), scheduled_for=scheduled_for,
            fire_reason=fire_reason, max_slots=max_slots, path=state_path,
        )
        job_id = lease.job_id
        slot_id = f"slot-{lease.slot_id}"
    elif slot_id is None:
        raw_jobs = state.read_state(state_path).get("current_jobs") or []
        active = {str(j.get("job_id")): j for j in raw_jobs}
        if job_id not in active:
            raise RuntimeError(f"reserved dispatch job is absent: {job_id}")
        slot_id = f"slot-{active[job_id]['slot_id']}"

    total_duration = 0.0
    final_exit = 1
    final_model = OPUS_MODEL
    attempt = 1

    while attempt <= max_attempts:
        # 2026-07-05 owner directive: ALL dispatch attempts use opus (4.8). The
        # previous ladder dropped to sonnet on the final attempt as a
        # different-model fallback; that's retired — every attempt is opus, only
        # RETRY_BACKOFF_S separates them.
        model = OPUS_MODEL
        final_model = model
        LOG.info("worker attempt=%d/%d model=%s effort=%s", attempt, max_attempts, model, DISPATCH_EFFORT)
        attempt_identity: dict[str, int] = {}
        try:
            exit_code, duration, attempt_output = _run_one_attempt(
                prompt_text=prompt_text, model=model, timeout_s=timeout_s,
                log_path=log_path, attempt=attempt, schedule_id=schedule_id,
                scheduled_for=scheduled_for, fire_reason=fire_reason,
                state_path=state_path, claude_bin=claude_bin,
                job_id=job_id, slot_id=slot_id,
                workdir=workdir,
                isolated_workspace=isolated_workspace,
                preselected_task_id=preselected_task_id,
                process_identity_sink=lambda pgid: attempt_identity.__setitem__(
                    "pgid", pgid,
                ),
            )
        except ProviderRegistryError as exc:
            LOG.error("provider registry denied worker spawn: %s", exc)
            state.record_completion(
                job_id=job_id,
                exit_code=2,
                outcome="provider_policy_denied",
                final_model=model,
                path=state_path,
            )
            return WorkerResult(
                exit_code=2,
                outcome="provider_policy_denied",
                final_model=model,
                attempts=attempt,
                duration_s=total_duration,
                log_tail=str(exc),
            )
        total_duration += duration
        final_exit = exit_code

        # Classify + report on THIS attempt's output only — the shared log's
        # global tail can contain a previous fire's quota/auth lines, and a
        # stale 'Not logged in' match would freeze the loop (2026-07-05 fix).
        log_tail = attempt_output
        category = _classify(exit_code, attempt_output)
        attempt_outcome = "failure"  # overridden by branches with a named shape
        LOG.info("worker attempt=%d exit=%d category=%s duration=%.1fs", attempt, exit_code, category, duration)

        if category == "ownership_lost":
            LOG.info(
                "worker attempt=%d lost state ownership to watchdog; no retry/failover",
                attempt,
            )
            return WorkerResult(
                exit_code=-1, outcome="superseded", final_model=model,
                attempts=attempt, duration_s=total_duration, log_tail=log_tail,
            )

        if category == "hang_survived":
            owned = state.mark_job_phase(
                job_id=job_id, phase="kill_failed_orphan",
                expected_phase="running", expected_attempt=attempt,
                path=state_path,
            )
            if owned:
                raw = next(
                    (j for j in (state.read_state(state_path).get("current_jobs") or [])
                     if str(j.get("job_id")) == job_id),
                    {},
                )
                pgid = int(raw.get("pgid") or -1)
                alerts.send_hang_alert(
                    job={
                        **raw, "survivors": procutil.pgid_members(pgid) if pgid > 0 else [],
                        "slot_quarantined": True,
                    },
                    log_tail=log_tail, state_path=state_path,
                )
            return WorkerResult(
                exit_code=137, outcome="kill_failed_orphan", final_model=model,
                attempts=attempt, duration_s=total_duration, log_tail=log_tail,
            )

        if category == "success":
            state.record_completion(
                job_id=job_id, expected_attempt=attempt,
                expected_phase="classifying",
                exit_code=exit_code, outcome="success", final_model=model,
                path=state_path,
            )
            # Outage-scoped quota-alert semantics (2026-07-05): a success marks
            # the end of any quota outage — reset the dedup key so the NEXT
            # outage sends its own email. The window itself (7d) is only a
            # backstop against pathological flapping.
            state.clear_alert_dedup("quota_blocked", path=state_path)
            return WorkerResult(
                exit_code=0, outcome="success", final_model=model,
                attempts=attempt, duration_s=total_duration, log_tail=log_tail,
            )

        if category == "fatal_fastfail":
            # The CLI died at second one and never exited; we reaped it in ~60s
            # instead of ~960s. Two things follow from "it never ran":
            #   - This is NOT a hang. Sending the hang alert would keep mailing
            #     the owner a CRITICAL about a frozen 50-minute agent that does
            #     not exist, which is what made the 2026-07-20 incidents read as
            #     a systemic failure. The completion receipt below is the record.
            #   - The task it claimed was never worked on. Release the claim NOW
            #     so a retry below — or the next fire — can pick it up, rather
            #     than stranding a P1 until the stale sweep.
            # Same idempotence argument as the hang path: the kill is confirmed
            # (an unkillable group returns hang_survived instead), and
            # release_owner_claims skips rows that are no longer claimed.
            repended_tasks = claim_release.repend_killed_job_claims(
                job_id=job_id, slot_id=slot_id, source="worker-fatal-fastfail",
            )
            LOG.warning(
                "worker attempt=%d terse CLI fatal fast-fail after %.1fs "
                "(hang cap avoided); released claims=%s; output=%r",
                attempt, duration, repended_tasks or "none", log_tail.strip(),
            )
            # Treated as transient from here on: a terse CLI fatal is the shape
            # an API/session-side problem takes, and the existing transient
            # contract (backoff, then retry within this same fire) is exactly
            # the right response. Falls through to the retry ladder below, whose
            # per-attempt receipt keeps the distinct outcome name so completion
            # history can tell this shape apart from an ordinary failed run.
            category = "transient"
            attempt_outcome = "fatal_fastfail"

        if category == "external_signal":
            signum = exit_code - 128 if exit_code > 128 else exit_code
            sent_receipt = termination.wait_for_sent_signal(
                target_kind="pgid",
                target_id=int(attempt_identity.get("pgid", -1)),
                signum=signum,
                job_id=job_id,
                attempt=attempt,
                ledger_path=termination.ledger_for_state(state_path),
            )
            if sent_receipt is not None:
                # A durable *sent* receipt is the only evidence allowed to
                # attribute a raw wait status to this system. An armed intent
                # or failed syscall is deliberately insufficient.
                repended_tasks = claim_release.repend_killed_job_claims(
                    job_id=job_id, slot_id=slot_id,
                    source="worker-system-termination",
                )
                entry = state.record_completion(
                    job_id=job_id, expected_attempt=attempt,
                    expected_phase="classifying",
                    exit_code=exit_code, outcome="system_terminated",
                    final_model=model, path=state_path,
                )
                LOG.warning(
                    "worker attempt=%d matched system termination intent=%s "
                    "reason=%s signal=%d released claims=%s",
                    attempt, sent_receipt.get("intent_id"),
                    sent_receipt.get("reason"), signum,
                    repended_tasks or "none",
                )
                return WorkerResult(
                    exit_code=exit_code, outcome="system_terminated",
                    final_model=model, attempts=attempt,
                    duration_s=total_duration, log_tail=log_tail,
                )

            unresolved_attempt = termination.match_unresolved_signal_attempt(
                target_kind="pgid",
                target_id=int(attempt_identity.get("pgid", -1)),
                signum=signum,
                job_id=job_id,
                attempt=attempt,
                ledger_path=termination.ledger_for_state(state_path),
            )
            if unresolved_attempt is not None:
                repended_tasks = claim_release.repend_killed_job_claims(
                    job_id=job_id, slot_id=slot_id,
                    source="worker-system-termination-unconfirmed",
                )
                state.record_completion(
                    job_id=job_id, expected_attempt=attempt,
                    expected_phase="classifying", exit_code=exit_code,
                    outcome="system_termination_unconfirmed",
                    final_model=model, path=state_path,
                )
                LOG.error(
                    "worker signal=%d matches durable system attempt intent=%s "
                    "but sender died before result receipt; attribution is unconfirmed",
                    signum, unresolved_attempt.get("intent_id"),
                )
                return WorkerResult(
                    exit_code=exit_code,
                    outcome="system_termination_unconfirmed",
                    final_model=model, attempts=attempt,
                    duration_s=total_duration, log_tail=log_tail,
                )

            # No exact sent receipt exists. POSIX cannot identify the sender;
            # therefore the only honest attribution is unknown_external.
            # No in-fire retry: the killer is still out there and a fresh fire
            # from the next tick re-dispatches the released claims anyway.
            repended_tasks = claim_release.repend_killed_job_claims(
                job_id=job_id, slot_id=slot_id,
                source="worker-unknown-external-signal",
            )
            LOG.warning(
                "worker attempt=%d killed by UNKNOWN EXTERNAL signal %d after %.1fs "
                "(no matching sent intent); released claims=%s",
                attempt, signum, total_duration, repended_tasks or "none",
            )
            # Killer tracer (2026-07-21, 4th unattributed kill): POSIX cannot
            # name the sender, but a janitor/cron that kills is ALIVE this very
            # second — snapshot the process table so the next occurrence names
            # every candidate. Pure evidence capture; never blocks the path.
            try:
                snap = subprocess.run(
                    ["ps", "-axo", "pid,ppid,etime,command"],
                    capture_output=True, text=True, timeout=10,
                ).stdout
                snap_path = log_path.parent / (
                    f"{log_path.stem}.attempt{attempt}.killsnap.txt")
                snap_path.write_text(snap, encoding="utf-8")
                LOG.warning("external-signal process snapshot: %s", snap_path)
            except Exception as exc:  # noqa: BLE001
                LOG.warning("external-signal snapshot failed: %s", exc)
            entry = state.record_completion(
                job_id=job_id, expected_attempt=attempt,
                expected_phase="classifying",
                    exit_code=exit_code, outcome="unknown_external", final_model=model,
                path=state_path,
            )
            if entry is not None:
                dead = entry["job"]
                alerts.send_external_signal_alert(
                    job={"pid": dead.get("pid", -1),
                         "pgid": int(dead.get("pgid") or -1),
                         "started_at": entry.get("fire_at"), "attempt": attempt,
                         "model": model, "log_path": dead.get("log_path", ""),
                         "repended_tasks": repended_tasks},
                    signum=signum, duration_s=total_duration,
                    state_path=state_path,
                )
            return WorkerResult(
                exit_code=exit_code, outcome="unknown_external", final_model=model,
                attempts=attempt, duration_s=total_duration, log_tail=log_tail,
            )

        if category == "hang":
            # Sanitize sentinel to canonical SIGKILL hang code before persisting:
            # state file readers + alerts expect a real POSIX exit code, not -1000.
            persisted_exit = 137 if exit_code == TIMEOUT_KILLED_SENTINEL else exit_code
            # WS-A2c: hand the dead fire's task-pool claim back BEFORE the CAS,
            # so this runs on both return points below (the one that closed the
            # job and the one that lost to health.py). Deliberately
            # unconditional:
            #   - The kill already happened and is CONFIRMED — reaching category
            #     "hang" requires _kill_pgid() to have returned True (a surviving
            #     group is classified "hang_survived" instead), so nothing can
            #     still be acting on this claim.
            #   - Double-release is a no-op. release_owner_claims
            #     (scripts/task_pool_claim.py:579-582) skips any row that is no
            #     longer claimed/in_progress, so if health.py already re-pended
            #     this job we simply release nothing.
            #   - Doing it only when we WIN the CAS would leave a real hole:
            #     health.py closes some aged-out jobs as silent_death /
            #     timeout_unverified WITHOUT re-pending, and in those cases
            #     `entry is None` here would mean nobody hands the claim back.
            # Best-effort: the helper swallows its own failures (WARNING only),
            # so neither killed_timeout nor the hang alert can be blocked by a
            # locked or corrupt task pool. The stale sweep is still the backstop.
            repended_tasks = claim_release.repend_killed_job_claims(
                job_id=job_id, slot_id=slot_id, source="worker",
            )
            # record_completion is the atomic hand-off; a non-None return means
            # WE closed this job and therefore own the incident report. It hands
            # back the job as it was at that instant, so we never re-read
            # current_job (health.py's max-age watchdog fires on the same hang
            # within ~1s and would have cleared it out from under us — that race
            # is what mailed the owner blind pid=-1 hang alerts, 2026-07-12 00:57).
            entry = state.record_completion(
                job_id=job_id, expected_attempt=attempt,
                expected_phase="classifying",
                exit_code=persisted_exit, outcome="killed_timeout", final_model=model,
                path=state_path,
            )
            if entry is None:
                LOG.info(
                    "worker attempt=%d hang: slot already closed by the health watchdog — "
                    "it owns the alert, staying silent to avoid a blind duplicate",
                    attempt,
                )
            else:
                hung = entry["job"]
                pgid = int(hung.get("pgid") or -1)
                alerts.send_hang_alert(
                    job={"pid": hung.get("pid", -1), "pgid": pgid,
                         "started_at": entry.get("fire_at"),
                         "attempt": attempt, "model": model,
                         "log_path": hung.get("log_path", ""),
                         # The sentinel is minted only by our configured
                         # deadline.  A raw signal is classified separately as
                         # external_signal, so do not call this proof of hang.
                         "timeout_kind": (
                             "work_cap" if exit_code == TIMEOUT_KILLED_SENTINEL else None
                         ),
                         # observed at alert time: macOS can and does refuse
                         # killpg, so report whether the SIGKILL actually landed
                         # rather than asserting it did (see procutil.kill_pgid).
                         "survivors": procutil.pgid_members(pgid) if pgid > 0 else [],
                         # WS-A2c receipt: which task claims this kill handed back.
                         "repended_tasks": repended_tasks},
                    log_tail=log_tail, state_path=state_path,
                )
            return WorkerResult(
                exit_code=persisted_exit, outcome="killed_timeout", final_model=model,
                attempts=attempt, duration_s=total_duration, log_tail=log_tail,
            )

        if category == "auth":
            owned = state.mark_job_phase(
                job_id=job_id, expected_attempt=attempt,
                expected_phase="classifying", phase="codex_failover",
                detach_process=True, path=state_path,
            )
            if not owned:
                return WorkerResult(
                    exit_code=-1, outcome="superseded", final_model=model,
                    attempts=attempt, duration_s=total_duration, log_tail=log_tail,
                )
            state.set_auth_blocked(True, path=state_path)
            alerts.send_auth_alert(log_tail=log_tail, state_path=state_path)
            # Claude stays blocked until a human fixes the credential, but Codex
            # authenticates through ChatGPT — let it cover this slot. Failover
            # buys back the hour; it does not repair the credential, so
            # auth_blocked remains set.
            recovered = _attempt_codex_failover(
                reason="auth", attempt=attempt, total_duration=total_duration,
                fallback_exit=exit_code, model=model, log_tail=log_tail,
                state_path=state_path, job_id=job_id, slot_id=slot_id,
                workdir=workdir,
                isolated_workspace=isolated_workspace,
                preselected_task_id=preselected_task_id,
            )
            if recovered is not None:
                if recovered.outcome == "kill_failed_orphan":
                    return recovered
                state.record_completion(
                    job_id=job_id, expected_attempt=attempt, exit_code=0,
                    expected_phase="codex_failover",
                    outcome=recovered.outcome, final_model=recovered.final_model,
                    path=state_path,
                )
                return recovered
            state.record_completion(
                job_id=job_id, expected_attempt=attempt, exit_code=exit_code,
                expected_phase="codex_failover",
                outcome="auth_blocked", final_model=model, path=state_path,
            )
            return WorkerResult(
                exit_code=exit_code, outcome="auth_blocked", final_model=model,
                attempts=attempt, duration_s=total_duration, log_tail=log_tail,
            )

        if category == "quota":
            # 2026-07-05 incident fix: quota exhaustion aborts THIS fire without
            # retries (retrying in 90s against an hours-long window is waste),
            # but deliberately does NOT set auth_blocked — quota auto-resolves
            # at the provider's reset time, so the next hourly fire's single
            # attempt self-resumes the loop with zero manual intervention.
            # One warn email per outage (4h dedup in send_quota_alert).
            owned = state.mark_job_phase(
                job_id=job_id, expected_attempt=attempt,
                expected_phase="classifying", phase="codex_failover",
                detach_process=True, path=state_path,
            )
            if not owned:
                return WorkerResult(
                    exit_code=-1, outcome="superseded", final_model=model,
                    attempts=attempt, duration_s=total_duration, log_tail=log_tail,
                )
            alerts.send_quota_alert(log_tail=log_tail, state_path=state_path)
            # Codex runs on a separate (ChatGPT) quota — hand it the slot rather
            # than dropping the hour. 2026-07-10: this is the failover the
            # 2026-07-04 supervisor cutover left behind in the retired shell
            # wrapper; without it every Claude quota outage silently lost every
            # hourly slot until the reset.
            recovered = _attempt_codex_failover(
                reason="quota", attempt=attempt, total_duration=total_duration,
                fallback_exit=exit_code, model=model, log_tail=log_tail,
                state_path=state_path, job_id=job_id, slot_id=slot_id,
                workdir=workdir,
                isolated_workspace=isolated_workspace,
                preselected_task_id=preselected_task_id,
            )
            if recovered is not None:
                if recovered.outcome == "kill_failed_orphan":
                    return recovered
                state.record_completion(
                    job_id=job_id, expected_attempt=attempt, exit_code=0,
                    expected_phase="codex_failover",
                    outcome=recovered.outcome, final_model=recovered.final_model,
                    path=state_path,
                )
                return recovered
            state.record_completion(
                job_id=job_id, expected_attempt=attempt, exit_code=exit_code,
                expected_phase="codex_failover",
                outcome="quota_blocked", final_model=model, path=state_path,
            )
            return WorkerResult(
                exit_code=exit_code, outcome="quota_blocked", final_model=model,
                attempts=attempt, duration_s=total_duration, log_tail=log_tail,
            )

        # transient or hard_failure — both fall through to retry loop
        if attempt < max_attempts:
            wait_s = RETRY_BACKOFF_S if category == "transient" else max(5, RETRY_BACKOFF_S // 3)
            state.record_completion(
                job_id=job_id, expected_attempt=attempt, exit_code=exit_code,
                outcome=attempt_outcome, final_model=model, release_slot=False,
                path=state_path,
            )
            LOG.info("worker attempt=%d %s; sleeping %ds before retry", attempt, category, wait_s)
            sleep_fn(wait_s)
        attempt += 1

    # All attempts exhausted
    log_tail = _read_tail(log_path)
    entry = {
        "exit_code": final_exit, "outcome": "failure",
        "attempts": attempt - 1, "final_model": final_model,
        "duration_s": round(total_duration, 2),
    }
    state.record_completion(
        job_id=job_id, expected_attempt=attempt - 1,
        expected_phase="classifying",
        exit_code=final_exit, outcome="failure", final_model=final_model,
        path=state_path,
    )
    alerts.send_completion_failure(entry=entry, log_tail=log_tail, state_path=state_path)
    return WorkerResult(
        exit_code=final_exit, outcome="failure", final_model=final_model,
        attempts=attempt - 1, duration_s=total_duration, log_tail=log_tail,
    )
