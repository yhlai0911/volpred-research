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
    list --pending-followup: completed collection + failed-job triage
    list --completed-pending-followup: legacy completed-only view
    run-next:  uv run python scripts/compute_queue.py run-next
    run-loop:  uv run python scripts/compute_queue.py run-loop  (drain until empty)
    show:      uv run python scripts/compute_queue.py show <id>
    cancel:    uv run python scripts/compute_queue.py cancel --id ID --reason WHY
    requeue:   uv run python scripts/compute_queue.py requeue --id ID
               (auth/quota/worker_killed failures only)
    reconcile-bindings:
               repair source-task ownership without executing payloads
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
import threading
import time
import uuid
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.dispatch_supervisor import procutil  # noqa: E402
from scripts.dispatch_supervisor.failure_class import classify_output  # noqa: E402
from volpred.canonical_write import guard_canonical_write  # noqa: E402
from volpred.ops.diagnostics import warn  # noqa: E402
from volpred.ops.git_writer_lock import is_registered_linked_worktree  # noqa: E402
from volpred.ops.timestamps import parse_iso_warn  # noqa: E402

# Payload execution is a distinct adapter from process-table probes and other
# subprocess users in this module. Tests replace only this callable so a child
# double cannot transitively alter PID identity or git/gate probes.
_run_job_subprocess = subprocess.run


def _canonical_root() -> Path:
    """Repo root that owns the queue, even when this copy of the script is in a worktree.

    ``ROOT`` follows ``__file__``, so running ``scripts/compute_queue.py`` from inside a
    linked worktree anchors it to that worktree — and every job enqueued there lands in a
    queue directory **no worker ever reads** (the compute worker always runs from the
    canonical checkout). That failure is silent: enqueue prints success, the job never runs.
    It cost K1698 its round-5 Codex review on 2026-07-20 (job queued 06:46, still unstarted
    at 17:10 with the reviewing fire long gone).

    The queue is a global singleton with a single reader, so a worktree-local queue path has
    no correct use — re-anchor rather than fail. A linked worktree's ``.git`` is a file, so
    the git call below is only paid when we are actually in one.
    """
    if not (ROOT / ".git").is_file():
        return ROOT
    try:
        from volpred.ops.git_writer_lock import git_common_dir

        return git_common_dir(ROOT).parent.resolve()
    except Exception:  # silent-ok: unprovable canonical root falls back to script-anchored ROOT.
        return ROOT


QUEUE_ROOT = _canonical_root()
QUEUE_DIR = QUEUE_ROOT / "storage" / "ops" / "compute_queue"
LOCK_FILE = QUEUE_DIR / ".worker.lock"
LOG_DIR = QUEUE_ROOT / "storage" / "logs" / "compute"
AGENT_JOB_DIR = QUEUE_ROOT / "storage" / "ops" / "agent_jobs"
AGENT_BRIEF_DIR = QUEUE_ROOT / "storage" / "ops" / "agent_briefs"

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
# Enqueue writes the durable job before linking the canonical task, so a
# missing task can be a short-lived cross-file split. It is not allowed to
# masquerade as a healthy queued job indefinitely.
SOURCE_TASK_CREATION_GRACE = timedelta(minutes=5)
# ``flock`` is the cross-process owner, but on macOS locks held by separate
# descriptors in one process do not serialize our ThreadPoolExecutor workers
# reliably. Keep the process-local half explicit so one worker never reads the
# canonical task file while a sibling thread is truncating and rewriting it.
_SOURCE_TASK_QUEUE_THREAD_LOCK = threading.RLock()
_RECEIPT_THREAD_LOCK = threading.RLock()


@dataclass(frozen=True)
class QueueReadiness:
    ready: tuple[tuple[int, str, Path], ...]
    sleeping: int
    blocked: tuple[tuple[str, str], ...]
    terminalized: tuple[tuple[str, str], ...]


@contextmanager
def _task_pool_locked_load(tpc: Any):
    """Serialize this process before taking the canonical cross-process lock."""
    with _SOURCE_TASK_QUEUE_THREAD_LOCK:
        with tpc._locked_load() as locked:
            yield locked


@contextmanager
def _task_pool_locked_readonly(tpc: Any):
    """Read the task pool under the same local→cross-process lock order."""
    with _SOURCE_TASK_QUEUE_THREAD_LOCK:
        with tpc._locked_readonly() as tasks:
            yield tasks


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
    """Effective run order key for a queued job; lower runs first.

    An explicit `queue_priority` always wins. Otherwise the job inherits the
    urgency of the work waiting on it: `claude_followup.priority` is the pool
    priority of the task this job was dispatched for, and a P1 task's job has no
    business queueing behind P2 work that merely arrived earlier. Without this,
    every job that did not pass --queue-priority landed on DEFAULT_QUEUE_PRIORITY
    and the sort degenerated to the FIFO it was meant to replace — which is the
    inversion originally reported (assign_98a32740, a P1 agent job, waited ~3h
    behind two P2 jobs queued 90 minutes earlier).

    Taken as a min so the id-derived floor still holds: a release-blocking
    lazypack render stays at RELEASE_BLOCKING_PRIORITY even if the task it
    reports to is P3. Reading the followup rather than backfilling queue files
    also keeps jobs enqueued by older code paths scheduled correctly.
    """
    declared = job.get("queue_priority")
    if isinstance(declared, int) and not isinstance(declared, bool):
        return declared
    floor = _default_queue_priority(str(job.get("id") or ""))
    followup = job.get("claude_followup")
    if isinstance(followup, dict):
        inherited = followup.get("priority")
        if isinstance(inherited, int) and not isinstance(inherited, bool):
            return min(floor, inherited)
    return floor

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
        serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        with tmp.open("w", encoding="utf-8") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        last_error: OSError | None = None
        for _attempt in range(3):
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
                last_error = None
                break
            except OSError as exc:
                last_error = exc
            finally:
                os.close(directory_fd)
        if last_error is not None:
            visible = _read_job_file(path, context="durability-uncertain")
            raise OSError(
                "directory fsync failed after replace; receipt durability "
                f"is uncertain visible_payload_matches={visible == payload}"
            ) from last_error
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass  # silent-ok: os.replace already consumed the temp file.


@contextmanager
def _receipt_lock():
    """Serialize receipt read/merge/write operations across threads/processes."""
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    lock_path = QUEUE_DIR / ".receipts.lock"
    with _RECEIPT_THREAD_LOCK, lock_path.open(
        "a+",
        encoding="utf-8",
    ) as handle:
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


def _artifact_contract_mismatch(job: dict[str, Any]) -> dict[str, Any] | None:
    """Return evidence that the agent succeeded but its exact output is absent."""
    meta_path = job.get("job_metadata")
    if not meta_path:
        return None
    path = Path(str(meta_path))
    if not path.is_absolute():
        path = ROOT / path
    try:
        metadata = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        warn(
            "compute_queue",
            "job_metadata unreadable while checking artifact contract",
            job=job.get("id"),
            path=str(path),
            err=str(exc),
        )
        return None
    if (
        metadata.get("exit_code") == 0
        and metadata.get("timed_out") is False
        and metadata.get("runner_exit_code") not in (None, 0)
        and metadata.get("result_artifact_exists") is False
    ):
        return metadata
    return None


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
        "source_task_link": (
            {
                "state": "pending",
                "attempted_at": None,
                "error": None,
            }
            if getattr(args, "source_task_id", None)
            else None
        ),
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
    with _receipt_lock():
        if job_path.exists():
            print(f"error: {job_id} already exists", file=sys.stderr)
            return 2
        if entry.get("kind") == "agent" and entry.get("cwd"):
            try:
                worktree_collision = _find_live_agent_workdir_collision(
                    Path(str(entry["cwd"])),
                    exclude_job_id=job_id,
                )
            except RuntimeError as exc:
                print(
                    f"error: worktree collision scan failed closed: {exc}",
                    file=sys.stderr,
                )
                return 2
            if worktree_collision is not None:
                print(
                    "error: worktree collision; refusing duplicate agent "
                    f"dispatch: worktree={worktree_collision['worktree']} "
                    f"existing_job={worktree_collision['job_id']} "
                    f"status={worktree_collision['status']} "
                    f"source_task={worktree_collision['source_task_id']}",
                    file=sys.stderr,
                )
                return 2
        _write_job_file(job_path, entry)
    print(f"enqueued: {job_id}")
    link_receipt = _link_source_task(job_id, entry.get("source_task_id"))
    if link_receipt is not None:
        with _receipt_lock():
            latest = _read_job_file(job_path, context="enqueue-source-task-link")
            if latest is None:
                raise RuntimeError(
                    f"job receipt disappeared after enqueue: {job_id}"
                )
            latest["source_task_link"] = link_receipt
            _write_job_file(job_path, latest)
    return 0


def _link_source_task(
    job_id: str,
    task_id: str | None,
) -> dict[str, Any] | None:
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
        return None
    attempted_at = utc_now()
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

        with _task_pool_locked_load(tpc) as (_fh, tasks):
            link_result = _link_source_task_record(
                tpc=tpc,
                tasks=tasks,
                job_id=job_id,
                task_id=task_id,
            )
        print(f"linked source task: {task_id} -> awaiting_agent_job")
        receipt = {
            "state": "linked",
            "attempted_at": attempted_at,
            "linked_at": utc_now(),
            "error": None,
        }
        receipt.update(link_result)
        return receipt
    except (Exception, SystemExit) as exc:  # noqa: BLE001 — durable retry receipt below
        print(f"warning: could not link source task {task_id}: {exc}", file=sys.stderr)
        return {
            "state": "error",
            "attempted_at": attempted_at,
            "linked_at": None,
            "error": f"{type(exc).__name__}: {exc}",
        }


def _link_source_task_record(
    *,
    tpc: Any,
    tasks: list[dict[str, Any]],
    job_id: str,
    task_id: str,
    allow_running_requeue_recovery: bool = False,
) -> dict[str, str]:
    task = tpc._find(tasks, task_id)
    status = str(task.get("status") or "pending")
    bound_job_id = task.get("compute_job_id")
    recovered_from_job_id: str | None = None

    # Before source-task settlement existed, PHASE A could durably mark the
    # terminal receipt collected yet leave the canonical task pinned to it.
    # The receipt is the proof that the old owner is finished *and* handed off;
    # only that exact evidence permits an atomic transfer to this successor.
    if (
        status == "awaiting_agent_job"
        and bound_job_id
        and str(bound_job_id) != job_id
        and task.get("blocked_reason")
        in {
            "external_compute_receipt_pending_collection",
            "external_compute_job_running",
        }
    ):
        prior_path = QUEUE_DIR / f"{bound_job_id}.json"
        prior = _read_job_file(
            prior_path,
            context="source-task-binding-prior-owner",
        )
        if (
            prior is not None
            and str(prior.get("id") or "") == str(bound_job_id)
            and str(prior.get("source_task_id") or "") == task_id
            and prior.get("status") in {"completed", "failed"}
            and prior.get("followup_dispatched") is True
            and _release_collected_source_task(
                task,
                prior,
                next_task_id=prior.get("followup_next_task_id"),
                tpc=tpc,
            )
        ):
            recovered_from_job_id = str(bound_job_id)
            status = "pending"
            bound_job_id = None

    is_idempotent = (
        status == "awaiting_agent_job"
        and str(bound_job_id or "") == job_id
        and task.get("blocked_reason") == "external_compute_job_active"
    )
    is_recoverable_requeue_split = (
        status == "awaiting_agent_job"
        and str(bound_job_id or "") == job_id
        and task.get("blocked_reason")
        == "external_compute_receipt_pending_collection"
    )
    is_recoverable_worker_killed_split = (
        allow_running_requeue_recovery
        and status == "awaiting_agent_job"
        and str(bound_job_id or "") == job_id
        and task.get("blocked_reason") == "external_compute_job_running"
    )
    can_transition = (
        status in {"pending", "claimed", "in_progress"}
        and (not bound_job_id or str(bound_job_id) == job_id)
    )
    if not (
        is_idempotent
        or is_recoverable_requeue_split
        or is_recoverable_worker_killed_split
        or can_transition
    ):
        raise RuntimeError(
            "source task is not legally bindable: "
            f"task_id={task_id} status={status} "
            f"compute_job_id={bound_job_id!r} requested_job_id={job_id}"
        )
    task["compute_job_id"] = job_id
    if is_recoverable_requeue_split or is_recoverable_worker_killed_split:
        task["blocked_reason"] = "external_compute_job_active"
        task.pop("compute_finished_at", None)
    if can_transition:
        previous_status = status
        task["status"] = "awaiting_agent_job"
        task["blocked_reason"] = "external_compute_job_active"
        for field in (
            "claimed_by",
            "claimed_at",
            "claim_expires_at",
            "claim_session_id",
            "started_at",
        ):
            task.pop(field, None)
        tpc._record_status_history(
            task,
            frm=previous_status,
            to="awaiting_agent_job",
            by=f"compute-job:{job_id}",
            note="durable_external_execution_receipt",
        )
    note = f"dispatched to compute job {job_id}; awaiting PHASE A collection"
    if job_id not in str(task.get("result") or ""):
        task["result"] = tpc._append_note(task.get("result"), note)
    return (
        {"recovered_from_job_id": recovered_from_job_id}
        if recovered_from_job_id
        else {}
    )


def _source_task_binding_issues(
    tasks: list[dict[str, Any]],
    *,
    task_id: str,
    job_id: str,
) -> tuple[str, ...]:
    """Return canonical, human-readable ownership predicate failures."""
    task = next(
        (item for item in tasks if str(item.get("id") or "") == task_id),
        None,
    )
    if task is None:
        return ("source_task_missing_from_pool",)
    issues: list[str] = []
    if task.get("status") != "awaiting_agent_job":
        issues.append(f"task_status={task.get('status')!r}")
    bound = str(task.get("compute_job_id") or "")
    if bound != job_id:
        issues.append(f"task_bound_to={bound or None!r}")
    if task.get("blocked_reason") != "external_compute_job_active":
        issues.append(f"blocked_reason={task.get('blocked_reason')!r}")
    return tuple(issues)


def _source_task_binding_is_valid(
    tasks: list[dict[str, Any]],
    *,
    task_id: str,
    job_id: str,
) -> bool:
    """Validate the canonical half of the task↔compute-job ownership pair."""
    return not _source_task_binding_issues(
        tasks,
        task_id=task_id,
        job_id=job_id,
    )


def _canonical_source_task_binding_is_valid(
    *,
    task_id: str,
    job_id: str,
) -> bool:
    from scripts import task_pool_claim as tpc

    with _task_pool_locked_readonly(tpc) as tasks:
        return _source_task_binding_is_valid(
            tasks,
            task_id=task_id,
            job_id=job_id,
        )


def _reconcile_job_source_task_link(
    job_path: Path,
    job: dict[str, Any],
) -> bool:
    task_id = job.get("source_task_id")
    if not task_id:
        return True
    current = job.get("source_task_link")
    if (
        isinstance(current, dict)
        and current.get("state") == "linked"
        and _canonical_source_task_binding_is_valid(
            task_id=str(task_id),
            job_id=str(job["id"]),
        )
    ):
        return True
    from scripts import task_pool_claim as tpc

    attempted_at = utc_now()
    with _task_pool_locked_load(tpc) as (_fh, tasks):
        with _receipt_lock():
            latest = _read_job_file(job_path, context="source-task-link")
            if latest is None or latest.get("status") != "queued":
                return False
            try:
                source_task = tpc._find(
                    tasks,
                    str(latest["source_task_id"]),
                )
            except SystemExit:
                source_task = None
            source_status = (
                str(source_task.get("status") or "pending").lower()
                if source_task is not None
                else None
            )
            if source_task is None:
                queued_at = parse_iso_warn(
                    latest.get("queued_at"),
                    tag="compute_queue",
                    field_name="queued_at",
                    fallback=None,
                    job_id=latest.get("id"),
                )
                if (
                    queued_at is not None
                    and datetime.now(timezone.utc) - queued_at
                    >= SOURCE_TASK_CREATION_GRACE
                ):
                    cancelled_at = utc_now()
                    latest["status"] = "cancelled"
                    latest["cancel_reason"] = (
                        "source_task_missing_after_grace"
                    )
                    latest["cancellation_kind"] = (
                        "automatic_invalid_source_binding"
                    )
                    latest["cancelled_at"] = cancelled_at
                    latest["completed_at"] = cancelled_at
                    latest["followup_dispatched"] = True
                    latest["source_task_settlement"] = {
                        "state": "not_required",
                        "reason": "source_task_missing_after_grace",
                    }
                    latest["source_task_link"] = {
                        "state": "terminal",
                        "reason": "source_task_missing_after_grace",
                    }
                    _write_job_file(job_path, latest)
                    return False
                latest["source_task_link"] = {
                    "state": "blocked",
                    "reason": "source_task_creation_grace",
                    "attempted_at": attempted_at,
                }
                _write_job_file(job_path, latest)
                return False
            if source_status in tpc.TERMINAL_STATUSES:
                cancelled_at = utc_now()
                latest["status"] = "cancelled"
                latest["cancel_reason"] = (
                    f"source_task_terminal:{source_status}"
                )
                latest["cancellation_kind"] = (
                    "automatic_invalid_source_binding"
                )
                latest["cancelled_at"] = cancelled_at
                latest["completed_at"] = cancelled_at
                latest["followup_dispatched"] = True
                latest["source_task_settlement"] = {
                    "state": "not_required",
                    "reason": f"source_task_terminal:{source_status}",
                }
                latest["source_task_link"] = {
                    "state": "terminal",
                    "reason": "source_task_terminal",
                    "source_task_status": source_status,
                }
                _write_job_file(job_path, latest)
                return False
            bound_job_id = str(source_task.get("compute_job_id") or "")
            if (
                source_status == "awaiting_agent_job"
                and bound_job_id
                and bound_job_id != str(latest["id"])
            ):
                owner = _read_job_file(
                    QUEUE_DIR / f"{bound_job_id}.json",
                    context="source-task-binding-owner",
                )
                owner_status = (
                    str(owner.get("status") or "").lower()
                    if owner is not None
                    else ""
                )
                owner_collected = bool(
                    owner is not None
                    and owner_status in {"completed", "failed"}
                    and owner.get("followup_dispatched") is True
                )
                if not owner_collected:
                    if owner is None:
                        reason = "source_task_owner_receipt_missing"
                    elif owner_status in {
                        "pending",
                        "queued",
                        "running",
                        "claimed",
                    }:
                        reason = "source_task_owned_by_live_job"
                    elif owner_status in {"completed", "failed"}:
                        reason = "prior_receipt_pending_collection"
                    else:
                        reason = "source_task_binding_conflict"
                    latest["source_task_link"] = {
                        "state": "blocked",
                        "reason": reason,
                        "attempted_at": attempted_at,
                        "bound_job_id": bound_job_id,
                        "bound_job_status": owner_status or None,
                    }
                    _write_job_file(job_path, latest)
                    return False
            try:
                history = latest.get("requeue_history")
                last_requeue_reason = (
                    history[-1].get("reason")
                    if isinstance(history, list)
                    and history
                    and isinstance(history[-1], dict)
                    else None
                )
                link_result = _link_source_task_record(
                    tpc=tpc,
                    tasks=tasks,
                    job_id=str(latest["id"]),
                    task_id=str(latest["source_task_id"]),
                    allow_running_requeue_recovery=(
                        last_requeue_reason == "manual:worker_killed"
                    ),
                )
                receipt = {
                    "state": "linked",
                    "attempted_at": attempted_at,
                    "linked_at": utc_now(),
                    "error": None,
                }
                receipt.update(link_result)
            except (Exception, SystemExit) as exc:
                receipt = {
                    "state": "error",
                    "reason": "source_task_link_error",
                    "attempted_at": attempted_at,
                    "linked_at": None,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            latest["source_task_link"] = receipt
            _write_job_file(job_path, latest)
    return isinstance(receipt, dict) and receipt.get("state") == "linked"


def _find_task_dispatch_collision(
    *,
    repo_root: Path,
    task_id: str,
    target_workdir: Path,
    runner=subprocess.run,
) -> dict[str, str] | None:
    """Return an unmerged worktree branch already carrying ``task_id``.

    ``enqueue-agent`` is the one dispatch boundary that knows both the canonical
    pool task id and the worktree that is about to receive an expensive agent.
    Keep the collision invariant here rather than duplicating best-effort prompt
    checks in every hourly lane.

    A matching commit already reachable from canonical HEAD is historical and
    therefore harmless. A matching commit reachable from another registered
    worktree branch but not HEAD is live, unmerged work for the same task and
    must stop the second dispatch.
    """

    def git(*args: str) -> subprocess.CompletedProcess:
        try:
            return runner(
                ["git", "-C", str(repo_root), *args],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f"git {' '.join(args[:2])} failed: {exc}") from exc

    matches = git(
        "log", "--all", "--fixed-strings", f"--grep={task_id}", "--format=%H"
    )
    if matches.returncode != 0:
        raise RuntimeError(
            f"git log collision scan failed rc={matches.returncode}: "
            f"{(matches.stderr or '').strip()[-240:]}"
        )
    matching_shas = [line.strip() for line in matches.stdout.splitlines() if line.strip()]
    if not matching_shas:
        return None

    worktrees = git("worktree", "list", "--porcelain")
    if worktrees.returncode != 0:
        raise RuntimeError(
            f"git worktree collision scan failed rc={worktrees.returncode}: "
            f"{(worktrees.stderr or '').strip()[-240:]}"
        )

    records: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in [*(worktrees.stdout or "").splitlines(), ""]:
        if not line:
            if current:
                records.append(current)
                current = {}
            continue
        key, _, value = line.partition(" ")
        if key in {"worktree", "branch"} and value:
            current[key] = value.removeprefix("refs/heads/") if key == "branch" else value

    target = target_workdir.resolve()
    for record in records:
        raw_path = record.get("worktree")
        branch = record.get("branch")
        if not raw_path or not branch or Path(raw_path).resolve() == target:
            continue
        for sha in matching_shas:
            merged = git("merge-base", "--is-ancestor", sha, "HEAD")
            if merged.returncode == 0:
                continue
            if merged.returncode != 1:
                raise RuntimeError(
                    f"cannot determine whether task commit {sha[:12]} is merged into HEAD"
                )
            on_branch = git("merge-base", "--is-ancestor", sha, branch)
            if on_branch.returncode == 0:
                return {"worktree": raw_path, "branch": branch, "commit": sha}
            if on_branch.returncode != 1:
                raise RuntimeError(
                    f"cannot inspect task commit {sha[:12]} on branch {branch}"
                )
    return None


def _find_live_agent_workdir_collision(
    target_workdir: Path,
    *,
    exclude_job_id: str | None = None,
) -> dict[str, str] | None:
    """Return the live compute receipt that already owns one worktree."""
    target = target_workdir.resolve(strict=False)
    for path in sorted(QUEUE_DIR.glob("*.json")):
        job = _read_job_file(path, context="agent-worktree-collision")
        if job is None:
            raise RuntimeError(
                f"cannot verify agent worktree ownership from {path}"
            )
        if (
            str(job.get("id") or path.stem) == str(exclude_job_id or "")
            or job.get("kind") != "agent"
            or job.get("status") not in {"queued", "running", "claimed"}
        ):
            continue
        raw_workdir = job.get("cwd") or _arg_value(
            job.get("args") or [],
            "--cwd",
        )
        if not raw_workdir:
            continue
        candidate = Path(str(raw_workdir))
        if not candidate.is_absolute():
            candidate = ROOT / candidate
        if candidate.resolve(strict=False) != target:
            continue
        return {
            "job_id": str(job.get("id") or path.stem),
            "status": str(job.get("status")),
            "source_task_id": str(job.get("source_task_id") or ""),
            "worktree": str(target),
        }
    return None


def _agent_model_policy(task_type: str | None) -> dict[str, Any]:
    """Resolve the current router choice against the reload-on-use registry."""
    from scripts import model_router
    from volpred.ops.execution.registry import load_provider_registry

    registry = load_provider_registry()
    routed_models = frozenset(model_router.MODEL_TO_CLI_FLAG.values())
    registered_models = frozenset(
        model_id
        for provider in registry.providers
        if provider.enabled
        for model_id in provider.model_ids
    )
    allowed_models = routed_models & registered_models
    model_short, _effort = model_router.pick_model(task_type)
    canonical_model = model_router.MODEL_TO_CLI_FLAG.get(model_short)
    if canonical_model is None or canonical_model not in allowed_models:
        raise RuntimeError(
            "canonical model router choice is absent from provider registry: "
            f"task_type={task_type!r} model={canonical_model!r}"
        )
    return {
        "allowed_models": allowed_models,
        "canonical_model": canonical_model,
        "registry_sha256": registry.sha256,
        "task_type": task_type,
    }


def _remap_retired_agent_model(
    job: dict[str, Any],
) -> dict[str, Any] | None:
    """Replace a queued legacy model immediately before its first spawn."""
    if (
        job.get("kind") != "agent"
        or job.get("script_path") != "scripts/run_agent_job.py"
    ):
        return None
    args = list(job.get("args") or [])
    current_model = _arg_value(args, "--model")
    followup = job.get("claude_followup")
    task_type = (
        str(followup.get("task_type"))
        if isinstance(followup, dict) and followup.get("task_type")
        else None
    )
    policy = _agent_model_policy(task_type)
    if current_model in policy["allowed_models"]:
        return None
    if current_model is None or "--model" not in args:
        raise RuntimeError(
            f"agent job {job.get('id')} has no replaceable --model argument"
        )
    model_index = args.index("--model") + 1
    replacement = str(policy["canonical_model"])
    args[model_index] = replacement
    job["args"] = args
    receipt = {
        "from_model": current_model,
        "to_model": replacement,
        "reason": "frozen_model_retired_before_spawn",
        "task_type": task_type,
        "registry_sha256": str(policy["registry_sha256"]),
        "remapped_at": utc_now(),
    }
    job.setdefault("model_remap_receipts", []).append(receipt)
    return receipt


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

    source_task_id = str(getattr(args, "source_task_id", "") or "").strip()
    if not source_task_id:
        print(
            "error: enqueue-agent requires --source-task-id so duplicate worktree "
            "dispatches can be rejected mechanically",
            file=sys.stderr,
        )
        return 2
    task_type = str(getattr(args, "followup_task_type", "") or "") or None
    try:
        model_policy = _agent_model_policy(task_type)
    except Exception as exc:  # noqa: BLE001 — model admission is fail-closed
        print(
            "error: canonical model router/provider registry unavailable: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 2
    if str(args.model) not in model_policy["allowed_models"]:
        print(
            f"error: model {args.model!r} is not allowed by the "
            "canonical model router/provider registry",
            file=sys.stderr,
        )
        return 2
    try:
        with _receipt_lock():
            worktree_collision = _find_live_agent_workdir_collision(workdir)
    except RuntimeError as exc:
        print(
            f"error: worktree collision scan failed closed: {exc}",
            file=sys.stderr,
        )
        return 2
    if worktree_collision is not None:
        print(
            "error: worktree collision; refusing duplicate agent dispatch: "
            f"worktree={worktree_collision['worktree']} "
            f"existing_job={worktree_collision['job_id']} "
            f"status={worktree_collision['status']} "
            f"source_task={worktree_collision['source_task_id']}",
            file=sys.stderr,
        )
        return 2
    try:
        collision = _find_task_dispatch_collision(
            repo_root=QUEUE_ROOT,
            task_id=source_task_id,
            target_workdir=workdir,
        )
    except RuntimeError as exc:
        print(f"error: task-id collision scan failed closed: {exc}", file=sys.stderr)
        return 2
    if collision:
        print(
            "error: task-id collision; refusing duplicate agent dispatch: "
            f"task={source_task_id} existing_worktree={collision['worktree']} "
            f"branch={collision['branch']} commit={collision['commit'][:12]}",
            file=sys.stderr,
        )
        return 2

    job_id = args.id or f"agent-{brief_path.stem}-{uuid.uuid4().hex[:6]}"

    # The declared artifact and the instructions must describe the same output.
    # Otherwise a typo is discovered only after an expensive agent has exited
    # successfully, when the runner cannot find the exact path it must verify.
    brief_text = brief_path.read_text(encoding="utf-8")
    if args.result_artifact:
        artifact_basename = Path(args.result_artifact).name
        basename_pattern = rf"(?<![A-Za-z0-9_.-]){re.escape(artifact_basename)}(?![A-Za-z0-9_.-])"
        if re.search(basename_pattern, brief_text) is None:
            print(
                "error: --result-artifact basename is absent from the agent brief; "
                "refusing a job whose output contract cannot be satisfied: "
                f"basename={artifact_basename!r} brief={brief_path}",
                file=sys.stderr,
            )
            return 2

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
    frozen_brief.write_text(brief_text, encoding="utf-8")

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
    rc = enqueue(inner)
    if rc != 0:
        frozen_brief.unlink(missing_ok=True)
    return rc


def _arg_value(args: Any, flag: str) -> str | None:
    if not isinstance(args, list):
        return None
    if flag not in args:
        return None
    index = args.index(flag)
    return args[index + 1] if index + 1 < len(args) else None


# Producers may stamp an explicit terminal classification into their own stderr
# (the lazypack render chain writes `[FAILURE_CLASS] none` after its three-layer
# fallback, because stale codex quota lines earlier in the same log would
# otherwise read as a quota death). The LAST marker wins; `none` means "a real
# failure of the work — do not backoff-requeue".
_FAILURE_CLASS_MARKER_RE = re.compile(
    r"^\[FAILURE_CLASS\]\s+(auth|quota|transient|none)\s*$", re.MULTILINE
)
_STDERR_CLASS_TAIL_BYTES = 16_384
_CODEX_QUOTA_RESET_RE = re.compile(r"^\[CODEX_QUOTA_RESET_AT\]\s+(\S+)\s*$", re.MULTILINE)


def _stderr_failure_class(job: dict[str, Any]) -> str | None:
    """Classify a compute-kind job's death from its stderr tail.

    Compute-kind jobs have no runner receipt (`job_metadata` is an agent-runner
    artifact), so before assign_5195e5ae D3 the quota backoff-requeue was
    structurally dead for them: a lazypack job killed by a codex quota wall
    failed terminally while the same wall would have re-queued an agent job.
    Reuses the supervisor's single-owner classifier over the stderr tail; an
    explicit `[FAILURE_CLASS]` producer marker overrides the regexes.
    """
    stderr_file = job.get("stderr_file")
    if not stderr_file:
        return None
    path = Path(str(stderr_file))
    if not path.is_absolute():
        path = ROOT / path
    try:
        with path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - _STDERR_CLASS_TAIL_BYTES))
            tail = fh.read().decode("utf-8", errors="replace")
    except OSError as e:
        warn("compute_queue", "stderr unreadable; failure class unavailable",
             job=job.get("id"), path=str(path), err=str(e))
        return None
    markers = _FAILURE_CLASS_MARKER_RE.findall(tail)
    if markers:
        return None if markers[-1] == "none" else markers[-1]
    return classify_output(tail)


def _runner_failure_class(job: dict[str, Any]) -> str | None:
    """What killed the job — `auth`, `quota`, `transient`, or None.

    Agent-kind jobs: written by scripts/run_agent_job.py into the job_metadata
    receipt (absent on jobs that predate the field, which read as None: the old
    triage brief).  Compute-kind jobs carry no runner receipt, so their class
    comes from the stderr tail via `_stderr_failure_class` — that is what lets
    `_requeue_quota_blocked` cover both kinds with one mechanism.
    """
    meta_path = job.get("job_metadata")
    if not meta_path:
        return _stderr_failure_class(job)
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


def _runner_proves_no_agent_spawn(job: dict[str, Any]) -> bool:
    """Return true only for a typed runner receipt proving zero Popen attempts."""
    meta_path = job.get("job_metadata")
    if not meta_path:
        return False
    path = Path(str(meta_path))
    if not path.is_absolute():
        path = ROOT / path
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        warn(
            "compute_queue",
            "job_metadata unreadable; cannot prove zero agent spawns",
            job=job.get("id"),
            path=str(path),
            err=str(exc),
        )
        return False
    return (
        meta.get("failure_class") == "policy_denial_pre_spawn"
        and meta.get("agent_spawned") is False
        and meta.get("agent_spawn_attempts") == 0
    )


def _codex_quota_reset_at(job: dict[str, Any]) -> datetime | None:
    """Return a runner-published Codex reset clock, if present and valid."""
    stderr_file = job.get("stderr_file")
    if not stderr_file:
        return None
    path = Path(str(stderr_file))
    if not path.is_absolute():
        path = ROOT / path
    try:
        tail = path.read_text(encoding="utf-8", errors="replace")[-_STDERR_CLASS_TAIL_BYTES:]
    except OSError as exc:
        warn("compute_queue", "Codex quota reset marker unreadable",
             job=job.get("id"), path=str(path), err=str(exc))
        return None
    matches = _CODEX_QUOTA_RESET_RE.findall(tail)
    if not matches:
        return None
    return parse_iso_warn(
        matches[-1], tag="compute_queue", field_name="codex_quota_reset_at",
        fallback=None, job_id=job.get("id"),
    )


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
    reset_at = _codex_quota_reset_at(job)
    job.setdefault("requeue_history", []).append({
        "at": utc_now(),
        "reason": "quota",
        "exit_code": job.get("exit_code"),
        "started_at": job.get("started_at"),
        "reset_at": reset_at.isoformat() if reset_at else None,
    })
    now = datetime.now(timezone.utc)
    wait_until = reset_at if reset_at and reset_at > now else (
        now + timedelta(seconds=QUOTA_REQUEUE_BACKOFF_S)
    )
    job["not_before"] = wait_until.isoformat()
    # Canonical queue status remains `queued` so the scheduler can resume it,
    # while attempt_status is the dedicated operator-facing classification.
    job["attempt_status"] = (
        "codex_quota_exhausted" if reset_at else "quota_exhausted"
    )
    job["quota_reset_at"] = reset_at.isoformat() if reset_at else None
    # Back to a clean work order: the attempt that just bounced computed nothing,
    # so leaving its exit code or timestamps on the job would describe a run that
    # never happened. `queued_at` stays put — the job keeps its place in line.
    job["status"] = "queued"
    job["started_at"] = None
    job["completed_at"] = None
    job["exit_code"] = None
    return True


# Canonical pending queue for escalation tasks (module constant so tests can
# point it at a fixture; production never overrides it).
NEXT_TASKS_PATH = ROOT / "storage" / "next_tasks.json"


def _job_arg(job: dict[str, Any], flag: str) -> str | None:
    args = job.get("args") or []
    for i, value in enumerate(args):
        if value == flag and i + 1 < len(args):
            return str(args[i + 1])
    return None


def _maybe_open_lazypack_repair_task(job: dict[str, Any]) -> None:
    """Terminal lazypack render failure → a real P1 repair task, never a black hole.

    assign_5195e5ae D3: before this, a lazypack job whose whole renderer chain
    failed simply sat as a failed receipt — no task, no owner, while the alert
    body claimed a retry mechanism that did not exist.  A non-quota terminal
    failure now files idempotent P1 work into the canonical pool (stable id per
    article, `if_exists='skip'`), so the article stranded in draft has an owner
    the dispatcher is guaranteed to feed.  Quota deaths never reach here — they
    take the `_requeue_quota_blocked` backoff instead.
    """
    job_id = str(job.get("id") or "")
    if not job_id.startswith("lazypack-"):
        return
    article_id = _job_arg(job, "--article-id") or job_id.removeprefix("lazypack-")
    task_id = f"lazypack_render_repair_{article_id}"
    record = {
        "id": task_id,
        "title": f"[lazypack] {article_id} 懶人包 render 三層全敗，文章卡在草稿",
        "description": (
            f"compute job `{job_id}` 的懶人包 render 鏈（codex → agy → deterministic "
            f"self-repair）全數失敗，文章 `{article_id}` 因缺 `## 懶人包圖組` 被 release "
            "gate 擋住。\n\n"
            "先重新驗證：文章若已補上圖組（後續 job 救回），只記錄 no-op 後完成。\n"
            "仍缺圖時依序排查：\n"
            f"1. 讀 stderr 找出 deterministic 層的具體 violation：{job.get('stderr_file')}\n"
            f"2. plan 檔：{_job_arg(job, '--plan')} — 三層都救不回通常代表 plan 的文案量"
            "超過版面（縮短 blocks 文字或拆面板），修 plan 後重新 enqueue。\n"
            "3. 若是 renderer bug，修 scripts/lazypack_render.py 並補 regression test。\n"
            f"重新排隊：uv run python scripts/lazypack_async_render.py enqueue "
            f"--article-id {article_id} --plan <fixed-plan>"
        ),
        "task_type": "platform_ops",
        "priority": 1,
        "status": "pending",
        "source": "compute_queue_lazypack_failure",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "tags": ["lazypack", "render_failure"],
        "payload": {
            "job_id": job_id,
            "article_id": article_id,
            "exit_code": job.get("exit_code"),
            "stderr_file": job.get("stderr_file"),
        },
    }
    try:
        from volpred.ops.next_tasks import append_task_record

        # Admission may clamp machine-source P1 → P2 (dispatch-lanes R2); report
        # the priority the pool actually admitted, not the one we asked for.
        rec, created = append_task_record(record, path=NEXT_TASKS_PATH, if_exists="skip")
        admitted = f"created (P{rec.get('priority')})" if created else (
            "already pending — not duplicated"
        )
        print(f"repair-task: {task_id} {admitted}")
    except Exception as exc:  # noqa: BLE001 — escalation must not mask the receipt
        warn("compute_queue", "lazypack repair task creation failed",
             job=job_id, task_id=task_id, err=f"{type(exc).__name__}: {exc}")


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
    contract_mismatch = None if timed_out else _artifact_contract_mismatch(job)
    workdir = _agent_workdir(job)
    # "No worktree" is not the same as "nothing to act on". Only kind=agent jobs
    # ever carry a cwd, so this guard used to drop EVERY failed compute job on the
    # floor — including ones whose enqueuer attached a claude_followup and a
    # source_task_id and is sitting in the task pool waiting for that collection.
    # k1730_armA_production_run_20260721 failed its experiment gate and starved its
    # parent task k1731_F3_armA_production_recheck for 62.9h that way; 20 receipts
    # were in that hole at once. A job with nothing to follow up on says so
    # explicitly via followup_dispatched (see cancel()), which is checked above.
    if not workdir and not timed_out and not job.get("claude_followup"):
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
    elif contract_mismatch:
        near_misses = contract_mismatch.get("result_artifact_near_misses") or []
        triage_lines = [
            "ARTIFACT CONTRACT MISMATCH — the agent exited successfully, but the exact declared output path is missing.",
            f"Job: {job.get('id')} (agent_exit_code=0, runner_exit_code={contract_mismatch.get('runner_exit_code')})",
            f"Declared result artifact: {contract_mismatch.get('result_artifact') or job.get('result_artifact')}",
            f"Near-miss candidates: {near_misses or '(none found)'}",
            f"Runner metadata: {job.get('job_metadata')}",
            f"stdout/stderr: {job.get('stdout_file')} | {job.get('stderr_file')}",
            f"Worktree/cwd: {workdir}",
            "Inspect the declared path and candidates, validate the existing output, and repair the path contract or collect the valid artifact.",
            "Do NOT re-enqueue the agent: the work itself succeeded, and a fresh run would only duplicate it.",
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
            "TRIAGE FAILED JOB — this job did not complete successfully.",
            f"Job: {job.get('id')} (exit_code={job.get('exit_code')}, "
            f"failure_reason={job.get('failure_reason')})",
            f"Worktree/cwd: {workdir or '(none — this is a compute job, it ran against the repo)'}",
            f"Script: {job.get('script_path')}",
            f"Result artifact (may be missing, partial, or stale): {job.get('result_artifact')}",
            f"Runner metadata: {job.get('job_metadata')}",
            f"stdout/stderr: {job.get('stdout_file')} | {job.get('stderr_file')}",
            "Inspect what actually exists on disk. Decide whether to preserve/commit and continue, "
            "re-enqueue from a fresh worktree, or document that nothing is salvageable. Do not treat any "
            "artifact as a successful result without validation, and never force-remove the worktree.",
        ]
        if job.get("failure_reason") == "experiment_gate_failed":
            gate = job.get("experiment_gate") or {}
            triage_lines += [
                "",
                "The SCRIPT ran to completion (process_exit_code=0) — the repo experiment gate is what "
                "failed, so any artifact it wrote is UNCERTIFIED, not absent. Fix the violation below "
                "and re-run; do not adopt the numbers as-is and do not weaken the gate.",
                str(gate.get("report") or "").strip(),
            ]
        if original_brief:
            triage_lines.append(f"Original completed-job followup (context only): {original_brief}")

    row = dict(job)
    if timed_out:
        row["followup_mode"] = "split_required"
    elif contract_mismatch:
        row["followup_mode"] = "artifact_contract_mismatch"
    else:
        row["followup_mode"] = "triage_failed"
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


# This process's own `ps lstart` fingerprint, probed once and cached — our own
# start time never changes for the life of the process.
_OWN_START_WALL: str | None = None


def _own_start_wall() -> str | None:
    """Fingerprint of THIS worker process for claim receipts, or None.

    Fail-open by design: a claim without a fingerprint is still safe (the
    reaper's worker-flock invariant covers it), so a broken/patched `ps` must
    not block claiming work — but it must say so out loud.
    """
    global _OWN_START_WALL
    if _OWN_START_WALL is not None:
        return _OWN_START_WALL
    try:
        wall = procutil.get_process_start_wall(os.getpid())
    except Exception as exc:  # noqa: BLE001 — e.g. monkeypatched subprocess in tests
        warn(
            "compute_queue",
            "own start-wall probe raised; claims will carry no fingerprint",
            err=f"{type(exc).__name__}: {exc}",
        )
        return None
    if not wall:
        # PROBE_FAILED (already logged by procutil) or an empty ps row for our
        # own live pid — either way there is nothing usable to pin.
        warn("compute_queue", "own start-wall probe returned no usable fingerprint")
        return None
    _OWN_START_WALL = wall
    return wall


# Terminal exit code the reaper stamps on a job whose worker died under it.
# Distinct from -1 (timeout), -2 (runner exception), -3 (execution-guard crash):
# those describe the JOB failing; -4 describes the WORKER dying (SIGTERM /
# crash / power loss) with the job still claimed.
WORKER_KILLED_EXIT_CODE = -4


def _stale_running_verdict(job: dict[str, Any]) -> tuple[bool, str]:
    """(claimer_is_dead, evidence) for one `running` receipt.

    MUST be judged while THIS process holds the worker flock. That flock is the
    load-bearing fact: jobs are only ever claimed and run inside a worker
    process that holds the flock for its entire lifetime (_acquire_lock ->
    finally _release_lock), and the kernel drops it at process death. So while
    we own the flock, no live legitimate claimer can exist anywhere. The pid
    probes below are pid-reuse-safe evidence collection (same `ps lstart`
    fingerprint scheme as scripts/dispatch_supervisor/procutil.py), not the
    safety argument itself:

    - no recorded pid                  -> flock verdict alone: claimer dead.
    - pid confirmed gone               -> claimer dead.
    - pid alive, fingerprint differs   -> pid recycled by an unrelated process;
                                          claimer dead.
    - pid alive, fingerprint matches   -> contradicts the flock invariant;
                                          refuse to reap (never finalize work we
                                          cannot explain) and say so loudly.
    - liveness probe failed            -> unverified; skip, next worker start
                                          retries.

    Even a dead claimer can leave live orphaned CHILDREN (the worker was
    SIGTERM'd alone and its subprocess got reparented). If the dead worker's
    process group still holds live members, the job's actual computation may
    still be executing — finalizing it now could race a later manual requeue
    against that survivor. Skip until the group drains; the launchd */15 tick
    guarantees another look.
    """
    pid = job.get("claimed_by_pid")
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return True, (
            "no claimed_by_pid on receipt; reaper holds the worker flock, so no "
            "live worker can own this claim"
        )
    if pid == os.getpid():
        return False, "claimed by this very process — reaper never self-reaps"
    current = procutil.get_process_start_wall(pid)
    if current is procutil.PROBE_FAILED:
        return False, f"pid={pid} liveness probe failed; leaving for the next worker start"
    expected = job.get("claimed_by_pid_start_wall")
    if current is not None:
        if expected and current == expected:
            return False, (
                f"pid={pid} alive with matching start-wall fingerprint {current!r} "
                "— refusing to reap a live claimer (flock invariant violated?)"
            )
        if not expected:
            # Legacy receipt (claimed before D6b recorded fingerprints) whose pid
            # number is now held by SOME process. The flock invariant proves the
            # claimer is dead (a live claimer would still hold the flock we own),
            # so this live pid must be an unrelated recycle — but say exactly
            # that in the evidence, because it is inference, not observation.
            evidence = (
                f"pid={pid} number is alive but receipt has no fingerprint; "
                "worker flock held by reaper proves the claimer died — treating "
                "the live pid as an unrelated recycle"
            )
        else:
            evidence = (
                f"pid={pid} alive but start-wall fingerprint differs "
                f"(claimed {expected!r}, found {current!r}) — pid recycled, claimer dead"
            )
    else:
        evidence = f"pid={pid} confirmed gone (ps reports no such process)"
    # Claimer dead — but check for surviving orphaned children before finalizing.
    members = procutil.pgid_members_checked(pid)
    if members is None:
        return False, (
            f"pid={pid} claimer dead but pgid probe failed; cannot rule out live "
            "orphaned children — leaving for the next worker start"
        )
    if members:
        return False, (
            f"pid={pid} claimer dead but its process group still holds live "
            f"members {members} — job may still be executing; skip until they drain"
        )
    return True, evidence


def _reap_stale_running(context: str) -> int:
    """Finalize orphan `running` receipts left behind by a dead worker (D6b).

    2026-07-20 incident: the D6 drain loop was SIGTERM'd mid-job and its two
    claimed receipts sat at status=running forever. The crash guard
    (_run_claimed) only covers exceptions — a signal kills the process before
    any `except` runs — and `cancel` correctly refuses running jobs, so nothing
    could ever retire them. This runs at worker start, right after the worker
    flock is acquired (the one moment we KNOW no other worker is alive): every
    running receipt whose claimer is provably dead is finalized to
    failed/worker_killed, which routes agent jobs into the normal
    `list --pending-followup` triage and makes both kinds eligible for
    `requeue`. Returns the number of receipts reaped.
    """
    reaped = 0
    for path in sorted(QUEUE_DIR.glob("*.json")):
        job = _read_job_file(path, context=context)
        if job is None or job.get("status") != "running":
            continue
        dead, evidence = _stale_running_verdict(job)
        if not dead:
            warn(
                "compute_queue",
                "running receipt left alone by stale-running reaper",
                job=job.get("id"),
                evidence=evidence,
            )
            continue
        source_settlement = _transition_source_task_after_worker_exit(job)
        with _receipt_lock():
            current = _read_job_file(path, context=context)
            if current is None or current.get("status") != "running":
                # Finalized by someone else between our scan and this lock —
                # nothing left to reap. Loud enough via their own write.
                continue
            now = utc_now()
            current["status"] = "failed"
            current["exit_code"] = WORKER_KILLED_EXIT_CODE
            current["failure_reason"] = "worker_killed"
            current["completed_at"] = now
            current["reap"] = {
                "at": now,
                "by_pid": os.getpid(),
                "context": context,
                "evidence": evidence,
                "orphaned_started_at": current.get("started_at"),
            }
            current["source_task_settlement"] = source_settlement
            _write_job_file(path, current)
        stderr_file = current.get("stderr_file")
        if stderr_file:
            try:
                with Path(stderr_file).open("a", encoding="utf-8") as se:
                    se.write(f"\n[WORKER_KILLED] reaped at {now}: {evidence}\n")
            except OSError as exc:
                warn(
                    "compute_queue",
                    "reap stderr marker write failed (receipt already finalized)",
                    job=current.get("id"),
                    err=str(exc),
                )
        print(f"reaped: {current['id']} worker_killed ({evidence})")
        reaped += 1
    return reaped


def _transition_source_task_after_worker_exit(
    job: dict[str, Any],
) -> dict[str, Any] | None:
    task_id = job.get("source_task_id")
    if not task_id:
        return None
    attempted_at = utc_now()
    try:
        from scripts import task_pool_claim as tpc

        with _task_pool_locked_load(tpc) as (_fh, tasks):
            task = tpc._find(tasks, str(task_id))
            if (
                task.get("status") != "awaiting_agent_job"
                or str(task.get("compute_job_id") or "") != str(job["id"])
                or task.get("blocked_reason")
                not in {
                    "external_compute_job_active",
                    "external_compute_job_running",
                    "external_compute_receipt_pending_collection",
                }
            ):
                raise RuntimeError(
                    "source task no longer matches reaped compute job"
                )
            task["blocked_reason"] = (
                "external_compute_receipt_pending_collection"
            )
            task["compute_finished_at"] = attempted_at
        return {
            "state": "settled",
            "task_id": str(task_id),
            "settled_at": attempted_at,
            "error": None,
        }
    except (Exception, SystemExit) as exc:
        warn(
            "compute_queue",
            "reaper could not settle source task",
            job=job.get("id"),
            task_id=task_id,
            err=f"{type(exc).__name__}: {exc}",
        )
        return {
            "state": "error",
            "task_id": str(task_id),
            "settled_at": None,
            "error": f"{type(exc).__name__}: {exc}",
        }


def _scan_queue_readiness(context: str) -> QueueReadiness:
    """Queued jobs allowed to start now, priority-then-arrival ordered.

    `ready` contains (priority, queued_at, path) tuples —
    priority first, arrival order within a priority, so a release-blocking
    render never waits out a 90-minute agent that arrived first — and
    `sleeping` counting jobs waiting out a `not_before` quota window (starting
    one of those now would just burn the same five seconds against the same
    wall). `blocked` names every queued job whose ownership cannot currently
    reconcile, so callers cannot mistake a dead queue for an empty one.
    """
    ready: list[tuple[int, str, Path]] = []
    sleeping = 0
    blocked: list[tuple[str, str]] = []
    terminalized: list[tuple[str, str]] = []
    for p in sorted(QUEUE_DIR.glob("*.json")):
        j = _read_job_file(p, context=context)
        if j is None:
            continue
        if j.get("status") == "cancelled":
            _reconcile_cancelled_source_task(p, j)
            continue
        if j.get("status") != "queued":
            continue
        if not _reconcile_job_source_task_link(p, j):
            latest = _read_job_file(
                p,
                context=f"{context}-blocked-readback",
            )
            if latest is not None and latest.get("status") == "queued":
                link = latest.get("source_task_link")
                reason = (
                    str(link.get("reason") or "source_task_link_error")
                    if isinstance(link, dict)
                    else "source_task_link_error"
                )
                blocked.append((str(latest.get("id") or p.stem), reason))
            elif (
                latest is not None
                and latest.get("status") == "cancelled"
                and latest.get("cancellation_kind")
                == "automatic_invalid_source_binding"
            ):
                link = latest.get("source_task_link")
                reason = (
                    str(link.get("reason") or "invalid_source_binding")
                    if isinstance(link, dict)
                    else "invalid_source_binding"
                )
                terminalized.append(
                    (str(latest.get("id") or p.stem), reason)
                )
            continue
        if _sleeping_until(j) is not None:
            sleeping += 1
            continue
        ready.append((_scheduling_priority(j), j.get("queued_at", ""), p))
    ready.sort(key=lambda item: (item[0], item[1], str(item[2])))
    return QueueReadiness(
        ready=tuple(ready),
        sleeping=sleeping,
        blocked=tuple(blocked),
        terminalized=tuple(terminalized),
    )


def _ready_queued_jobs(context: str) -> tuple[list[tuple[int, str, Path]], int]:
    """Compatibility view for callers that only consume ready/sleeping."""
    scan = _scan_queue_readiness(context)
    return list(scan.ready), scan.sleeping


def reconcile_bindings(args) -> int:
    """Repair source ownership without claiming or executing any payload."""
    ensure_dirs()
    if not _acquire_lock():
        print("worker already running (lock held); cannot reconcile safely")
        return 4
    try:
        queued_before: set[str] = set()
        for path in sorted(QUEUE_DIR.glob("*.json")):
            job = _read_job_file(path, context="reconcile-bindings-before")
            if job is not None and job.get("status") == "queued":
                queued_before.add(str(job.get("id") or path.stem))

        scan = _scan_queue_readiness("reconcile-bindings")
        reason_counts = Counter(reason for _job_id, reason in scan.blocked)
        report = {
            "queued_before": len(queued_before),
            "ready": len(scan.ready),
            "sleeping": scan.sleeping,
            "blocked": len(scan.blocked),
            "terminalized": len(scan.terminalized),
            "blocked_reasons": dict(sorted(reason_counts.items())),
        }
        if getattr(args, "json", False):
            print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        else:
            print(
                "reconcile-bindings: "
                + " ".join(f"{key}={value}" for key, value in report.items())
            )
        return 3 if scan.blocked else 0
    finally:
        _release_lock()


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
    def claim_under_receipt_lock(
        claimed_by_pid_start_wall: str | None,
        canonical_tasks: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        job = _read_job_file(job_path, context=context)
        if job is None or job.get("status") != "queued":
            return None
        current_task_id = job.get("source_task_id")
        if current_task_id and (
            canonical_tasks is None
            or not _source_task_binding_is_valid(
                canonical_tasks,
                task_id=str(current_task_id),
                job_id=str(job["id"]),
            )
        ):
            return None
        source_link = job.get("source_task_link")
        if (
            job.get("source_task_id")
            and (
                not isinstance(source_link, dict)
                or source_link.get("state") != "linked"
            )
        ):
            return None
        if _sleeping_until(job) is not None:
            return None
        job["status"] = "running"
        job["started_at"] = utc_now()
        job["claimed_by_pid"] = os.getpid()
        # D6b: pid-reuse-safe fingerprint (same lstart scheme as the dispatch
        # supervisor's procutil). The probe happens before the receipt critical
        # section: it may execute `ps`, and no external subprocess belongs
        # inside a queue-wide flock. None means the reaper falls back to the
        # worker-flock invariant.
        job["claimed_by_pid_start_wall"] = claimed_by_pid_start_wall
        _write_job_file(job_path, job)
        return job

    initial = _read_job_file(job_path, context=context)
    if initial is None or initial.get("status") != "queued":
        return None
    # Probe before either the canonical-task or receipt lock. Besides keeping
    # the receipt critical section bounded, this prevents a subprocess adapter
    # that writes producer output receipts from recursively taking the same
    # flock (tests exercise that real adapter shape).
    claimed_by_pid_start_wall = _own_start_wall()
    task_id = initial.get("source_task_id")
    if not task_id:
        with _receipt_lock():
            return claim_under_receipt_lock(claimed_by_pid_start_wall)

    # Lock order is canonical task SH -> compute receipt EX, matching the
    # writer's canonical task EX -> compute receipt EX order. Holding the task
    # lock through the receipt compare-and-set prevents a reassignment between
    # validation and publishing `running`.
    from scripts import task_pool_claim as tpc

    with _task_pool_locked_readonly(tpc) as tasks:
        if not _source_task_binding_is_valid(
            tasks,
            task_id=str(task_id),
            job_id=str(initial["id"]),
        ):
            return None
        with _receipt_lock():
            return claim_under_receipt_lock(claimed_by_pid_start_wall, tasks)


@contextmanager
def _source_task_execution_fence(job: dict[str, Any]):
    """Fence only the source task while its external child is running."""
    task_id = job.get("source_task_id")
    if not task_id:
        yield True
        return
    from scripts import task_pool_claim as tpc
    from volpred.ops.next_tasks import (
        normalize_task_priority,
        task_execution_fence_paths,
        task_record_sha256,
    )

    lock_path, metadata_path = task_execution_fence_paths(
        tpc.NEXT_TASKS,
        str(task_id),
    )
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as fence_handle:
        activated = False
        fence_locked = False
        binding_valid = False
        try:
            # Lock order is canonical queue EX -> task fence EX. Taking the
            # task fence first exposed stale metadata from its previous use
            # while this thread waited for the queue lock; parallel jobs then
            # rejected one another as if an unrelated task had changed.
            with _task_pool_locked_load(tpc) as (_fh, tasks):
                fcntl.flock(fence_handle.fileno(), fcntl.LOCK_EX)
                fence_locked = True
                if not _source_task_binding_is_valid(
                    tasks,
                    task_id=str(task_id),
                    job_id=str(job["id"]),
                ):
                    current = tpc._find(tasks, str(task_id))
                    normalize_task_priority(current)
                    _write_job_file(
                        metadata_path,
                        {
                            "task_id": str(task_id),
                            "job_id": str(job["id"]),
                            "record_sha256": task_record_sha256(current),
                            "activated_at": None,
                        },
                    )
                else:
                    task = tpc._find(tasks, str(task_id))
                    task["blocked_reason"] = "external_compute_job_running"
                    task["compute_started_at"] = utc_now()
                    normalize_task_priority(task)
                    activated = True
                    binding_valid = True
                    _write_job_file(
                        metadata_path,
                        {
                            "task_id": str(task_id),
                            "job_id": str(job["id"]),
                            "record_sha256": task_record_sha256(task),
                            "activated_at": utc_now(),
                        },
                    )
            yield binding_valid
        finally:
            if fence_locked:
                fcntl.flock(fence_handle.fileno(), fcntl.LOCK_UN)
            if activated:
                try:
                    settled_at = utc_now()
                    with _task_pool_locked_load(tpc) as (_fh, tasks):
                        task = tpc._find(tasks, str(task_id))
                        if (
                            str(task.get("compute_job_id") or "")
                            == str(job["id"])
                            and task.get("blocked_reason")
                            == "external_compute_job_running"
                        ):
                            task["blocked_reason"] = (
                                "external_compute_receipt_pending_collection"
                            )
                            task["compute_finished_at"] = settled_at
                        else:
                            raise RuntimeError(
                                "source task ownership changed before "
                                "execution settlement"
                            )
                    job["source_task_settlement"] = {
                        "state": "pending_collection",
                        "task_id": str(task_id),
                        "settled_at": settled_at,
                        "error": None,
                    }
                except (Exception, SystemExit) as exc:
                    job["source_task_settlement"] = {
                        "state": "error",
                        "task_id": str(task_id),
                        "settled_at": None,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                    warn(
                        "compute_queue",
                        "could not settle source task execution fence",
                        task_id=task_id,
                        job_id=job.get("id"),
                        err=f"{type(exc).__name__}: {exc}",
                    )


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
        _reap_stale_running("run-next")
        scan = _scan_queue_readiness("run-next")
        if scan.terminalized:
            terminal_reason_counts = Counter(
                reason for _job_id, reason in scan.terminalized
            )
            terminal_reason_summary = ",".join(
                f"{reason}={count}"
                for reason, count in sorted(terminal_reason_counts.items())
            )
            print(
                "binding-reconcile: "
                f"binding_terminalized={len(scan.terminalized)} "
                f"terminalized_reasons={terminal_reason_summary}"
            )
        for _prio, _queued_at, job_path in scan.ready:
            job = _claim_job(job_path, context="run-next")
            if job is None:
                continue  # lost the claim race; take the next candidate
            print(f"running: {job['id']} ({job['script_path']})")
            _run_claimed(job_path, job)
            return 0
        if scan.blocked:
            reason_counts = Counter(reason for _job_id, reason in scan.blocked)
            reason_summary = ",".join(
                f"{reason}={count}"
                for reason, count in sorted(reason_counts.items())
            )
            print(
                "no queued jobs ready "
                f"(binding_blocked={len(scan.blocked)} "
                f"reasons={reason_summary}"
                + (
                    f" binding_terminalized={len(scan.terminalized)}"
                    if scan.terminalized
                    else ""
                )
                + ")"
            )
            return 3
        if scan.terminalized:
            reason_counts = Counter(
                reason for _job_id, reason in scan.terminalized
            )
            reason_summary = ",".join(
                f"{reason}={count}"
                for reason, count in sorted(reason_counts.items())
            )
            print(
                "no queued jobs ready "
                f"(binding_terminalized={len(scan.terminalized)} "
                f"terminalized_reasons={reason_summary})"
            )
            return 0
        print(
            f"no queued jobs ready ({scan.sleeping} waiting on not_before)"
            if scan.sleeping
            else "no queued jobs"
        )
        return 0
    finally:
        _release_lock()


def _execute_job(job_path: Path, job: dict[str, Any]) -> None:
    """Run one already-claimed job through to its terminal receipt.

    Thread-safe by construction: every path it touches (stdout/stderr logs, the
    per-job receipt) is owned by this job, and receipt writes go through the
    receipt flock, so bounded-parallel drain slots cannot trample each other.
    """
    env = os.environ.copy()
    env.update(job.get("env") or {})
    env["VOLPRED_COMPUTE_JOB_ID"] = str(job["id"])
    stdout_p = Path(job["stdout_file"])
    stderr_p = Path(job["stderr_file"])
    stdout_p.parent.mkdir(parents=True, exist_ok=True)

    preflight_error: str | None = None
    proc: subprocess.CompletedProcess | None = None
    try:
        with stdout_p.open("w") as so, stderr_p.open("w") as se:
            # A task-local fence protects only this source record from the last
            # binding CAS until the child exits. Other queue tasks remain fully
            # writable, and a child may safely materialize unrelated work.
            with _source_task_execution_fence(job) as binding_valid:
                if binding_valid:
                    try:
                        remap_receipt = _remap_retired_agent_model(job)
                        if remap_receipt is not None:
                            with _receipt_lock():
                                _write_job_file(job_path, job)
                            print(
                                "model-remapped: "
                                f"{job['id']} "
                                f"{remap_receipt['from_model']}→"
                                f"{remap_receipt['to_model']}",
                                file=so,
                                flush=True,
                            )
                    except Exception as exc:  # noqa: BLE001 — fail closed before Popen
                        preflight_error = (
                            f"{type(exc).__name__}: {exc}"
                        )
                        print(
                            "[AGENT_MODEL_PREFLIGHT_DENIED] "
                            f"{preflight_error}",
                            file=se,
                            flush=True,
                        )
                    if preflight_error is None:
                        cmd_parts = (
                            shlex.split(job["interpreter"])
                            + [job["script_path"]]
                            + (job.get("args") or [])
                        )
                        proc = _run_job_subprocess(
                            cmd_parts,
                            cwd=str(ROOT),
                            env=env,
                            stdout=so,
                            stderr=se,
                            timeout=job.get("timeout_seconds", 3600),
                        )
        if not binding_valid:
            job["status"] = "cancelled"
            job["exit_code"] = None
            job["failure_reason"] = "source_task_binding_lost_before_spawn"
            warn(
                "compute_queue",
                "refused stale compute job before spawn",
                job=job.get("id"),
                source_task_id=job.get("source_task_id"),
            )
        elif preflight_error is not None:
            job["status"] = "failed"
            job["exit_code"] = 2
            job["failure_reason"] = "agent_model_preflight_denied"
            job["model_preflight_error"] = preflight_error
        else:
            assert proc is not None
            job["exit_code"] = proc.returncode
        if (
            binding_valid
            and preflight_error is None
            and proc is not None
            and proc.returncode != 0
        ):
            job["status"] = "failed"
            if _runner_timed_out(job):
                _mark_timeout(job)
            elif _requeue_quota_blocked(job):
                print(f"quota-blocked: {job['id']} never started — re-queued "
                      f"(bounce {job['quota_requeues']}/{QUOTA_REQUEUE_MAX}, "
                      f"not_before={job['not_before']})")
            else:
                # Non-quota terminal failure: lazypack jobs escalate to a real
                # P1 repair task instead of a receipt nobody owns (D3).
                _maybe_open_lazypack_repair_task(job)
        elif binding_valid and preflight_error is None and proc is not None:
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
        # Holding the flock proves no other worker is alive — the one safe
        # moment to finalize running receipts stranded by a killed worker.
        _reap_stale_running("run-loop")
        limit = _resolve_max_parallel(getattr(args, "max_parallel", None))
        print(f"drain-loop: start pid={os.getpid()} max_parallel={limit}")
        jobs_run = 0
        terminalized_seen: dict[str, str] = {}
        with ThreadPoolExecutor(max_workers=limit, thread_name_prefix="compute-job") as pool:
            in_flight: dict[Future, str] = {}
            while True:
                scan = _scan_queue_readiness("run-loop")
                terminalized_seen.update(scan.terminalized)
                for _prio, _queued_at, job_path in scan.ready:
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
        final_scan = _scan_queue_readiness("run-loop")
        terminalized_seen.update(final_scan.terminalized)
        suffix = (
            f" sleeping={final_scan.sleeping}"
            if final_scan.sleeping
            else ""
        )
        if final_scan.blocked:
            reason_counts = Counter(reason for _job_id, reason in final_scan.blocked)
            reason_summary = ",".join(
                f"{reason}={count}"
                for reason, count in sorted(reason_counts.items())
            )
            suffix += (
                f" binding_blocked={len(final_scan.blocked)}"
                f" reasons={reason_summary}"
            )
        if terminalized_seen:
            terminal_reason_counts = Counter(terminalized_seen.values())
            terminal_reason_summary = ",".join(
                f"{reason}={count}"
                for reason, count in sorted(terminal_reason_counts.items())
            )
            suffix += (
                f" binding_terminalized={len(terminalized_seen)}"
                f" terminalized_reasons={terminal_reason_summary}"
            )
        print(f"drain-loop: exit pid={os.getpid()} jobs_run={jobs_run}{suffix}")
        return 3 if final_scan.blocked else 0
    finally:
        _release_lock()


def _release_collected_source_task(
    task: dict[str, Any],
    job: dict[str, Any],
    *,
    next_task_id: str | None,
    tpc: Any,
) -> dict[str, Any] | None:
    """Settle a terminal receipt without depending on PHASE A call ordering.

    The source task may still be owned by this job, may already be terminal or
    pending, or may have moved on to a newer compute owner.  Only the first case
    releases the task back to pending.  The other valid cases acknowledge the
    old receipt without weakening the stronger/newer canonical state.
    """
    if (
        str(task.get("id") or "") != str(job.get("source_task_id") or "")
        or job.get("status") not in {"completed", "failed"}
    ):
        return None

    task_id = str(task["id"])
    job_id = str(job["id"])
    task_status = str(task.get("status") or "")
    bound_job_id = str(task.get("compute_job_id") or "")
    released_at = utc_now()
    if (
        task_status == "awaiting_agent_job"
        and bound_job_id == job_id
        and task.get("blocked_reason")
        in {
            "external_compute_receipt_pending_collection",
            "external_compute_job_running",
        }
    ):
        task["status"] = "pending"
        followup_id = str(next_task_id or "(unspecified)")
        tpc._record_status_history(
            task,
            frm="awaiting_agent_job",
            to="pending",
            by=f"compute-followup:{job_id}",
            note=f"terminal receipt collected; followup={followup_id}",
        )
        task["compute_released_at"] = released_at
        task["compute_release_reason"] = "terminal_receipt_collected"
        for field in (
            "blocked_reason",
            "compute_job_id",
            "compute_started_at",
            "compute_finished_at",
            "external_execution_ref",
        ):
            task.pop(field, None)
        return {
            "state": "pending_queue_commit",
            "task_id": task_id,
            "reason": "terminal_receipt_collected",
            "attempted_at": released_at,
        }

    if task_status in tpc.TERMINAL_STATUSES:
        if bound_job_id == job_id:
            task["compute_released_at"] = released_at
            task["compute_release_reason"] = "terminal_source_task_settled"
            for field in (
                "compute_job_id",
                "compute_started_at",
                "compute_finished_at",
                "external_execution_ref",
            ):
                task.pop(field, None)
            if task.get("blocked_reason") in {
                "external_compute_receipt_pending_collection",
                "external_compute_job_running",
                "external_compute_job_active",
            }:
                task.pop("blocked_reason", None)
            state = "pending_queue_commit"
        else:
            state = "settled"
        settlement = {
            "state": state,
            "task_id": task_id,
            "reason": "terminal_source_task_settled",
            "source_task_status": task_status,
        }
        settlement[
            "attempted_at" if state == "pending_queue_commit" else "settled_at"
        ] = released_at
        return settlement

    if task_status == "pending" and not bound_job_id:
        return {
            "state": "settled",
            "task_id": task_id,
            "reason": "source_task_already_released",
            "settled_at": released_at,
        }

    if (
        task_status == "awaiting_agent_job"
        and bound_job_id
        and bound_job_id != job_id
    ):
        return {
            "state": "settled",
            "task_id": task_id,
            "reason": "newer_compute_owner_preserved",
            "owner_job_id": bound_job_id,
            "settled_at": released_at,
        }

    return None


def _ack_followup_source_task_settlement(path: Path) -> None:
    with _receipt_lock():
        current = _read_job_file(path, context="followup-settlement-ack")
        settlement = current.get("source_task_settlement") if current else None
        if (
            current is None
            or not isinstance(settlement, dict)
            or settlement.get("state") != "pending_queue_commit"
        ):
            return
        current["source_task_settlement"] = {
            key: value
            for key, value in settlement.items()
            if key not in {"state", "attempted_at"}
        } | {
            "state": "settled",
            "settled_at": utc_now(),
        }
        _write_job_file(path, current)


def mark_followup_dispatched(args) -> int:
    p = QUEUE_DIR / f"{args.id}.json"
    if not p.exists():
        print(f"error: not found {args.id}", file=sys.stderr)
        return 2

    preview = _read_job_file(p, context="mark-followup-preview")
    if preview is None:
        return 2
    source_task_id = preview.get("source_task_id")

    def mark_under_receipt_lock(
        source_task: dict[str, Any] | None = None,
    ) -> int:
        j = _read_job_file(p, context="mark-followup-dispatched")
        if j is None:
            return 2
        # This check and requeue()'s followup check use the same receipt lock.
        # Whichever transition wins makes the other refuse: a queued/running
        # worker and a triage followup can therefore never own the same job at
        # once.
        if j.get("status") not in {"completed", "failed"}:
            print(
                f"error: cannot dispatch followup for {args.id} — "
                f"status={j.get('status')}, not terminal.",
                file=sys.stderr,
            )
            return 2
        if j.get("source_task_id"):
            settlement_result = (
                source_task is not None
                and _release_collected_source_task(
                    source_task,
                    j,
                    next_task_id=args.next_task_id,
                    tpc=tpc,
                )
            )
            settlement = j.get("source_task_settlement")
            already_committed = (
                j.get("followup_dispatched") is True
                and isinstance(settlement, dict)
                and settlement.get("state") == "pending_queue_commit"
                and source_task is not None
                and source_task.get("status") == "pending"
                and not source_task.get("compute_job_id")
            )
            if not settlement_result and not already_committed:
                print(
                    f"error: cannot dispatch followup for {args.id} — "
                    "source task settlement failed; canonical source is "
                    "missing or has an invalid ownership state.",
                    file=sys.stderr,
                )
                return 2
        else:
            settlement_result = None
        j["followup_dispatched"] = True
        j["followup_dispatched_at"] = utc_now()
        if args.next_task_id:
            j["followup_next_task_id"] = args.next_task_id
        if settlement_result:
            j["source_task_settlement"] = settlement_result
        _write_job_file(p, j)
        return 0

    if source_task_id:
        from scripts import task_pool_claim as tpc

        with _task_pool_locked_load(tpc) as (_fh, tasks):
            try:
                source_task = tpc._find(tasks, str(source_task_id))
            except SystemExit:
                source_task = None
            with _receipt_lock():
                rc = mark_under_receipt_lock(source_task)
        if rc == 0:
            _ack_followup_source_task_settlement(p)
    else:
        tpc = None
        with _receipt_lock():
            rc = mark_under_receipt_lock()

    if rc != 0:
        return rc
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
    requested_model = getattr(args, "model", None)
    fields = {
        "followup_brief": args.followup_brief,
        "followup_task_type": args.followup_task_type,
        "followup_priority": args.followup_priority,
        "timeout": args.timeout,
        "brief_file": args.brief_file,
        "model": requested_model,
    }
    if not any(v is not None for v in fields.values()):
        print("error: amend needs at least one field to change", file=sys.stderr)
        return 2

    if requested_model is not None:
        try:
            task_type = getattr(args, "followup_task_type", None)
            allowed_models = _agent_model_policy(task_type)["allowed_models"]
        except Exception as exc:  # noqa: BLE001 — model policy is fail-closed
            print(
                "error: canonical model router/provider registry unavailable: "
                f"{type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
            return 2
        if str(requested_model) not in allowed_models:
            print(
                f"error: model {requested_model!r} is not allowed by the "
                "canonical model router/provider registry",
                file=sys.stderr,
            )
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

        if requested_model is not None:
            if job.get("kind") != "agent":
                print(
                    f"error: --model only applies to agent jobs "
                    f"(kind={job.get('kind')})",
                    file=sys.stderr,
                )
                return 2
            argv = list(job.get("args") or [])
            try:
                model_index = argv.index("--model") + 1
                argv[model_index]
            except (ValueError, IndexError):
                print(
                    f"error: {args.id} agent job has no replaceable --model argument",
                    file=sys.stderr,
                )
                return 2
            argv[model_index] = str(requested_model)
            job["args"] = argv
            changed.append("model")

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
    path = QUEUE_DIR / f"{args.id}.json"

    def cancel_under_receipt_lock(
        source_task: dict[str, Any] | None = None,
    ) -> tuple[int, dict[str, Any] | None]:
        loaded = _load_queued_job(args.id, "cancel")
        if loaded is None:
            return 2, None
        loaded_path, job = loaded
        job["cancel_reason"] = reason
        if job.get("source_task_id"):
            if source_task is None or not _release_cancelled_source_task(
                source_task,
                job,
                tpc=tpc,
            ):
                print(
                    f"error: cannot cancel {args.id} — canonical source task "
                    "binding no longer matches.",
                    file=sys.stderr,
                )
                return 2, None
        job["status"] = "cancelled"
        cancelled_at = utc_now()
        job["cancelled_at"] = cancelled_at
        # Keep completed_at populated for generic terminal-state consumers while
        # preserving the semantically precise cancellation timestamp for audit.
        job["completed_at"] = cancelled_at
        # A cancelled job has no result, so it has nothing to follow up on. Saying so
        # explicitly keeps it out of `list --pending-followup` instead of relying on the
        # collector to infer that "cancelled" means "do not triage me".
        job["followup_dispatched"] = True
        if job.get("source_task_id"):
            job["source_task_settlement"] = {
                "state": "pending_queue_commit",
                "task_id": str(job["source_task_id"]),
                "attempted_at": cancelled_at,
            }
        _write_job_file(loaded_path, job)
        return 0, job

    preview = _read_job_file(path, context="cancel-preview")
    if preview is None:
        return 2
    if preview.get("source_task_id"):
        from scripts import task_pool_claim as tpc

        with _task_pool_locked_load(tpc) as (_fh, tasks):
            source_task = tpc._find(tasks, str(preview["source_task_id"]))
            with _receipt_lock():
                rc, cancelled_job = cancel_under_receipt_lock(source_task)
        if rc == 0 and cancelled_job is not None:
            _ack_cancelled_source_task_settlement(path)
    else:
        with _receipt_lock():
            rc, _cancelled_job = cancel_under_receipt_lock()
    if rc != 0:
        return rc
    print(f"cancelled: {args.id}")
    return 0


def _release_cancelled_source_task(
    task: dict[str, Any],
    job: dict[str, Any],
    *,
    tpc: Any,
) -> bool:
    if (
        str(task.get("id") or "") != str(job.get("source_task_id"))
        or task.get("status") != "awaiting_agent_job"
        or str(task.get("compute_job_id") or "") != str(job.get("id"))
        or task.get("blocked_reason")
        not in {
            "external_compute_job_active",
            "external_compute_job_running",
            "external_compute_receipt_pending_collection",
        }
    ):
        return False
    released_at = utc_now()
    task["status"] = "pending"
    tpc._record_status_history(
        task,
        frm="awaiting_agent_job",
        to="pending",
        by=f"compute-cancel:{job.get('id')}",
        note=str(job.get("cancel_reason") or "compute_job_cancelled"),
    )
    task["compute_released_at"] = released_at
    task["compute_release_reason"] = str(
        job.get("cancel_reason") or "compute_job_cancelled"
    )
    for field in (
        "blocked_reason",
        "compute_job_id",
        "compute_started_at",
        "compute_finished_at",
        "external_execution_ref",
    ):
        task.pop(field, None)
    return True


def _ack_cancelled_source_task_settlement(path: Path) -> None:
    with _receipt_lock():
        current = _read_job_file(path, context="cancel-settlement-ack")
        if (
            current is None
            or current.get("status") != "cancelled"
            or not current.get("source_task_id")
        ):
            return
        current["source_task_settlement"] = {
            "state": "settled",
            "task_id": str(current["source_task_id"]),
            "settled_at": utc_now(),
        }
        _write_job_file(path, current)


def _reconcile_cancelled_source_task(path: Path, job: dict[str, Any]) -> None:
    settlement = job.get("source_task_settlement")
    if (
        job.get("status") != "cancelled"
        or not job.get("source_task_id")
        or (
            isinstance(settlement, dict)
            and settlement.get("state") in {"settled", "not_required"}
        )
    ):
        return
    from scripts import task_pool_claim as tpc

    with _task_pool_locked_load(tpc) as (_fh, tasks):
        task = tpc._find(tasks, str(job["source_task_id"]))
        if task.get("status") == "pending" and not task.get("compute_job_id"):
            pass
        elif not _release_cancelled_source_task(task, job, tpc=tpc):
            warn(
                "compute_queue",
                "cancelled source task settlement did not match",
                job=job.get("id"),
                task_id=job.get("source_task_id"),
            )
            return
    _ack_cancelled_source_task_settlement(path)


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
    if not path.exists():
        print(f"error: not found {args.id}", file=sys.stderr)
        return 2
    preview = _read_job_file(path, context="requeue-preview")
    if preview is None:
        return 2
    source_task_id = preview.get("source_task_id")

    def requeue_under_receipt_lock(
        source_task: dict[str, Any] | None = None,
    ) -> tuple[int, str | None]:
        job = _read_job_file(path, context="requeue")
        if job is None:
            return 2, None
        if job.get("status") != "failed":
            print(
                f"error: cannot requeue {args.id} — "
                f"status={job.get('status')}, not failed.",
                file=sys.stderr,
            )
            return 2, None
        if job.get("followup_dispatched"):
            followup_id = (
                job.get("followup_next_task_id") or "(unknown followup task)"
            )
            print(
                f"error: cannot requeue {args.id} — disposition is owned by "
                f"followup {followup_id}. Do not retry the delegated original receipt.",
                file=sys.stderr,
            )
            return 2, None
        failure = _runner_failure_class(job)
        worker_killed = job.get("failure_reason") == "worker_killed"
        safe_policy_denial = (
            failure == "policy_denial_pre_spawn"
            and _runner_proves_no_agent_spawn(job)
        )
        if (
            failure not in ("auth", "quota")
            and not safe_policy_denial
            and not worker_killed
        ):
            print(
                f"error: cannot requeue {args.id} — failure_class={failure}. "
                "Only auth/quota deaths, typed policy_denial_pre_spawn receipts "
                "with agent_spawned=false, and reaper-stamped worker_killed "
                "jobs are safe to re-run. Triage this one's worktree instead.",
                file=sys.stderr,
            )
            return 2, None
        blocked_kind = (
            failure
            if failure in {
                "auth",
                "quota",
                "policy_denial_pre_spawn",
            }
            else "worker_killed"
        )
        if job.get("source_task_id"):
            if source_task is None:
                return 2, None
            if (
                str(source_task.get("id") or "")
                != str(job.get("source_task_id"))
                or source_task.get("status") != "awaiting_agent_job"
                or str(source_task.get("compute_job_id") or "")
                != str(job["id"])
                or source_task.get("blocked_reason")
                not in {
                    "external_compute_job_active",
                    "external_compute_job_running",
                    "external_compute_receipt_pending_collection",
                }
            ):
                print(
                    f"error: cannot requeue {args.id} — canonical source task "
                    "binding no longer matches.",
                    file=sys.stderr,
                )
                return 2, None
            source_task["blocked_reason"] = "external_compute_job_active"
            source_task.pop("compute_finished_at", None)

        job.setdefault("requeue_history", []).append({
            "at": utc_now(),
            "reason": f"manual:{blocked_kind}",
            "exit_code": job.get("exit_code"),
            "started_at": job.get("started_at"),
            "failure_reason": job.get("failure_reason"),
            "by": os.environ.get("VOLPRED_ACTOR")
            or os.environ.get("VOLPRED_TASK_CLAIM_OWNER"),
        })
        job["status"] = "queued"
        job["started_at"] = None
        job["completed_at"] = None
        job["exit_code"] = None
        job["not_before"] = None
        job["failure_reason"] = None
        job["claimed_by_pid"] = None
        job["claimed_by_pid_start_wall"] = None
        job["source_task_link"] = (
            {
                "state": "linked",
                "attempted_at": utc_now(),
                "linked_at": utc_now(),
                "error": None,
            }
            if job.get("source_task_id")
            else job.get("source_task_link")
        )
        _write_job_file(path, job)
        return 0, blocked_kind

    if source_task_id:
        from scripts import task_pool_claim as tpc

        with _task_pool_locked_load(tpc) as (_fh, tasks):
            source_task = tpc._find(tasks, str(source_task_id))
            with _receipt_lock():
                rc, blocked_kind = requeue_under_receipt_lock(source_task)
    else:
        with _receipt_lock():
            rc, blocked_kind = requeue_under_receipt_lock()
    if rc != 0:
        return rc
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
    ea.add_argument("--model", default="claude-opus-5")
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
        required=True,
        help=(
            "Pool task this job was dispatched for; marks it in_progress and blocks "
            "dispatch when another unmerged worktree branch already carries that task id."
        ),
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
    am.add_argument(
        "--model",
        help="Replace a queued agent job's frozen provider model.",
    )
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

    rb = sub.add_parser(
        "reconcile-bindings",
        help="Repair/terminalize queued source-task bindings without executing payloads.",
    )
    rb.add_argument("--json", action="store_true")
    rb.set_defaults(func=reconcile_bindings)

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

    m = sub.add_parser(
        "mark-followup-dispatched",
        help=(
            "Acknowledge a terminal receipt after its followup is durable. "
            "Order-independent with source task completion; preserves terminal "
            "state and any newer compute owner."
        ),
        description=(
            "Acknowledge a terminal receipt after its followup is durable. "
            "This operation is order-independent with source task completion: "
            "it preserves terminal state and any newer compute owner."
        ),
    )
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
