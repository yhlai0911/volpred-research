"""hourly-dispatch supervisor daemon package.

Replaces `scripts/cron_hourly_dispatch.sh` + LaunchAgent StartCalendarInterval
with a long-lived Python supervisor that owns runtime env once at startup.

Architecture spec: docs/refactor_plan_hourly_dispatch.md §3.

Sub-modules:
  state     — JSON state file (`storage/ops/dispatch_state.json`) with fcntl lock
  worker    — subprocess.Popen wrapper with PGID + timeout + retry ladder
  health    — independent liveness check (asyncio loop + sync check_once)
  scheduler — asyncio tick → enqueue (croniter-driven)
  alerts    — send-alert shim with per-class dedup

Status: production daemon with a configurable multi-slot worker pool. Logical
fires retain stable job/slot IDs across retry and use cohort-drained PHASE-Z.
"""

__version__ = "0.5.0-multislot"
