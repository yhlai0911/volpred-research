#!/usr/bin/env python3
"""Measure the local compute lane instead of asserting things about it.

The recurring question is "we have CPU but nothing is running — is dispatch
broken?", and the recurring mistake is answering it by raising a slot count.
The shared-launchd Claude coalition is capped at one slot until per-fire custody
is isolated, and that cap has nothing to do with CPU-only work: model-free jobs
reach the queue through `compute_task_admission.py` without consuming a
supervisor slot at all. So "the CPU is idle" has two very different causes, and
only evidence separates them:

* nothing model-free is *queued* — the pending pool declares no `compute_spec`,
  so there is no work for the lane to do and no wiring is broken;
* work is queued and waiting — then the wait times say where.

This reports both halves, plus the `agent` jobs that also ride this queue.
Those are not model-free: they spawn a CLI and answer to quota, so mixing their
wait and failure statistics into a "compute utilization" number is how a healthy
lane gets mistaken for a broken one, and vice versa. They are counted, and
counted separately.

Usage::

    uv run python scripts/compute_lane_report.py --days 7
    uv run python scripts/compute_lane_report.py --json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

QUEUE_DIR = REPO_ROOT / "storage" / "ops" / "compute_queue"
NEXT_TASKS = REPO_ROOT / "storage" / "next_tasks.json"
SCHEDULES = REPO_ROOT / "config" / "runtime_schedules.json"


def _parse_ts(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None  # silent-ok: absent/!ISO timestamp is reported as a missing sample


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(int(len(ordered) * fraction), len(ordered) - 1)
    return ordered[index]


def _max_parallel() -> int:
    """Canonical CPU bound for the lane.

    Delegates to the queue's own resolver rather than re-reading the schedule.
    A report that computes utilization against a different denominator than the
    worker actually honours is worse than no report.
    """
    from scripts.compute_queue import _resolve_max_parallel

    try:
        return int(_resolve_max_parallel(None))
    except Exception as exc:
        from volpred.ops.diagnostics import warn

        warn("compute_lane_report", "max_parallel unresolved", err=str(exc))
        return 0


def _pending_supply() -> dict[str, Any]:
    """How much *admissible* model-free work is actually waiting."""
    try:
        raw = json.loads(NEXT_TASKS.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}
    tasks = raw if isinstance(raw, list) else raw.get("tasks", [])
    pending = [t for t in tasks if isinstance(t, dict) and t.get("status") == "pending"]
    with_spec = [t for t in pending if t.get("compute_spec")]
    return {
        "pending_total": len(pending),
        "pending_with_compute_spec": len(with_spec),
        "pending_topology_compute_queue": sum(
            1 for t in pending if t.get("topology") == "compute_queue"
        ),
        "admissible_task_ids": [str(t.get("id")) for t in with_spec][:20],
    }


def _lane_stats(days: float) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    live: dict[str, int] = defaultdict(int)

    for path in sorted(QUEUE_DIR.glob("*.json")):
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue  # silent-ok: a torn receipt is re-read on the next run
        if not isinstance(job, dict):
            continue
        kind = str(job.get("kind") or "unknown")
        status = str(job.get("status") or "unknown")
        if status in {"queued", "running"}:
            live[f"{kind}:{status}"] += 1
            continue
        completed = _parse_ts(job.get("completed_at"))
        if completed is None or completed < cutoff:
            continue
        queued = _parse_ts(job.get("queued_at"))
        started = _parse_ts(job.get("started_at"))
        buckets[kind].append(
            {
                "wait_s": (started - queued).total_seconds()
                if queued and started
                else None,
                "exec_s": (completed - started).total_seconds() if started else None,
                "status": status,
            }
        )

    parallel = _max_parallel()
    capacity_h = parallel * days * 24 if parallel else 0.0
    by_kind: dict[str, Any] = {}
    for kind, rows in buckets.items():
        waits = [r["wait_s"] for r in rows if r["wait_s"] is not None]
        execs = [r["exec_s"] for r in rows if r["exec_s"] is not None]
        exec_hours = sum(execs) / 3600.0
        by_kind[kind] = {
            "settled": len(rows),
            "failed": sum(1 for r in rows if r["status"] == "failed"),
            "cancelled": sum(1 for r in rows if r["status"] == "cancelled"),
            "wait_median_h": round(_percentile(waits, 0.5) / 3600.0, 2),
            "wait_p90_h": round(_percentile(waits, 0.9) / 3600.0, 2),
            "wait_max_h": round(max(waits) / 3600.0, 2) if waits else 0.0,
            "exec_hours": round(exec_hours, 2),
            "utilization_pct": (
                round(exec_hours / capacity_h * 100.0, 2) if capacity_h else None
            ),
        }
    return {
        "max_parallel": parallel,
        "capacity_core_hours": round(capacity_h, 1),
        "by_kind": by_kind,
        "in_flight": dict(live),
    }


def build_report(days: float) -> dict[str, Any]:
    supply = _pending_supply()
    lane = _lane_stats(days)
    compute = lane["by_kind"].get("compute") or {}
    starved = bool(supply.get("pending_with_compute_spec")) and not lane["in_flight"]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_days": days,
        "supply": supply,
        "lane": lane,
        # The distinction the whole report exists to make.
        "verdict": (
            "queued_work_not_running"
            if starved
            else "no_model_free_work_queued"
            if not supply.get("pending_with_compute_spec")
            else "lane_working"
        ),
        "compute_utilization_pct": compute.get("utilization_pct"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=float, default=7.0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    report = build_report(args.days)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0

    supply = report["supply"]
    lane = report["lane"]
    print(f"compute lane — last {report['window_days']:g}d")
    print(f"  verdict: {report['verdict']}")
    print(
        f"  supply: {supply.get('pending_total')} pending, "
        f"{supply.get('pending_with_compute_spec')} declare compute_spec "
        f"(only these can be admitted without a Claude slot)"
    )
    print(
        f"  capacity: max_parallel={lane['max_parallel']} "
        f"({lane['capacity_core_hours']} core-hours in window)"
    )
    for kind, stats in sorted(lane["by_kind"].items()):
        print(
            f"  {kind:8} settled={stats['settled']:>4} failed={stats['failed']:>3} "
            f"wait_med={stats['wait_median_h']:>6.2f}h wait_p90={stats['wait_p90_h']:>6.2f}h "
            f"exec={stats['exec_hours']:>7.2f}h util={stats['utilization_pct']}%"
        )
    if lane["in_flight"]:
        print(f"  in flight: {lane['in_flight']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
