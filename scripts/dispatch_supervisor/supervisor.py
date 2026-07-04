"""Supervisor daemon entry point.

Runs under launchd Aqua agent `com.volpred.dispatch-supervisor.plist`
(RunAtLoad=true, KeepAlive=true, NOT StartCalendarInterval).

Boot sequence::

    1. _set_runtime_env()                    — ulimit -Sn 65536; source-like env hygiene
    2. state.mark_supervisor_started()        — heartbeat timestamps only
    3. _handle_restart_orphan()               — identity-verified kill of any job
                                                 left `current_job` by a crashed
                                                 prior instance (Codex review §10 #3)
    4. alerts.send_supervisor_restart()       — info-level breadcrumb (dedup 60s)
    5. asyncio.gather(scheduler_loop, health_loop) — wrapped so an uncaught crash
                                                 here alerts before launchd restarts us
                                                 (Codex review §10 #7)

CLI::
    uv run python -m scripts.dispatch_supervisor.supervisor          # production
    uv run python -m scripts.dispatch_supervisor.supervisor --dry-run # shadow phase
    uv run python -m scripts.dispatch_supervisor.supervisor --version
    uv run python -m scripts.dispatch_supervisor.supervisor --once    # single tick for smoke

`--once` runs a single scheduler tick (no async loop) for smoke testing under
cron. Health-loop is skipped in --once mode.

Deliverable 5/8 — all 7 Codex review must-fix items landed (2026-07-04).
Deliverables 6-8 cover shadow run, cutover, deprecate, retro.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import resource
import sys
import traceback
from pathlib import Path

from . import alerts, health, procutil, scheduler, state, worker, __version__

ROOT = Path(__file__).resolve().parents[2]
LOG_DIR = Path(os.environ.get("VOLPRED_HOME_DIR", str(Path.home() / ".volpred"))) / "logs"
SUPERVISOR_LOG = LOG_DIR / "dispatch_supervisor.log"


def _setup_logging(level: int = logging.INFO) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(SUPERVISOR_LOG, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)
    # also echo to stderr so launchd StandardErrorPath captures
    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    root.addHandler(sh)


def _set_runtime_env() -> None:
    """Apply env hygiene that the legacy shell wrapper used to do per-fire.

    Set ONCE at supervisor boot so all worker children inherit:
      - RLIMIT_NOFILE soft to 65536 (strike 3 mitigation)
    """
    try:
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        target = 65536
        if soft < target:
            new_soft = min(target, hard if hard > 0 else target)
            resource.setrlimit(resource.RLIMIT_NOFILE, (new_soft, hard))
            logging.info("RLIMIT_NOFILE %d -> %d (hard=%s)", soft, new_soft, hard)
    except (ValueError, OSError) as exc:
        logging.warning("setrlimit NOFILE failed: %s", exc)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="dispatch-supervisor")
    parser.add_argument("--dry-run", action="store_true",
                        help="Shadow mode: log decisions but do not spawn workers.")
    parser.add_argument("--once", action="store_true",
                        help="Run a single scheduler tick (no async loop) and exit.")
    parser.add_argument("--version", action="store_true")
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args(argv)


def _handle_restart_orphan() -> None:
    """Identity-verified orphan cleanup on boot (Codex review §10 #3, #2, #4
    fixes — 2026-06-15 original + 2026-07-04 gate-blocking follow-ups).

    `state.mark_supervisor_started()` no longer silently discards a stale
    `current_job` (see its docstring). This flags it via
    `mark_restart_orphan_pending()` (NOT cleared yet — see that function's
    docstring for why: a second crash mid-cleanup must be able to retry the
    same orphan, not lose it), and — ONLY if the pid still exists AND its
    `ps`-derived start-time fingerprint still matches what was recorded at
    spawn (`procutil.IDENTITY_MATCH`; a `ps` failure yielding
    `IDENTITY_UNVERIFIED` does NOT count — do not kill an unverified target)
    — force-kills its process group. `finalize_restart_orphan_cleanup()` is
    the last call in every branch, only after the outcome is recorded, so a
    crash before that point leaves the slot intact for the next restart to
    retry. Runs before `send_supervisor_restart()` so the restart alert body
    would reflect it if we later want to fold this in; kept as its own alert
    for now since it's a materially different event (an actual orphan found).
    """
    # NOTE: read `state.STATE_PATH` here (call-time attribute lookup) rather
    # than relying on downstream functions' own `path=STATE_PATH` defaults —
    # those defaults bind at function-DEFINITION time, so monkeypatching
    # `state.STATE_PATH` in a test would silently not apply to them.
    state_path = state.STATE_PATH
    orphan = state.mark_restart_orphan_pending(state_path)
    if orphan is None:
        return
    if orphan.get("cleanup_recorded"):
        # Codex review round-2 low finding (2026-07-04): a prior restart's
        # cleanup already appended this orphan's completion entry (the
        # `cleanup_recorded` flag is set atomically WITH that append — see
        # state.append_completion_entry) but crashed before finalize. Do not
        # append a duplicate entry; just finish the deferred finalize.
        logging.info(
            "restart: orphan pid=%s cleanup already recorded by a prior attempt — finalizing only",
            orphan.get("pid"),
        )
        # Codex review round-3 medium #1 (2026-07-04): the crash-before-alert
        # gap could suppress the ONLY runbook prompt for an orphan we did NOT
        # kill and cannot verify is dead. Re-emit the orphan alert here (its
        # 60s dedup prevents spam on a fast retry, while a genuine restart
        # minutes later re-surfaces a still-alive unverified orphan). Only
        # re-alert for the not-killed outcomes — a killed orphan is resolved.
        recorded_outcome = str(orphan.get("cleanup_outcome") or "")
        if recorded_outcome and recorded_outcome != "killed_supervisor_restart":
            alerts.send_orphan_restart_alert(
                job=orphan, killed=False, outcome=recorded_outcome, state_path=state_path,
            )
        state.finalize_restart_orphan_cleanup(state_path)
        return
    if orphan.get("pid") is None:
        # Codex review fix #2 (2026-07-04): supervisor crashed between
        # reserve_fire() (writes the pid=None placeholder) and worker.py's
        # attach_process() call, which now runs immediately after Popen()
        # returns (narrowed to just that syscall — see worker.py). We cannot
        # identify or kill a child we were never told the pid of; the best
        # we can do is stop this slot from being wedged forever and make the
        # gap loudly visible instead of silently swallowing it.
        logging.warning(
            "restart: abandoned pid=None reservation (schedule_id=%s attempt=%s) — "
            "clearing stuck slot; if Popen had already succeeded before the crash, "
            "that child is now untracked and will only be found by max-age/health checks "
            "once/if it (re)acquires a pid we happen to observe",
            orphan.get("schedule_id"), orphan.get("attempt"),
        )
        state.append_completion_entry(
            orphan, exit_code=-1, outcome="reservation_abandoned_no_pid",
            final_model=str(orphan.get("model", "?")), path=state_path,
            mark_cleanup_recorded=True,
        )
        alerts.send_orphan_restart_alert(
            job=orphan, killed=False, outcome="reservation_abandoned_no_pid", state_path=state_path,
        )
        state.finalize_restart_orphan_cleanup(state_path)
        return
    pid = int(orphan["pid"])
    started_wall = orphan.get("started_wall")
    identity = procutil.check_identity(pid, started_wall)
    if identity == procutil.IDENTITY_MATCH:
        pgid = int(orphan.get("pgid") or pid)
        logging.warning(
            "restart: orphan job pid=%d pgid=%d still alive (identity-verified) — killing", pid, pgid,
        )
        worker._kill_pgid(pgid)
        exit_code, outcome, killed = -9, "killed_supervisor_restart", True
    elif identity == procutil.IDENTITY_UNVERIFIED:
        # Codex review fix #4: no fingerprint was recorded (attach raced
        # ahead of a slow/failed `ps` call). Do NOT kill an unverified
        # target — record distinctly so ops can check by hand instead of
        # trusting a bare "pid is alive" as proof it's ours.
        logging.warning(
            "restart: orphan job pid=%d alive but NO identity fingerprint recorded — "
            "NOT killing (unverified target), recording for manual check", pid,
        )
        exit_code, outcome, killed = -1, "orphan_unverified_not_killed", False
    else:
        logging.info("restart: stale current_job pid=%d already gone / pid reused — no kill needed", pid)
        exit_code, outcome, killed = -1, "orphan_gone_or_reused", False
    state.append_completion_entry(
        orphan, exit_code=exit_code, outcome=outcome,
        final_model=str(orphan.get("model", "?")), path=state_path,
        mark_cleanup_recorded=True,
    )
    alerts.send_orphan_restart_alert(job=orphan, killed=killed, outcome=outcome, state_path=state_path)
    state.finalize_restart_orphan_cleanup(state_path)


async def _run_async(*, dry_run: bool) -> int:
    await asyncio.gather(
        scheduler.scheduler_loop(dry_run=dry_run),
        health.health_loop(),
    )
    return 0


async def _run_once_async(*, dry_run: bool) -> int:
    cron_expr = scheduler.load_cron_expr()
    decision = await scheduler._tick_once(
        state_path=state.STATE_PATH,
        cron_expr=cron_expr,
        prompt_path=scheduler.DEFAULT_PROMPT_PATH,
        log_path=scheduler.DEFAULT_LOG_PATH,
        dry_run=dry_run,
    )
    logging.info("--once decision=%s", decision)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.version:
        print(f"dispatch-supervisor {__version__}")
        return 0
    _setup_logging(getattr(logging, args.log_level.upper(), logging.INFO))
    _set_runtime_env()
    prev_started = state.read_state().get("supervisor_started_at")
    state.mark_supervisor_started()
    _handle_restart_orphan()
    alerts.send_supervisor_restart(prev_started=prev_started)
    try:
        if args.once:
            return asyncio.run(_run_once_async(dry_run=args.dry_run))
        return asyncio.run(_run_async(dry_run=args.dry_run))
    except KeyboardInterrupt:
        logging.info("supervisor interrupted")
        return 130
    except Exception as exc:  # noqa: BLE001
        # Codex review §10 #7 fix: an uncaught exception escaping
        # asyncio.gather() used to just crash to stderr — launchd's
        # KeepAlive restarts the process (send_supervisor_restart covers
        # the NEXT boot) but nothing alerts on THIS crash's traceback.
        logging.exception("supervisor top-level crash: %s", exc)
        alerts.send_loop_crash("supervisor_main", traceback.format_exc())
        raise


if __name__ == "__main__":
    sys.exit(main())
