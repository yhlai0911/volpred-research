#!/usr/bin/env python3
"""Detect compute-queue jobs that can never start because their source-task
binding is stale (the "silent stall").

Why this exists
---------------
`compute_queue` will only start a queued job whose `source_task_id` still
points back at it. `_source_task_binding_is_valid` demands all three of:

    task.status        == "awaiting_agent_job"
    task.compute_job_id == <this job's id>
    task.blocked_reason == "external_compute_job_active"

Before the settlement fix, a job that failed any of these was skipped by
`_ready_queued_jobs` silently. The worker printed "no queued jobs" and exited
0, which was indistinguishable from an empty queue. On 2026-07-28 that
ambiguity hid a **totally dead queue**: 10 of 10 queued jobs were unstartable,
the oldest for 36h, while every worker tick reported success. The worker now
reconciles collected terminal owners, terminalizes permanently invalid source
references, and exits non-zero with typed blockage counts when ownership still
cannot move.

The dominant shape is a binding that was never released: a job completes, the
source task keeps `status=awaiting_agent_job` but flips `blocked_reason` to
`external_compute_receipt_pending_collection` and keeps `compute_job_id`
pinned to the *finished* job. Any newly enqueued job against that same source
task is then permanently unrunnable — it is bound to nothing that will ever
release it.

This script only *reports*. Releasing the stale bindings is the fix, and it
belongs to the queue's own state machine (task `assign_1c16f316`), not to a
detector — a script that unblocks by rewriting task records would be exactly
the "修資料不修流程" this repo forbids.

One brain, not two: the verdict is computed with `compute_queue`'s own
predicate, imported rather than restated, so a change to the start condition
cannot leave this audit quietly reporting on rules the worker no longer uses.

Alert egress stays with check_alerts (`.claude/rules/alert.md` single-owner
rule) — this script never sends mail, so running it twice cannot double-page.

Usage:
    uv run python scripts/audit_compute_queue_bindings.py [--json]

Exit code: 0 when every queued job can start, 1 when any is stranded (so a
cron/CI caller can gate on it). The verdict goes to stdout either way.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from scripts import compute_queue as cq  # noqa: E402
from scripts import task_pool_claim as tpc  # noqa: E402

def audit(tasks: list[dict]) -> dict:
    """Classify every queued job as startable or stranded."""
    jobs: list[dict[str, Any]] = []
    for path in sorted(cq.QUEUE_DIR.glob("*.json")):
        job = cq._read_job_file(path, context="audit-bindings")
        if job is None or job.get("status") != "queued":
            continue

        source_task_id = job.get("source_task_id")
        record = {
            "job_id": job.get("id"),
            "title": job.get("title"),
            "source_task_id": source_task_id,
            "queued_at": job.get("queued_at"),
        }

        if not source_task_id:
            # No binding to go stale; the worker starts it on merit alone.
            record.update(startable=True, reasons=[])
            jobs.append(record)
            continue

        reasons = list(
            cq._source_task_binding_issues(
                tasks,
                task_id=str(source_task_id),
                job_id=str(job["id"]),
            )
        )
        startable = not reasons
        record.update(
            startable=startable,
            reasons=reasons,
        )
        jobs.append(record)

    stranded = [j for j in jobs if not j["startable"]]
    return {
        "queued_total": len(jobs),
        "startable": len(jobs) - len(stranded),
        "stranded": len(stranded),
        # A queue where nothing can run is a dead queue, not a slow one, and it
        # reads identically to an empty one from the worker's log.
        "queue_dead": bool(jobs) and len(stranded) == len(jobs),
        "jobs": jobs,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--json", action="store_true", help="emit the raw verdict instead of a table"
    )
    args = parser.parse_args(argv)

    with tpc._locked_readonly() as tasks:
        verdict = audit(list(tasks))

    if args.json:
        print(json.dumps(verdict, indent=2, ensure_ascii=False))
    else:
        for job in verdict["jobs"]:
            mark = "ok       " if job["startable"] else "STRANDED "
            print(f"{mark} {str(job['job_id'])[:56]:58} {'; '.join(job['reasons'])}")
        print(
            f"\nqueued={verdict['queued_total']} startable={verdict['startable']} "
            f"stranded={verdict['stranded']}"
        )
        if verdict["queue_dead"]:
            print(
                "\nQUEUE DEAD AT READBACK — no queued job can start before "
                "ownership reconciliation. Run compute_queue.py "
                "reconcile-bindings; unresolved blockages are fail-loud."
            )

    return 1 if verdict["stranded"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
