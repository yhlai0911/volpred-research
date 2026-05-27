"""Alert sink module — `send-alert` shim with dedup window.

Status: Deliverable 2/8 — STUB. Full implementation in Deliverable 3.

Contract sketch::

    def send_auth_alert(job: state.CurrentJob | None) -> None:
        if state.should_dedup_alert('auth_blocked', window_s=3600):
            return
        # subprocess uv run volpred ops send-alert --level critical ...
        state.mark_alert_sent('auth_blocked')

    def send_hang_alert(job: state.CurrentJob) -> None: ...
    def send_silent_death_alert(job: state.CurrentJob) -> None: ...
    def send_completion_failure(entry: dict) -> None: ...
    def send_supervisor_restart(prev_started: str | None) -> None: ...

Dedup windows (per alert class):
  auth_blocked         : 3600s  (once per hour max — until unblock)
  hang_killed          : 600s   (10min — protect against retry storms)
  silent_death         : 600s
  completion_failure   : 0s     (no dedup — every failure visible)
  supervisor_restart   : 60s    (suppress restart storms)
"""
from __future__ import annotations

# Deliverable 3 imports:
#   import subprocess
#   from . import state
