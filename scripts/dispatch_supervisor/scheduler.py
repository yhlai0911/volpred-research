"""Scheduler — asyncio tick → "is it time to fire?" → worker.run_worker.

Tick every TICK_INTERVAL_S (=60s). On each tick:

  1. `state.heartbeat()` — prove supervisor alive
  2. If `auth_blocked` true → log + skip (manual unblock via CLI)
  3. If `current_job` non-null → log + skip (worker in flight; health watches)
  4. Compute most recent scheduled fire time via croniter
  5. If `last_fire_at < that fire time` → spawn worker (or DRY-RUN log only)
  6. Block-wait for worker to return; loop continues on next tick

The worker call is blocking; we run it inside `asyncio.to_thread()` so the
event loop stays responsive for health_loop concurrent execution.

In `dry_run=True` mode (shadow phase per refactor_plan §4 phase 2) the
scheduler logs "WOULD enqueue at <fire_at>" + updates last_fire_at but
does NOT spawn a worker. Used to diff against legacy shell decisions.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from croniter import croniter

from . import state, worker

LOG = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
SCHEDULES_PATH = ROOT / "config" / "runtime_schedules.json"
DEFAULT_PROMPT_PATH = ROOT / "scripts" / "cron_hourly_dispatch_prompt.md"
DEFAULT_LOG_DIR = Path(os.environ.get("VOLPRED_HOME_DIR", str(Path.home() / ".volpred"))) / "logs"
DEFAULT_LOG_PATH = DEFAULT_LOG_DIR / "dispatch_supervisor_worker.log"

TICK_INTERVAL_S = 60
FALLBACK_CRON = "7 * * * *"
# config/runtime_schedules.json id; cron field is often null because legacy
# scheduling lived in LaunchAgent plist. Supervisor falls back to "7 * * * *".
SCHEDULE_ID = "volpred-hourly-dispatch"


def load_cron_expr(*, schedules_path: Path = SCHEDULES_PATH, schedule_id: str = SCHEDULE_ID) -> str:
    """Read the schedule cron expression for the named schedule.

    Codex-review §10 #6 fix: canonical field is `schedule` (the `cron` field
    is `null` for `volpred-hourly-dispatch` because legacy scheduling lived
    in the LaunchAgent plist — see config/runtime_schedules.json). Reading
    only `cron` worked by coincidence (fallback `7 * * * *` matched), but if
    ops bumped `schedule` in config the supervisor would silently ignore it.

    Tries `schedule` first (canonical), falls back to `cron` (legacy),
    then FALLBACK_CRON. Looks in `cron_jobs[]` (canonical) and legacy
    `items[]`.
    """
    try:
        data = json.loads(schedules_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        LOG.warning("load_cron_expr fallback (%s): %s", FALLBACK_CRON, exc)
        return FALLBACK_CRON
    for key in ("cron_jobs", "items"):
        entries = data.get(key) or []
        if not isinstance(entries, list):
            continue
        for item in entries:
            if not isinstance(item, dict):
                continue
            if item.get("id") != schedule_id:
                continue
            for field in ("schedule", "cron"):
                cron_expr = item.get(field)
                if isinstance(cron_expr, str) and cron_expr.strip():
                    LOG.debug("schedule id=%s using field=%r expr=%r",
                              schedule_id, field, cron_expr.strip())
                    return cron_expr.strip()
    LOG.info("schedule id=%s has no schedule/cron field; supervisor using fallback %r",
             schedule_id, FALLBACK_CRON)
    return FALLBACK_CRON


def _prev_fire(cron_expr: str, *, now: datetime | None = None) -> datetime:
    base = now or datetime.now()
    return croniter(cron_expr, base).get_prev(datetime)


def _next_fire(cron_expr: str, *, now: datetime | None = None) -> datetime:
    base = now or datetime.now()
    return croniter(cron_expr, base).get_next(datetime)


def _due_to_fire(*, cron_expr: str, last_fire_at: str | None, now: datetime | None = None) -> tuple[bool, datetime]:
    """Decide if we should fire now. Returns (due, prev_scheduled_fire)."""
    prev = _prev_fire(cron_expr, now=now)
    if not last_fire_at:
        return True, prev
    try:
        last_dt = datetime.fromisoformat(last_fire_at)
        # tz-naive cron + tz-aware state: drop tz for comparison (cron uses local time)
        if last_dt.tzinfo is not None:
            last_dt = last_dt.astimezone().replace(tzinfo=None)
    except (TypeError, ValueError) as exc:
        LOG.warning(
            "invalid last_fire_at=%r; treating scheduler as due: %s",
            last_fire_at,
            exc,
        )
        return True, prev
    return last_dt < prev, prev


def _load_prompt(path: Path = DEFAULT_PROMPT_PATH) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        LOG.error("prompt file missing: %s", path)
        return ""


async def scheduler_loop(
    *,
    state_path: Path = state.STATE_PATH,
    schedules_path: Path = SCHEDULES_PATH,
    prompt_path: Path = DEFAULT_PROMPT_PATH,
    log_path: Path = DEFAULT_LOG_PATH,
    tick_interval_s: int = TICK_INTERVAL_S,
    dry_run: bool = False,
) -> None:
    """Long-running scheduler. Loops until cancelled."""
    cron_expr = load_cron_expr(schedules_path=schedules_path)
    LOG.info("scheduler_loop start cron=%r dry_run=%s tick=%ds", cron_expr, dry_run, tick_interval_s)
    while True:
        try:
            await asyncio.sleep(tick_interval_s)
            await _tick_once(
                state_path=state_path, cron_expr=cron_expr,
                prompt_path=prompt_path, log_path=log_path,
                dry_run=dry_run,
            )
            # reload cron expr in case ops changed config mid-run
            cron_expr = load_cron_expr(schedules_path=schedules_path)
        except asyncio.CancelledError:
            LOG.info("scheduler_loop cancelled")
            raise
        except Exception as exc:  # noqa: BLE001
            LOG.exception("scheduler tick crashed: %s", exc)


async def _tick_once(
    *,
    state_path: Path,
    cron_expr: str,
    prompt_path: Path,
    log_path: Path,
    dry_run: bool,
) -> dict[str, Any]:
    """One tick. Returns a small dict describing the decision (for tests + audit log)."""
    state.heartbeat(path=state_path)
    snap = state.read_state(state_path)
    if snap.get("auth_blocked"):
        return {"action": "skip", "reason": "auth_blocked"}
    if snap.get("current_job"):
        return {"action": "skip", "reason": "job_in_flight"}
    due, prev_fire = _due_to_fire(cron_expr=cron_expr, last_fire_at=snap.get("last_fire_at"))
    if not due:
        return {"action": "skip", "reason": "not_due", "prev_fire": prev_fire.isoformat()}
    if dry_run:
        LOG.info("DRY-RUN would fire (prev_scheduled=%s)", prev_fire.isoformat())
        # update last_fire_at so we don't re-log every tick — shadow run still tracks
        with state._locked_state(state_path) as (_fh, data):
            data["last_fire_at"] = state._now()
        return {"action": "dry_run_fire", "prev_fire": prev_fire.isoformat()}
    prompt = _load_prompt(prompt_path)
    if not prompt:
        LOG.error("empty prompt — refusing to fire")
        return {"action": "skip", "reason": "empty_prompt"}
    LOG.info("firing worker prev_scheduled=%s log=%s", prev_fire.isoformat(), log_path)
    # Block in thread so health_loop keeps running concurrently
    result = await asyncio.to_thread(
        worker.run_worker,
        prompt_text=prompt, schedule_id=SCHEDULE_ID,
        log_path=log_path, state_path=state_path,
    )
    LOG.info("worker returned outcome=%s attempts=%d duration=%.1fs", result.outcome, result.attempts, result.duration_s)
    return {
        "action": "fired", "outcome": result.outcome,
        "attempts": result.attempts, "exit_code": result.exit_code,
    }
