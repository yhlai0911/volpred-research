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
    status (str)       — queued / running / completed / failed / cancelled
    queued_at / started_at / completed_at (ISO UTC)
    exit_code (int|null)       — job-level code (includes queue postconditions)
    process_exit_code (int|null, optional) — raw rc when a postcondition fails
    stdout_file / stderr_file (str)
    result_artifact (str|null)  — declared output; a completed job must contain it
    output_paths (list[str])    — job-owned deliverables eligible for path-scoped commit
    output_paths_updated_at (ISO UTC|null) — producer write-back timestamp
    job_metadata (str|null)     — runner lifecycle/validation receipt (agent jobs)
    kind (str)         — compute / agent
    cwd (str|null)     — agent working directory (worktree when explicit)
    claude_followup (dict|null) — { brief, task_type, priority }
    followup_dispatched (bool)  — true after hourly_dispatch creates next_task
    timeout_seconds (int)
    cancelled_at (ISO UTC, optional) — operator cancellation timestamp
    cancel_reason (str, optional)    — required audit reason for cancellation
    not_before (ISO UTC|null, optional) — worker must not start it before this
    quota_requeues (int, optional)      — times the quota wall bounced this job
    requeue_history (list, optional)    — one record per bounced attempt
    claimed_by_pid (int|null)           — worker pid that claimed the job
    claimed_by_pid_start_wall (str|null) — `ps lstart` fingerprint of that pid
                                           (pid-reuse-safe liveness, see D6b reaper)
    reap (dict, optional)               — D6b receipt: how a stranded running job
                                           was judged dead and finalized

Usage:
    enqueue:   uv run python scripts/compute_queue.py enqueue --script X --title Y ...
    list:      uv run python scripts/compute_queue.py list
    list --pending-followup: completed collection + failed-agent triage
    list --completed-pending-followup: legacy completed-only view
    run-next:  uv run python scripts/compute_queue.py run-next
    run-loop:  uv run python scripts/compute_queue.py run-loop  (drain until empty)
    show:      uv run python scripts/compute_queue.py show <id>
    cancel:    uv run python scripts/compute_queue.py cancel --id ID --reason WHY
    requeue:   uv run python scripts/compute_queue.py requeue --id ID
               (auth/quota/worker_killed failures only)
    mark-followup-dispatched: ... --id <id>
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import time
import uuid
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.dispatch_supervisor import procutil  # noqa: E402
from volpred.canonical_write import guard_canonical_write  # noqa: E402
from volpred.ops.diagnostics import warn  # noqa: E402
from volpred.ops.git_writer_lock import is_registered_linked_worktree  # noqa: E402
from volpred.ops.timestamps import parse_iso_warn  # noqa: E402

QUEUE_DIR = ROOT / "storage" / "ops" / "compute_queue"
LOCK_FILE = QUEUE_DIR / ".worker.lock"
LOG_DIR = ROOT / "storage" / "logs" / "compute"
AGENT_JOB_DIR = ROOT / "storage" / "ops" / "agent_jobs"
AGENT_BRIEF_DIR = ROOT / "storage" / "ops" / "agent_briefs"

# Agent jobs. A research agent needs 20-60min of wall clock (that is the whole
# reason it cannot live inside a ~50min dispatch fire), so the default budget has
# to actually cover one. The grace is how much earlier the runner's inner bound
# fires, leaving it time to write a diagnosis before the worker kills the script.
AGENT_DEFAULT_TIMEOUT = 5400  # 90 min
AGENT_TIMEOUT_GRACE = 120

# Scheduling priority (lower runs first). The queue used to be pure FIFO, which
# is the right default only when every job costs the same. It does not: a
# lazypack render is a few minutes and it is the last thing standing between a
# finished draft and a reader, while a GARCH multistart or a research agent is
# 60-90 minutes and nobody is waiting on the minute. FIFO put the reader behind
# the compute (observed 2026-07-19: two general drafts skipped 20 release cycles
# each). Priority restores the ordering that matters — release-blocking work
# first, everything else in arrival order behind it.
DEFAULT_QUEUE_PRIORITY = 5
RELEASE_BLOCKING_PRIORITY = 1
# Job-id prefixes whose completion unblocks a reader-facing release gate.
RELEASE_BLOCKING_JOB_PREFIXES = ("lazypack-",)


def _default_queue_priority(job_id: str) -> int:
    """Priority for a job that did not declare one.

    Derived from the id rather than stored per-caller so that jobs queued
    before this field existed are scheduled correctly too — the alternative
    (backfilling every queue file) would have to be re-run for every job that
    a stale code path enqueues without the field.
    """
    if any(str(job_id).startswith(p) for p in RELEASE_BLOCKING_JOB_PREFIXES):
        return RELEASE_BLOCKING_PRIORITY
    return DEFAULT_QUEUE_PRIORITY


def _scheduling_priority(job: dict) -> int:
    """Effective run order key for a queued job; lower runs first."""
    declared = job.get("queue_priority")
    if isinstance(declared, int) and not isinstance(declared, bool):
        return declared
    return _default_queue_priority(str(job.get("id") or ""))

# Drain-loop parallelism (D6, owner directive 2026-07-20). The worker costs no
# Claude tokens, so serializing it to one job per 15-minute tick was pure queue
# latency; but compute jobs are multi-core-hungry (GARCH MLE multistarts,
# bootstrap), and the same M1 Max also carries dispatch agents and the
# interactive session. cpu//3 budgets ~3 cores per job with headroom left over
# (10 cores -> 3 jobs); the cap of 3 keeps a bigger future machine from turning
# the queue into a thundering herd. Override without touching code via the
# `max_parallel` field on the volpred-compute-worker entry in
# config/runtime_schedules.json (the canonical schedule spec) — see
# _resolve_max_parallel for the precedence.
DRAIN_MAX_PARALLEL_DEFAULT = min(3, max(1, (os.cpu_count() or 1) // 3))

# Quota re-queue. A quota-class death is not a failure of the work: the CLI
# answers "You've hit your session limit · resets 10:20pm" in about five seconds
# and the agent never exists. Nothing ran, nothing was spent, the worktree is
# untouched.
#
# `run_agent_job.py` has said so in its receipt since 2026-07-14, and nothing
# read it. On 2026-07-16 the session window closed at 20:45 CST and the next five
# agent jobs — k1708, and the k1625/k1630/k1649/k1678 closeouts — each died on
# that same wall and each was filed as `triage_failed`, i.e. as five separate
# work orders asking a fire to go inspect a worktree that nobody had written to.
# Five fires to rediscover one clock.
#
# Waiting is the whole remedy, so the queue does the waiting itself. This is not
# the retry ladder that failure_class.py warns against — a ladder re-attempts
# against an unchanged wall, whereas this re-attempts against a moved clock, at
# a cost of ~5s and zero tokens per bounce.
#
# The cap exists because not every quota window is a session window: a weekly
# limit can outlast any sane wait. When the bounces run out the job fails for
# real, and its triage brief says which wall it died on and how long it waited —
# which is the point at which a person genuinely is the next step.
QUOTA_REQUEUE_MAX = 16
QUOTA_REQUEUE_BACKOFF_S = 1800  # 30 min × 16 ≈ 8h of patience


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


def _write_job_file(path: Path, payload: dict[str, Any]) -> None:
    """Atomically replace one queue receipt.

    The worker and its child producer can both add lifecycle metadata to the same
    receipt.  A temp-file + replace prevents readers from observing truncated
    JSON; callers still merge the keys they own before writing.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass  # silent-ok: os.replace already consumed the temp file.


@contextmanager
def _receipt_lock():
    """Serialize receipt read/merge/write operations across worker processes."""
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    lock_path = QUEUE_DIR / ".receipts.lock"
    with lock_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _normalize_output_path(raw: str | Path) -> str:
    path = Path(raw)
    absolute = path if path.is_absolute() else ROOT / path
    absolute = absolute.resolve(strict=False)
    try:
        return str(absolute.relative_to(ROOT.resolve(strict=False)))
    except ValueError:
        return str(absolute)


def record_output_paths(job_id: str, paths: list[str | Path]) -> bool:
    """Merge producer-observed deliverables into a queue receipt.

    Enqueue-time declarations make failure recovery possible even if the child
    dies abruptly.  This write-back records what the producer actually placed on
    disk (for example a panel written before Codex exits non-zero).  The worker
    merges these keys back before its terminal write so they cannot be clobbered.
    """
    if not job_id or Path(job_id).name != job_id:
        print(f"[compute_queue] WARN invalid job id for output write-back: {job_id!r}",
              file=sys.stderr)
        return False
    job_path = QUEUE_DIR / f"{job_id}.json"
    observed = [_normalize_output_path(path) for path in paths if str(path).strip()]
    if not observed:
        return True
    with _receipt_lock():
        job = _read_job_file(job_path, context="record-output-paths")
        if job is None:
            return False
        current = job.get("output_paths") or []
        if not isinstance(current, list):
            current = []
        job["output_paths"] = list(dict.fromkeys([*(str(p) for p in current), *observed]))
        job["output_paths_updated_at"] = utc_now()
        _write_job_file(job_path, job)
    return True


def _merge_runtime_output_paths(job_path: Path, job: dict[str, Any]) -> None:
    """Preserve child write-backs before the worker records terminal status."""
    latest = _read_job_file(job_path, context="merge-runtime-output-paths")
    if latest is None:
        return
    current = job.get("output_paths") or []
    runtime = latest.get("output_paths") or []
    if not isinstance(current, list):
        current = []
    if not isinstance(runtime, list):
        runtime = []
    job["output_paths"] = list(dict.fromkeys([*(str(p) for p in current),
                                                *(str(p) for p in runtime)]))
    if latest.get("output_paths_updated_at"):
        job["output_paths_updated_at"] = latest["output_paths_updated_at"]


def _declared_result_artifact(job: dict[str, Any]) -> Path | None:
    """Resolve a queue result artifact on the worker side of the boundary."""
    raw = job.get("result_artifact")
    if not raw:
        return None
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


# The canonical certificate filename, fixed by experiment_gates.CERT_FILENAME. A job
# whose declared deliverable IS that certificate adjudicated an experiment; it did not
# write one. Kept as a literal rather than an import: the gate that matters runs inside
# the worktree, and this side must not start depending on the canonical module's shape.
_REVIEW_ARTIFACT_NAME = "review_verdict.json"


def _is_review_job(artifact_path: Path | None) -> bool:
    """Did this job judge someone else's experiment rather than author one?"""
    return artifact_path is not None and artifact_path.name == _REVIEW_ARTIFACT_NAME


def _review_verdict_unfilled(artifact_path: Path) -> list[str]:
    """A review job's deliverable is a FILLED verdict, not a scaffold.

    2026-07-19 k528: the verdict template was pre-generated, Codex never wrote
    the adjudication, and the job still went `completed` because the artifact
    existence check passed on eight `FILL:` placeholders. Existence is not the
    postcondition — content is. Returns a list of problems (empty = filled).
    """
    try:
        data = json.loads(artifact_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"unreadable: {exc}"]
    if not isinstance(data, dict):
        return ["not a JSON object"]
    problems: list[str] = []
    verdict = str(data.get("verdict", ""))
    if verdict not in {"PASS", "CONDITIONAL PASS", "CONDITIONAL_PASS", "FAIL"}:
        problems.append(f"verdict={verdict!r} is not an adjudication")
    for key, value in data.items():
        if isinstance(value, str) and value.startswith("FILL:"):
            problems.append(f"{key} unfilled")
        elif isinstance(value, list):
            problems.extend(
                f"{key}[] unfilled" for item in value
                if isinstance(item, str) and item.startswith("FILL:")
            )
    return problems


def _experiment_scope(job: dict[str, Any], artifact_path: Path | None) -> Path | None:
    """The `experiments/<kid>` directory this job produced, if any.

    Prefer the declared artifact: for agent jobs it is already resolved on the
    worktree side of the boundary, so its `experiments/<kid>` ancestor is the
    exact tree the agent wrote.  Fall back to whatever the worktree's git status
    calls dirty, which covers an agent that produced an experiment but declared
    no artifact.
    """
    if artifact_path is not None:
        parts = artifact_path.parts
        if "experiments" in parts:
            idx = parts.index("experiments")
            if idx + 1 < len(parts):
                return Path(*parts[: idx + 2])

    workdir = _agent_workdir(job)
    if not workdir:
        return None
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=workdir,
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        ).stdout
    except Exception as e:  # noqa: BLE001
        print(f"[gate] WARNING: git status failed in {workdir}: {e}", file=sys.stderr)
        return None

    for line in out.splitlines():
        rel = line[3:].strip().strip('"')
        parts = Path(rel).parts
        if len(parts) >= 2 and parts[0] == "experiments":
            return Path(workdir) / parts[0] / parts[1]
    return None


def _experiment_gate_failure(
    job: dict[str, Any], artifact_path: Path | None
) -> dict[str, Any] | None:
    """Run the repo's experiment-integrity gates over what this job produced.

    This is the choke point the gates never had. A dispatched agent runs in a
    worktree, runs its own `test_kXXXX.py`, and never runs `scripts/tests/` --
    so the ratchets that would have caught K1701 and K1709 sat unrun while an
    xhigh experiment was wasted (docs/error_log.md 2026-07-14). Every worktree
    experiment comes back through here, so here is where the repo gets to
    check its own rules before calling the work accepted.

    Returns a report dict on violation (caller fails the job), else None.
    """
    scope = _experiment_scope(job, artifact_path)
    if scope is None:
        # Not an experiment job (paper review, ops, lazypack...). Recorded, not
        # silent: a job that SHOULD have been gated and was not must be findable.
        job["experiment_gate"] = {"status": "out_of_scope"}
        return None

    workdir = Path(_agent_workdir(job) or ROOT)
    gate_script = workdir / "scripts" / "experiment_gates.py"
    if not gate_script.exists():
        # A worktree branched before the gates existed genuinely has no gate to
        # run. Say so loudly rather than passing the job off as gated.
        print(
            f"[gate] WARNING: no experiment_gates.py in {workdir} — job {job['id']} "
            "was NOT gated (worktree base predates the gates; rebase it).",
            file=sys.stderr,
        )
        job["experiment_gate"] = {"status": "unavailable", "workdir": str(workdir)}
        return None

    try:
        proc = subprocess.run(
            [sys.executable, str(gate_script), "run", "--path", str(scope)],
            cwd=str(workdir),
            capture_output=True,
            text=True,
            timeout=600,
        )
    except Exception as e:  # noqa: BLE001
        print(f"[gate] WARNING: gate run crashed for {job['id']}: {e}", file=sys.stderr)
        job["experiment_gate"] = {"status": "error", "error": str(e)}
        return None

    if proc.returncode == 0:
        job["experiment_gate"] = {"status": "passed", "scope": str(scope)}
        return None

    report = {
        "status": "failed",
        "scope": str(scope),
        "exit_code": proc.returncode,
        "report": (proc.stderr or proc.stdout).strip(),
    }

    if _is_review_job(artifact_path):
        # A reviewer writes its verdict INTO the experiment it judges, so the scope
        # above resolves to someone else's tree. Charging the reviewer for what it
        # found inverts the incentive the gates exist to protect: on 2026-07-17
        # k1729-certify returned a valid FAIL verdict, opened the repair task, and
        # was filed `failed` for the very defect it was sent to find -- so every
        # later fire re-triaged finished work, and the only way for a review to be
        # "completed" would have been to find nothing. The finding is real and is
        # kept; it belongs to the experiment's own disposition, not to this job.
        job["experiment_gate"] = {**report, "charged_to": "experiment"}
        return None

    return report


def slug(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s[:60] or uuid.uuid4().hex[:8]


def _file_sha256(raw_path: Any) -> str | None:
    if not raw_path:
        return None
    path = Path(str(raw_path))
    if not path.is_absolute():
        path = ROOT / path
    if not path.is_file():
        return None
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        warn(
            "compute_queue",
            "brief snapshot unreadable while building retry signature",
            path=str(path),
            err=str(exc),
        )
        return None


def _job_signature(job: dict[str, Any]) -> str:
    """Stable work identity used to reject an unchanged retry after timeout."""
    kind = str(job.get("kind") or "compute")
    if kind == "agent" or job.get("script_path") == "scripts/run_agent_job.py":
        args = job.get("args") or []
        cwd = Path(str(job.get("cwd") or _arg_value(args, "--cwd") or ROOT))
        raw_artifact = job.get("result_artifact")
        artifact_identity = raw_artifact
        if raw_artifact:
            try:
                artifact_identity = str(Path(str(raw_artifact)).relative_to(cwd))
            except ValueError:
                artifact_identity = str(raw_artifact)
        identity = {
            "kind": "agent",
            "model": _arg_value(args, "--model"),
            "effort": _arg_value(args, "--effort"),
            "brief_sha256": _file_sha256(
                job.get("brief_snapshot") or _arg_value(args, "--brief-file")
            ),
            "result_artifact": artifact_identity,
        }
    else:
        identity = {
            "kind": kind,
            "script_path": job.get("script_path"),
            "interpreter": job.get("interpreter"),
            "args": job.get("args") or [],
            "cwd": job.get("cwd"),
            "result_artifact": job.get("result_artifact"),
        }
    return hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _runner_timed_out(job: dict[str, Any]) -> bool:
    meta_path = job.get("job_metadata")
    if not meta_path:
        return False
    path = Path(str(meta_path))
    if not path.is_absolute():
        path = ROOT / path
    try:
        metadata = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        warn(
            "compute_queue",
            "runner metadata unreadable while checking timeout",
            job=job.get("id"),
            path=str(path),
            err=str(exc),
        )
        return False
    return metadata.get("timed_out") is True


def _job_timed_out(job: dict[str, Any]) -> bool:
    return (
        job.get("failure_reason") == "timeout"
        or job.get("split_required") is True
        or job.get("exit_code") == -1
        or _runner_timed_out(job)
    )


def _mark_timeout(job: dict[str, Any]) -> None:
    job["failure_reason"] = "timeout"
    job["split_required"] = True
    job["timed_out_at"] = utc_now()


def _validate_timeout_split(entry: dict[str, Any], args: Any) -> str | None:
    """Validate parent tracing and reject an unchanged timed-out work order."""
    parent_id = getattr(args, "timeout_parent_job_id", None)
    split_stage = getattr(args, "split_stage", None)
    if bool(parent_id) != bool(split_stage):
        return "--timeout-parent-job-id and --split-stage must be provided together"

    if parent_id:
        parent_path = QUEUE_DIR / f"{parent_id}.json"
        parent = (
            _read_job_file(parent_path, context="timeout-split-parent")
            if parent_path.exists()
            else None
        )
        if parent is None:
            return f"timeout parent job not found or unreadable: {parent_id}"
        if parent.get("status") != "failed" or not _job_timed_out(parent):
            return f"timeout parent is not a failed timeout receipt: {parent_id}"
        if entry["timeout_seconds"] >= int(parent.get("timeout_seconds") or 3600):
            return "split child timeout must be shorter than its timed-out parent"
        entry["parent_timeout_job_id"] = parent_id
        entry["split_stage"] = str(split_stage)

    signature = _job_signature(entry)
    for path in sorted(QUEUE_DIR.glob("*.json")):
        previous = _read_job_file(path, context="timeout-retry-guard")
        if previous is None or previous.get("status") != "failed" or not _job_timed_out(previous):
            continue
        if _job_signature(previous) == signature:
            return (
                f"unchanged retry of timed-out job {previous.get('id')} is prohibited; "
                "split the scope/arguments or brief, use a shorter timeout, and pass "
                "--timeout-parent-job-id plus --split-stage"
            )
    return None


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

    # `result_artifact` is a validation contract, not an ownership contract.
    # In particular, agent artifacts can live in a worktree and lazypack's
    # legacy result_artifact is a directory.  Only explicit, exact output paths
    # are eligible for the reaper's path-scoped commit.
    declared_outputs = getattr(args, "output_paths", None) or []

    entry = {
        "id": job_id,
        "title": args.title or args.script,
        "script_path": args.script,
        "interpreter": args.interpreter or "uv run python",
        "args": args.script_args or [],
        "env": dict(kv.split("=", 1) for kv in (args.env or [])),
        "status": "queued",
        "queue_priority": (
            args.queue_priority
            if isinstance(getattr(args, "queue_priority", None), int)
            else _default_queue_priority(job_id)
        ),
        "queued_at": utc_now(),
        "started_at": None,
        "completed_at": None,
        "exit_code": None,
        "stdout_file": str(LOG_DIR / f"{job_id}.stdout"),
        "stderr_file": str(LOG_DIR / f"{job_id}.stderr"),
        "result_artifact": args.result_artifact,
        "output_paths": list(dict.fromkeys(
            _normalize_output_path(path) for path in declared_outputs
        )),
        "output_paths_updated_at": None,
        "job_metadata": getattr(args, "job_metadata", None),
        "kind": getattr(args, "job_kind", "compute"),
        "cwd": getattr(args, "job_cwd", None),
        "claude_followup": followup,
        "followup_dispatched": False,
        "source_task_id": getattr(args, "source_task_id", None),
        "timeout_seconds": args.timeout or 3600,
        # Where the brief came from vs the frozen copy the runner will actually read.
        # Keeping both makes "the agent read something else than I wrote" auditable.
        "brief_source": getattr(args, "brief_source", None),
        "brief_snapshot": getattr(args, "brief_snapshot", None),
    }
    split_error = _validate_timeout_split(entry, args)
    if split_error:
        print(f"error: {split_error}", file=sys.stderr)
        return 2
    _write_job_file(job_path, entry)
    print(f"enqueued: {job_id}")
    _link_source_task(job_id, entry.get("source_task_id"))
    return 0


def _link_source_task(job_id: str, task_id: str | None) -> None:
    """Mark the pool task that spawned this job as in_progress.

    Without this the task stays `pending` while its job sits in the queue, so
    every later fire's urgency lane re-surfaces it as undispatched work and the
    honest response — enqueue it — produces a duplicate job (observed
    2026-07-19: assign_98a32740 / assign_1238781f both queued yet still
    pending, three fires apart).  The link is written at the one moment both
    ids are known; a reconciler after the fact would be a second owner for the
    same invariant.

    Never fails the enqueue: the job file is already durable, and a job with an
    unlinked task is strictly better than a fire that aborts mid-dispatch.
    """
    if not task_id:
        return
    try:
        # Import under the canonical `scripts.` name. Path-inserting scripts/ and
        # importing bare `task_pool_claim` would create a second module object
        # with its own NEXT_TASKS constant, so a caller holding
        # `scripts.task_pool_claim` (tests, other scripts) would be editing a
        # different file than this one writes.
        repo_root = str(Path(__file__).resolve().parent.parent)
        if repo_root not in sys.path:
            sys.path.insert(0, repo_root)
        from scripts import task_pool_claim as tpc

        # _locked_load writes the mutated list back on context exit; mutating in
        # place is the whole contract, there is no separate write call.
        with tpc._locked_load() as (_fh, tasks):
            task = tpc._find(tasks, task_id)
            task["compute_job_id"] = job_id
            if task.get("status") in ("pending", "claimed"):
                task["status"] = "in_progress"
            task["result"] = tpc._append_note(
                task.get("result"),
                f"dispatched to compute job {job_id}; awaiting PHASE A collection",
            )
        print(f"linked source task: {task_id} -> in_progress")
    except Exception as exc:  # noqa: BLE001 — advisory link, never blocks enqueue
        print(f"warning: could not link source task {task_id}: {exc}", file=sys.stderr)


def enqueue_agent(args) -> int:
    """Queue a long-lived `claude -p` agent instead of running it inside a fire.

    A fire is capped at ~50min; a research agent needs 20-60min. Spawning the
    agent from inside the fire kills the fire (SIGKILL at the cap) or orphans the
    agent (ppid=1, work never collected) — both observed 2026-07-11/12, see
    docs/error_log.md 3-STRIKE. The agent belongs here, in the same detached,
    locked, later-collected container heavy compute already uses.
    """
    brief_path = Path(args.brief_file)
    if not brief_path.is_absolute():
        brief_path = ROOT / brief_path
    if not brief_path.exists():
        print(f"error: brief file not found: {brief_path}", file=sys.stderr)
        return 2

    # An agent works in a git worktree. If that worktree is missing at enqueue time
    # the job cannot possibly run — fail here, where a human is watching, instead of
    # 60 minutes later inside the worker (K1684, 2026-07-12: enqueued against a
    # worktree that orphan-recovery had already removed → instant exit 2, work lost).
    if not args.cwd:
        print(
            "error: enqueue-agent requires --cwd pointing to a registered linked worktree; "
            "the shared main checkout is not an agent workspace",
            file=sys.stderr,
        )
        return 2
    cwd_path = Path(args.cwd)
    if not cwd_path.is_absolute():
        cwd_path = ROOT / cwd_path
    if not cwd_path.is_dir():
        print(f"error: --cwd does not exist: {cwd_path}", file=sys.stderr)
        return 2
    if not is_registered_linked_worktree(ROOT, cwd_path):
        print(
            f"error: --cwd must be a registered non-main linked worktree: {cwd_path}",
            file=sys.stderr,
        )
        return 2
    workdir = cwd_path.resolve()

    job_id = args.id or f"agent-{brief_path.stem}-{uuid.uuid4().hex[:6]}"

    # Freeze the brief HERE, at enqueue. The runner opens its brief when the worker
    # picks the job up (*/15) — not now — so "enqueue, then fix the brief" is not an
    # edit, it is a race against the worker, and the author does not find out who won.
    # 2026-07-14: a corrected verdict schema landed 48s too late, the agent read the
    # stale brief, and a 30-minute xhigh review produced a verdict the merge gate could
    # not accept. Snapshotting makes the spec immutable the moment it is queued, and
    # incidentally rescues briefs written to /tmp from being swept before the job runs.
    # To change a queued brief now: `amend --brief-file`, which refuses once it is running.
    frozen_brief = AGENT_BRIEF_DIR / f"{job_id}.md"
    # 2026-07-15 CI tree-clean leak: a test that patches ROOT but not AGENT_BRIEF_DIR
    # sent this write into the real repo. Guard at the writer so the leak fails loudly.
    guard_canonical_write(frozen_brief)
    AGENT_BRIEF_DIR.mkdir(parents=True, exist_ok=True)
    frozen_brief.write_text(brief_path.read_text(encoding="utf-8"), encoding="utf-8")

    # `result_artifact` is the AGENT'S output, never the runner's summary. Resolve
    # it on the same side of the worktree boundary as the agent itself. The runner
    # only verifies that this path exists after a successful exit; it never writes
    # or creates it. Lifecycle metadata has a separate, main-repo-owned path.
    artifact_path = None
    if args.result_artifact:
        artifact_path = Path(args.result_artifact)
        if not artifact_path.is_absolute():
            artifact_path = workdir / artifact_path
    metadata_path = AGENT_JOB_DIR / f"{job_id}.json"

    script_args = [
        "--brief-file", str(frozen_brief),
        "--model", args.model,
        "--effort", args.effort,
    ]
    script_args += ["--cwd", str(workdir)]
    if artifact_path is not None:
        script_args += ["--result-artifact", str(artifact_path)]
    script_args += ["--job-metadata", str(metadata_path)]

    # Couple the inner bound to the outer budget. The worker kills the whole script
    # at timeout_seconds; the runner must fire slightly earlier so it can write a
    # diagnosis first. Passing this explicitly is what keeps the two honest — the
    # runner's own default is a floor, and a stale one (see run_agent_job.py).
    outer_timeout = args.timeout or AGENT_DEFAULT_TIMEOUT
    inner_timeout = max(60, outer_timeout - AGENT_TIMEOUT_GRACE)
    script_args += ["--timeout", str(inner_timeout)]

    inner = argparse.Namespace(
        id=job_id,
        title=args.title or f"agent: {brief_path.stem}",
        script="scripts/run_agent_job.py",
        interpreter="uv run python",
        script_args=script_args,
        env=None,
        result_artifact=str(artifact_path) if artifact_path is not None else None,
        output_paths=None,
        job_metadata=str(metadata_path),
        job_kind="agent",
        job_cwd=str(workdir),
        followup_brief=args.followup_brief,
        followup_task_type=args.followup_task_type,
        followup_priority=args.followup_priority,
        queue_priority=getattr(args, "queue_priority", None),
        timeout=outer_timeout,
        brief_source=str(brief_path),
        brief_snapshot=str(frozen_brief),
        timeout_parent_job_id=getattr(args, "timeout_parent_job_id", None),
        split_stage=getattr(args, "split_stage", None),
        source_task_id=getattr(args, "source_task_id", None),
    )
    return enqueue(inner)


def _arg_value(args: Any, flag: str) -> str | None:
    if not isinstance(args, list):
        return None
    if flag not in args:
        return None
    index = args.index(flag)
    return args[index + 1] if index + 1 < len(args) else None


def _runner_failure_class(job: dict[str, Any]) -> str | None:
    """What the runner said killed the agent — `auth`, `quota`, `transient`, or None.

    Written by scripts/run_agent_job.py into the job_metadata receipt. Absent on
    jobs that predate the field, which read as None: the old triage brief.
    """
    meta_path = job.get("job_metadata")
    if not meta_path:
        return None
    path = Path(meta_path)
    if not path.is_absolute():
        path = ROOT / path
    try:
        meta = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        warn("compute_queue", "job_metadata unreadable; falling back to generic triage",
             job=job.get("id"), path=str(path), err=str(e))
        return None
    value = meta.get("failure_class")
    return value if isinstance(value, str) else None


def _sleeping_until(job: dict[str, Any]) -> datetime | None:
    """The job's `not_before`, if it is still in the future. Else None.

    An unparseable `not_before` warns and reads as "no restriction": a corrupt
    timestamp must not strand a job in the queue forever (no-silent-fallback.md
    Pattern B — the fallback is caller-chosen, and here running late beats never).
    """
    raw = job.get("not_before")
    if not raw:
        return None
    when = parse_iso_warn(
        raw, tag="compute_queue", field_name="not_before", fallback=None,
        job_id=job.get("id"),
    )
    if when is None:
        return None
    return when if when > datetime.now(timezone.utc) else None


def _requeue_quota_blocked(job: dict[str, Any]) -> bool:
    """Send a quota-killed agent job back to the queue to wait out the window.

    Returns True if the job was re-queued (caller must not mark it failed), False
    if it should fail normally — either because the wall was not quota, or because
    the job has already spent its patience.
    """
    # Once a followup owns the disposition, the queue must not create a second
    # writer.  This is normally impossible for the automatic path (the worker
    # has not published a terminal receipt yet), but pin the invariant here as
    # well as in the manual CLI so legacy/corrupt receipts fail closed.
    if job.get("followup_dispatched"):
        return False
    if _runner_failure_class(job) != "quota":
        return False
    bounces = job.get("quota_requeues") or 0
    if bounces >= QUOTA_REQUEUE_MAX:
        return False

    job["quota_requeues"] = bounces + 1
    job.setdefault("requeue_history", []).append({
        "at": utc_now(),
        "reason": "quota",
        "exit_code": job.get("exit_code"),
        "started_at": job.get("started_at"),
    })
    job["not_before"] = (
        datetime.now(timezone.utc) + timedelta(seconds=QUOTA_REQUEUE_BACKOFF_S)
    ).isoformat()
    # Back to a clean work order: the attempt that just bounced computed nothing,
    # so leaving its exit code or timestamps on the job would describe a run that
    # never happened. `queued_at` stays put — the job keeps its place in line.
    job["status"] = "queued"
    job["started_at"] = None
    job["completed_at"] = None
    job["exit_code"] = None
    return True


def _agent_workdir(job: dict[str, Any]) -> str | None:
    """Read new schema first, then infer legacy run_agent_job receipts."""
    raw = None
    if job.get("kind") == "agent" and job.get("cwd"):
        raw = str(job["cwd"])
    elif job.get("script_path") == "scripts/run_agent_job.py":
        raw = _arg_value(job.get("args") or [], "--cwd")
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        path = ROOT / path
    path = path.resolve(strict=False)
    if path == ROOT.resolve(strict=False):
        return None
    return str(path)


_EXPERIMENT_ID_RE = re.compile(r"k(\d{3,5})", re.IGNORECASE)


def _certified_verdict_for_job(job: dict[str, Any]) -> dict[str, Any] | None:
    """Advisory: does this job's K-experiment already carry a certified PASS verdict?

    A job's work can be finished outside this queue — the codex salvage/review paths
    do exactly that — and nothing writes back here. The followup then keeps reading as
    work-to-do. On 2026-07-16 two of three pending followups were in that state:
    k1711-mcs-eval had sat for two days asking a fire to split and re-run an evaluation
    that was already merged and PASS-certified, and k1704's collect/rerun/certify chain
    was likewise complete.

    This only ANNOTATES the row; it never drops it. A verdict can predate the job (a
    re-run of an already-adjudicated experiment is legitimate), so only a reader looking
    at the commits can settle whether the followup is truly stale.
    """
    haystack = f"{job.get('id') or ''} {job.get('title') or ''}"
    match = _EXPERIMENT_ID_RE.search(haystack)
    if not match:
        return None
    experiment = f"k{match.group(1)}"
    verdict_path = ROOT / "experiments" / experiment / "review_verdict.json"
    if not verdict_path.is_file():
        return None
    try:
        payload = json.loads(verdict_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        warn(
            "compute_queue",
            "review_verdict unreadable; skipping stale-followup annotation",
            path=str(verdict_path),
            error=str(exc),
        )
        return None
    if not isinstance(payload, dict):
        warn(
            "compute_queue",
            "review_verdict is not a JSON object; skipping stale-followup annotation",
            path=str(verdict_path),
        )
        return None
    # Key names and the normalisation below follow the canonical certificate written by
    # `experiment_gates.py verdict-template` (kid / verdict / reviewed_at / reviewed_commit).
    if str(payload.get("verdict") or "").strip().upper() != "PASS":
        return None
    return {
        "experiment": experiment,
        "kid": payload.get("kid"),
        "verdict_path": str(verdict_path.relative_to(ROOT)),
        "reviewer": payload.get("reviewer"),
        "certified_at": payload.get("reviewed_at"),
        "reviewed_commit": payload.get("reviewed_commit"),
        "advice": (
            f"{experiment} already carries a certified PASS verdict. Check its commits and "
            "knowledge entries to see whether this followup's work is already done BEFORE "
            "executing its brief; if it is, close it out instead of re-running certified work."
        ),
    }


def _pending_followup_view(job: dict[str, Any]) -> dict[str, Any] | None:
    """Return a dispatch view with explicit success-vs-failure semantics."""
    if job.get("followup_dispatched"):
        return None

    certified = _certified_verdict_for_job(job)

    if job.get("status") == "completed" and job.get("claude_followup"):
        row = dict(job)
        row["followup_mode"] = "collect_completed"
        gate = job.get("experiment_gate")
        if isinstance(gate, dict) and gate.get("charged_to") == "experiment":
            # The gate failed over the tree this job reviewed. The job is still
            # completed (see _experiment_gate_failure), but the finding must land
            # somewhere a human acts on, or "charged to the experiment" is just a
            # word for dropped.
            followup = dict(row.get("claude_followup") or {})
            followup["brief"] = "\n".join(
                [
                    str(followup.get("brief") or "").strip(),
                    "",
                    "EXPERIMENT-GATE FINDING — charged to the experiment, NOT to this review job:",
                    f"The repo gates were run over {gate.get('scope')} and FAILED. This job reviewed "
                    "that experiment, so the violation belongs to the experiment's disposition: fold "
                    "it into the experiment's repair task (open one if none exists) and make sure the "
                    "re-review covers it. Do not re-run or re-triage this review job over it.",
                    str(gate.get("report") or "").strip(),
                ]
            )
            row["claude_followup"] = followup
        if certified:
            row["possibly_superseded"] = certified
        return row

    if job.get("status") != "failed":
        return None
    timed_out = _job_timed_out(job)
    workdir = _agent_workdir(job)
    if not workdir and not timed_out:
        return None

    original = job.get("claude_followup") or {}
    if not isinstance(original, dict):
        original = {}
    original_brief = original.get("brief")

    # An auth-class death is not a failure of the WORK — the runner exhausted its
    # retries against a login wall and the agent never started. Sending a fire to
    # "inspect what exists in the worktree" would waste it: nothing exists. Say so,
    # and ask for the one action that can help.
    if timed_out:
        timeout_seconds = int(job.get("timeout_seconds") or 3600)
        triage_lines = [
            "TIMEOUT — SPLIT REQUIRED. This work order reached an execution deadline.",
            f"Parent job: {job.get('id')} (budget={timeout_seconds}s, exit_code={job.get('exit_code')})",
            f"Worktree/cwd (if any): {workdir}",
            f"Result artifact (may be missing, partial, or stale): {job.get('result_artifact')}",
            f"stdout/stderr: {job.get('stdout_file')} | {job.get('stderr_file')}",
            "First inspect and preserve any valid partial outputs. Do not treat them as final results.",
            "Do NOT re-enqueue the same script arguments or unchanged agent brief. Materialize at least "
            "two bounded child stages (for example: data preparation, implementation/checkpoint, compute "
            "shard, validation/review, merge), each with one explicit artifact and success criterion.",
            f"Every compute child must use a timeout shorter than {timeout_seconds}s and record "
            f"--timeout-parent-job-id {job.get('id')} plus a distinct --split-stage value.",
        ]
        if original_brief:
            triage_lines.append(f"Original completed-job followup (context only): {original_brief}")
    elif _runner_failure_class(job) == "auth":
        triage_lines = [
            "AGENT JOB BLOCKED ON AUTH — the `claude` CLI was not logged in, so the agent never ran.",
            f"Job: {job.get('id')} (exit_code={job.get('exit_code')})",
            f"Runner metadata (attempts, failure_class): {job.get('job_metadata')}",
            f"stdout/stderr: {job.get('stdout_file')} | {job.get('stderr_file')}",
            f"Worktree/cwd is untouched and still holds the pre-job state: {workdir}",
            "The runner already retried through its backoff ladder. Confirm the CLI can authenticate "
            "now (the supervisor's own fires are the cheapest signal — if they are landing, auth is back), "
            "then simply RE-ENQUEUE the same brief with enqueue-agent. Do NOT triage the worktree for "
            "salvage and do NOT record any research verdict: no work was performed.",
        ]
        if original_brief:
            triage_lines.append(f"Followup to run once it completes (context only): {original_brief}")
    elif _runner_failure_class(job) == "quota":
        waited_h = round(job.get("quota_requeues", 0) * QUOTA_REQUEUE_BACKOFF_S / 3600, 1)
        triage_lines = [
            "AGENT JOB OUT OF PATIENCE ON QUOTA — the model window never reopened, "
            "so the agent never ran.",
            f"Job: {job.get('id')} (exit_code={job.get('exit_code')})",
            f"The queue already re-queued it {job.get('quota_requeues', 0)} times over ~{waited_h}h "
            f"and it hit the same wall every time (see requeue_history in its job file).",
            f"Runner metadata (failure_class): {job.get('job_metadata')}",
            f"stdout/stderr: {job.get('stdout_file')} | {job.get('stderr_file')}",
            f"Worktree/cwd is untouched and still holds the pre-job state: {workdir}",
            "A window this long is a weekly/monthly limit, not a session one — it outlasts what "
            "the queue can wait out. Confirm the current quota state, then RE-ENQUEUE the same "
            "brief with enqueue-agent once it is back. Do NOT triage the worktree for salvage and "
            "do NOT record any research verdict: no work was performed.",
        ]
        if original_brief:
            triage_lines.append(f"Followup to run once it completes (context only): {original_brief}")
    else:
        triage_lines = [
            "TRIAGE FAILED AGENT JOB — this job did not complete successfully.",
            f"Job: {job.get('id')} (exit_code={job.get('exit_code')})",
            f"Worktree/cwd: {workdir}",
            f"Result artifact (may be missing, partial, or stale): {job.get('result_artifact')}",
            f"Runner metadata: {job.get('job_metadata')}",
            f"stdout/stderr: {job.get('stdout_file')} | {job.get('stderr_file')}",
            "Inspect what actually exists in the worktree. Decide whether to preserve/commit and continue, "
            "re-enqueue from a fresh worktree, or document that nothing is salvageable. Do not treat any "
            "artifact as a successful result without validation, and never force-remove the worktree.",
        ]
        if original_brief:
            triage_lines.append(f"Original completed-job followup (context only): {original_brief}")

    row = dict(job)
    row["followup_mode"] = "split_required" if timed_out else "triage_failed"
    if timed_out:
        row["split_contract"] = {
            "parent_timeout_job_id": job.get("id"),
            "minimum_child_stages": 2,
            "child_timeout_lt_seconds": int(job.get("timeout_seconds") or 3600),
            "identical_retry_prohibited": True,
        }
    original_priority = original.get("priority")
    triage_priority = original_priority if isinstance(original_priority, int) else 2
    row["claude_followup"] = {
        "brief": "\n".join(triage_lines),
        "task_type": "platform_ops",
        "priority": min(triage_priority, 2),
    }
    if certified:
        row["possibly_superseded"] = certified
    return row


def list_jobs(args) -> int:
    ensure_dirs()
    rows = []
    for p in sorted(QUEUE_DIR.glob("*.json")):
        j = _read_job_file(p, context="list")
        if j is None:
            continue
        if args.status and j.get("status") != args.status:
            continue
        if getattr(args, "pending_followup", False):
            view = _pending_followup_view(j)
            if view is None:
                continue
            rows.append(view)
            continue
        if getattr(args, "completed_pending_followup", False):
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


# The open handle whose flock IS the worker mutex. Held for the worker's whole
# lifetime (one run-next slot or an entire drain loop) and dropped by the kernel
# the instant the process dies.
_WORKER_LOCK_HANDLE = None


def _acquire_lock() -> bool:
    """Take the exclusive worker mutex; True means this process now owns it.

    flock, not mtime (D6 refactor): the old scheme wrote a lock file and treated
    >6h-old ones as stale, which was both too patient (a crashed worker blocked
    the queue for up to 6h) and too impatient (a legitimate drain loop can run
    longer than any fixed threshold). A kernel flock has neither hole — it dies
    with its owner. This is also what makes the launchd */15 tick safe restart
    insurance: a tick that lands while a drain loop is alive loses this flock
    and exits immediately. The lock file itself is never unlinked; releasing the
    fd is the release (unlink+recreate would let two processes flock different
    inodes of the "same" path).
    """
    global _WORKER_LOCK_HANDLE
    if _WORKER_LOCK_HANDLE is not None:
        return False  # this process already runs a worker; a second is a bug
    try:
        handle = LOCK_FILE.open("a+", encoding="utf-8")
    except OSError as exc:
        _warn_compute_queue("worker lock write failed; skipping run", LOCK_FILE, exc)
        return False
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return False  # silent-ok: lock held by a live worker; caller prints the skip line
    except OSError as exc:
        handle.close()
        _warn_compute_queue("worker lock flock failed; skipping run", LOCK_FILE, exc)
        return False
    try:
        # Owner stamp is observability only — the flock above is the mutex.
        handle.truncate(0)
        handle.write(f"{os.getpid()} {utc_now()}\n")
        handle.flush()
    except OSError as exc:
        _warn_compute_queue("worker lock owner stamp failed (lock still held)", LOCK_FILE, exc)
    _WORKER_LOCK_HANDLE = handle
    return True


def _release_lock():
    global _WORKER_LOCK_HANDLE
    handle = _WORKER_LOCK_HANDLE
    _WORKER_LOCK_HANDLE = None
    if handle is None:
        return
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def _ready_queued_jobs(context: str) -> tuple[list[tuple[int, str, Path]], int]:
    """Queued jobs allowed to start now, priority-then-arrival ordered.

    Returns (ready, sleeping): `ready` as (priority, queued_at, path) tuples —
    priority first, arrival order within a priority, so a release-blocking
    render never waits out a 90-minute agent that arrived first — and
    `sleeping` counting jobs waiting out a `not_before` quota window (starting
    one of those now would just burn the same five seconds against the same
    wall).
    """
    ready: list[tuple[int, str, Path]] = []
    sleeping = 0
    for p in sorted(QUEUE_DIR.glob("*.json")):
        j = _read_job_file(p, context=context)
        if j is None:
            continue
        if j.get("status") != "queued":
            continue
        if _sleeping_until(j) is not None:
            sleeping += 1
            continue
        ready.append((_scheduling_priority(j), j.get("queued_at", ""), p))
    ready.sort(key=lambda item: (item[0], item[1], str(item[2])))
    return ready, sleeping


def _claim_job(job_path: Path, *, context: str) -> dict[str, Any] | None:
    """Atomically flip one queued job to running; None if someone else got it.

    Compare-and-set under the receipt flock: re-read, verify the job is still
    queued and still allowed to start, then publish `running` in the same
    critical section. Two claimers (parallel drain slots, a stray run-next tick,
    an operator's cancel/amend) can therefore never both own the same job —
    whichever writes first wins and the loser re-reads a non-queued status here
    and walks away. Before this, the scan-then-mark in run_next was a TOCTOU
    that only stayed safe because the worker mutex forbade a second worker.
    """
    with _receipt_lock():
        job = _read_job_file(job_path, context=context)
        if job is None or job.get("status") != "queued":
            return None
        if _sleeping_until(job) is not None:
            return None
        job["status"] = "running"
        job["started_at"] = utc_now()
        job["claimed_by_pid"] = os.getpid()
        _write_job_file(job_path, job)
    return job


def _run_claimed(job_path: Path, job: dict[str, Any]) -> None:
    """Execute one claimed job and always leave a terminal (or re-queued) receipt.

    _execute_job already converts subprocess failures into receipt state; this
    guard covers everything OUTSIDE that inner try (log-dir creation, receipt
    merge, a bug in the postconditions themselves). A drain loop runs for hours,
    so one crashing job must neither kill the loop nor strand a `running`
    receipt that no process is actually running.
    """
    try:
        _execute_job(job_path, job)
    except Exception as exc:  # noqa: BLE001 — fail-loud catch-all; receipt is the trace
        warn(
            "compute_queue",
            "job execution crashed outside the runner guard",
            job=job.get("id"),
            err=f"{type(exc).__name__}: {exc}",
        )
        job["status"] = "failed"
        job["exit_code"] = -3
        job["execution_error"] = f"{type(exc).__name__}: {exc}"
        with _receipt_lock():
            _merge_runtime_output_paths(job_path, job)
            job["completed_at"] = utc_now()
            _write_job_file(job_path, job)
        print(f"done: {job['id']} status=failed exit=-3 (execution error)")


def run_next(args) -> int:
    """Consume at most one queued job — the legacy single-shot entrypoint."""
    ensure_dirs()
    if not _acquire_lock():
        print("worker already running (lock held); skip")
        return 0

    try:
        ready, sleeping = _ready_queued_jobs("run-next")
        for _prio, _queued_at, job_path in ready:
            job = _claim_job(job_path, context="run-next")
            if job is None:
                continue  # lost the claim race; take the next candidate
            print(f"running: {job['id']} ({job['script_path']})")
            _run_claimed(job_path, job)
            return 0
        print(f"no queued jobs ready ({sleeping} waiting on not_before)"
              if sleeping else "no queued jobs")
        return 0
    finally:
        _release_lock()


def _execute_job(job_path: Path, job: dict[str, Any]) -> None:
    """Run one already-claimed job through to its terminal receipt.

    Thread-safe by construction: every path it touches (stdout/stderr logs, the
    per-job receipt) is owned by this job, and receipt writes go through the
    receipt flock, so bounded-parallel drain slots cannot trample each other.
    """
    # Build command
    cmd_parts = shlex.split(job["interpreter"]) + [job["script_path"]] + (job.get("args") or [])
    env = os.environ.copy()
    env.update(job.get("env") or {})
    env["VOLPRED_COMPUTE_JOB_ID"] = str(job["id"])
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
        if proc.returncode != 0:
            job["status"] = "failed"
            if _runner_timed_out(job):
                _mark_timeout(job)
            elif _requeue_quota_blocked(job):
                print(f"quota-blocked: {job['id']} never started — re-queued "
                      f"(bounce {job['quota_requeues']}/{QUOTA_REQUEUE_MAX}, "
                      f"not_before={job['not_before']})")
        else:
            artifact_path = _declared_result_artifact(job)
            if artifact_path is not None and not artifact_path.exists():
                # A successful process without its declared output is not a
                # successful job. Keep both codes: process_exit_code preserves
                # what actually ran; exit_code=3 is the queue postcondition.
                job["process_exit_code"] = proc.returncode
                job["exit_code"] = 3
                job["status"] = "failed"
                job["failure_reason"] = "result_artifact_missing"
                job["missing_result_artifact"] = str(artifact_path)
                with stderr_p.open("a") as se:
                    se.write(f"\n[RESULT_ARTIFACT_MISSING] {artifact_path}\n")
            elif _is_review_job(artifact_path) and (
                unfilled := _review_verdict_unfilled(artifact_path)
            ):
                # The verdict file exists but was never adjudicated (or is
                # not a verdict at all). k528 2026-07-19: existence-only
                # check let a FILL: scaffold pass as a completed review.
                job["process_exit_code"] = proc.returncode
                job["exit_code"] = 5
                job["status"] = "failed"
                job["failure_reason"] = "review_verdict_unfilled"
                job["review_verdict_unfilled"] = unfilled
                with stderr_p.open("a") as se:
                    se.write(f"\n[REVIEW_VERDICT_UNFILLED] {unfilled}\n")
            else:
                gate = _experiment_gate_failure(job, artifact_path)
                if gate is not None:
                    # The artifact exists and the process was happy. That only
                    # means the experiment ran the way its author meant it to.
                    # It broke a rule the repo already paid to learn, so it is
                    # not a completed job -- it routes to triage_failed.
                    job["process_exit_code"] = proc.returncode
                    job["exit_code"] = 4
                    job["status"] = "failed"
                    job["failure_reason"] = "experiment_gate_failed"
                    job["experiment_gate"] = gate
                    with stderr_p.open("a") as se:
                        se.write(f"\n[EXPERIMENT_GATE_FAILED]\n{gate['report']}\n")
                else:
                    job["status"] = "completed"
    except subprocess.TimeoutExpired:
        job["status"] = "failed"
        job["exit_code"] = -1
        _mark_timeout(job)
        stderr_p.write_text(stderr_p.read_text() + "\n[TIMEOUT]\n")
    except Exception as e:
        job["status"] = "failed"
        job["exit_code"] = -2
        stderr_p.write_text(stderr_p.read_text() + f"\n[EXCEPTION] {e}\n")

    with _receipt_lock():
        _merge_runtime_output_paths(job_path, job)
        # A re-queued job did not finish; stamping completed_at would make an
        # attempt that never ran look like a run.
        if job["status"] != "queued":
            job["completed_at"] = utc_now()
        _write_job_file(job_path, job)
    print(f"done: {job['id']} status={job['status']} exit={job['exit_code']}")


def _resolve_max_parallel(cli_value: int | None) -> int:
    """Effective drain-loop parallelism bound.

    Precedence: explicit CLI flag > `max_parallel` on the volpred-compute-worker
    entry in config/runtime_schedules.json > DRAIN_MAX_PARALLEL_DEFAULT. The
    config file wins over a code constant because it is the repo's canonical
    schedule spec (CLAUDE.md: 排程 → config/runtime_schedules.json): ops can
    retune the bound in the same place the job's cadence lives, without a code
    change. Every fallback is loud, and run-loop prints the effective bound at
    startup, so the value in force is always observable in the worker log.
    """
    if cli_value is not None:
        if cli_value < 1:
            raise SystemExit(f"error: --max-parallel must be >= 1, got {cli_value}")
        return cli_value
    config_path = ROOT / "config" / "runtime_schedules.json"
    entries: list[Any] = []
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
        raw_entries = data.get("cron_jobs") if isinstance(data, dict) else None
        entries = raw_entries if isinstance(raw_entries, list) else []
    except (OSError, json.JSONDecodeError) as exc:
        warn(
            "compute_queue",
            "runtime_schedules.json unreadable; using default max_parallel",
            path=str(config_path),
            err=str(exc),
        )
    for entry in entries:
        if isinstance(entry, dict) and entry.get("id") == "volpred-compute-worker":
            raw = entry.get("max_parallel")
            if raw is None:
                break
            if isinstance(raw, int) and not isinstance(raw, bool) and raw >= 1:
                return raw
            warn(
                "compute_queue",
                "invalid max_parallel override in runtime_schedules.json; using default",
                value=repr(raw),
            )
            break
    return DRAIN_MAX_PARALLEL_DEFAULT


def run_loop(args) -> int:
    """Work-conserving drain: consume queued jobs continuously until none remain.

    D6 (owner directive 2026-07-20): the worker costs no Claude tokens, so
    "one job per 15-minute tick" was pure queue latency. This loop claims and
    runs jobs continuously, at most `max_parallel` at a time, rescanning after
    every completion so work enqueued mid-drain is picked up too. It exits when
    nothing is claimable and nothing is in flight. Jobs sleeping on `not_before`
    deliberately do NOT keep the loop alive — the launchd */15 tick is the
    restart insurance that will come back for them (and for a crashed loop);
    when a loop is already draining, that tick's invocation loses the worker
    flock in _acquire_lock and exits immediately.
    """
    ensure_dirs()
    if not _acquire_lock():
        print("worker already running (lock held); skip")
        return 0

    try:
        limit = _resolve_max_parallel(getattr(args, "max_parallel", None))
        print(f"drain-loop: start pid={os.getpid()} max_parallel={limit}")
        jobs_run = 0
        with ThreadPoolExecutor(max_workers=limit, thread_name_prefix="compute-job") as pool:
            in_flight: dict[Future, str] = {}
            while True:
                ready, _sleeping = _ready_queued_jobs("run-loop")
                for _prio, _queued_at, job_path in ready:
                    if len(in_flight) >= limit:
                        break
                    job = _claim_job(job_path, context="run-loop")
                    if job is None:
                        continue  # lost the claim race; take the next candidate
                    print(f"running: {job['id']} ({job['script_path']})")
                    in_flight[pool.submit(_run_claimed, job_path, job)] = str(job["id"])
                if not in_flight:
                    break
                done, _pending = wait(in_flight, return_when=FIRST_COMPLETED)
                for future in done:
                    job_id = in_flight.pop(future)
                    jobs_run += 1
                    exc = future.exception()
                    if exc is not None:
                        # _run_claimed already writes a failed receipt for
                        # job-level crashes; reaching here means the guard
                        # itself failed. Keep draining, but say so.
                        warn(
                            "compute_queue",
                            "drain worker raised past the receipt guard",
                            job=job_id,
                            err=f"{type(exc).__name__}: {exc}",
                        )
        _ready, sleeping = _ready_queued_jobs("run-loop")
        suffix = f" ({sleeping} left waiting on not_before)" if sleeping else ""
        print(f"drain-loop: exit pid={os.getpid()} jobs_run={jobs_run}{suffix}")
        return 0
    finally:
        _release_lock()


def mark_followup_dispatched(args) -> int:
    p = QUEUE_DIR / f"{args.id}.json"
    if not p.exists():
        print(f"error: not found {args.id}", file=sys.stderr)
        return 2
    with _receipt_lock():
        j = _read_job_file(p, context="mark-followup-dispatched")
        if j is None:
            return 2
        # This check and requeue()'s followup check use the same receipt lock.
        # Whichever transition wins makes the other refuse: a queued/running
        # worker and a triage followup can therefore never own the same job at
        # once.  Before this gate, requeue-first followed by mark-followup could
        # leave a queued job carrying an active triage task.
        if j.get("status") not in {"completed", "failed"}:
            print(
                f"error: cannot dispatch followup for {args.id} — "
                f"status={j.get('status')}, not terminal.",
                file=sys.stderr,
            )
            return 2
        j["followup_dispatched"] = True
        j["followup_dispatched_at"] = utc_now()
        if args.next_task_id:
            j["followup_next_task_id"] = args.next_task_id
        _write_job_file(p, j)
    print(f"marked: {args.id} followup_dispatched=true")
    return 0


def _load_queued_job(job_id: str, verb: str) -> tuple[Path, dict[str, Any]] | None:
    """Fetch a job that has not started yet. Caller must already hold the receipt lock.

    A queued spec is a work order nobody has read; an in-flight one is a promise the
    worker is already keeping. Only the first is safe to rewrite, so status is the gate
    — not a timestamp, not "it probably has not started". Refusing loudly is the point:
    before this, the only way to fix a queued job was to hand-edit its JSON, which
    CLAUDE.md forbids, so the real-world choice was "edit it anyway" or "let it run
    wrong". Both happened.
    """
    path = QUEUE_DIR / f"{job_id}.json"
    if not path.exists():
        print(f"error: not found {job_id}", file=sys.stderr)
        return None
    job = _read_job_file(path, context=verb)
    if job is None:
        return None
    status = job.get("status")
    if status != "queued":
        print(
            f"error: cannot {verb} {job_id} — status={status}, not queued. "
            f"A job the worker already picked up is not yours to rewrite; "
            f"let it finish and act on the result.",
            file=sys.stderr,
        )
        return None
    return path, job


def amend(args) -> int:
    """Correct a queued job's spec — the sanctioned alternative to editing its JSON."""
    fields = {
        "followup_brief": args.followup_brief,
        "followup_task_type": args.followup_task_type,
        "followup_priority": args.followup_priority,
        "timeout": args.timeout,
        "brief_file": args.brief_file,
    }
    if not any(v is not None for v in fields.values()):
        print("error: amend needs at least one field to change", file=sys.stderr)
        return 2

    with _receipt_lock():
        loaded = _load_queued_job(args.id, "amend")
        if loaded is None:
            return 2
        path, job = loaded
        changed = []

        if args.brief_file is not None:
            if job.get("kind") != "agent":
                print(f"error: --brief-file only applies to agent jobs (kind={job.get('kind')})",
                      file=sys.stderr)
                return 2
            src = Path(args.brief_file)
            if not src.is_absolute():
                src = ROOT / src
            if not src.exists():
                print(f"error: brief file not found: {src}", file=sys.stderr)
                return 2
            snapshot = job.get("brief_snapshot")
            if not snapshot:
                print(f"error: {args.id} has no brief snapshot (enqueued before snapshotting); "
                      f"cancel and re-enqueue instead", file=sys.stderr)
                return 2
            # Rewrite the frozen copy in place: `args` already points the runner at it,
            # so the snapshot path is the one thing that must NOT move.
            guard_canonical_write(snapshot)
            Path(snapshot).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
            job["brief_source"] = str(src)
            changed.append("brief")

        followup = job.get("claude_followup") or {}
        for key, arg in (
            ("brief", args.followup_brief),
            ("task_type", args.followup_task_type),
            ("priority", args.followup_priority),
        ):
            if arg is not None:
                followup[key] = arg
                changed.append(f"followup.{key}")
        if followup:
            job["claude_followup"] = followup

        if args.timeout is not None:
            job["timeout_seconds"] = args.timeout
            changed.append("timeout")

        job["amended_at"] = utc_now()
        _write_job_file(path, job)

    print(f"amended: {args.id} [{', '.join(changed)}]")
    return 0


def cancel(args) -> int:
    """Drop a queued job before the worker sees it."""
    reason = str(getattr(args, "reason", "") or "").strip()
    if not reason:
        print("error: cancel requires a non-empty --reason for the audit trail", file=sys.stderr)
        return 2
    with _receipt_lock():
        loaded = _load_queued_job(args.id, "cancel")
        if loaded is None:
            return 2
        path, job = loaded
        job["status"] = "cancelled"
        cancelled_at = utc_now()
        job["cancelled_at"] = cancelled_at
        # Keep completed_at populated for generic terminal-state consumers while
        # preserving the semantically precise cancellation timestamp for audit.
        job["completed_at"] = cancelled_at
        job["cancel_reason"] = reason
        # A cancelled job has no result, so it has nothing to follow up on. Saying so
        # explicitly keeps it out of `list --pending-followup` instead of relying on the
        # collector to infer that "cancelled" means "do not triage me".
        job["followup_dispatched"] = True
        _write_job_file(path, job)
    print(f"cancelled: {args.id}")
    return 0


def requeue(args) -> int:
    """Put a failed agent job back in line — only if it never actually ran.

    The worker now re-queues quota-blocked jobs on its own, so this exists for the
    two cases it cannot cover: jobs that failed before that logic landed, and
    auth-class deaths, where the runner's retry ladder is exhausted and a person
    had to log back in before a retry could mean anything.

    The failure class is the gate, and it comes from the runner's own receipt
    rather than from the operator's belief about the job. `auth` and `quota` both
    mean the CLI turned the agent away at the door: no compute, no tokens, an
    untouched worktree. Every other class has a worktree whose state is the whole
    question — re-running it would race the salvage, so this refuses.

    D6b adds one more admissible class: `failure_reason=worker_killed`, stamped
    by the stale-running reaper when the WORKER died (SIGTERM/crash) with the
    job still claimed. Unlike auth/quota this does NOT guarantee the job never
    ran — the reaper already refused to finalize while the dead worker's process
    group had live members, but for kind=agent jobs the operator should still
    confirm the worktree holds nothing worth salvaging before re-running.
    """
    path = QUEUE_DIR / f"{args.id}.json"
    with _receipt_lock():
        if not path.exists():
            print(f"error: not found {args.id}", file=sys.stderr)
            return 2
        job = _read_job_file(path, context="requeue")
        if job is None:
            return 2
        if job.get("status") != "failed":
            print(f"error: cannot requeue {args.id} — status={job.get('status')}, not failed.",
                  file=sys.stderr)
            return 2
        if job.get("followup_dispatched"):
            followup_id = job.get("followup_next_task_id") or "(unknown followup task)"
            print(
                f"error: cannot requeue {args.id} — disposition is owned by "
                f"followup {followup_id}. Do not retry the delegated original receipt.",
                file=sys.stderr,
            )
            return 2
        failure = _runner_failure_class(job)
        worker_killed = job.get("failure_reason") == "worker_killed"
        if failure not in ("auth", "quota") and not worker_killed:
            print(
                f"error: cannot requeue {args.id} — failure_class={failure}. Only auth/quota "
                f"deaths and reaper-stamped worker_killed jobs are safe to re-run: auth/quota "
                f"guarantee the agent never started, worker_killed means the worker (not the "
                f"job) died. Triage this one's worktree instead.",
                file=sys.stderr,
            )
            return 2
        blocked_kind = failure if failure in ("auth", "quota") else "worker_killed"

        job.setdefault("requeue_history", []).append({
            "at": utc_now(),
            "reason": f"manual:{blocked_kind}",
            "exit_code": job.get("exit_code"),
            "started_at": job.get("started_at"),
            "failure_reason": job.get("failure_reason"),
            "by": os.environ.get("VOLPRED_ACTOR") or os.environ.get("VOLPRED_TASK_CLAIM_OWNER"),
        })
        job["status"] = "queued"
        job["started_at"] = None
        job["completed_at"] = None
        job["exit_code"] = None
        job["not_before"] = None
        # The retired attempt's verdict and claim identity now live in
        # requeue_history / reap; leaving them on a queued job would let a
        # LATER unrelated failure inherit `worker_killed` and slip past this
        # very gate on a second requeue.
        job["failure_reason"] = None
        job["claimed_by_pid"] = None
        job["claimed_by_pid_start_wall"] = None
        _write_job_file(path, job)
    if blocked_kind == "worker_killed":
        print(f"requeued: {args.id} (worker died mid-claim; job re-runs from scratch)")
    else:
        print(f"requeued: {args.id} (was {blocked_kind}-blocked; the agent never ran)")
    return 0


def record_output_paths_cli(args) -> int:
    if not record_output_paths(args.id, args.path):
        return 2
    print(f"recorded: {args.id} output_paths={len(args.path)}")
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
    e.add_argument(
        "--output-path",
        dest="output_paths",
        action="append",
        help="Job-owned deliverable path eligible for path-scoped auto-commit (repeatable).",
    )
    e.add_argument("--followup-brief")
    e.add_argument("--followup-task-type")
    e.add_argument("--followup-priority", type=int)
    e.add_argument("--queue-priority", type=int, help="Scheduling priority; lower runs first. Default 1 for release-blocking (lazypack-*) jobs, 5 otherwise.")
    e.add_argument("--timeout", type=int)
    e.add_argument("--timeout-parent-job-id")
    e.add_argument("--split-stage")
    e.add_argument(
        "--source-task-id",
        help="Pool task this job was dispatched for; marked in_progress so A0 stops re-surfacing it.",
    )
    e.set_defaults(func=enqueue)

    ea = sub.add_parser(
        "enqueue-agent",
        help="Queue a long-lived claude -p agent (the ONLY legal way to run one from a dispatch fire).",
    )
    ea.add_argument("--id")
    ea.add_argument("--title")
    ea.add_argument("--brief-file", required=True, help="Agent brief markdown (write it with the Write tool first).")
    ea.add_argument("--model", default="claude-opus-4-8")
    ea.add_argument("--effort", default="high", choices=["low", "medium", "high", "xhigh", "max"])
    ea.add_argument(
        "--cwd",
        required=True,
        help="Registered non-main git worktree where the agent is allowed to write.",
    )
    ea.add_argument("--result-artifact")
    ea.add_argument("--followup-brief")
    ea.add_argument("--followup-task-type")
    ea.add_argument("--followup-priority", type=int)
    ea.add_argument("--queue-priority", type=int, help="Scheduling priority; lower runs first. Default 1 for release-blocking (lazypack-*) jobs, 5 otherwise.")
    ea.add_argument("--timeout", type=int)
    ea.add_argument("--timeout-parent-job-id")
    ea.add_argument("--split-stage")
    ea.add_argument(
        "--source-task-id",
        help="Pool task this job was dispatched for; marked in_progress so A0 stops re-surfacing it.",
    )
    ea.set_defaults(func=enqueue_agent)

    am = sub.add_parser(
        "amend",
        help="Correct a QUEUED job's spec (refuses once running). Use this instead of editing the JSON.",
    )
    am.add_argument("--id", required=True)
    am.add_argument("--brief-file", help="Replace an agent job's frozen brief with this file's contents.")
    am.add_argument("--followup-brief")
    am.add_argument("--followup-task-type")
    am.add_argument("--followup-priority", type=int)
    am.add_argument("--timeout", type=int)
    am.set_defaults(func=amend)

    cx = sub.add_parser("cancel", help="Drop a QUEUED job before the worker picks it up.")
    cx.add_argument("--id", required=True)
    cx.add_argument("--reason", required=True, help="Audit reason for cancelling this work order.")
    cx.set_defaults(func=cancel)

    rq = sub.add_parser(
        "requeue",
        help="Re-queue a FAILED job that never really ran: auth/quota-blocked agent jobs, "
             "or reaper-stamped worker_killed jobs. Refuses any other failure.",
    )
    rq.add_argument("--id", required=True)
    rq.set_defaults(func=requeue)

    l = sub.add_parser("list")
    l.add_argument("--status")
    l.add_argument(
        "--pending-followup",
        action="store_true",
        help="List completed collection and failed-agent worktree triage followups.",
    )
    l.add_argument("--completed-pending-followup", action="store_true")
    l.add_argument("--json", action="store_true")
    l.set_defaults(func=list_jobs)

    s = sub.add_parser("show")
    s.add_argument("id")
    s.set_defaults(func=show)

    r = sub.add_parser("run-next", help="Consume at most ONE queued job (legacy single-shot).")
    r.set_defaults(func=run_next)

    rl = sub.add_parser(
        "run-loop",
        help="Drain the queue: run queued jobs continuously with bounded parallelism until empty.",
    )
    rl.add_argument(
        "--max-parallel",
        dest="max_parallel",
        type=int,
        default=None,
        help="Parallelism bound override (default: `max_parallel` on the volpred-compute-worker "
             "entry in config/runtime_schedules.json, else min(3, cpu//3)).",
    )
    rl.set_defaults(func=run_loop)

    m = sub.add_parser("mark-followup-dispatched")
    m.add_argument("--id", required=True)
    m.add_argument("--next-task-id")
    m.set_defaults(func=mark_followup_dispatched)

    o = sub.add_parser(
        "record-output-paths",
        help="Producer write-back: merge paths actually written by the running job.",
    )
    o.add_argument("--id", required=True)
    o.add_argument("--path", action="append", required=True)
    o.set_defaults(func=record_output_paths_cli)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
