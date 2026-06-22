"""Auto-mark pending_sessions.json job replayed when the corresponding maintain CLI runs.

Why this exists:
- session_crons (in-process Claude Code CronCreate) fire prompts to the live session
  every interval; the main thread runs a `*_maintain` CLI to handle each fire.
- Independently, the hourly piggy-back recorder
  (`scripts/run_due_jobs.py::_write_pending_sessions`) inspects `cron_last_run.json`
  + `pending_sessions.json` to detect "session offline" missed fires and append to
  `recorded_count`.
- Without coordination, the piggy-back recorder cannot tell whether session was
  online and processed the fire — it bumps `recorded_count` regardless. Result:
  even an active session accumulates 1+ pending entries per cron tick, leading to
  the 2026-04-27 "110 累積 missed fire" incident.

Fix: every `*_maintain` CLI entry calls `mark_self_replayed(job_id)` immediately
on entry. This writes `replayed_at = now()` for that job into pending_sessions.json.
The piggy-back recorder's `_job_is_due()` check then sees a fresh `replayed_at`
and skips recording, because no cron fire window has elapsed since.

Net effect: session-online cron ticks no longer accumulate `recorded_count`;
session-offline ticks (the genuine missed-fire case) still do.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# src/volpred/ops/pending_replay.py → repo root is parents[3]
PROJECT = Path(__file__).resolve().parents[3]
PENDING_PATH = PROJECT / "storage" / "ops" / "pending_sessions.json"


def _warn_pending_replay(message: str, exc: Exception) -> None:
    print(
        f"[pending_replay] WARN {message} "
        f"path={PENDING_PATH} error={type(exc).__name__}: {exc}",
        file=sys.stderr,
    )


def mark_self_replayed(job_id: str) -> bool:
    """Mark `job_id` in pending_sessions.json as replayed = now (UTC).

    Silent no-op if pending_sessions.json missing or unreadable; never raises
    so a transient FS issue cannot break the maintain CLI itself.

    Args:
        job_id: session_crons.items[].id (e.g. "continue_task", "git_sync")

    Returns:
        True if pending_sessions.json was updated, False otherwise.
    """
    if not PENDING_PATH.exists():
        return False
    try:
        state = json.loads(PENDING_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        _warn_pending_replay("pending_sessions read failed; replay marker not written", exc)
        return False

    jobs = state.get("jobs")
    if not isinstance(jobs, dict):
        jobs = {}
        state["jobs"] = jobs

    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")

    job_entry = jobs.get(job_id)
    if job_entry is None:
        # First-ever fire seen by this CLI: create minimal entry
        # (piggy-back recorder later fills cron/prompt/description if it ever fires offline)
        jobs[job_id] = {
            "cron": "",
            "prompt": "",
            "description": "auto-created by *_maintain CLI on first session-online fire",
            "recorded_at": None,
            "replayed_at": now_iso,
            "recorded_count": 0,
        }
    else:
        job_entry["replayed_at"] = now_iso

    state["last_replay_at"] = now_iso

    try:
        PENDING_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n")
        return True
    except OSError as exc:
        _warn_pending_replay("pending_sessions write failed; replay marker not written", exc)
        return False
