#!/usr/bin/env python3
"""Compute Queue — separate heavy CPU work from Claude token-cost work.

Architecture (per user 2026-05-12 directive):
- Heavy compute (GARCH MLE, bootstrap, data fetch, backtest) → queued here,
  run by local worker (0 Claude tokens).
- Decision/writing/interpretation → Claude agent dispatched after compute
  result available (~75% token savings per K-experiment).

Schema (queue file `storage/ops/compute_queue/<id>.json`):
    id (str)           — unique, kebab-case
    title (str)        — human-readable
    script_path (str)  — relative to project root
    interpreter (str)  — e.g. "uv run python" or "bash"
    args (list[str])
    env (dict[str,str])
    status (str)       — queued / running / completed / failed
    queued_at / started_at / completed_at (ISO UTC)
    exit_code (int|null)
    stdout_file / stderr_file (str)
    result_artifact (str|null)  — path Claude followup will read
    claude_followup (dict|null) — { brief, task_type, priority }
    followup_dispatched (bool)  — true after hourly_dispatch creates next_task
    timeout_seconds (int)

Usage:
    enqueue:   uv run python scripts/compute_queue.py enqueue --script X --title Y ...
    list:      uv run python scripts/compute_queue.py list
    list-completed-pending-followup: ...
    run-next:  uv run python scripts/compute_queue.py run-next
    show:      uv run python scripts/compute_queue.py show <id>
    mark-followup-dispatched: ... --id <id>
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
QUEUE_DIR = ROOT / "storage" / "ops" / "compute_queue"
LOCK_FILE = QUEUE_DIR / ".worker.lock"
LOG_DIR = ROOT / "storage" / "logs" / "compute"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ensure_dirs():
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def _warn_compute_queue(message: str, path: Path, exc: Exception) -> None:
    print(
        f"[compute_queue] WARN {message}: "
        f"path={path} error={type(exc).__name__}: {exc}",
        file=sys.stderr,
    )


def _read_job_file(path: Path, *, context: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        _warn_compute_queue(f"{context} job JSON read failed; skipping", path, exc)
        return None
    if not isinstance(payload, dict):
        _warn_compute_queue(
            f"{context} job JSON schema invalid; skipping",
            path,
            TypeError(f"expected dict, got {type(payload).__name__}"),
        )
        return None
    return payload


def slug(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s[:60] or uuid.uuid4().hex[:8]


def enqueue(args) -> int:
    ensure_dirs()
    job_id = args.id or f"compute-{slug(args.title or args.script)}-{int(time.time())}"
    job_path = QUEUE_DIR / f"{job_id}.json"
    if job_path.exists():
        print(f"error: {job_id} already exists", file=sys.stderr)
        return 2

    followup = None
    if args.followup_brief:
        followup = {
            "brief": args.followup_brief,
            "task_type": args.followup_task_type or "paper_review",
            "priority": args.followup_priority or 3,
        }

    entry = {
        "id": job_id,
        "title": args.title or args.script,
        "script_path": args.script,
        "interpreter": args.interpreter or "uv run python",
        "args": args.script_args or [],
        "env": dict(kv.split("=", 1) for kv in (args.env or [])),
        "status": "queued",
        "queued_at": utc_now(),
        "started_at": None,
        "completed_at": None,
        "exit_code": None,
        "stdout_file": str(LOG_DIR / f"{job_id}.stdout"),
        "stderr_file": str(LOG_DIR / f"{job_id}.stderr"),
        "result_artifact": args.result_artifact,
        "claude_followup": followup,
        "followup_dispatched": False,
        "timeout_seconds": args.timeout or 3600,
    }
    with job_path.open("w", encoding="utf-8") as f:
        json.dump(entry, f, ensure_ascii=False, indent=2)
    print(f"enqueued: {job_id}")
    return 0


def list_jobs(args) -> int:
    ensure_dirs()
    rows = []
    for p in sorted(QUEUE_DIR.glob("*.json")):
        j = _read_job_file(p, context="list")
        if j is None:
            continue
        if args.status and j.get("status") != args.status:
            continue
        if args.completed_pending_followup:
            if j.get("status") != "completed" or j.get("followup_dispatched"):
                continue
            if not j.get("claude_followup"):
                continue
        rows.append(j)

    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        if not rows:
            print("(no jobs)")
            return 0
        print(f"{'STATUS':<10} {'ID':<55} TITLE")
        for j in rows:
            print(f"{j.get('status','?'):<10} {j['id']:<55} {j.get('title','')[:60]}")
    return 0


def show(args) -> int:
    p = QUEUE_DIR / f"{args.id}.json"
    if not p.exists():
        print(f"error: not found {args.id}", file=sys.stderr)
        return 2
    print(p.read_text())
    return 0


def _acquire_lock() -> bool:
    """Return True if lock acquired. Stale locks > 6h auto-released."""
    if LOCK_FILE.exists():
        try:
            mtime = LOCK_FILE.stat().st_mtime
            if time.time() - mtime > 6 * 3600:
                LOCK_FILE.unlink()  # stale
            else:
                return False
        except FileNotFoundError:
            pass  # silent-ok: another worker removed the lock; retry write below.
    try:
        LOCK_FILE.write_text(f"{os.getpid()} {utc_now()}\n")
        return True
    except OSError as exc:
        _warn_compute_queue("worker lock write failed; skipping run", LOCK_FILE, exc)
        return False


def _release_lock():
    try:
        LOCK_FILE.unlink()
    except FileNotFoundError:
        pass  # silent-ok: lock was already removed by another cleanup path.


def run_next(args) -> int:
    ensure_dirs()
    if not _acquire_lock():
        print("worker already running (lock held); skip")
        return 0

    try:
        # Find oldest queued job
        queued = []
        for p in sorted(QUEUE_DIR.glob("*.json")):
            j = _read_job_file(p, context="run-next")
            if j is None:
                continue
            if j.get("status") == "queued":
                queued.append((j.get("queued_at", ""), p, j))
        if not queued:
            print("no queued jobs")
            return 0
        queued.sort()
        _, job_path, job = queued[0]

        # Mark running
        job["status"] = "running"
        job["started_at"] = utc_now()
        job_path.write_text(json.dumps(job, ensure_ascii=False, indent=2))
        print(f"running: {job['id']} ({job['script_path']})")

        # Build command
        cmd_parts = shlex.split(job["interpreter"]) + [job["script_path"]] + (job.get("args") or [])
        env = os.environ.copy()
        env.update(job.get("env") or {})
        stdout_p = Path(job["stdout_file"])
        stderr_p = Path(job["stderr_file"])
        stdout_p.parent.mkdir(parents=True, exist_ok=True)

        try:
            with stdout_p.open("w") as so, stderr_p.open("w") as se:
                proc = subprocess.run(
                    cmd_parts,
                    cwd=str(ROOT),
                    env=env,
                    stdout=so,
                    stderr=se,
                    timeout=job.get("timeout_seconds", 3600),
                )
            job["exit_code"] = proc.returncode
            job["status"] = "completed" if proc.returncode == 0 else "failed"
        except subprocess.TimeoutExpired:
            job["status"] = "failed"
            job["exit_code"] = -1
            stderr_p.write_text(stderr_p.read_text() + "\n[TIMEOUT]\n")
        except Exception as e:
            job["status"] = "failed"
            job["exit_code"] = -2
            stderr_p.write_text(stderr_p.read_text() + f"\n[EXCEPTION] {e}\n")

        job["completed_at"] = utc_now()
        job_path.write_text(json.dumps(job, ensure_ascii=False, indent=2))
        print(f"done: {job['id']} status={job['status']} exit={job['exit_code']}")
        return 0
    finally:
        _release_lock()


def mark_followup_dispatched(args) -> int:
    p = QUEUE_DIR / f"{args.id}.json"
    if not p.exists():
        print(f"error: not found {args.id}", file=sys.stderr)
        return 2
    j = json.loads(p.read_text())
    j["followup_dispatched"] = True
    j["followup_dispatched_at"] = utc_now()
    if args.next_task_id:
        j["followup_next_task_id"] = args.next_task_id
    p.write_text(json.dumps(j, ensure_ascii=False, indent=2))
    print(f"marked: {args.id} followup_dispatched=true")
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("enqueue")
    e.add_argument("--id")
    e.add_argument("--title")
    e.add_argument("--script", required=True)
    e.add_argument("--interpreter")
    e.add_argument("--script-args", nargs="*")
    e.add_argument("--env", nargs="*", help="KEY=VAL")
    e.add_argument("--result-artifact")
    e.add_argument("--followup-brief")
    e.add_argument("--followup-task-type")
    e.add_argument("--followup-priority", type=int)
    e.add_argument("--timeout", type=int)
    e.set_defaults(func=enqueue)

    l = sub.add_parser("list")
    l.add_argument("--status")
    l.add_argument("--completed-pending-followup", action="store_true")
    l.add_argument("--json", action="store_true")
    l.set_defaults(func=list_jobs)

    s = sub.add_parser("show")
    s.add_argument("id")
    s.set_defaults(func=show)

    r = sub.add_parser("run-next")
    r.set_defaults(func=run_next)

    m = sub.add_parser("mark-followup-dispatched")
    m.add_argument("--id", required=True)
    m.add_argument("--next-task-id")
    m.set_defaults(func=mark_followup_dispatched)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
