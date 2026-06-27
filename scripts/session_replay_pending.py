#!/usr/bin/env python3
"""Session startup: replay pending_sessions.json + mark replayed_at.

For high-frequency session crons (continue_task, question_research, etc.) the
"replay" is implicit — the active session's in-process cron will fire on the
next tick. This script's job is to update `replayed_at` timestamps in
`storage/ops/pending_sessions.json` so the piggy-back recorder
(`scripts/run_due_jobs.py::_write_pending_sessions`) stops re-recording the
same offline window every hour.

Per `scripts/session_startup.md §2.0`:
- 跳過 replay if recorded_count == 0 OR replayed_at >= recorded_at (already current)
- For high-frequency crons "合併只跑 1 次" — this script effectively performs that merge
- For low-frequency crons (e.g. ndc-indicator-maintain monthly), main thread should
  still manually run the corresponding maintain command before this script

Usage:
  uv run python scripts/session_replay_pending.py [--dry-run]
  -> reports {recorded_count_total, jobs_marked, jobs_skipped}
  -> exits 0 if anything updated, 0 if nothing to do (no error)
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
PENDING_PATH = PROJECT / "storage" / "ops" / "pending_sessions.json"


def _warn_session_replay(message: str, exc: Exception | None = None) -> None:
    suffix = f" error={type(exc).__name__}: {exc}" if exc is not None else ""
    print(f"[session-replay] WARN {message} path={PENDING_PATH}{suffix}", file=sys.stderr)


def _warn_session_replay_error(message: str, exc: Exception | None = None) -> None:
    suffix = f" error={type(exc).__name__}: {exc}" if exc is not None else ""
    print(f"[session-replay] ERROR {message} path={PENDING_PATH}{suffix}", file=sys.stderr)


def _load_pending_state() -> dict | None:
    try:
        state = json.loads(PENDING_PATH.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        _warn_session_replay_error("pending_sessions read failed; cannot mark replayed", exc)
        return None
    if not isinstance(state, dict):
        _warn_session_replay_error(
            f"pending_sessions schema invalid; expected object got {type(state).__name__}"
        )
        return None
    return state


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Show what would change without writing")
    args = parser.parse_args()

    if not PENDING_PATH.exists():
        print(f"[session-replay] pending_sessions.json not found at {PENDING_PATH} — nothing to do.")
        return 0

    state = _load_pending_state()
    if state is None:
        return 1
    jobs = state.get("jobs", {}) or {}
    if not isinstance(jobs, dict):
        _warn_session_replay_error(
            f"pending_sessions jobs schema invalid; expected object got {type(jobs).__name__}"
        )
        return 1
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")

    marked: list[str] = []
    skipped: list[str] = []
    invalid_recorded_count_job_ids: set[str] = set()

    for job_id, job in jobs.items():
        if not isinstance(job, dict):
            _warn_session_replay(
                f"pending_sessions job schema invalid; skipping job_id={job_id} type={type(job).__name__}"
            )
            skipped.append(f"{job_id}(invalid_schema)")
            continue
        try:
            recorded_count = int(job.get("recorded_count", 0))
        except (TypeError, ValueError) as exc:
            _warn_session_replay(f"pending_sessions recorded_count invalid; skipping job_id={job_id}", exc)
            skipped.append(f"{job_id}(invalid_recorded_count)")
            invalid_recorded_count_job_ids.add(str(job_id))
            continue
        recorded_at = job.get("recorded_at")
        replayed_at = job.get("replayed_at")

        if recorded_count == 0:
            skipped.append(f"{job_id}(never_fired)")
            continue

        if replayed_at and recorded_at and replayed_at >= recorded_at:
            skipped.append(f"{job_id}(already_current)")
            continue

        if not args.dry_run:
            job["replayed_at"] = now_iso
        marked.append(job_id)

    if not args.dry_run and marked:
        state["last_replay_at"] = now_iso
        PENDING_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n")

    total_recorded_count = 0
    for job_id, job in jobs.items():
        if isinstance(job, dict):
            if str(job_id) in invalid_recorded_count_job_ids:
                continue
            try:
                total_recorded_count += int(job.get("recorded_count", 0))
            except (TypeError, ValueError) as exc:
                _warn_session_replay(
                    f"pending_sessions recorded_count invalid while summing total; "
                    f"excluding job_id={job_id}",
                    exc,
                )
                continue
    print(f"[session-replay] mode={'DRY-RUN' if args.dry_run else 'WRITE'}")
    print(f"  Total jobs in pending_sessions: {len(jobs)}")
    print(f"  Total recorded_count (累積 missed fire): {total_recorded_count}")
    print(f"  Marked replayed: {len(marked)} → {marked}")
    print(f"  Skipped (already current / never fired): {len(skipped)}")
    if marked and not args.dry_run:
        print(f"  Wrote replayed_at = {now_iso}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
