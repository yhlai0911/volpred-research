"""Health monitor — independent worker liveness check.

Runs as asyncio task inside supervisor.py main loop. Polls
`state.get_current_job()` every CHECK_INTERVAL_S seconds:

  - job.age_seconds > MAX_JOB_AGE_S    → identity-verified SIGKILL pgid, record
                                          killed_timeout, alert
  - PID dead/reused but state has job  → record silent_death / silent_failure, alert

This is the belt-and-suspenders layer behind worker.py's own
`Popen.wait(timeout=)`. If worker.py itself hangs inside `wait()` (shouldn't,
but Python signal handling on macOS can surprise), health.py rescues from
outside via state-file inspection.

Codex review §10 #2 fix (2026-06-15): both branches used to trust a bare
`os.kill(pid, 0)` check. Across a 30s poll interval the OS can recycle a pid
to an unrelated process — killing/misreporting on that stale pid would hit
the WRONG process. Every identity-sensitive decision below goes through
`procutil.pid_identity_matches()`, which compares the `ps`-derived start-time
fingerprint captured at spawn.
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import time
import traceback
from pathlib import Path

from . import alerts, procutil, state

LOG = logging.getLogger(__name__)

CHECK_INTERVAL_S = 30
MAX_JOB_AGE_S = 3000  # 50min — matches worker DEFAULT_TIMEOUT_S


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
            pass  # silent-ok: process group exited between SIGTERM and probe.
    except ProcessLookupError:
        pass  # silent-ok: process group was already gone before SIGTERM.
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
    identity_ok = procutil.pid_identity_matches(job.pid, job.started_wall)
    if job.age_seconds > max_age_s:
        if identity_ok:
            LOG.warning("health: worker pgid=%d age=%.0fs > %.0fs cap — force-killing", job.pgid, job.age_seconds, max_age_s)
            _force_kill_pgid(job.pgid)
            exit_code, outcome = -9, "killed_timeout"
        else:
            # Codex review §10 #2: pid/pgid no longer matches the fingerprint
            # captured at spawn — either already gone or recycled to an
            # unrelated process. Do NOT signal it; record as silent death
            # instead of a (potentially wrong-target) kill.
            LOG.warning(
                "health: worker pid=%d aged out but identity mismatch (pgid=%d reused/gone) — skipping kill",
                job.pid, job.pgid,
            )
            exit_code, outcome = -1, "silent_death"
        state.record_completion(exit_code=exit_code, outcome=outcome, final_model=job.model, path=state_path)
        alerts.send_hang_alert(
            job={"pid": job.pid, "pgid": job.pgid, "started_at": job.started_at,
                 "attempt": job.attempt, "model": job.model},
            log_tail="(killed by health monitor — see worker log_path)" if identity_ok
                     else "(identity mismatch at max-age check — not killed, recorded as silent_death)",
            state_path=state_path,
        )
        return "killed" if identity_ok else "silent_death"
    if not identity_ok:
        LOG.warning("health: worker pid=%d dead/reused but state has current_job — recording silent failure", job.pid)
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
            # Codex review §10 #7 fix: this used to only LOG.exception — a
            # crash-looping health monitor (the belt-and-suspenders layer
            # behind worker.py's own timeout) would silently stop protecting
            # against hangs with zero visibility to the boss.
            LOG.exception("health_loop unexpected error: %s", exc)
            alerts.send_loop_crash("health_loop", traceback.format_exc(), state_path=state_path)
            # don't die — sleep and continue
