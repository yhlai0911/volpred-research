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

ROOT = Path(__file__).resolve().parent.parent
CLAUDE_BIN = os.environ.get("VOLPRED_CLAUDE_BIN", "claude")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> int:
    ap = argparse.ArgumentParser(description="Run a long-lived claude -p agent under the compute worker.")
    ap.add_argument("--brief-file", required=True, help="Path to the agent brief (markdown).")
    ap.add_argument("--model", default="claude-opus-4-8")
    ap.add_argument("--effort", default="high", choices=["low", "medium", "high", "xhigh", "max"])
    ap.add_argument("--cwd", default=None, help="Working dir (e.g. a git worktree). Defaults to repo root.")
    ap.add_argument("--result-artifact", default=None, help="Where to write the run summary JSON.")
    # The compute worker already bounds the whole script via job.timeout_seconds.
    # This is the inner bound so a wedged agent surfaces as a job failure rather
    # than eating the worker's entire budget with no diagnosis.
    ap.add_argument("--timeout", type=int, default=3300, help="Seconds before the agent is killed (default 3300).")
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
    try:
        proc = subprocess.run(
            argv, cwd=str(workdir), env=env, timeout=args.timeout,
            start_new_session=True,  # own process group: a wedged agent can be killed as a unit
        )
        exit_code = proc.returncode
    except subprocess.TimeoutExpired:
        timed_out = True
        exit_code = -1
        print(f"[run_agent_job] TIMEOUT after {args.timeout}s", file=sys.stderr, flush=True)

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
