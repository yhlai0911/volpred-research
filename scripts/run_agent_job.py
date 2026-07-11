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
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.dispatch_supervisor import procutil  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CLAUDE_BIN = os.environ.get("VOLPRED_CLAUDE_BIN", "claude")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
        proc.kill()
        return False
    return procutil.kill_pgid(pgid)


def main() -> int:
    ap = argparse.ArgumentParser(description="Run a long-lived claude -p agent under the compute worker.")
    ap.add_argument("--brief-file", required=True, help="Path to the agent brief (markdown).")
    ap.add_argument("--model", default="claude-opus-4-8")
    ap.add_argument("--effort", default="high", choices=["low", "medium", "high", "xhigh", "max"])
    ap.add_argument("--cwd", default=None, help="Working dir (e.g. a git worktree). Defaults to repo root.")
    ap.add_argument("--result-artifact", default=None, help="Where to write the run summary JSON.")
    # Inner bound. It exists so a wedged agent surfaces as a diagnosed job failure
    # (artifact written, stderr explains) instead of being hard-killed by the
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

    brief_path = Path(args.brief_file)
    if not brief_path.is_absolute():
        brief_path = ROOT / brief_path
    if not brief_path.exists():
        print(f"[run_agent_job] brief not found: {brief_path}", file=sys.stderr)
        return 2
    brief = brief_path.read_text()

    workdir = Path(args.cwd) if args.cwd else ROOT
    if not workdir.is_absolute():
        workdir = ROOT / workdir
    if not workdir.exists():
        print(f"[run_agent_job] cwd not found: {workdir}", file=sys.stderr)
        return 2

    argv = [
        CLAUDE_BIN, "-p", "--dangerously-skip-permissions",
        "--effort", args.effort, "--model", args.model, brief,
    ]

    # The agent runs under the compute worker, NOT under a dispatch fire. Stamp
    # the actor accordingly: it must not inherit `dispatch-worker:*` (that stamp
    # is what the PreToolUse gate keys on, and it would wrongly deny the agent's
    # own legitimate tool use).
    env = {**os.environ, "VOLPRED_ACTOR": f"agent-job:{brief_path.stem}"}

    started = _utc_now()
    print(f"[run_agent_job] start {started} model={args.model} effort={args.effort} cwd={workdir}", flush=True)

    timed_out = False
    # start_new_session: the agent leads its own process group, so on timeout the
    # whole tree (agent + the compute it shelled out to) dies as a unit. Killing
    # only the agent pid would leave its compute orphaned and still writing — see
    # _kill_agent_tree.
    proc = subprocess.Popen(argv, cwd=str(workdir), env=env, start_new_session=True)
    try:
        exit_code = proc.wait(timeout=args.timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        exit_code = -1
        print(f"[run_agent_job] TIMEOUT after {args.timeout}s — killing agent tree",
              file=sys.stderr, flush=True)
        _kill_agent_tree(proc)

    finished = _utc_now()
    summary = {
        "brief_file": str(brief_path.relative_to(ROOT)) if brief_path.is_relative_to(ROOT) else str(brief_path),
        "model": args.model,
        "effort": args.effort,
        "cwd": str(workdir),
        "started_at": started,
        "finished_at": finished,
        "exit_code": exit_code,
        "timed_out": timed_out,
    }
    if args.result_artifact:
        art = Path(args.result_artifact)
        if not art.is_absolute():
            art = ROOT / art
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
        print(f"[run_agent_job] artifact → {art}", flush=True)

    print(f"[run_agent_job] done exit={exit_code} timed_out={timed_out}", flush=True)
    return 0 if exit_code == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
