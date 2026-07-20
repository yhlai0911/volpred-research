#!/usr/bin/env python3
"""Drain (retry) the publisher projection dead-letter queues.

Two queues, one loop (WS-C4): `.failed_supabase_syncs.json` (Supabase rows)
and `.failed_mirror_syncs.json` (Mirror PUTs). The script name predates the
Mirror queue; the cron id (`supabase_sync_drain`) and entrypoint are left
alone so the schedule/ownership wiring stays put.

Root cause (2026-06-02): `.failed_supabase_syncs.json` was a WRITE-ONLY
dead-letter queue. publisher.py / ops/content.py / daily_update.py append a
mile_id whenever a Supabase sync fails (often a transient network/Supabase
blip); health.py/alerts.py only COUNT it (WARN when >=2). Nothing ever retried
or drained it, so a transient failure became a permanent stale-divergence entry
that accumulated and required manual `sync_article` intervention every time.

This script is the missing consumer. It re-syncs each queued article and
removes the ones that now succeed, leaving only genuinely-persistent failures
(which keep triggering the existing WARN alert -> human escalation).

Wired to a cron (config/runtime_schedules.json: supabase_sync_drain) so transient
failures self-heal without manual action.

Race tolerance: writers append without a lock. We snapshot the queue, attempt
syncs, then RE-READ the queue before writing back and only remove ids we
successfully synced (or whose article no longer exists in feed) — any ids
appended concurrently during the drain are preserved.

Usage:
  uv run python scripts/drain_failed_supabase_syncs.py            # drain
  uv run python scripts/drain_failed_supabase_syncs.py --dry-run  # report only
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from volpred.canonical_write import guard_canonical_write  # noqa: E402
from volpred.ops.scheduled_writer_commit import (  # noqa: E402
    commit_owned_outputs,
    dirty_paths_before_write,
    writable_output_paths,
)

QUEUE_PATH = ROOT / "storage" / ".failed_supabase_syncs.json"
MIRROR_QUEUE_PATH = ROOT / "storage" / ".failed_mirror_syncs.json"
FEED_PATH = ROOT / "storage" / "reports" / "feed.json"


def _warn_drain(message: str, path: Path, exc: Exception | None = None) -> None:
    suffix = f": {type(exc).__name__}: {exc}" if exc is not None else ""
    print(f"[drain] WARN {message}: path={path}{suffix}")


def _load_list(path: Path) -> list:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        _warn_drain("queue JSON is not a list; treating as empty", path)
        return []
    except Exception as exc:
        _warn_drain("queue JSON read failed; treating as empty", path, exc)
        return []


def _resync_supabase(art: dict) -> bool:
    from supabase_sync import sync_article  # noqa: E402

    return bool(sync_article(art, storage_dir="storage"))


def _resync_mirror(art: dict) -> bool:
    """Re-PUT one article to the Mirror.

    Calls the low-level PUT rather than ``Publisher._mirror_article`` on
    purpose: the article id is already in the queue we are draining, and the
    write-back below is what decides whether it stays. Going through the
    dead-lettering wrapper would re-append it mid-drain.
    """
    from volpred.publisher.publisher import Publisher  # noqa: E402

    publisher = Publisher(storage_dir="storage")
    return bool(publisher._sync_report_to_remote(str(art.get("id")), art))


def _mirror_enabled() -> bool:
    from volpred.publisher.publisher import Publisher  # noqa: E402

    return bool(Publisher(storage_dir="storage")._mirror_enabled())


def _drain_queue(spec: dict, by_id: dict, *, dry_run: bool) -> dict:
    """Retry every id in one queue; return a per-queue summary.

    Does not write anything back — main() batches the write-back so both
    queues land under a single ownership check and commit.
    """
    label, path, resync = spec["label"], spec["path"], spec["resync"]
    queue = _load_list(path)
    summary: dict = {
        "queue_before": len(queue),
        "synced": [],
        "dropped_not_in_feed": [],
        "still_failing": [],
        "skipped": None,
    }
    if not queue:
        return summary
    if spec.get("precondition") and not spec["precondition"]():
        # e.g. Mirror disabled (no REMOTE_URL / kill switch). Nothing can be
        # retried, so leave the queue intact rather than reporting fake failures.
        summary["skipped"] = spec.get("skip_reason", "precondition not met")
        print(f"[drain] {label}: {summary['skipped']} — queue left intact ({len(queue)} pending)")
        return summary

    for mile_id in list(dict.fromkeys(queue)):  # dedup, preserve order
        art = by_id.get(mile_id)
        if art is None:
            # article no longer in feed (deleted/retracted) — can't sync; drop it
            summary["dropped_not_in_feed"].append(mile_id)
            continue
        if dry_run:
            summary["still_failing"].append(mile_id)  # would attempt; report as pending
            continue
        try:
            ok = bool(resync(art))
        except Exception as e:  # noqa: BLE001
            print(f"[drain] {label} {mile_id} sync exception: {type(e).__name__}: {str(e)[:200]}")
            ok = False
        (summary["synced"] if ok else summary["still_failing"]).append(mile_id)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    specs = [
        {
            "label": "supabase",
            "path": QUEUE_PATH,
            "resync": _resync_supabase,
        },
        {
            "label": "mirror",
            "path": MIRROR_QUEUE_PATH,
            "resync": _resync_mirror,
            "precondition": _mirror_enabled,
            "skip_reason": "mirror disabled (no REMOTE_URL or remote writes off)",
        },
    ]
    active = [s for s in specs if _load_list(s["path"])]
    if not active:
        print("[drain] queues empty — nothing to do")
        return 0

    paths = [s["path"] for s in active]
    dirty_before = (
        dirty_paths_before_write(ROOT, paths, label="drain_failed_syncs")
        if not args.dry_run
        else frozenset()
    )
    if not args.dry_run and not writable_output_paths(
        ROOT,
        paths,
        dirty_before=dirty_before,
        label="drain_failed_syncs",
    ):
        return 1

    feed = json.loads(FEED_PATH.read_text(encoding="utf-8"))
    by_id = {it.get("id"): it for it in feed if isinstance(it, dict)}

    results = {s["label"]: _drain_queue(s, by_id, dry_run=args.dry_run) for s in active}

    if not args.dry_run:
        written = []
        for spec in active:
            summary = results[spec["label"]]
            if summary["skipped"]:
                continue
            # race-tolerant write-back: re-read current queue, remove only the ids
            # we resolved (synced or not_found); preserve any concurrent appends.
            resolved = set(summary["synced"]) | set(summary["dropped_not_in_feed"])
            current = _load_list(spec["path"])
            remaining = [mid for mid in current if mid not in resolved]
            guard_canonical_write(spec["path"])
            spec["path"].write_text(json.dumps(remaining), encoding="utf-8")
            written.append(spec["path"])
        if written:
            total = sum(
                len(r["synced"]) + len(r["dropped_not_in_feed"]) for r in results.values()
            )
            commit_owned_outputs(
                ROOT,
                written,
                dirty_before=dirty_before,
                message=f"ops(sync): drain {total} failed projection sync(s)",
                label="drain_failed_syncs",
            )

    for spec in specs:
        summary = results.get(spec["label"])
        if summary is None:
            continue
        summary["queue_after"] = (
            len(summary["still_failing"]) + (summary["queue_before"] if summary["skipped"] else 0)
            if args.dry_run
            else len(_load_list(spec["path"]))
        )

    print(json.dumps({"dry_run": args.dry_run, "queues": results}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
