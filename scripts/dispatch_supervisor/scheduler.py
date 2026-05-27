"""Scheduler module — asyncio tick → enqueue decision.

Status: Deliverable 2/8 — STUB. Full implementation in Deliverable 3.

Contract sketch::

    async def scheduler_loop(*, schedules: dict, state_path: Path) -> None:
        '''Long-running coroutine. Tick every 60s.

        Each tick:
          1. state.heartbeat()
          2. read auth_blocked → if true, log + skip (manual unblock required)
          3. read current_job → if non-null, log + skip (job in flight; health.py
             watches timeout)
          4. resolve next fire time via croniter on schedules['hourly_dispatch']
          5. if now >= next_fire and last_fire_at < next_fire:
                spawn worker.run_worker(...) (blocking call inside scheduler_loop
                runs in executor to keep tick loop responsive)
          6. on worker return: state.record_completion(...) + alerts.dispatch(...)
        '''

Schedule source: config/runtime_schedules.json — item `hourly_dispatch` cron
field. Hardcoded fallback `7 * * * *` if config unreadable.
"""
from __future__ import annotations

# Deliverable 3 imports:
#   import asyncio
#   from croniter import croniter
#   from . import state, worker, alerts
