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

Usage:
    enqueue:   uv run python scripts/compute_queue.py enqueue --script X --title Y ...
    list:      uv run python scripts/compute_queue.py list
    list --pending-followup: completed collection + failed-agent triage
    list --completed-pending-followup: legacy completed-only view
    run-next:  uv run python scripts/compute_queue.py run-next
    show:      uv run python scripts/compute_queue.py show <id>
    mark-followup-dispatched: ... --id <id>
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import shlex
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from volpred.ops.diagnostics import warn  # noqa: E402

QUEUE_DIR = ROOT / "storage" / "ops" / "compute_queue"
LOCK_FILE = QUEUE_DIR / ".worker.lock"
LOG_DIR = ROOT / "storage" / "logs" / "compute"
AGENT_JOB_DIR = ROOT / "storage" / "ops" / "agent_jobs"

# Agent jobs. A research agent needs 20-60min of wall clock (that is the whole
# reason it cannot live inside a ~50min dispatch fire), so the default budget has
# to actually cover one. The grace is how much earlier the runner's inner bound
# fires, leaving it time to write a diagnosis before the worker kills the script.
AGENT_DEFAULT_TIMEOUT = 5400  # 90 min
AGENT_TIMEOUT_GRACE = 120


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

    return {
        "status": "failed",
        "scope": str(scope),
        "exit_code": proc.returncode,
        "report": (proc.stderr or proc.stdout).strip(),
    }


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
        "timeout_seconds": args.timeout or 3600,
    }
    _write_job_file(job_path, entry)
    print(f"enqueued: {job_id}")
    return 0


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
    workdir = ROOT
    if args.cwd:
        cwd_path = Path(args.cwd)
        if not cwd_path.is_absolute():
            cwd_path = ROOT / cwd_path
        if not cwd_path.is_dir():
            print(f"error: --cwd does not exist: {cwd_path}", file=sys.stderr)
            return 2
        workdir = cwd_path

    job_id = args.id or f"agent-{brief_path.stem}-{uuid.uuid4().hex[:6]}"

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
        "--brief-file", str(brief_path),
        "--model", args.model,
        "--effort", args.effort,
    ]
    if args.cwd:
        script_args += ["--cwd", args.cwd]
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
        timeout=outer_timeout,
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


def _pending_followup_view(job: dict[str, Any]) -> dict[str, Any] | None:
    """Return a dispatch view with explicit success-vs-failure semantics."""
    if job.get("followup_dispatched"):
        return None

    if job.get("status") == "completed" and job.get("claude_followup"):
        row = dict(job)
        row["followup_mode"] = "collect_completed"
        return row

    if job.get("status") != "failed":
        return None
    workdir = _agent_workdir(job)
    if not workdir:
        return None

    original = job.get("claude_followup") or {}
    if not isinstance(original, dict):
        original = {}
    original_brief = original.get("brief")

    # An auth-class death is not a failure of the WORK — the runner exhausted its
    # retries against a login wall and the agent never started. Sending a fire to
    # "inspect what exists in the worktree" would waste it: nothing exists. Say so,
    # and ask for the one action that can help.
    if _runner_failure_class(job) == "auth":
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
    row["followup_mode"] = "triage_failed"
    original_priority = original.get("priority")
    triage_priority = original_priority if isinstance(original_priority, int) else 2
    row["claude_followup"] = {
        "brief": "\n".join(triage_lines),
        "task_type": "platform_ops",
        "priority": min(triage_priority, 2),
    }
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
        with _receipt_lock():
            _write_job_file(job_path, job)
        print(f"running: {job['id']} ({job['script_path']})")

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
            stderr_p.write_text(stderr_p.read_text() + "\n[TIMEOUT]\n")
        except Exception as e:
            job["status"] = "failed"
            job["exit_code"] = -2
            stderr_p.write_text(stderr_p.read_text() + f"\n[EXCEPTION] {e}\n")

        with _receipt_lock():
            _merge_runtime_output_paths(job_path, job)
            job["completed_at"] = utc_now()
            _write_job_file(job_path, job)
        print(f"done: {job['id']} status={job['status']} exit={job['exit_code']}")
        return 0
    finally:
        _release_lock()


def mark_followup_dispatched(args) -> int:
    p = QUEUE_DIR / f"{args.id}.json"
    if not p.exists():
        print(f"error: not found {args.id}", file=sys.stderr)
        return 2
    with _receipt_lock():
        j = json.loads(p.read_text())
        j["followup_dispatched"] = True
        j["followup_dispatched_at"] = utc_now()
        if args.next_task_id:
            j["followup_next_task_id"] = args.next_task_id
        _write_job_file(p, j)
    print(f"marked: {args.id} followup_dispatched=true")
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
    e.add_argument("--timeout", type=int)
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
    ea.add_argument("--cwd", help="Working dir for the agent, e.g. a git worktree path.")
    ea.add_argument("--result-artifact")
    ea.add_argument("--followup-brief")
    ea.add_argument("--followup-task-type")
    ea.add_argument("--followup-priority", type=int)
    ea.add_argument("--timeout", type=int)
    ea.set_defaults(func=enqueue_agent)

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

    r = sub.add_parser("run-next")
    r.set_defaults(func=run_next)

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
