#!/usr/bin/env python3
"""Record a cron job's actual last-successful-run time in `cron_last_run.json`.

2026-07-10. Before this existed, the ONLY writer of `storage/ops/cron_last_run.json`
was `scripts/run_due_jobs.py`, which stamps a marker for jobs it fires. But jobs
flagged `piggy_back_skip: true` in `config/runtime_schedules.json` are, by design,
never fired by run_due_jobs — their LaunchAgent owns them, precisely so the
piggy-back cannot double-fire them (the 2026-05-29 collect_us double-fetch
incident). Consequence: those five jobs ran on schedule while their marker stayed
frozen at whatever day the flag was flipped on:

    collect_tw_data       frozen 2026-05-28   (ran today)
    collect_us_data       frozen 2026-05-29   (ran today)
    market_calendar_sync  frozen 2026-05-25   (weekly)
    memory_health_daily   frozen 2026-05-28   (ran today 05:30)
    indicator_arena_daily NEVER written       (piggy_back_skip since birth)

The freshness monitor was thus reading a dead marker for a live job: it could
never detect a real outage of these five, and the one signal it did emit
("memory_health_daily 42 days stale") was a false alarm about a healthy job.

Fix: the wrapper records its own run. `scripts/cron_lib.sh::cron_emit_exit` calls
this on exit 0, so every wrapper that sources cron_lib self-reports regardless of
who invoked it (launchd, host cron, or the run_due_jobs piggy-back).

## The job id comes from the wrapper's PATH, never from a passed-in name

`cron_emit_exit`'s first argument is a free-text log label, and a 2026-07-10 sweep
found 8 wrappers whose label already differs from their config id
(`market_calendar_sync` logs as `market_cal`, `supabase_sync_drain` as
`drain_failed_syncs`, …). Keying the marker on that label would silently write to
a key nobody reads. So the wrapper passes `$0` and we reverse-look-up the id in
`config/runtime_schedules.json` — the single source of truth for
`wrapper_script → id`. A wrapper absent from config gets a loud WARN, never a
guessed key.

Semantics match run_due_jobs exactly: **only a successful run (exit 0) updates the
marker.** A job that runs but always fails must go stale — that is the outage the
monitor exists to surface.

Concurrency: several wrappers fire in the same minute (05:30, 08:00 …) while
run_due_jobs may be mid-scan. Every writer takes an exclusive `flock`, does a
read-modify-write of only its own key, then `os.replace` (atomic within a
filesystem). A blind whole-dict write — which is what run_due_jobs used to do —
drops any marker another writer set after it loaded its copy.

Fail-open: a marker is bookkeeping, never a reason to fail the job it describes.
Every failure path logs (no silent fallback) and exits 0.

Usage:
    python3 scripts/cron_mark_last_run.py --wrapper "$0"        # from a wrapper
    python3 scripts/cron_mark_last_run.py --job-id collect_us_data
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from volpred.canonical_write import guard_canonical_write  # noqa: E402

# Overridable so tests can exercise the real shell helper end-to-end without
# stamping the live marker file (same convention as VOLPRED_HOME_DIR elsewhere).
LAST_RUN_PATH = Path(
    os.environ.get("VOLPRED_CRON_MARKER_PATH", str(ROOT / "storage" / "ops" / "cron_last_run.json"))
)
SCHEDULES_PATH = ROOT / "config" / "runtime_schedules.json"


def _log(msg: str) -> None:
    print(f"[cron-mark-last-run] {msg}", flush=True)


def _warn(msg: str) -> None:
    """Observable trace for the fail-open paths below.

    They already printed via `_log`, but audit_silent_fallbacks resolves call
    *names*, not one level of indirection, so a `_log(...)` before `return 0`
    reads as a silent fallback to the gate. `_warn*` is the auditor's sanctioned
    name for a module-local helper. This standalone marker-stamper imports only
    the stdlib-only canonical-write guard from `src/`; shell wrappers still
    invoke it with plain system Python.
    """
    _log(f"WARN {msg}")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def job_id_for_wrapper(wrapper: str | Path, *, schedules_path: Path = SCHEDULES_PATH) -> str:
    """Reverse-look-up a config job id from a wrapper script path.

    Matches on basename: `wrapper_script` in config is an absolute
    `~/.volpred/bin/...` path, while a wrapper invoked through a symlink or a
    relative path may present differently. A 2026-07-10 sweep confirmed every
    `wrapper_script` basename is unique, so this is unambiguous — and if that ever
    stops being true, this raises rather than picking one.
    """
    target = Path(wrapper).name
    data = json.loads(schedules_path.read_text(encoding="utf-8"))
    items = (data.get("system_crontab") or {}).get("items") or []
    matches = [
        item["id"] for item in items
        if isinstance(item, dict) and item.get("id") and item.get("wrapper_script")
        and Path(item["wrapper_script"]).name == target
    ]
    if not matches:
        raise LookupError(f"no system_crontab item has wrapper_script basename {target!r}")
    if len(matches) > 1:
        raise LookupError(f"wrapper basename {target!r} maps to multiple ids: {matches}")
    return matches[0]


def _read(path: Path) -> dict:
    """Load the marker map. A corrupt file must NOT silently become {} — the very
    next write would then erase every other job's marker."""
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))  # ValueError → caller handles
    if not isinstance(data, dict):
        raise TypeError(f"expected dict, got {type(data).__name__}")
    return data


def _atomic_write(path: Path, data: dict) -> None:
    guard_canonical_write(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)  # atomic within the filesystem
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


# Schema note stamped into the file itself (WS-D1 2026-07-20): this marker map is
# NOT a universal liveness source. It only records exit-0 markers from run_due_jobs
# piggyback fires and from wrappers sourcing cron_lib.sh. A launchd-direct job
# (`host_crontab_managed: false`) without cron_lib self-report never refreshes here
# (daily_update froze at 2026-04-25 for ~3 months while running healthy). Monitors
# must resolve liveness via `volpred.ops.schedules.job_liveness()`, never from this
# file alone. Readers skip `_`-prefixed keys.
_META_KEY = "_meta"
_META = {
    "scope": "piggyback-and-cron_lib-self-report-only",
    "note": (
        "exit-0 success markers from run_due_jobs piggyback fires + cron_lib.sh "
        "self-reporting wrappers. NOT universal liveness: host_crontab_managed=false "
        "jobs without self-report never refresh here. Resolve liveness via "
        "volpred.ops.schedules.job_liveness()."
    ),
    "writers": ["scripts/run_due_jobs.py", "scripts/cron_mark_last_run.py"],
}


def merge_last_run(updates: dict[str, str], *, path: Path = LAST_RUN_PATH) -> dict:
    """Merge `updates` into the marker map under an exclusive lock.

    Read-modify-write, not overwrite: keys this caller does not name keep whatever
    another writer set. Returns the merged map. Raises on I/O or JSON errors;
    callers that must not fail (cron wrappers) catch and log. Every write also
    (re)stamps the `_meta` scope record so the file self-documents its coverage.
    """
    if not updates:
        return _read(path)
    guard_canonical_write(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(path.name + ".lock")
    with open(lock_path, "w", encoding="utf-8") as lock_fh:
        fcntl.flock(lock_fh, fcntl.LOCK_EX)
        try:
            data = _read(path)
            data.update(updates)
            data[_META_KEY] = _META
            _atomic_write(path, data)
            return data
        finally:
            fcntl.flock(lock_fh, fcntl.LOCK_UN)


def mark_last_run(job_id: str, *, iso: str | None = None, path: Path = LAST_RUN_PATH) -> str:
    """Stamp one job's last-successful-run time. Returns the timestamp written."""
    ts = iso or _now_iso()
    merge_last_run({job_id: ts}, path=path)
    return ts


def main() -> int:
    ap = argparse.ArgumentParser(description="Record a cron job's last successful run.")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--wrapper", help="path of the calling wrapper ($0); id is looked up in config")
    src.add_argument("--job-id", help="explicit id from system_crontab.items")
    ap.add_argument("--iso", help="timestamp to record (default: now, UTC)")
    ap.add_argument("--path", type=Path, default=LAST_RUN_PATH)
    ap.add_argument("--schedules", type=Path, default=SCHEDULES_PATH)
    args = ap.parse_args()

    try:
        job_id = args.job_id or job_id_for_wrapper(args.wrapper, schedules_path=args.schedules)
    except Exception as exc:  # noqa: BLE001 — bookkeeping must never fail the job
        _warn(f"cannot resolve job id from wrapper={args.wrapper!r}: "
              f"{type(exc).__name__}: {exc} — marker NOT updated")
        return 0

    try:
        ts = mark_last_run(job_id, iso=args.iso, path=args.path)
    except Exception as exc:  # noqa: BLE001
        _warn(f"could not record {job_id}: {type(exc).__name__}: {exc}")
        return 0
    _log(f"{job_id} last_run={ts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
