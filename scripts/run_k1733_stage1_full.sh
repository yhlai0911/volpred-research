#!/usr/bin/env bash
# K1733 split stage 1 — full-replicate production run.
#
# Why this wrapper exists
# ----------------------
# Parent job agent-brief_k1733-b39c59 timed out (5159s) with the analysis code
# finished but `K1733_results.json` never written, so the followup is
# split_required. The code, the cached price panel, the figures and the README
# all live in the linked worktree `dispatch-slot-1-9189c746-k1733`; main has no
# `experiments/k1733/` at all.
#
# `compute_queue.py enqueue --script` runs script jobs with cwd = repo ROOT and
# has no --cwd flag (only enqueue-agent does). K1733.py passes repo-root-relative
# `inputs` to `finalize_experiment`, which hashes them for the reproduce_spec —
# so running it from main ROOT raises FileNotFoundError *after* results.json is
# written, yielding an artifact with no reproduce_spec (verified 2026-07-30 by a
# scratch --quick run). Stage 1 therefore has to execute with cwd = the worktree
# root, which is what this wrapper does. No agent needed: the analysis code is
# already written and validated.
#
# Runtime note: a --quick run (n_ord=20 / n_boot=60 / n_null=40) completed the
# whole pipeline in 131s. Full mode is 200/1000/500 replicates, so this is
# expected to take roughly 20-40 min, inside the 3600s job timeout.
#
# This script performs NO git mutation. Stage 2 owns verification and the merge.
set -euo pipefail

WORKTREE="${K1733_WORKTREE:-/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-9189c746-k1733}"
EXP_REL="experiments/k1733"

if [[ ! -d "$WORKTREE/$EXP_REL" ]]; then
  echo "error: K1733 worktree experiment dir missing: $WORKTREE/$EXP_REL" >&2
  exit 2
fi

cd "$WORKTREE"

# Guard the exact failure mode described above: the reproduce_spec inputs must
# resolve from this cwd, or finalize_experiment will crash after writing the JSON.
missing=0
for csv in "$EXP_REL"/data/*_adjusted_ohlc.csv "$EXP_REL"/data/prices_raw.csv; do
  [[ -f "$csv" ]] || { echo "error: missing cached input: $csv" >&2; missing=1; }
done
[[ "$missing" -eq 0 ]] || exit 2

echo "[stage1] cwd=$(pwd)"
echo "[stage1] full-replicate run (no --quick, no --refresh; cached panel only)"

# No --refresh: the panel is already snapshotted in the worktree, so the run is
# deterministic and needs no network. No --quick: this must be the production run.
exec uv run python "$EXP_REL/K1733.py"
