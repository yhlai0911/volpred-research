"""Scheduler — asyncio tick → "is it time to fire?" → worker.run_worker.

Tick every TICK_INTERVAL_S (=60s). On each tick:

  1. `state.heartbeat()` — belt-and-suspenders only. This tick BLOCKS in step 6
     for the entire worker run, so it cannot keep the heartbeat fresh; the
     liveness owner is `health.health_loop()` (30s, never blocks). Kept here so
     `--once` smoke runs, which skip health_loop, still stamp one beat.
  2. If `auth_blocked` true → log + skip (manual unblock via CLI)
  3. If `current_job` non-null → log + skip (worker in flight; health watches)
  4. Compute most recent scheduled fire time via croniter
  5. If due (and not dry_run) → `phase_z.run_pre_fire_guard()` — fail-open git
     conflict backstop, so the slot starts on a clean, valid tree
  6. If `last_fire_at < that fire time` → spawn worker (or DRY-RUN log only)
  7. Block-wait for worker to return, then `phase_z.run_phase_z()`; loop
     continues on next tick

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
import subprocess
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

from croniter import croniter

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))
from volpred.ops.timestamps import parse_iso_warn  # noqa: E402

from . import alerts, phase_z, state, worker

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


PREGATE_SCRIPT = ROOT / "scripts" / "hourly_dispatch_pregate.py"
PREGATE_TIMEOUT_S = 60
PREGATE_MODES = ("off", "shadow", "enforce")


def load_pregate_config(*, schedules_path: Path = SCHEDULES_PATH, schedule_id: str = SCHEDULE_ID) -> dict[str, Any]:
    """Read the pregate config from the canonical schedule entry.

    2026-07-10 rewire: scripts/hourly_dispatch_pregate.py (zero-token "is this
    cron slot worth the ~95K claude -p cold-load?" triage) was orphaned by the
    7/4 supervisor cutover — it was only wired into the legacy shell. This
    reads `pregate: {mode, window_hours}` from the volpred-hourly-dispatch
    entry so the flip shadow→enforce is a config edit, no daemon restart
    (scheduler_loop re-reads config every tick).

    Fail-open: missing/invalid config → mode "off" (never skip on uncertainty).
    """
    fallback = {"mode": "off", "window_hours": 3.0}
    try:
        data = json.loads(schedules_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        LOG.warning("load_pregate_config fail-open mode=off: %s", exc)
        return fallback
    for key in ("cron_jobs", "items"):
        entries = data.get(key) or []
        if not isinstance(entries, list):
            continue
        for item in entries:
            if not isinstance(item, dict) or item.get("id") != schedule_id:
                continue
            cfg = item.get("pregate")
            if not isinstance(cfg, dict):
                return fallback
            mode = str(cfg.get("mode", "off")).lower()
            if mode not in PREGATE_MODES:
                LOG.warning("pregate mode %r invalid — fail-open mode=off", mode)
                mode = "off"
            try:
                window_hours = float(cfg.get("window_hours", 3.0))
            except (TypeError, ValueError):
                LOG.warning("pregate window_hours %r invalid — using 3.0", cfg.get("window_hours"))
                window_hours = 3.0
            return {"mode": mode, "window_hours": window_hours}
    return fallback


def _run_pregate(*, mode: str, window_hours: float) -> bool:
    """Run the zero-token pregate as a subprocess. Returns True = SKIP this fire.

    Subprocess (not import) so a pregate crash can never take down the daemon.
    Pregate CLI exit semantics: 0 = SKIP, anything else = PROCEED — a crash
    (exit≠0) or timeout is therefore inherently fail-open. In shadow mode we
    pass --shadow: pregate always exits 1 (proceed) but appends the would-be
    decision to storage/logs/hourly_pregate.jsonl for the observation window.
    """
    cmd = [sys.executable, str(PREGATE_SCRIPT), "--window-hours", str(window_hours),
           "--invoker", "supervisor"]
    if mode == "shadow":
        cmd.append("--shadow")
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=PREGATE_TIMEOUT_S, cwd=str(ROOT), check=False,
        )
    except subprocess.TimeoutExpired:
        LOG.warning("pregate timeout after %ss — fail-open PROCEED", PREGATE_TIMEOUT_S)
        return False
    except OSError as exc:
        LOG.warning("pregate spawn failed (%s) — fail-open PROCEED", exc)
        return False
    if proc.returncode == 0:
        return True
    if proc.returncode != 1:
        LOG.warning("pregate unexpected exit=%s stderr=%s — fail-open PROCEED",
                    proc.returncode, (proc.stderr or "")[-300:])
    return False


def _prev_fire(cron_expr: str, *, now: datetime | None = None) -> datetime:
    base = now or datetime.now()
    return croniter(cron_expr, base).get_prev(datetime)


def _next_fire(cron_expr: str, *, now: datetime | None = None) -> datetime:
    base = now or datetime.now()
    return croniter(cron_expr, base).get_next(datetime)


def _parse_last_fire(raw: str | None) -> datetime | None:
    """`last_fire_at` as a naive-local datetime, or None if missing/unparseable.

    tz-naive cron + tz-aware state: croniter's `prev` is naive local, so an
    aware stored value must be converted to the same frame before comparing.
    """
    if not raw:
        return None
    dt = parse_iso_warn(
        raw,
        tag="supervisor",
        field_name="last_fire_at",
        fallback=None,
        assume_tz=None,
    )
    if dt is None:
        return None  # parse failed → parse_iso_warn already emitted a WARN
    return dt.astimezone().replace(tzinfo=None) if dt.tzinfo is not None else dt


def _due_to_fire(*, cron_expr: str, last_fire_at: str | None, now: datetime | None = None) -> tuple[bool, datetime]:
    """Decide if we should fire now. Returns (due, prev_scheduled_fire).

    2026-07-10 root-cause fix. This used to `return True` when `last_fire_at`
    was missing or unparseable — "we don't know when we last fired" was treated
    as "fire right now". In a 60s-tick daemon that turns any loss of
    `dispatch_state.json` into an immediate ~95K opus cold-load, and keeps
    firing every tick until something writes the field back.

    That is exactly what happened: an external writer reset production state
    (daemon never logged a reset of its own), and the very next tick fired an
    off-slot duplicate of the 22:07 slot at 22:58. Log audit: 9 such off-slot
    fires in 159 (+24…+54 min after their slot), each a full cold-load.

    Unknown is now NOT due. `_tick_once` bootstraps the field and we resume on
    the next real cron slot — worst case one skipped hour, never a burn.
    """
    prev = _prev_fire(cron_expr, now=now)
    last_dt = _parse_last_fire(last_fire_at)
    if last_dt is None:
        return False, prev
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
                dry_run=dry_run, schedules_path=schedules_path,
            )
            # reload cron expr in case ops changed config mid-run
            cron_expr = load_cron_expr(schedules_path=schedules_path)
        except asyncio.CancelledError:
            LOG.info("scheduler_loop cancelled")
            raise
        except Exception as exc:  # noqa: BLE001
            # Codex review §10 #7 fix: this used to only LOG.exception — a
            # crash-looping scheduler (the ONLY thing that ever fires
            # hourly-dispatch) would silently stop dispatching with zero
            # alert. Escalate so the boss sees it instead of discovering a
            # dispatch drought hours later.
            LOG.exception("scheduler tick crashed: %s", exc)
            alerts.send_loop_crash("scheduler_loop", traceback.format_exc(), state_path=state_path)


async def _tick_once(
    *,
    state_path: Path,
    cron_expr: str,
    prompt_path: Path,
    log_path: Path,
    dry_run: bool,
    repo_root: Path = ROOT,
    schedules_path: Path = SCHEDULES_PATH,
) -> dict[str, Any]:
    """One tick. Returns a small dict describing the decision (for tests + audit log)."""
    state.heartbeat(path=state_path)
    snap = state.read_state(state_path)
    if snap.get("auth_blocked"):
        return {"action": "skip", "reason": "auth_blocked"}
    if snap.get("current_job"):
        # NOTE: a pending fire_requested_at deliberately survives this skip —
        # "fire ASAP" means right after the in-flight job, never in parallel.
        return {"action": "skip", "reason": "job_in_flight"}
    if _parse_last_fire(snap.get("last_fire_at")) is None:
        # Cold start, or `dispatch_state.json` was lost / clobbered by an
        # external writer (the daemon logs its own resets; a silent loss is
        # someone else's write). `_due_to_fire` now refuses to treat "unknown"
        # as "due" — so stamp the field and let the NEXT real slot fire.
        # Without this bootstrap the daemon would never fire again.
        with state._locked_state(state_path) as (_fh, data):
            if _parse_last_fire(data.get("last_fire_at")) is None:
                data["last_fire_at"] = state._now()
        LOG.warning(
            "last_fire_at missing/unparseable (cold start or external state loss) — "
            "bootstrapped to now; the next scheduled slot fires normally. "
            "NOT firing an off-slot catch-up (2026-07-10: that cost 9 stray ~95K cold-loads)."
        )
        return {"action": "skip", "reason": "bootstrap_last_fire_at"}
    due, prev_fire = _due_to_fire(cron_expr=cron_expr, last_fire_at=snap.get("last_fire_at"))
    fire_reason = "cron"
    if not due:
        # External ASAP trigger (e.g. boss replied to an email — see
        # state.request_fire): fire now instead of waiting for the next cron
        # slot. Consumed atomically so one request produces exactly one fire.
        requested = state.consume_fire_request(state_path)
        if requested is not None:
            LOG.info("fire request consumed (reason=%s) — firing off-cadence", requested)
            due = True
            fire_reason = f"requested:{requested}"
    else:
        # Cron is due anyway — clear any pending request so it doesn't cause
        # a SECOND fire right after this one (the request is satisfied). Keep
        # the request visible in fire_reason: a requested fire must never be
        # pregate-skipped (boss asked for it), so it can't stay plain "cron".
        requested = state.consume_fire_request(state_path)
        if requested is not None:
            fire_reason = f"cron+requested:{requested}"
    if not due:
        return {"action": "skip", "reason": "not_due", "prev_fire": prev_fire.isoformat()}
    # Git conflict guard (2026-07-10 rewire; see phase_z.run_pre_fire_guard).
    # Orphaned by the 7/4 cutover — its only caller was the now-unloaded
    # cron_hourly_dispatch.sh, while the concurrent-writer risk it backstops
    # (dispatcher + always-on codex_loop on one branch) never went away.
    #
    # Ordered BEFORE the pregate, exactly as the legacy shell had it ("run the
    # watchdog FIRST so every hourly slot starts on a clean, valid tree"): the
    # files it repairs are read by the live site AND by the pregate itself, not
    # only by the dispatched agent, so a pregate-skipped slot still deserves a
    # clean tree. dry_run touches no repo → never guards.
    #
    # try/except is belt-and-suspenders: run_pre_fire_guard is already no-raise
    # and fail-open, but a guard must never be able to veto the dispatch it
    # guards (same rationale as the phase_z call below).
    if not dry_run:
        try:
            guard_outcome = await asyncio.to_thread(phase_z.run_pre_fire_guard, repo_root=repo_root)
            LOG.info("pre_fire_guard outcome=%s", guard_outcome)
        except Exception as exc:  # noqa: BLE001
            LOG.warning("pre_fire_guard failed (non-fatal, firing anyway): %s", exc)
    # Zero-token pregate (2026-07-10 rewire; see load_pregate_config docstring).
    # Gates ONLY plain cron fires — requested fires always run. Shadow mode
    # never skips (pregate exits 1) but logs the would-be decision for the
    # observation window before the config flip to enforce.
    if fire_reason == "cron" and not dry_run:
        pregate_cfg = load_pregate_config(schedules_path=schedules_path)
        if pregate_cfg["mode"] in ("shadow", "enforce"):
            pregate_skip = await asyncio.to_thread(
                _run_pregate,
                mode=pregate_cfg["mode"], window_hours=pregate_cfg["window_hours"],
            )
            if pregate_skip:  # only reachable in enforce mode
                LOG.info("pregate SKIP — no work worth the cold-load; slot consumed (prev_scheduled=%s)",
                         prev_fire.isoformat())
                # consume the slot like dry_run does, so we don't re-evaluate
                # every tick for the rest of the hour
                with state._locked_state(state_path) as (_fh, data):
                    data["last_fire_at"] = state._now()
                return {"action": "pregate_skip", "prev_fire": prev_fire.isoformat()}
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
    # PHASE-Z safety net (post-fire deterministic commit) — port of the legacy
    # cron_hourly_dispatch.sh PHASE-Z block. Runs ONCE per real fire regardless
    # of worker outcome — success / hang / failure AND the case where the worker
    # call itself raises (Codex review #2): a crashed worker is exactly when the
    # tree is most likely left dirty, so PHASE-Z lives in `finally`. The
    # dispatched agent's own PHASE Z is prompt-discretion (~90% reliable), so
    # this wrapper-level commit captures whatever it left. Run in a thread (git
    # subprocess) so the event loop stays responsive; a git hiccup is logged,
    # never crashes the tick (run_phase_z is itself no-raise, belt-and-suspenders
    # here too). If the worker raised, PHASE-Z still runs, then the exception
    # propagates to scheduler_loop's crash handler (which alerts).
    phase_z_outcome: dict | None = None
    try:
        # Block in thread so health_loop keeps running concurrently
        result = await asyncio.to_thread(
            worker.run_worker,
            prompt_text=prompt, schedule_id=SCHEDULE_ID,
            scheduled_for=prev_fire.isoformat(), fire_reason=fire_reason,
            log_path=log_path, state_path=state_path,
        )
        LOG.info("worker returned outcome=%s attempts=%d duration=%.1fs",
                 result.outcome, result.attempts, result.duration_s)
    finally:
        try:
            phase_z_outcome = await asyncio.to_thread(phase_z.run_phase_z, repo_root=repo_root)
            LOG.info("phase_z outcome=%s", phase_z_outcome)
        except Exception as exc:  # noqa: BLE001
            LOG.warning("phase_z safety-net failed (non-fatal): %s", exc)
    return {
        "action": "fired", "outcome": result.outcome,
        "attempts": result.attempts, "exit_code": result.exit_code,
        "phase_z": phase_z_outcome, "fire_reason": fire_reason,
    }
