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
CODEX_BOUNDED="${CODEX_BOUNDED:-$REPO_ROOT/scripts/codex_exec_bounded.sh}"
QUOTA_HANDLER="${CODEX_QUOTA_HANDLER:-$REPO_ROOT/scripts/codex_review_quota.py}"

[[ -n "$PROMPT_FILE" ]] || { echo "usage: codex_review_job.sh <prompt-file> <out> [timeout]" >&2; exit 2; }
[[ -n "$OUT" ]]         || { echo "usage: codex_review_job.sh <prompt-file> <out> [timeout]" >&2; exit 2; }
[[ -f "$PROMPT_FILE" ]] || { echo "prompt file not found: $PROMPT_FILE" >&2; exit 2; }

mkdir -p "$(dirname "$OUT")"
TMP_OUT="$(mktemp "${OUT}.tmp.XXXXXX")"
cleanup() {
  rm -f "$TMP_OUT"
}
trap cleanup EXIT

echo "[codex-review] prompt=$PROMPT_FILE out=$OUT timeout=${TIMEOUT}s"
set +e
bash "$CODEX_BOUNDED" --timeout "$TIMEOUT" -s read-only - < "$PROMPT_FILE" > "$TMP_OUT" 2>"${OUT}.stderr"
RC=$?
set -e

if rg -qi "you.ve hit your usage limit|usage limit.*try again at" "${OUT}.stderr"; then
  # Shell redirection used to create OUT before Codex even started.  A quota
  # rejection therefore left a normal-looking, zero-byte verdict behind.  Keep
  # quota output quarantined in TMP_OUT and remove only legacy empty artifacts.
  [[ ! -e "$OUT" || -s "$OUT" ]] || rm -f "$OUT"
  set +e
  uv run python "$QUOTA_HANDLER" handle \
    --stderr "${OUT}.stderr" --prompt "$PROMPT_FILE" --out "$OUT"
  HANDLER_RC=$?
  set -e
  if [[ $HANDLER_RC -ne 0 ]]; then
    echo "[codex-review] quota handler failed rc=$HANDLER_RC" >&2
  fi
  echo "[codex-review] QUOTA_EXHAUSTED — no verdict artifact published" >&2
  [[ $RC -ne 0 ]] && exit "$RC"
  exit 1
fi

if [[ $RC -eq 124 ]]; then
  echo "[codex-review] TIMED OUT after ${TIMEOUT}s" >&2
elif [[ $RC -ne 0 ]]; then
  echo "[codex-review] codex exited $RC — see ${OUT}.stderr" >&2
fi

# A zero-byte verdict is a failed review, not a passing one. Fail closed so the followup
# never mistakes silence for approval.
if [[ ! -s "$TMP_OUT" ]]; then
  echo "[codex-review] EMPTY verdict — treating as FAILED review" >&2
  [[ $RC -ne 0 ]] && exit "$RC"
  exit 1
fi

# Publish only after the child exits.  Readers can see the prior complete
# verdict or the new complete verdict, never a file being streamed into place.
mv "$TMP_OUT" "$OUT"
echo "[codex-review] wrote $(wc -c < "$OUT") bytes to $OUT (codex rc=$RC)"
exit "$RC"
