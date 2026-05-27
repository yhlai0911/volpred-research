"""Worker module — subprocess.Popen wrapper with PGID isolation + timeout.

Status: Deliverable 2/8 — STUB. Full implementation in Deliverable 3 (per
docs/refactor_plan_hourly_dispatch.md §8).

Contract sketch (for Deliverable 3 implementation)::

    @dataclass
    class WorkerResult:
        exit_code: int
        outcome: str             # success | failure | killed_timeout
        final_model: str         # opus / sonnet after retry-with-fallback
        duration_s: float
        log_tail: str            # last 50 lines of worker log (for alert payload)

    def run_worker(
        *, prompt_path: Path, model: str, timeout_s: int,
        log_path: Path, state_path: Path = state.STATE_PATH,
    ) -> WorkerResult: ...

Must:
- start_new_session=True (clean PGID for SIGKILL group)
- Popen.wait(timeout=timeout_s) — no perl alarm
- on timeout: os.killpg(pgid, SIGTERM) → 10s grace → SIGKILL
- record begin_fire(...) BEFORE wait; record_completion(...) AFTER wait
- ulimit set once at supervisor boot, inherited by Popen children

Retry-with-fallback ladder (per plan §3 retry policy):
    attempt 1: opus    → if exit≠0 and stderr~/529/ : sleep 90s, attempt 2
    attempt 2: opus    → if exit≠0 and stderr~/529/ : sleep 90s, attempt 3
    attempt 3: sonnet  → final attempt; record outcome
    auth-class error : NO retry, set_auth_blocked(True), send auth alert
"""
from __future__ import annotations

# Imports kept minimal in scaffold; Deliverable 3 will add:
#   import subprocess, signal, os, re, time
#   from . import state, alerts
