#!/usr/bin/env bash
# Queueable Codex review — the compute-queue counterpart to scripts/codex_exec_bounded.sh.
#
# Why this exists (2026-07-12): an hourly fire may not spawn `codex exec` at all — a
# primary-path review of a full experiment runs 10-40 min and the fire has a 3000s hard
# cap, so the父-waits-child shape ends in SIGKILL (3-STRIKE, 2026-07-12). Reviews that
# long belong in the compute queue, which runs them detached under its own timeout.
# codex_exec_bounded.sh stays what it is: short calls you would sit and watch.
#
# Usage:
#   bash scripts/codex_review_job.sh <prompt-file> <out> [timeout]
#
# Positional, deliberately: compute_queue's `--script-args` is an argparse nargs='*', so any
# dash-prefixed value there is swallowed as a flag of compute_queue itself.
#
# Enqueue form:
#   uv run python scripts/compute_queue.py enqueue \
#     --script scripts/codex_review_job.sh --interpreter bash \
#     --script-args storage/ops/codex_reviews/kXXXX_prompt.md \
#                   storage/ops/codex_reviews/kXXXX_verdict.md 2400 \
#     --result-artifact storage/ops/codex_reviews/kXXXX_verdict.md \
#     --output-path storage/ops/codex_reviews/kXXXX_verdict.md \
#     --followup-brief '...' --followup-task-type experiment --timeout 2700
#
# Sandbox is read-only: a reviewer that can write is a reviewer that can "fix" the thing
# it was meant to judge. Exit 124 = codex timed out (GNU timeout convention, inherited
# from codex_exec_bounded.sh).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

PROMPT_FILE="${1:-}"
OUT="${2:-}"
TIMEOUT="${3:-2400}"

[[ -n "$PROMPT_FILE" ]] || { echo "usage: codex_review_job.sh <prompt-file> <out> [timeout]" >&2; exit 2; }
[[ -n "$OUT" ]]         || { echo "usage: codex_review_job.sh <prompt-file> <out> [timeout]" >&2; exit 2; }
[[ -f "$PROMPT_FILE" ]] || { echo "prompt file not found: $PROMPT_FILE" >&2; exit 2; }

mkdir -p "$(dirname "$OUT")"

echo "[codex-review] prompt=$PROMPT_FILE out=$OUT timeout=${TIMEOUT}s"
set +e
bash scripts/codex_exec_bounded.sh --timeout "$TIMEOUT" -s read-only - < "$PROMPT_FILE" > "$OUT" 2>"${OUT}.stderr"
RC=$?
set -e

if [[ $RC -eq 124 ]]; then
  echo "[codex-review] TIMED OUT after ${TIMEOUT}s — verdict file holds partial output" >&2
elif [[ $RC -ne 0 ]]; then
  echo "[codex-review] codex exited $RC — see ${OUT}.stderr" >&2
fi

# A zero-byte verdict is a failed review, not a passing one. Fail closed so the followup
# never mistakes silence for approval.
if [[ ! -s "$OUT" ]]; then
  echo "[codex-review] EMPTY verdict — treating as FAILED review" >&2
  exit "${RC:-1}"
fi

echo "[codex-review] wrote $(wc -c < "$OUT") bytes to $OUT (codex rc=$RC)"
exit "$RC"
