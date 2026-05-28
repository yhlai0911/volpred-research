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

Status: Deliverable 4/8 — modules integrated + regression tests + ops CLI.
Remaining: Codex review gate (6), shadow run (5), cutover, deprecate.
"""

__version__ = "0.3.0-d4"
