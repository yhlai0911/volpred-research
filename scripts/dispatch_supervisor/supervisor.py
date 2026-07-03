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
    """Codex review §10 #3 fix — identity-verified orphan cleanup on boot.

    `state.mark_supervisor_started()` no longer silently discards a stale
    `current_job` (see its docstring). This claims it, and — ONLY if the pid
    still exists AND its `ps`-derived start-time fingerprint still matches
    what was recorded at spawn (i.e. it is definitely the same process, not a
    reused pid) — force-kills its process group and records the outcome.
    Runs before `send_supervisor_restart()` so the restart alert body would
    reflect it if we later want to fold this in; kept as its own alert for
    now since it's a materially different event (an actual orphan found).
    """
    # NOTE: read `state.STATE_PATH` here (call-time attribute lookup) rather
    # than relying on downstream functions' own `path=STATE_PATH` defaults —
    # those defaults bind at function-DEFINITION time, so monkeypatching
    # `state.STATE_PATH` in a test would silently not apply to them.
    state_path = state.STATE_PATH
    orphan = state.claim_and_clear_current_job(state_path)
    if orphan is None or orphan.get("pid") is None:
        return
    pid = int(orphan["pid"])
    started_wall = orphan.get("started_wall")
    identity_ok = procutil.pid_identity_matches(pid, started_wall)
    if identity_ok:
        pgid = int(orphan.get("pgid") or pid)
        logging.warning(
            "restart: orphan job pid=%d pgid=%d still alive (identity-verified) — killing", pid, pgid,
        )
        worker._kill_pgid(pgid)
        exit_code, outcome = -9, "killed_supervisor_restart"
    else:
        logging.info("restart: stale current_job pid=%d already gone / pid reused — no kill needed", pid)
        exit_code, outcome = -1, "orphan_gone_or_reused"
    state.append_completion_entry(
        orphan, exit_code=exit_code, outcome=outcome,
        final_model=str(orphan.get("model", "?")), path=state_path,
    )
    alerts.send_orphan_restart_alert(job=orphan, killed=identity_ok, state_path=state_path)


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
