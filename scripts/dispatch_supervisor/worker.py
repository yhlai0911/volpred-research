"""Worker — subprocess.Popen wrapper with PGID isolation, timeout, retry ladder.

Replaces all `perl alarm` + watchdog + shell trap layers from
`scripts/cron_hourly_dispatch.sh` with one Python `Popen.wait(timeout=...)`.

Retry ladder (refactor_plan §3 retry policy)::

    attempt 1: opus    → opus exit≠0 + transient (529 / network) → sleep 90s
    attempt 2: opus    → opus exit≠0 + transient → sleep 90s
    attempt 3: sonnet  (final fallback)
    auth-class error  → NO retry; set_auth_blocked(True); send_auth_alert; abort
    hang (SIGKILL'd)  → NO retry; record killed_timeout; alert

Each attempt records `begin_fire` BEFORE Popen.wait + `record_completion`
AFTER. Health monitor (health.py) reads `current_job.age_seconds` from the
same state file to independently detect frozen workers if THIS process itself
hangs inside `wait()` (shouldn't happen with `timeout=` but health is the
belt-and-suspenders layer).
"""
from __future__ import annotations

import logging
import os
import re
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from . import alerts, state

LOG = logging.getLogger(__name__)

# Default upstream constants (overridable via env for tests + ops)
DEFAULT_TIMEOUT_S = 3000  # 50min — matches CLAUDE.md hourly cap
GRACE_PERIOD_S = 10        # SIGTERM grace before SIGKILL
RETRY_BACKOFF_S = 90        # between transient-failure attempts
MAX_ATTEMPTS = 3

OPUS_MODEL = "claude-opus-4-7"
SONNET_MODEL = "claude-sonnet-4-6"

CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "/Users/yhlai0911/.local/bin/claude")

# Exit codes from `claude -p` that we recognise
HANG_EXIT_CODES = {137, 142, 143}  # SIGKILL / SIGALRM / SIGTERM

# stderr/stdout regex classifiers
_AUTH_RE = re.compile(r"(Not logged in|Please run /login|invalid_api_key|authentication)", re.I)
_TRANSIENT_RE = re.compile(r"(529|Overloaded|ECONNRESET|ETIMEDOUT|Connection reset|rate.?limit)", re.I)


@dataclass
class WorkerResult:
    exit_code: int
    outcome: str             # success | failure | killed_timeout | auth_blocked
    final_model: str
    attempts: int
    duration_s: float
    log_tail: str            # last ~2KB of combined stdout+stderr


def _classify(exit_code: int, output: str) -> str:
    """Return one of: success | hang | auth | transient | hard_failure."""
    if exit_code == 0:
        return "success"
    if exit_code in HANG_EXIT_CODES:
        return "hang"
    if _AUTH_RE.search(output or ""):
        return "auth"
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
        return ""
    except OSError as exc:
        LOG.warning("read_tail %s failed: %s", path, exc)
        return ""


def _kill_pgid(pgid: int, *, grace_s: float = GRACE_PERIOD_S) -> None:
    """SIGTERM whole process group; SIGKILL after grace_s if still alive."""
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except PermissionError as exc:
        LOG.warning("killpg SIGTERM denied pgid=%d: %s", pgid, exc)
    deadline = time.time() + grace_s
    while time.time() < deadline:
        try:
            os.killpg(pgid, 0)  # liveness probe
        except ProcessLookupError:
            return
        time.sleep(0.5)
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except PermissionError as exc:
        LOG.warning("killpg SIGKILL denied pgid=%d: %s", pgid, exc)


def _spawn(*, argv: Sequence[str], log_path: Path) -> subprocess.Popen:
    """Spawn child in its own process group; redirect combined stdout+stderr to log_path."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_fh = log_path.open("ab")
    return subprocess.Popen(
        list(argv),
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        start_new_session=True,  # new PGID — clean SIGKILL group
        close_fds=True,
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
) -> tuple[int, float]:
    """Single Popen attempt. Returns (exit_code, duration_s).

    On timeout: SIGKILL whole PGID, return exit_code=-9 (mapped to killed_timeout
    upstream via HANG_EXIT_CODES + outcome classification).
    """
    argv = [
        claude_bin, "-p", "--dangerously-skip-permissions",
        "--model", model, prompt_text,
    ]
    started = time.time()
    proc = _spawn(argv=argv, log_path=log_path)
    pgid = os.getpgid(proc.pid)
    state.begin_fire(
        pid=proc.pid, pgid=pgid, schedule_id=schedule_id,
        attempt=attempt, model=model, log_path=str(log_path),
        path=state_path,
    )
    try:
        exit_code = proc.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        LOG.warning("worker attempt=%d timeout=%ds — SIGTERM→SIGKILL pgid=%d", attempt, timeout_s, pgid)
        _kill_pgid(pgid)
        try:
            exit_code = proc.wait(timeout=GRACE_PERIOD_S + 5)
        except subprocess.TimeoutExpired:
            exit_code = 137  # treat as SIGKILL outcome
    duration = time.time() - started
    return exit_code, duration


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
        model = SONNET_MODEL if attempt == max_attempts else OPUS_MODEL
        final_model = model
        LOG.info("worker attempt=%d/%d model=%s", attempt, max_attempts, model)
        exit_code, duration = _run_one_attempt(
            prompt_text=prompt_text, model=model, timeout_s=timeout_s,
            log_path=log_path, attempt=attempt, schedule_id=schedule_id,
            state_path=state_path, claude_bin=claude_bin,
        )
        total_duration += duration
        final_exit = exit_code

        log_tail = _read_tail(log_path)
        category = _classify(exit_code, log_tail)
        LOG.info("worker attempt=%d exit=%d category=%s duration=%.1fs", attempt, exit_code, category, duration)

        if category == "success":
            state.record_completion(
                exit_code=exit_code, outcome="success", final_model=model,
                path=state_path,
            )
            return WorkerResult(
                exit_code=0, outcome="success", final_model=model,
                attempts=attempt, duration_s=total_duration, log_tail=log_tail,
            )

        if category == "hang":
            entry = state.record_completion(
                exit_code=exit_code, outcome="killed_timeout", final_model=model,
                path=state_path,
            )
            alerts.send_hang_alert(
                job={"pid": -1, "pgid": -1, "started_at": (entry or {}).get("fire_at"),
                     "attempt": attempt, "model": model},
                log_tail=log_tail, state_path=state_path,
            )
            return WorkerResult(
                exit_code=exit_code, outcome="killed_timeout", final_model=model,
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
