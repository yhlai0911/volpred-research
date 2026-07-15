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
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Sequence

from . import alerts, codex_failover, failure_class, procutil, state

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
    if exit_code == TIMEOUT_KILLED_SENTINEL:
        return "hang"
    if exit_code == 0:
        return "success"
    if exit_code in HANG_EXIT_CODES:
        return "hang"
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


def _kill_pgid(pgid: int, *, grace_s: float = GRACE_PERIOD_S) -> bool:
    """SIGTERM whole process group; SIGKILL after grace_s if still alive.

    Codex review fix #5 (2026-07-04): the actual implementation moved to
    `procutil.kill_pgid()` — health.py had its own near-duplicate copy that
    missed a PermissionError fix applied here (found via a live smoke test),
    so both now share one implementation. Kept as a thin wrapper so existing
    callers/tests referencing `worker._kill_pgid` by name are unaffected.
    """
    return procutil.kill_pgid(pgid, grace_s=grace_s)


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
        "--effort", effort, "--model", model,
        "--add-dir", str(PROJECT_ROOT),
        "--settings", str(PROJECT_ROOT / ".claude" / "settings.json"),
        prompt_text,
    ]
    managed_state = True
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
    # attributable (see _dispatch_actor). Extend os.environ — the supervisor
    # boot set VOLPRED_ACTOR=dispatch-supervisor as a process default, which we
    # deliberately override here so AGENT writes carry the fire, not the daemon.
    child_env = {
        **os.environ,
        "VOLPRED_ACTOR": _dispatch_actor(
            schedule_id, slot_id=slot_id, job_id=job_id,
        ),
        "VOLPRED_DISPATCH_SLOT": slot_id,
        "VOLPRED_DISPATCH_JOB_ID": job_id,
    }
    try:
        proc = _spawn(argv=argv, log_path=log_path, env=child_env, cwd=workdir)
    except OSError:
        # Spawn itself failed (e.g. claude_bin missing) — free the slot we
        # just reserved so it doesn't wedge forever with no process behind it.
        state.release_reservation(job_id=job_id, path=state_path)
        raise
    pgid = os.getpgid(proc.pid)
    # Attach pid+pgid IMMEDIATELY (fast — os.getpgid() is a plain syscall) so
    # the pid=None reservation window (a supervisor crash here would strand
    # current_job forever — see supervisor._handle_restart_orphan's
    # pid-is-None branch, Codex review fix #2, 2026-07-04) is narrowed down
    # to the Popen() call itself, not the slower `ps`-based fingerprint call
    # that used to run first and be attached in the same step.
    state.attach_process(
        job_id=job_id, expected_attempt=attempt, pid=proc.pid, pgid=pgid,
        started_wall=None, path=state_path,
    )
    # Codex review §10 #2: fingerprint the process's OS start time so later
    # identity checks (health.py polling, restart orphan cleanup) can detect
    # PID reuse instead of trusting a bare `os.kill(pid, 0)`.
    started_wall = procutil.get_process_start_wall(proc.pid)
    if started_wall:
        state.update_started_wall(
            job_id=job_id, expected_attempt=attempt, pid=proc.pid,
            started_wall=started_wall, path=state_path,
        )
    try:
        exit_code = proc.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        # Codex-review §10 #1 fix: our own watchdog timeout fired. Whatever
        # POSIX signal status we observe next (raw negative wait() return,
        # 137 fallback if SIGKILL also raced), this MUST be classified as
        # "hang" and short-circuit retry. Returning the sentinel makes the
        # classification path single-source and impossible to misread.
        LOG.warning("worker attempt=%d timeout=%ds — SIGTERM→SIGKILL pgid=%d", attempt, timeout_s, pgid)
        killed = bool(_kill_pgid(pgid))
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
        if managed_state and not state.mark_job_phase(
            job_id=job_id, phase="classifying", expected_phase="running",
            expected_attempt=attempt, expected_pid=proc.pid, path=state_path,
        ):
            return OWNERSHIP_LOST_SENTINEL, duration, attempt_output
        return TIMEOUT_KILLED_SENTINEL, duration, attempt_output
    duration = time.time() - started
    attempt_output = _read_since(log_path, log_offset)
    if managed_state and not state.mark_job_phase(
        job_id=job_id, phase="classifying", expected_phase="running",
        expected_attempt=attempt, expected_pid=proc.pid, path=state_path,
    ):
        return OWNERSHIP_LOST_SENTINEL, duration, attempt_output
    return _normalize_signal_exit(exit_code), duration, attempt_output


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

    try:
        result = codex_failover.run_codex_failover(
            reason=reason, slot_id=slot_id, job_id=job_id,
            on_process_started=_track_started,
            on_process_finished=_track_finished,
            workdir=workdir,
        )
    except Exception as exc:  # failover must never take the supervisor down
        LOG.exception("codex failover raised unexpectedly reason=%s", reason)
        alerts.send_codex_failover_alert(
            reason=reason, recovered=False, exit_code=-1,
            detail=f"failover 本身拋出例外：{exc}", attempted=True,
            output_tail=log_tail, state_path=state_path,
        )
        return None

    alerts.send_codex_failover_alert(
        reason=reason, recovered=result.recovered, exit_code=result.exit_code,
        detail=result.detail, attempted=result.attempted,
        output_tail=result.output_tail, state_path=state_path,
    )
    if result.process_active:
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
        exit_code, duration, attempt_output = _run_one_attempt(
            prompt_text=prompt_text, model=model, timeout_s=timeout_s,
            log_path=log_path, attempt=attempt, schedule_id=schedule_id,
            scheduled_for=scheduled_for, fire_reason=fire_reason,
            state_path=state_path, claude_bin=claude_bin,
            job_id=job_id, slot_id=slot_id,
            workdir=workdir,
        )
        total_duration += duration
        final_exit = exit_code

        # Classify + report on THIS attempt's output only — the shared log's
        # global tail can contain a previous fire's quota/auth lines, and a
        # stale 'Not logged in' match would freeze the loop (2026-07-05 fix).
        log_tail = attempt_output
        category = _classify(exit_code, attempt_output)
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

        if category == "hang":
            # Sanitize sentinel to canonical SIGKILL hang code before persisting:
            # state file readers + alerts expect a real POSIX exit code, not -1000.
            persisted_exit = 137 if exit_code == TIMEOUT_KILLED_SENTINEL else exit_code
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
                         # observed at alert time: macOS can and does refuse
                         # killpg, so report whether the SIGKILL actually landed
                         # rather than asserting it did (see procutil.kill_pgid).
                         "survivors": procutil.pgid_members(pgid) if pgid > 0 else []},
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
                outcome="failure", final_model=model, release_slot=False,
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
