"""hourly-dispatch supervisor daemon package.

Replaces `scripts/cron_hourly_dispatch.sh` + LaunchAgent StartCalendarInterval
with a long-lived Python supervisor that owns runtime env once at startup.

Architecture spec: docs/refactor_plan_hourly_dispatch.md §3.

Sub-modules:
  state    — JSON state file (`storage/ops/dispatch_state.json`) with fcntl lock
  worker   — subprocess.Popen wrapper with PGID + timeout (Deliverable 3)
  health   — independent liveness check (Deliverable 3)
  scheduler — asyncio tick → enqueue (Deliverable 3)
  alerts   — send-alert shim with dedup (Deliverable 3)

Status: Deliverable 2/8 — scaffold only. Worker / scheduler / health stubbed.
"""

__version__ = "0.1.0-scaffold"
