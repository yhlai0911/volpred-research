"""Worker — subprocess.Popen wrapper with PGID isolation, timeout, retry ladder.

Replaces all `perl alarm` + watchdog + shell trap layers from
`scripts/cron_hourly_dispatch.sh` with one Python `Popen.wait(timeout=...)`.

Retry ladder (refactor_plan §3 retry policy)::

    attempt 1: opus    → opus exit≠0 + transient (529 / network) → sleep 90s
    attempt 2: opus    → opus exit≠0 + transient → sleep 90s
    attempt 3: sonnet  (final fallback)
    auth-class error  → NO retry; set_auth_blocked(True); send_auth_alert; abort
    hang (SIGKILL'd)  → NO retry; record killed_timeout; alert

Each attempt calls `state.reserve_fire()` BEFORE Popen spawn (atomic slot
claim — Codex review §10 #5), `state.attach_process()` right after (records
pid/pgid + a `ps`-derived start-time fingerprint for PID-reuse-safe identity
checks — §10 #2), then `record_completion` AFTER. Health monitor (health.py)
reads `current_job.age_seconds` from the same state file to independently
detect frozen workers if THIS process itself hangs inside `wait()` (shouldn't
happen with `timeout=` but health is the belt-and-suspenders layer).
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Sequence

from . import alerts, procutil, state

LOG = logging.getLogger(__name__)

# Default upstream constants (overridable via env for tests + ops)
DEFAULT_TIMEOUT_S = 3000  # 50min — matches CLAUDE.md hourly cap
GRACE_PERIOD_S = 10        # SIGTERM grace before SIGKILL
RETRY_BACKOFF_S = 90        # between transient-failure attempts
MAX_ATTEMPTS = 3

OPUS_MODEL = "claude-opus-4-8"
# Retired 2026-07-05 (owner all-opus directive): the retry ladder no longer
# drops to sonnet on the final attempt. Kept defined as a valid roster alias so
# any external reference still resolves, but no dispatch path selects it.
SONNET_MODEL = "claude-sonnet-5"

CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "/Users/yhlai0911/.local/bin/claude")

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

# stderr/stdout regex classifiers
_AUTH_RE = re.compile(r"(Not logged in|Please run /login|invalid_api_key|authentication)", re.I)
_TRANSIENT_RE = re.compile(r"(529|Overloaded|ECONNRESET|ETIMEDOUT|Connection reset|rate.?limit)", re.I)
# 2026-07-05 incident: the weekly Claude Code quota ran out 11:07-16:00 and
# "You've hit your weekly limit · resets 4pm" matched NO class → hard_failure →
# the full retry ladder (opus→opus→sonnet) burned on every hourly fire (15
# wasted attempts + completion noise over 5h). Quota exhaustion is neither
# transient (retrying in 90s cannot help) nor auth (it auto-resolves at the
# reset time; requiring a manual unblock would strand the loop). Its own class:
# abort THIS fire without retries, do NOT set auth_blocked — the next hourly
# fire is a single cheap attempt that self-resumes the moment quota resets.
_QUOTA_RE = re.compile(
    r"(hit your (?:weekly|5.?hour|monthly|usage|session) limit|usage limit (?:reached|exceeded))",
    re.I,
)


@dataclass
class WorkerResult:
    exit_code: int
    outcome: str             # success | failure | killed_timeout | auth_blocked
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
    """Return one of: success | hang | auth | quota | transient | hard_failure."""
    if exit_code == TIMEOUT_KILLED_SENTINEL:
        return "hang"
    if exit_code == 0:
        return "success"
    if exit_code in HANG_EXIT_CODES:
        return "hang"
    if _AUTH_RE.search(output or ""):
        return "auth"
    # quota BEFORE transient: both are "come back later", but transient's 90s
    # backoff is pointless against an hours-long quota window.
    if _QUOTA_RE.search(output or ""):
        return "quota"
    if _TRANSIENT_RE.search(output or ""):
        return "transient"
    return "hard_failure"


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


def _kill_pgid(pgid: int, *, grace_s: float = GRACE_PERIOD_S) -> None:
    """SIGTERM whole process group; SIGKILL after grace_s if still alive.

    Codex review fix #5 (2026-07-04): the actual implementation moved to
    `procutil.kill_pgid()` — health.py had its own near-duplicate copy that
    missed a PermissionError fix applied here (found via a live smoke test),
    so both now share one implementation. Kept as a thin wrapper so existing
    callers/tests referencing `worker._kill_pgid` by name are unaffected.
    """
    procutil.kill_pgid(pgid, grace_s=grace_s)


def _dispatch_actor(schedule_id: str, *, now: datetime | None = None) -> str:
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
    return f"dispatch-worker:{schedule_id}:{(now or datetime.now()).strftime('%H%M')}"


def _spawn(
    *, argv: Sequence[str], log_path: Path, env: dict[str, str] | None = None
) -> subprocess.Popen:
    """Spawn child in its own process group; redirect combined stdout+stderr to log_path.

    `env=None` (the default) inherits the parent's environment unchanged — the
    pre-2026-07-10 behaviour. Callers that need to stamp VOLPRED_ACTOR pass an
    os.environ EXTENSION (`{**os.environ, ...}`), never a replacement, so PATH /
    auth / HOME survive.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_fh = log_path.open("ab")
    return subprocess.Popen(
        list(argv),
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        start_new_session=True,  # new PGID — clean SIGKILL group
        close_fds=True,
        env=env,
    )


def _run_one_attempt(
    *,
    prompt_text: str,
    model: str,
    timeout_s: int,
    log_path: Path,
    attempt: int,
    schedule_id: str,
    state_path: Path,
    claude_bin: str = CLAUDE_BIN,
    effort: str = DISPATCH_EFFORT,
) -> tuple[int, float]:
    """Single Popen attempt. Returns (exit_code, duration_s, attempt_output).

    `attempt_output` is ONLY the bytes this attempt appended to the shared
    log (spawn-time offset → EOF, tail-capped 2KB) — the classification
    input, immune to previous fires' leftovers (2026-07-05 fix).

    On timeout: SIGKILL whole PGID, return exit_code=-9 (mapped to killed_timeout
    upstream via HANG_EXIT_CODES + outcome classification).
    """
    argv = [
        claude_bin, "-p", "--dangerously-skip-permissions",
        "--effort", effort, "--model", model, prompt_text,
    ]
    # Codex review §10 #5: reserve the state slot BEFORE spawning so no other
    # caller can pass a concurrent "current_job is None" check while we spawn.
    state.reserve_fire(
        schedule_id=schedule_id, attempt=attempt, model=model,
        log_path=str(log_path), path=state_path,
    )
    # Record where the shared append-log ends BEFORE we spawn: classification
    # must only ever see THIS attempt's bytes (2026-07-05 cross-fire
    # contamination fix — see _read_since).
    log_offset = _log_size(log_path)
    started = time.time()
    # Stamp the fire onto the agent's env so its shared-state writes are
    # attributable (see _dispatch_actor). Extend os.environ — the supervisor
    # boot set VOLPRED_ACTOR=dispatch-supervisor as a process default, which we
    # deliberately override here so AGENT writes carry the fire, not the daemon.
    child_env = {**os.environ, "VOLPRED_ACTOR": _dispatch_actor(schedule_id)}
    try:
        proc = _spawn(argv=argv, log_path=log_path, env=child_env)
    except OSError:
        # Spawn itself failed (e.g. claude_bin missing) — free the slot we
        # just reserved so it doesn't wedge forever with no process behind it.
        state.release_reservation(path=state_path)
        raise
    pgid = os.getpgid(proc.pid)
    # Attach pid+pgid IMMEDIATELY (fast — os.getpgid() is a plain syscall) so
    # the pid=None reservation window (a supervisor crash here would strand
    # current_job forever — see supervisor._handle_restart_orphan's
    # pid-is-None branch, Codex review fix #2, 2026-07-04) is narrowed down
    # to the Popen() call itself, not the slower `ps`-based fingerprint call
    # that used to run first and be attached in the same step.
    state.attach_process(pid=proc.pid, pgid=pgid, started_wall=None, path=state_path)
    # Codex review §10 #2: fingerprint the process's OS start time so later
    # identity checks (health.py polling, restart orphan cleanup) can detect
    # PID reuse instead of trusting a bare `os.kill(pid, 0)`.
    started_wall = procutil.get_process_start_wall(proc.pid)
    if started_wall:
        state.update_started_wall(pid=proc.pid, started_wall=started_wall, path=state_path)
    try:
        exit_code = proc.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        # Codex-review §10 #1 fix: our own watchdog timeout fired. Whatever
        # POSIX signal status we observe next (raw negative wait() return,
        # 137 fallback if SIGKILL also raced), this MUST be classified as
        # "hang" and short-circuit retry. Returning the sentinel makes the
        # classification path single-source and impossible to misread.
        LOG.warning("worker attempt=%d timeout=%ds — SIGTERM→SIGKILL pgid=%d", attempt, timeout_s, pgid)
        _kill_pgid(pgid)
        try:
            proc.wait(timeout=GRACE_PERIOD_S + 5)
        except subprocess.TimeoutExpired:
            LOG.warning(
                "worker attempt=%d still alive after SIGKILL grace pgid=%d",
                attempt,
                pgid,
            )
        duration = time.time() - started
        return TIMEOUT_KILLED_SENTINEL, duration, _read_since(log_path, log_offset)
    duration = time.time() - started
    return _normalize_signal_exit(exit_code), duration, _read_since(log_path, log_offset)


def run_worker(
    *,
    prompt_text: str,
    schedule_id: str = "hourly_dispatch",
    log_path: Path,
    timeout_s: int = DEFAULT_TIMEOUT_S,
    max_attempts: int = MAX_ATTEMPTS,
    state_path: Path = state.STATE_PATH,
    claude_bin: str = CLAUDE_BIN,
    sleep_fn=time.sleep,
) -> WorkerResult:
    """Run prompt through claude -p with retry ladder.

    `sleep_fn` injectable for tests (avoid real 90s backoff).
    """
    if state.read_state(state_path).get("auth_blocked"):
        LOG.warning("auth_blocked=true — refusing to spawn worker (manual unblock required)")
        return WorkerResult(
            exit_code=-2, outcome="auth_blocked", final_model="(none)",
            attempts=0, duration_s=0.0, log_tail="",
        )

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
        exit_code, duration, attempt_output = _run_one_attempt(
            prompt_text=prompt_text, model=model, timeout_s=timeout_s,
            log_path=log_path, attempt=attempt, schedule_id=schedule_id,
            state_path=state_path, claude_bin=claude_bin,
        )
        total_duration += duration
        final_exit = exit_code

        # Classify + report on THIS attempt's output only — the shared log's
        # global tail can contain a previous fire's quota/auth lines, and a
        # stale 'Not logged in' match would freeze the loop (2026-07-05 fix).
        log_tail = attempt_output
        category = _classify(exit_code, attempt_output)
        LOG.info("worker attempt=%d exit=%d category=%s duration=%.1fs", attempt, exit_code, category, duration)

        if category == "success":
            state.record_completion(
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

        if category == "hang":
            # Sanitize sentinel to canonical SIGKILL hang code before persisting:
            # state file readers + alerts expect a real POSIX exit code, not -1000.
            persisted_exit = 137 if exit_code == TIMEOUT_KILLED_SENTINEL else exit_code
            entry = state.record_completion(
                exit_code=persisted_exit, outcome="killed_timeout", final_model=model,
                path=state_path,
            )
            alerts.send_hang_alert(
                job={"pid": -1, "pgid": -1, "started_at": (entry or {}).get("fire_at"),
                     "attempt": attempt, "model": model},
                log_tail=log_tail, state_path=state_path,
            )
            return WorkerResult(
                exit_code=persisted_exit, outcome="killed_timeout", final_model=model,
                attempts=attempt, duration_s=total_duration, log_tail=log_tail,
            )

        if category == "auth":
            state.record_completion(
                exit_code=exit_code, outcome="auth_blocked", final_model=model,
                path=state_path,
            )
            state.set_auth_blocked(True, path=state_path)
            alerts.send_auth_alert(log_tail=log_tail, state_path=state_path)
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
            state.record_completion(
                exit_code=exit_code, outcome="quota_blocked", final_model=model,
                path=state_path,
            )
            alerts.send_quota_alert(log_tail=log_tail, state_path=state_path)
            return WorkerResult(
                exit_code=exit_code, outcome="quota_blocked", final_model=model,
                attempts=attempt, duration_s=total_duration, log_tail=log_tail,
            )

        # transient or hard_failure — both fall through to retry loop
        state.record_completion(
            exit_code=exit_code, outcome="failure", final_model=model,
            path=state_path,
        )
        if attempt < max_attempts:
            wait_s = RETRY_BACKOFF_S if category == "transient" else max(5, RETRY_BACKOFF_S // 3)
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
    alerts.send_completion_failure(entry=entry, log_tail=log_tail, state_path=state_path)
    return WorkerResult(
        exit_code=final_exit, outcome="failure", final_model=final_model,
        attempts=attempt - 1, duration_s=total_duration, log_tail=log_tail,
    )
