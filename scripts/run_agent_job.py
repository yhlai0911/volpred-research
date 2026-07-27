#!/usr/bin/env python3
"""Agent job runner — executes a long-running `claude -p` agent OUTSIDE a dispatch fire.

Why this exists
---------------
A supervisor fire is a ~50min-capped container. A research agent needs 20-60min.
Running the agent *inside* the fire has exactly two outcomes, both observed on
2026-07-11/12 (docs/error_log.md, 3-STRIKE):

  parent waits for child  → parent burns the whole cap → SIGKILL at 3001.3s
                            ("hang_killed" ×3, all identical to the decisecond)
  parent exits first      → child reparents to init (ppid=1), runs unsupervised,
                            nobody ever collects its worktree commits

Both are the same domain-model error: a job longer than the container it runs in.

The fix is the container the repo already had for heavy compute — the compute
queue. Its worker is a detached */15 cron process with its own lock and its own
timeout, and a LATER fire collects the result in PHASE A. That is the correct
lifecycle for anything that outlives one fire, agentic work included.

So: a fire ENQUEUES an agent job (returns immediately) and a later fire COLLECTS
it. This script is what the compute worker runs in between.

Invoked by `scripts/compute_queue.py` as an ordinary job script — never by a fire
directly (the PreToolUse hook denies `claude -p` from inside a fire).
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import shutil
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from scripts.dispatch_supervisor import failure_class, procutil  # noqa: E402
from volpred.ops import termination  # noqa: E402
from volpred.ops.execution.registry import (  # noqa: E402
    ProviderRegistryError,
    authorize_provider_spawn,
    load_provider_registry,
    verify_spawn_receipt,
)
from volpred.ops.git_writer_lock import is_registered_linked_worktree  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

# Where the CLI actually lives when PATH can't be trusted. launchd hands its jobs
# a minimal PATH that omits ~/.local/bin — `cron_compute_worker.sh` already works
# around that for `uv` by spelling out /opt/homebrew/bin/uv, but nobody did the
# same for `claude`, so every kind=agent job drained by the launchd worker died
# on FileNotFoundError one second after start (2026-07-20: k528_round5_collection,
# exit 1 at 05:16:21). kind=compute jobs never exec the CLI, which is why the
# breakage stayed invisible until an agent job happened to land on that worker.
# Fixing it here rather than in the wrapper keeps one owner for "can we exec the
# CLI": launchd, cron and interactive runs all resolve through this function.
_CLAUDE_FALLBACK_PATHS = (
    Path.home() / ".local" / "bin" / "claude",
    Path("/opt/homebrew/bin/claude"),
    Path("/usr/local/bin/claude"),
)


def _resolve_claude_bin() -> str:
    """Return an executable path for the Claude CLI, or raise saying why not.

    Never falls back to the bare name `claude` on failure: that just defers the
    same FileNotFoundError to Popen, where it surfaces as a traceback and gets
    classified as a research failure instead of a host misconfiguration.
    """
    override = os.environ.get("VOLPRED_CLAUDE_BIN")
    if override:
        # An explicit override that doesn't resolve is a config error, not a
        # licence to silently search elsewhere.
        found = shutil.which(override)
        if found:
            return found
        raise FileNotFoundError(
            f"VOLPRED_CLAUDE_BIN={override!r} is not an executable on this host"
        )
    found = shutil.which("claude")
    if found:
        return found
    for candidate in _CLAUDE_FALLBACK_PATHS:
        if os.access(candidate, os.X_OK):
            return str(candidate)
    raise FileNotFoundError(
        "claude CLI not found on PATH nor at "
        + ", ".join(str(p) for p in _CLAUDE_FALLBACK_PATHS)
        + " — set VOLPRED_CLAUDE_BIN to its absolute path"
    )


# An auth wall costs five seconds and zero tokens: the CLI answers "Not logged in"
# and exits before the agent exists. It is worth a couple of retries because the
# usual cause is a credential refresh racing the spawn (2026-07-14: the compute
# worker's 13:45 agent job died this way while the supervisor's own fires at
# 13:24 and 22:07 authenticated fine). If it is instead a real logout, three
# cheap attempts cost four minutes and then say so — still far better than the
# old behaviour, which filed a 60-minute research job as a research failure and
# spent a whole later fire discovering the agent had never started.
AUTH_MAX_ATTEMPTS = 3
AUTH_BACKOFF_S = 120
# Don't start an attempt that has no room to finish the actual work.
AUTH_RETRY_MIN_BUDGET_S = 600
# Enough to carry the CLI's auth/quota banner; not enough to hold a research log.
_TAIL_LINES = 200


# Prepended to every brief. The agent runs headless: when its turn ends the
# process tree goes with it, so anything it parked in the background dies
# unfinished and unreported. On 2026-07-20 the K1698 rev3 job did exactly that —
# edited the generator correctly, launched the full rerun in the background,
# ended the turn saying "背景重跑完成時我會被叫醒", and was collected as a failed
# job with the rerun dead at 800/2192 files. The agent's reasoning was sound for
# an interactive session; nobody had told it that it wasn't in one. Telling it
# is the runner's job, not each dispatcher's memory.
BRIEF_PREAMBLE = """\
<runtime-contract>
You are running headless under the compute worker (`claude -p`), not in an
interactive session. Two consequences you must plan around:

1. **Nothing wakes you up.** When this turn ends, your process tree is torn
   down. Work you left running in the background dies unfinished, and its
   output is lost. Never park a computation in the background and end the
   turn intending to return to it — run it in the foreground and wait.
2. **Your result artifact is the only thing that is collected.** Prose in your
   final message is not read as a result. If you run out of time or hit a
   blocker, still write the artifact, with the `unresolved` field naming
   exactly what remains and why — a partial artifact that is honest about its
   gaps is collectable; a missing one is a failed job.
</runtime-contract>

"""


def _compose_brief(brief_text: str) -> str:
    """The brief the agent actually receives: runtime contract, then the task."""
    return BRIEF_PREAMBLE + brief_text


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run_attempt(
    argv: list[str], workdir: Path, env: dict[str, str], timeout: int
) -> tuple[int, bool, str]:
    """Run the agent once. Returns (exit_code, timed_out, tail_of_its_output).

    The output is teed, not swallowed: every line still reaches the compute log on
    its original stream. We keep a bounded tail only so the caller can classify
    what killed the attempt — and only THIS attempt's output, because a stale
    `Not logged in` from an earlier one would be read as a fresh auth verdict.
    """
    tail: deque[str] = deque(maxlen=_TAIL_LINES)

    def _pump(src, dst) -> None:
        for line in iter(src.readline, ""):
            dst.write(line)
            dst.flush()
            tail.append(line)
        src.close()

    # start_new_session: the agent leads its own process group, so on timeout the
    # whole tree (agent + the compute it shelled out to) dies as a unit. Killing
    # only the agent pid would leave its compute orphaned and still writing — see
    # _kill_agent_tree.
    proc = subprocess.Popen(
        argv, cwd=str(workdir), env=env, start_new_session=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1,
    )
    pumps = [
        threading.Thread(target=_pump, args=(proc.stdout, sys.stdout), daemon=True),
        threading.Thread(target=_pump, args=(proc.stderr, sys.stderr), daemon=True),
    ]
    for t in pumps:
        t.start()

    timed_out = False
    try:
        exit_code = proc.wait(timeout=max(timeout, 1))
    except subprocess.TimeoutExpired:
        timed_out = True
        exit_code = -1
        print(f"[run_agent_job] TIMEOUT after {timeout}s — killing agent tree",
              file=sys.stderr, flush=True)
        _kill_agent_tree(proc)
    for t in pumps:
        t.join(timeout=5)
    return exit_code, timed_out, "".join(tail)


def _should_retry_auth(failure: str | None, attempts: int, deadline: float) -> bool:
    if failure != "auth" or attempts >= AUTH_MAX_ATTEMPTS:
        return False
    remaining = deadline - time.monotonic() - AUTH_BACKOFF_S
    return remaining >= AUTH_RETRY_MIN_BUDGET_S


def _kill_agent_tree(proc: subprocess.Popen) -> bool:
    """Kill the agent AND everything it spawned. Returns True if the group is gone.

    An agent's real work happens in its children: it shells out to python for the
    compute, and that grandchild is what actually holds the run. Killing only the
    direct `claude` pid leaves that grandchild alive, reparented to init, writing
    results into a worktree with nobody left to verify, commit, or merge them.
    That is not a timeout — it is a silent fork of unsupervised work.

    Observed 2026-07-12 (K1685): the agent was killed at its 3300s bound; its
    compute child kept running and wrote a complete 37KB results.json 24 minutes
    later, into a worktree whose job was already marked `failed`. The results were
    real and nobody was watching. One day earlier the identical bug was fixed in
    gen_lazypack_codex (scripts/tests/test_lazypack_codex_timeout_orphan.py) — it
    came straight back because the kill lived in that file instead of in an owner.

    `procutil.kill_pgid` IS that owner: SIGTERM→grace→SIGKILL, macOS EPERM
    fallback to per-pid, and it reports whether the group is confirmed gone.
    Do not hand-roll another one here.
    """
    try:
        pgid = os.getpgid(proc.pid)
    except (ProcessLookupError, PermissionError) as e:
        print(f"[run_agent_job] cannot resolve pgid for {proc.pid}: {e}", file=sys.stderr, flush=True)
        intent = termination.arm(
            target_kind="pid", target_id=proc.pid,
            reason="agent_job_unresolved_pgid", actor="run_agent_job",
            signal_sequence=[signal.SIGKILL],
        )
        termination.send_pid(intent, signal.SIGKILL)
        return False
    intent = termination.arm(
        target_kind="pgid", target_id=pgid,
        reason="agent_job_timeout", actor="run_agent_job",
        signal_sequence=termination.terminating_signals(),
    )
    return procutil.kill_pgid(pgid, intent=intent)


def main() -> int:
    ap = argparse.ArgumentParser(description="Run a long-lived claude -p agent under the compute worker.")
    ap.add_argument("--brief-file", required=True, help="Path to the agent brief (markdown).")
    ap.add_argument("--model", default="claude-opus-4-8")
    ap.add_argument("--effort", default="high", choices=["low", "medium", "high", "xhigh", "max"])
    ap.add_argument(
        "--cwd",
        required=True,
        help="Registered non-main git worktree where the agent is allowed to write.",
    )
    ap.add_argument(
        "--result-artifact",
        default=None,
        help=(
            "Agent-produced artifact to verify after the run. Relative paths are "
            "resolved from --cwd; this runner never writes the artifact."
        ),
    )
    ap.add_argument(
        "--job-metadata",
        default=None,
        help=(
            "Independent runner-metadata JSON. Relative paths are resolved from the "
            "repo root; defaults to storage/ops/agent_jobs/<brief>-<pid>.json."
        ),
    )
    # Inner bound. It exists so a wedged agent surfaces as a diagnosed job failure
    # (metadata written, stderr explains) instead of being hard-killed by the
    # worker with nothing to read. It must therefore fire just BEFORE the worker's
    # own job.timeout_seconds — which means it has to be DERIVED from that budget,
    # never guessed.
    #
    # It used to default to a flat 3300s while `enqueue-agent` never passed the
    # flag at all. So a job queued with timeout_seconds=10800 was still killed at
    # 55 minutes: the outer budget was a number nobody honoured. That is the same
    # domain error this whole script was written to escape — a job longer than the
    # container it runs in — rebuilt one layer down (docs/error_log.md 2026-07-12).
    #
    # `compute_queue.enqueue_agent` now always passes this, set to the outer budget
    # minus a grace. The default here is only a floor for direct invocation.
    ap.add_argument("--timeout", type=int, default=3300,
                    help="Seconds before the agent tree is killed. Callers MUST derive this "
                         "from the compute job's timeout_seconds (enqueue-agent does).")
    args = ap.parse_args()
    try:
        # Startup guard catches an invalid registry even if validation below
        # returns before the first attempt. Every actual attempt reloads again.
        load_provider_registry()
    except ProviderRegistryError as exc:
        print(
            f"[run_agent_job] provider registry startup denied: {exc}",
            file=sys.stderr,
        )
        return 2

    brief_path = Path(args.brief_file)
    if not brief_path.is_absolute():
        brief_path = ROOT / brief_path
    if not brief_path.exists():
        print(f"[run_agent_job] brief not found: {brief_path}", file=sys.stderr)
        return 2
    brief = _compose_brief(brief_path.read_text())

    workdir = Path(args.cwd)
    if not workdir.is_absolute():
        workdir = ROOT / workdir
    if not workdir.exists():
        print(f"[run_agent_job] cwd not found: {workdir}", file=sys.stderr)
        return 2
    if not is_registered_linked_worktree(ROOT, workdir):
        print(
            f"[run_agent_job] refusing non-worktree/main cwd: {workdir}",
            file=sys.stderr,
        )
        return 2

    result_artifact = None
    if args.result_artifact:
        result_artifact = Path(args.result_artifact)
        if not result_artifact.is_absolute():
            result_artifact = workdir / result_artifact

    if args.job_metadata:
        metadata_path = Path(args.job_metadata)
        if not metadata_path.is_absolute():
            metadata_path = ROOT / metadata_path
    else:
        metadata_path = (
            ROOT / "storage" / "ops" / "agent_jobs" /
            f"{brief_path.stem}-{os.getpid()}.json"
        )

    if result_artifact is not None and metadata_path == result_artifact:
        print(
            "[run_agent_job] --job-metadata must be separate from --result-artifact",
            file=sys.stderr,
        )
        return 2

    try:
        claude_bin = _resolve_claude_bin()
    except FileNotFoundError as exc:
        # Exit 2 (config error), not 1: a job that never started is a host
        # problem for the owner to fix, not a failed piece of research for a
        # triage agent to go read a worktree about.
        print(f"[run_agent_job] {exc}", file=sys.stderr)
        return 2

    argv = [
        claude_bin, "-p", "--dangerously-skip-permissions",
        "--effort", args.effort, "--model", args.model,
        "--setting-sources", "",
        "--settings", str(ROOT / ".claude" / "settings.json"),
        brief,
    ]

    # The agent runs under the compute worker, NOT under a dispatch fire. Stamp
    # the actor accordingly: it must not inherit `dispatch-worker:*` (that stamp
    # is what the PreToolUse gate keys on, and it would wrongly deny the agent's
    # own legitimate tool use).
    env = {**os.environ, "VOLPRED_ACTOR": f"agent-job:{brief_path.stem}"}

    started = _utc_now()
    print(f"[run_agent_job] start {started} model={args.model} effort={args.effort} cwd={workdir}", flush=True)

    deadline = time.monotonic() + args.timeout
    attempts = 0
    failure = None
    provider_receipt = None
    provider_policy_denial = None
    while True:
        attempts += 1
        remaining = int(deadline - time.monotonic())
        provider_receipt = None
        try:
            # Reload immediately before every Popen, including auth retries.
            # A config change between attempts therefore fails closed rather
            # than inheriting a once-valid startup decision.
            provider_receipt = authorize_provider_spawn(
                contract_id="compute-agent.claude",
                model_id=args.model,
                executable_path=claude_bin,
                environment=env,
            )
            verify_spawn_receipt(provider_receipt)
        except ProviderRegistryError as exc:
            print(
                f"[run_agent_job] provider policy denied spawn: {exc}",
                file=sys.stderr,
                flush=True,
            )
            exit_code, timed_out, output = 2, False, str(exc)
            failure = "policy_denial"
            provider_policy_denial = str(exc)
            break
        attempt_env = {**env, **provider_receipt.environment()}
        attempt_argv = [provider_receipt.resolved_executable, *argv[1:]]
        if provider_receipt.settings_path is None:
            provider_policy_denial = (
                "Claude launch contract requires pinned settings"
            )
            exit_code, timed_out = 2, False
            failure = "policy_denial"
            provider_receipt = None
            break
        attempt_argv[attempt_argv.index("--settings") + 1] = (
            provider_receipt.settings_path
        )
        exit_code, timed_out, output = _run_attempt(
            attempt_argv, workdir, attempt_env, remaining
        )
        if exit_code == 0:
            failure = None
            break
        failure = failure_class.classify_output(output)
        if not _should_retry_auth(failure, attempts, deadline):
            break
        print(
            f"[run_agent_job] attempt {attempts} hit an auth wall ({exit_code}) — "
            f"the agent never ran. Retrying in {AUTH_BACKOFF_S}s.",
            file=sys.stderr, flush=True,
        )
        time.sleep(AUTH_BACKOFF_S)

    finished = _utc_now()
    artifact_exists = result_artifact.exists() if result_artifact is not None else None
    artifact_near_misses: list[str] = []
    if result_artifact is not None and artifact_exists is False:
        candidates = {
            candidate.resolve(strict=False)
            for pattern in ("*_results.json", "*results*.json")
            for candidate in result_artifact.parent.glob(pattern)
            if candidate.is_file()
        }
        artifact_near_misses = [str(candidate) for candidate in sorted(candidates)][:20]
    validation_ok = exit_code == 0 and artifact_exists is not False
    runner_exit_code = 0 if validation_ok else 1
    summary = {
        "brief_file": str(brief_path.relative_to(ROOT)) if brief_path.is_relative_to(ROOT) else str(brief_path),
        "model": args.model,
        "effort": args.effort,
        "cwd": str(workdir),
        "started_at": started,
        "finished_at": finished,
        "exit_code": exit_code,
        "timed_out": timed_out,
        # Which wall the job hit, so the collecting fire routes on the failure's
        # NATURE and not merely on "nonzero": an `auth` job computed nothing and
        # needs re-enqueueing, whereas a `hard_failure` (None) has a worktree
        # worth triaging.
        "failure_class": failure,
        "attempts": attempts,
        "provider_id": (
            provider_receipt.provider_id if provider_receipt is not None else None
        ),
        "provider_registry_sha256": (
            provider_receipt.registry_sha256
            if provider_receipt is not None
            else None
        ),
        "provider_policy_denial": provider_policy_denial,
        "result_artifact": str(result_artifact) if result_artifact is not None else None,
        "result_artifact_exists": artifact_exists,
        "result_artifact_near_misses": artifact_near_misses,
        "validation_ok": validation_ok,
        "runner_exit_code": runner_exit_code,
    }

    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_tmp = metadata_path.with_name(f".{metadata_path.name}.{os.getpid()}.tmp")
    metadata_tmp.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    os.replace(metadata_tmp, metadata_path)
    print(f"[run_agent_job] metadata → {metadata_path}", flush=True)

    if exit_code == 0 and artifact_exists is False:
        print(
            f"[run_agent_job] expected result artifact missing: {result_artifact}",
            file=sys.stderr,
            flush=True,
        )
        if artifact_near_misses:
            print(
                "[run_agent_job] near-miss result artifact candidates: "
                + ", ".join(artifact_near_misses),
                file=sys.stderr,
                flush=True,
            )

    print(
        f"[run_agent_job] done exit={exit_code} timed_out={timed_out} "
        f"artifact_ok={artifact_exists is not False}",
        flush=True,
    )
    return runner_exit_code


if __name__ == "__main__":
    sys.exit(main())
