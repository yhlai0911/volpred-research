#!/usr/bin/env python3
"""Automatically admit explicit local-compute tasks to ``compute_queue``.

The Claude dispatch supervisor must keep its shared-launchd coalition at one
slot until per-fire custody is isolated.  That safety gate is unrelated to
CPU-only work.  This adapter is the missing mechanical seam: a task producer
declares a relative script in ``compute_spec`` and the compute-worker tick
atomically reserves the pending task, creates a durable queue receipt, and
links the two records.  No Claude process is spawned and no supervisor slot is
consumed.

Task contract (stored in ``storage/next_tasks.json``)::

    {
      "topology": "compute_queue",              # optional when compute_spec exists
      "compute_spec": {
        "script": "scripts/my_cpu_job.py",
        "args": ["--input", "..."],
        "result_artifact": "experiments/k1/result.json",
        "output_paths": ["experiments/k1/result.json"],
        "timeout_seconds": 1800,
        "followup": {"brief": "...", "task_type": "paper_review", "priority": 3}
      }
    }

``compute_spec`` is deliberately opt-in.  An experiment description without a
fully specified executable remains an agent task; this module never guesses a
script from prose.  ``--dry-run`` is safe to use in diagnostics.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import re
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import compute_queue as cq
from scripts import task_pool_claim as tpc
from scripts.model_router import pick_topology
from volpred.ops.diagnostics import warn

ADMISSION_OWNER = "compute-admission"
ADMISSION_LOCK = ROOT / "storage" / "ops" / "compute_queue" / ".admission.lock"
ACTIVE_STATUSES = {"queued", "running"}
TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
_ENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _slug(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_-]+", "-", value).strip("-").lower()
    return value[:48] or "task"


def _safe_relative(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty relative path")
    path = Path(value.strip())
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{field} must stay inside the repository")
    return path.as_posix()


def _resolve_script(script: str) -> Path:
    path = (ROOT / script).resolve(strict=False)
    try:
        path.relative_to(ROOT.resolve())
    except (TypeError, ValueError) as exc:
        raise ValueError("compute script escapes repository") from exc
    if not path.is_file():
        raise ValueError(f"compute script does not exist: {script}")
    return path


def normalize_compute_spec(task: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize the executable contract without mutating a task."""
    raw = task.get("compute_spec")
    if not isinstance(raw, dict):
        raise TypeError("compute_spec must be an object")
    script = _safe_relative(raw.get("script"), field="compute_spec.script")
    _resolve_script(script)
    args = raw.get("args", [])
    if not isinstance(args, list) or any(not isinstance(item, str) for item in args):
        raise ValueError("compute_spec.args must be a list of strings")
    interpreter = raw.get("interpreter", "uv run python")
    if not isinstance(interpreter, str) or not interpreter.strip():
        raise ValueError("compute_spec.interpreter must be a non-empty string")
    env = raw.get("env", {})
    if not isinstance(env, dict) or any(
        not isinstance(key, str)
        or not _ENV_KEY.fullmatch(key)
        or not isinstance(value, str)
        for key, value in env.items()
    ):
        raise ValueError("compute_spec.env must map shell-safe names to strings")
    result_artifact = raw.get("result_artifact")
    if result_artifact is not None:
        result_artifact = _safe_relative(
            result_artifact, field="compute_spec.result_artifact"
        )
    output_paths = raw.get("output_paths", [])
    if not isinstance(output_paths, list):
        raise TypeError("compute_spec.output_paths must be a list")
    output_paths = [
        _safe_relative(path, field="compute_spec.output_paths[]")
        for path in output_paths
    ]
    timeout = raw.get("timeout_seconds", raw.get("timeout", 3600))
    if isinstance(timeout, bool) or not isinstance(timeout, int) or not 60 <= timeout <= 86_400:
        raise ValueError("compute_spec.timeout_seconds must be an integer in [60, 86400]")
    followup = raw.get("followup")
    if followup is not None:
        if not isinstance(followup, dict) or not isinstance(followup.get("brief"), str) or not followup["brief"].strip():
            raise ValueError("compute_spec.followup.brief is required when followup is set")
        followup = {
            "brief": followup["brief"],
            "task_type": str(followup.get("task_type") or "paper_review"),
            "priority": int(followup.get("priority", 3)),
        }
    queue_priority = raw.get("queue_priority", task.get("priority", 5))
    if isinstance(queue_priority, bool) or not isinstance(queue_priority, int):
        raise TypeError("compute_spec.queue_priority must be an integer")
    return {
        "script": script,
        "args": list(args),
        "interpreter": interpreter.strip(),
        "env": dict(env),
        "result_artifact": result_artifact,
        "output_paths": list(dict.fromkeys(output_paths)),
        "timeout_seconds": timeout,
        "followup": followup,
        "queue_priority": queue_priority,
    }


def job_id_for(task: dict[str, Any], spec: dict[str, Any]) -> str:
    """Stable id per task/spec, so retries are idempotent but changed specs can run."""
    fingerprint = json.dumps(spec, sort_keys=True, ensure_ascii=False).encode("utf-8")
    digest = hashlib.sha256(fingerprint).hexdigest()[:12]
    return f"compute-task-{_slug(str(task.get('id') or 'unknown'))}-{digest}"


def _read_job(job_id: str) -> dict[str, Any] | None:
    path = cq.QUEUE_DIR / f"{job_id}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None  # silent-ok: absence is the normal first-admission state.
    except json.JSONDecodeError as exc:
        warn(
            "compute_task_admission",
            "queue receipt JSON unreadable; treating as absent",
            path=str(path),
            err=f"{type(exc).__name__}: {exc}",
        )
        return None
    except OSError as exc:
        warn(
            "compute_task_admission",
            "queue receipt read failed; treating as absent",
            path=str(path),
            err=f"{type(exc).__name__}: {exc}",
        )
        return None
    return data if isinstance(data, dict) else None


def _reserve(task_id: str, *, job_id: str, spec: dict[str, Any]) -> bool:
    """Reserve only a still-pending task; this closes the claim/enqueue race."""
    with tpc._locked_load() as (_fh, tasks):
        task = tpc._find(tasks, task_id)
        if str(task.get("status") or "").lower() != "pending":
            return False
        if task.get("compute_job_id"):
            return False
        now = tpc._now()
        task["status"] = "in_progress"
        task["claimed_by"] = ADMISSION_OWNER
        tpc._write_claim_window(task, now)
        task["compute_admission"] = {
            "state": "reserved",
            "reserved_at": now,
            "job_id": job_id,
            "token_cost_estimate": 0,
        }
        tpc._record_status_history(
            task,
            frm="pending",
            to="in_progress",
            by=ADMISSION_OWNER,
            note="compute_queue_admission_reserved",
        )
        return True


def _release(task_id: str, *, reason: str) -> None:
    with tpc._locked_load() as (_fh, tasks):
        task = tpc._find(tasks, task_id)
        if (
            str(task.get("claimed_by") or "") != ADMISSION_OWNER
            or task.get("compute_job_id")
        ):
            return
        tpc._repend_task(task, note="compute_queue_admission_released", reason=reason)
        task["compute_admission"] = {
            "state": "released",
            "released_at": tpc._now(),
            "reason": reason,
        }


def _task_state(task_id: str) -> dict[str, Any] | None:
    with tpc._locked_readonly() as tasks:
        for task in tasks:
            if str(task.get("id") or "") == task_id:
                return dict(task)
    return None


def _enqueue(task: dict[str, Any], spec: dict[str, Any], job_id: str) -> int:
    followup = spec.get("followup") or {}
    args = SimpleNamespace(
        id=job_id,
        title=task.get("title") or task.get("id") or job_id,
        script=spec["script"],
        interpreter=spec["interpreter"],
        script_args=spec["args"],
        env=[f"{key}={value}" for key, value in spec["env"].items()],
        result_artifact=spec["result_artifact"],
        output_paths=spec["output_paths"],
        followup_brief=followup.get("brief"),
        followup_task_type=followup.get("task_type"),
        followup_priority=followup.get("priority"),
        queue_priority=spec["queue_priority"],
        timeout=spec["timeout_seconds"],
        timeout_parent_job_id=None,
        split_stage=None,
        source_task_id=str(task["id"]),
        job_metadata=None,
        job_kind="compute",
        job_cwd=None,
        brief_source=None,
        brief_snapshot=None,
        routing={
            "lane": "compute_queue",
            "token_cost_estimate": 0,
            "router": "automatic_compute_admission",
            "source_task_id": str(task["id"]),
        },
    )
    return cq.enqueue(args)


def admit_one(task: dict[str, Any], *, dry_run: bool = False) -> dict[str, Any]:
    task_id = str(task.get("id") or "")
    try:
        spec = normalize_compute_spec(task)
    except ValueError as exc:
        return {"task_id": task_id, "status": "invalid", "reason": str(exc)}
    route = pick_topology(task.get("task_type"), task)
    if route["topology"] != "compute_queue":
        return {"task_id": task_id, "status": "skipped", "reason": "topology_not_compute_queue"}
    job_id = job_id_for(task, spec)
    existing = _read_job(job_id)
    if existing and existing.get("status") in ACTIVE_STATUSES:
        if dry_run:
            return {"task_id": task_id, "job_id": job_id, "status": "already_queued"}
        state = _task_state(task_id)
        if (
            state
            and str(state.get("status") or "").lower() == "pending"
            and _reserve(task_id, job_id=job_id, spec=spec)
        ):
            cq._link_source_task(job_id, task_id)
        return {"task_id": task_id, "job_id": job_id, "status": "already_queued"}
    if existing and existing.get("status") in TERMINAL_STATUSES:
        return {"task_id": task_id, "job_id": job_id, "status": "terminal_exists"}
    if dry_run:
        return {"task_id": task_id, "job_id": job_id, "status": "eligible", "token_cost_estimate": 0}
    if not _reserve(task_id, job_id=job_id, spec=spec):
        return {"task_id": task_id, "job_id": job_id, "status": "race_lost"}
    rc = _enqueue(task, spec, job_id)
    if rc != 0 and _read_job(job_id) is None:
        _release(task_id, reason=f"enqueue_failed_rc_{rc}")
        return {"task_id": task_id, "job_id": job_id, "status": "enqueue_failed", "rc": rc}
    linked = _task_state(task_id)
    if not linked or linked.get("status") != "awaiting_agent_job" or str(linked.get("compute_job_id")) != job_id:
        # The queue receipt is durable even if the cross-file link failed; leave
        # the task retryable and expose the broken read-back instead of claiming
        # success.
        _release(task_id, reason="source_task_link_readback_failed")
        return {"task_id": task_id, "job_id": job_id, "status": "link_readback_failed", "rc": rc}
    return {
        "task_id": task_id,
        "job_id": job_id,
        "status": "enqueued" if rc == 0 else "reconciled_existing",
        "token_cost_estimate": 0,
    }


@contextmanager
def admission_lock() -> Iterator[None]:
    ADMISSION_LOCK.parent.mkdir(parents=True, exist_ok=True)
    with ADMISSION_LOCK.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def admit(*, limit: int | None = None, dry_run: bool = False) -> dict[str, Any]:
    with admission_lock():
        with tpc._locked_readonly() as tasks:
            candidates = [
                dict(task)
                for task in tasks
                if isinstance(task, dict)
                and str(task.get("status") or "").lower() == "pending"
                and isinstance(task.get("compute_spec"), dict)
            ]
        candidates.sort(key=lambda task: (int(task.get("priority", 5)), str(task.get("created_at") or "")))
        if limit is not None:
            candidates = candidates[:limit]
        results = [admit_one(task, dry_run=dry_run) for task in candidates]
    return {
        "ok": True,
        "dry_run": dry_run,
        "candidate_count": len(candidates),
        "enqueued": sum(row["status"] in {"enqueued", "reconciled_existing"} for row in results),
        "token_cost_estimate": sum(int(row.get("token_cost_estimate", 0)) for row in results),
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=0, help="max tasks per tick; 0 means no artificial task-count cap")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.limit < 0:
        parser.error("--limit must be >= 0")
    report = admit(limit=args.limit or None, dry_run=args.dry_run)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(
            "compute-admission: "
            f"candidates={report['candidate_count']} "
            f"enqueued={report['enqueued']} "
            f"token_cost_estimate={report['token_cost_estimate']} "
            f"dry_run={report['dry_run']}"
        )
        for row in report["results"]:
            print(f"  {row.get('task_id')}: {row.get('status')}" + (f" ({row.get('reason')})" if row.get("reason") else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
