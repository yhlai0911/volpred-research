"""Health monitor — independent worker liveness check.

Runs as asyncio task inside supervisor.py main loop. Polls
`state.get_current_job()` every CHECK_INTERVAL_S seconds:

  - job.age_seconds > MAX_JOB_AGE_S    → SIGKILL pgid, record killed_timeout, alert
  - PID dead but state.current_job set → record silent_failure, alert

This is the belt-and-suspenders layer behind worker.py's own
`Popen.wait(timeout=)`. If worker.py itself hangs inside `wait()` (shouldn't,
but Python signal handling on macOS can surprise), health.py rescues from
outside via state-file inspection.
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import time
from pathlib import Path

from . import alerts, state

LOG = logging.getLogger(__name__)

CHECK_INTERVAL_S = 30
MAX_JOB_AGE_S = 3000  # 50min — matches worker DEFAULT_TIMEOUT_S


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but we lack signal permission — still "alive" for monitoring
        return True


def _force_kill_pgid(pgid: int) -> None:
    if pgid <= 0:
        return
    try:
        os.killpg(pgid, signal.SIGTERM)
        time.sleep(2)
        try:
            os.killpg(pgid, 0)
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    except ProcessLookupError:
        pass
    except PermissionError as exc:
        LOG.warning("force_kill pgid=%d denied: %s", pgid, exc)


def check_once(*, state_path: Path = state.STATE_PATH, max_age_s: float = MAX_JOB_AGE_S) -> str | None:
    """Single non-async health pass. Returns action taken ('killed' | 'silent_death' | None).

    Extracted as sync function so tests (and CLI smoke checks) can call without
    spinning up asyncio.
    """
    job = state.get_current_job(state_path)
    if job is None:
        return None
    if job.age_seconds > max_age_s:
        LOG.warning("health: worker pgid=%d age=%.0fs > %.0fs cap — force-killing", job.pgid, job.age_seconds, max_age_s)
        _force_kill_pgid(job.pgid)
        entry = state.record_completion(
            exit_code=-9, outcome="killed_timeout", final_model=job.model,
            path=state_path,
        )
        alerts.send_hang_alert(
            job={"pid": job.pid, "pgid": job.pgid, "started_at": job.started_at,
                 "attempt": job.attempt, "model": job.model},
            log_tail="(killed by health monitor — see worker log_path)",
            state_path=state_path,
        )
        return "killed"
    if not _pid_alive(job.pid):
        LOG.warning("health: worker pid=%d dead but state has current_job — recording silent failure", job.pid)
        state.record_completion(
            exit_code=-1, outcome="failure", final_model=job.model,
            path=state_path,
        )
        alerts.send_silent_death_alert(
            job={"pid": job.pid, "pgid": job.pgid, "started_at": job.started_at,
                 "attempt": job.attempt, "model": job.model},
            state_path=state_path,
        )
        return "silent_death"
    return None


async def health_loop(*, state_path: Path = state.STATE_PATH, check_interval_s: int = CHECK_INTERVAL_S) -> None:
    """Long-running health monitor coroutine."""
    LOG.info("health_loop start interval=%ds", check_interval_s)
    while True:
        try:
            await asyncio.sleep(check_interval_s)
            check_once(state_path=state_path)
        except asyncio.CancelledError:
            LOG.info("health_loop cancelled")
            raise
        except Exception as exc:  # noqa: BLE001
            LOG.exception("health_loop unexpected error: %s", exc)
            # don't die — sleep and continue
