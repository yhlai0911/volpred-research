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
`procutil.check_identity()`, which compares the `ps`-derived start-time
fingerprint captured at spawn and returns one of MATCH / MISMATCH / DEAD /
UNVERIFIED (Codex review fix #4, 2026-07-04 — a bare-bool version of this
check used to *degrade to "assume same process"* when no fingerprint had
been recorded, which is backwards for a kill decision; UNVERIFIED forces
this module to decide explicitly rather than kill on unverified evidence).
"""
from __future__ import annotations

import asyncio
import logging
import traceback
from pathlib import Path

from . import alerts, procutil, state

LOG = logging.getLogger(__name__)

CHECK_INTERVAL_S = 30
MAX_JOB_AGE_S = 3000  # 50min — matches worker DEFAULT_TIMEOUT_S


def _force_kill_pgid(pgid: int) -> None:
    """Codex review fix #5 (2026-07-04): this used to be a near-duplicate of
    worker.py's kill routine and missed a PermissionError fix applied there
    (found via a live smoke test) — now both share `procutil.kill_pgid()`."""
    procutil.kill_pgid(pgid)


def check_once(*, state_path: Path = state.STATE_PATH, max_age_s: float = MAX_JOB_AGE_S) -> str | None:
    """Single non-async health pass. Returns action taken
    ('killed' | 'silent_death' | 'timeout_unverified' | None).

    Extracted as sync function so tests (and CLI smoke checks) can call without
    spinning up asyncio.
    """
    job = state.get_current_job(state_path)
    if job is None:
        return None
    identity = procutil.check_identity(job.pid, job.started_wall)
    if job.age_seconds > max_age_s:
        if identity == procutil.IDENTITY_MATCH:
            LOG.warning("health: worker pgid=%d age=%.0fs > %.0fs cap — force-killing", job.pgid, job.age_seconds, max_age_s)
            _force_kill_pgid(job.pgid)
            exit_code, outcome = -9, "killed_timeout"
            log_tail = "(killed by health monitor — see worker log_path)"
        elif identity == procutil.IDENTITY_UNVERIFIED:
            # Codex review fix #4: no fingerprint was ever recorded for this
            # job — we cannot confirm this pid is still our worker and not a
            # PID-reuse collision, so we must NOT signal it. Clear the slot
            # (via record_completion below) so the scheduler isn't wedged
            # forever, but flag it distinctly so ops knows to check by hand.
            LOG.warning(
                "health: worker pid=%d aged out with NO identity fingerprint recorded — "
                "NOT killing (unverified target), recording for manual check",
                job.pid,
            )
            exit_code, outcome = -1, "timeout_unverified"
            log_tail = (
                "(aged out but no fingerprint recorded — NOT killed; process may still be "
                "alive. Manual check runbook: docs/runbooks/dispatch-supervisor-unverified-orphan.md)"
            )
        else:
            # IDENTITY_MISMATCH or IDENTITY_DEAD — confirmed NOT our process
            # (already gone, or the OS recycled the pid to something else).
            LOG.warning(
                "health: worker pid=%d aged out but identity=%s (pgid=%d) — skipping kill",
                job.pid, identity, job.pgid,
            )
            exit_code, outcome = -1, "silent_death"
            log_tail = "(identity mismatch/dead at max-age check — not killed, recorded as silent_death)"
        state.record_completion(exit_code=exit_code, outcome=outcome, final_model=job.model, path=state_path)
        alerts.send_hang_alert(
            job={"pid": job.pid, "pgid": job.pgid, "started_at": job.started_at,
                 "attempt": job.attempt, "model": job.model},
            log_tail=log_tail,
            state_path=state_path,
        )
        return "killed" if identity == procutil.IDENTITY_MATCH else outcome
    if identity in (procutil.IDENTITY_MISMATCH, procutil.IDENTITY_DEAD):
        LOG.warning(
            "health: worker pid=%d dead/reused (identity=%s) but state has current_job — recording silent failure",
            job.pid, identity,
        )
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
    # IDENTITY_MATCH, or IDENTITY_UNVERIFIED while still within budget — leave
    # it alone. An unverified fingerprint here just means it hasn't been
    # captured yet, not that anything is actually wrong.
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
