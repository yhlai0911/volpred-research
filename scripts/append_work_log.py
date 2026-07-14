#!/usr/bin/env python3
"""Append an entry to storage/work_log.json under an exclusive lock.

Why this exists (2026-07-13, hourly-02): work_log.json has a dozen writers
(dispatch, codex_loop, backfill-from-commits, pregate, dashboard...) and none of
them locked. Every one of them does a read-modify-write of the whole array, so
two overlapping writers silently drop the loser's entries. It happened to this
fire: two entries were appended, `git add`ed, and by the time the commit landed
the file had reverted to the previous writer's snapshot — a textbook lost update.

`next_tasks.json` has taken `fcntl.LOCK_EX` since the cross-session claim race
(memory `feedback_refill_check_saturation_and_running_hourly`); the same lesson
was simply never carried over to the work log. This is that carry-over: one
locked, atomic append path that every writer should route through.

Usage:
    uv run python scripts/append_work_log.py \
        --task-id dedup_gate_thin_signature_guard \
        --task-type platform_ops \
        --actor hourly-02 \
        --outcome completed \
        --commit efe9b285a \
        --summary-file /tmp/summary.md

`--summary-file` rather than `--summary` on purpose: summaries are Chinese prose
and routinely contain characters that get mangled passing through a shell.
"""

from __future__ import annotations

import argparse
import datetime
import fcntl
import json
import os
import stat
import sys
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from volpred.canonical_write import guard_canonical_write  # noqa: E402

WORK_LOG = ROOT / "storage" / "work_log.json"
LOCK_PATH = ROOT / "storage" / ".work_log.lock"

# mkstemp() creates 0600. Replacing the log with that temp file would silently
# tighten its mode on every append, so the previous mode is carried over (and a
# fresh log gets the ordinary 0644 the repo's other state files use).
DEFAULT_MODE = 0o644


def _clean_argv_text(text: str | None) -> str | None:
    """Strip lone surrogates that argv can carry in when the locale is not UTF-8.

    Python decodes argv with `surrogateescape`, so under a C/POSIX locale a
    non-ASCII `--summary` arrives as unpaired surrogates. Those serialize fine
    until `json.dumps` refuses them, and the append dies at the last step
    (2026-07-13, hourly-04: a Chinese summary raised UnicodeEncodeError on
    '\\udc9b'). `--summary-file` is read as real UTF-8 and never has this
    problem, which is why it exists -- this keeps the arg form honest too.
    """
    if text is None:
        return None
    return text.encode("utf-8", "replace").decode("utf-8")


def append_entries(
    entries: Sequence[dict],
    path: Path = WORK_LOG,
    lock_path: Path = LOCK_PATH,
    *,
    dedupe: Callable[[list[dict], list[dict]], list[dict]] | None = None,
) -> tuple[list[dict], int]:
    """Append `entries` to the work log under one exclusive lock.

    Returns `(appended_entries, total_entries)`.

    The lock is a separate file, not the log itself: we replace the log via
    rename (so a crashed writer can never leave a half-written array), and a
    lock held on the replaced inode would protect nothing.

    `dedupe(existing, candidates) -> to_append` runs INSIDE the lock, against the
    log as it actually is at write time. That placement is the whole point: a
    batch writer that de-duplicates against a snapshot it read before taking the
    lock will re-append anything a concurrent writer landed in between. Callers
    with an idempotency key (e.g. backfill's commit sha) must filter here, not
    before the call.
    """
    guard_canonical_write(path)
    guard_canonical_write(lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "w") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            try:
                log = json.loads(path.read_text(encoding="utf-8"))
                prev_mode = stat.S_IMODE(path.stat().st_mode)
            except FileNotFoundError:
                log = []
                prev_mode = DEFAULT_MODE
            if not isinstance(log, list):
                raise TypeError(f"{path} is not a JSON array (got {type(log).__name__})")

            to_append = list(entries)
            if dedupe is not None:
                to_append = dedupe(log, to_append)
            if not to_append:
                return [], len(log)
            log.extend(to_append)

            # Serialize fully before touching the real file: a writer that dies
            # mid-encode must not leave the canonical log truncated.
            payload = json.dumps(log, ensure_ascii=False, indent=2)
            fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".work_log.", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    fh.write(payload)
                    fh.flush()
                    os.fsync(fh.fileno())
                os.chmod(tmp, prev_mode)
                os.replace(tmp, path)
            except BaseException:
                Path(tmp).unlink(missing_ok=True)
                raise
            return to_append, len(log)
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def append_entry(entry: dict, path: Path = WORK_LOG, lock_path: Path = LOCK_PATH) -> int:
    """Append a single `entry` to the work log; returns the new entry count."""
    _, total = append_entries([entry], path=path, lock_path=lock_path)
    return total


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--task-id", required=True)
    ap.add_argument("--task-type", required=True)
    ap.add_argument("--actor", required=True, help="e.g. hourly-02 — required for attribution")
    ap.add_argument("--outcome", default="completed")
    ap.add_argument("--commit", default=None)
    ap.add_argument("--owner", default=None, help="defaults to --actor")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--summary", help="ASCII-safe summaries only; prefer --summary-file")
    src.add_argument("--summary-file", help="read the summary from a file (UTF-8)")
    args = ap.parse_args()

    summary = (
        Path(args.summary_file).read_text(encoding="utf-8").strip()
        if args.summary_file
        else _clean_argv_text(args.summary)
    )
    entry = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc)
        .astimezone()
        .isoformat(timespec="seconds"),
        "task_type": args.task_type,
        "task_id": args.task_id,
        "outcome": args.outcome,
        "actor": args.actor,
        "owner": args.owner or args.actor,
        "commit": args.commit,
        "summary": summary,
    }
    total = append_entry(entry)
    print(f"appended {args.task_id} (actor={args.actor}); work_log now has {total} entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
