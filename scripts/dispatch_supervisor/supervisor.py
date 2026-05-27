"""Supervisor daemon entry point.

Status: Deliverable 2/8 — STUB main loop. Full asyncio composition in Deliverable 3.

Runs under launchd Aqua agent `com.volpred.dispatch-supervisor.plist`
(RunAtLoad=true, KeepAlive=true, NOT StartCalendarInterval).

Boot sequence (Deliverable 3 will fill in)::

    async def main() -> None:
        _set_runtime_env()              # ulimit -Sn 65536, PATH from ~/.zshrc, etc.
        state.mark_supervisor_started() # cleanup any orphan current_job
        schedules = _load_schedules()   # config/runtime_schedules.json
        await asyncio.gather(
            scheduler.scheduler_loop(schedules=schedules, state_path=state.STATE_PATH),
            health.health_loop(state_path=state.STATE_PATH),
        )

CLI::
    uv run python -m scripts.dispatch_supervisor.supervisor [--dry-run]

`--dry-run` is the shadow-phase mode (refactor_plan §4 phase 2): scheduler ticks
log "WOULD enqueue at HH:07" but no worker is spawned. Used to diff supervisor
decisions vs old shell wrapper for 7 days before cutover.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="dispatch-supervisor",
        description="hourly-dispatch supervisor daemon (Deliverable 2/8 scaffold).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Shadow mode: log decisions but do not spawn workers.",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Print scaffold version and exit.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.version:
        from . import __version__
        print(f"dispatch-supervisor {__version__}")
        return 0
    # Scaffold guard: prevent accidental production launch before Deliverable 3.
    sys.stderr.write(
        "[supervisor] SCAFFOLD-ONLY (Deliverable 2/8). "
        "Scheduler + worker + health are stubs; refusing to run main loop. "
        "Track refactor_plan_hourly_dispatch.md §8.\n"
    )
    return 78  # EX_CONFIG — refuse to start


if __name__ == "__main__":
    sys.exit(main())
