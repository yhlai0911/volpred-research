"""Health monitor module — independent worker liveness check.

Status: Deliverable 2/8 — STUB. Full implementation in Deliverable 3.

Runs as asyncio task inside supervisor.py (not separate process — health-check
inside supervisor is fine, because the launchd KeepAlive of supervisor itself
is the external safety net per refactor_plan §3).

Contract sketch::

    async def health_loop(*, state_path: Path, check_interval_s: int = 30) -> None:
        while True:
            await asyncio.sleep(check_interval_s)
            job = state.get_current_job(state_path)
            if job is None:
                continue
            if job.age_seconds > MAX_JOB_AGE_S:
                # worker stuck past timeout — escalate
                _force_kill_pgid(job.pgid)
                state.record_completion(exit_code=-9, outcome='killed_timeout',
                                        final_model=job.model)
                alerts.send_hang_alert(job)
            elif not _pid_alive(job.pid):
                # worker died silently without state update
                state.record_completion(exit_code=-1, outcome='failure',
                                        final_model=job.model)
                alerts.send_silent_death_alert(job)

MAX_JOB_AGE_S = 3000  # 50min — matches CLAUDE.md hourly cap
"""
from __future__ import annotations

# Deliverable 3 imports:
#   import asyncio, os, signal
#   from . import state, alerts

MAX_JOB_AGE_S = 3000
