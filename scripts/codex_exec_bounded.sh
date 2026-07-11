#!/usr/bin/env bash
# Bounded `codex exec` — the only sanctioned way to call codex from a Bash tool call.
#
# Why this exists (2026-07-11, boss Telegram msg 465):
# a hourly agent ran `codex exec` inline to re-render a lazypack. The call hung
# with zero output for >30 min, the agent sat blocked in Bash with no timeout of
# its own, and it rode straight into the supervisor's 3000s hard cap → SIGKILL →
# hang_killed. The agent had no way to bound it: macOS ships no coreutils
# `timeout`, so "just add a timeout" was not actually available to anyone.
# Now it is, and `.claude/hooks/pretooluse-bash-optimizer.sh` denies the bare form.
#
# Usage:
#   bash scripts/codex_exec_bounded.sh [--timeout N] <codex exec args...>
#   bash scripts/codex_exec_bounded.sh --timeout 300 -s workspace-write "review this"
#   printf '%s' "$PROMPT" | bash scripts/codex_exec_bounded.sh --timeout 600 -s read-only -
#
# Default timeout: 600s. Exit 124 = timed out (same convention as GNU timeout).
#
# For HEAVY agentic work (lazypack renders, long reviews, anything you would not
# sit and watch), do not use this at all — enqueue it:
#   uv run python scripts/compute_queue.py enqueue --script <path> --timeout 1800
set -euo pipefail

TIMEOUT_S=600
if [[ "${1:-}" == "--timeout" ]]; then
  TIMEOUT_S="${2:?--timeout needs a value}"
  shift 2
fi

if [[ $# -eq 0 ]]; then
  echo "usage: $0 [--timeout N] <codex exec args...>" >&2
  exit 2
fi

# A python watchdog rather than gtimeout/perl-alarm, for two reasons found while
# testing this script: perl's `alarm` + `exec` leaves a pending SIGALRM in the
# EXEC'D process, so the handler is gone and the shell reports 142 (128+SIGALRM)
# instead of 124 — and either way only codex itself is signalled, not the tools
# it spawned. `start_new_session` + `killpg` takes the whole tree down and keeps
# the GNU-timeout exit convention that callers actually check for.
exec python3 -c '
import os, signal, subprocess, sys

timeout = float(sys.argv[1])
proc = subprocess.Popen(["codex", "exec", *sys.argv[2:]], start_new_session=True)
try:
    sys.exit(proc.wait(timeout=timeout))
except subprocess.TimeoutExpired:
    try:
        os.killpg(proc.pid, signal.SIGKILL)  # start_new_session => pgid == pid
    except (ProcessLookupError, PermissionError) as exc:
        print(f"WARN: killpg failed ({exc}); killing pid only", file=sys.stderr)
        proc.kill()
    proc.wait()
    print(f"\nERROR: codex exec exceeded {timeout:.0f}s — killed", file=sys.stderr)
    sys.exit(124)
except FileNotFoundError:
    print("ERROR: codex CLI not found on PATH", file=sys.stderr)
    sys.exit(127)
' "$TIMEOUT_S" "$@"
