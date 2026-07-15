#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

backup="$(mktemp "${TMPDIR:-/tmp}/k1378-feed-backup.XXXXXX")"
base="$(mktemp "${TMPDIR:-/tmp}/k1378-feed-base.XXXXXX")"
desired="$(mktemp "${TMPDIR:-/tmp}/k1378-feed-desired.XXXXXX")"

cleanup() {
  if [[ -f "$backup" ]]; then
    cp "$backup" storage/reports/feed.json
  fi
  rm -f "$backup" "$base" "$desired"
}
trap cleanup EXIT

cp storage/reports/feed.json "$backup"
git show HEAD:storage/reports/feed.json > "$base"
jq --slurpfile single storage/reports/mile_54f79768.json \
  'map(if .id == "mile_54f79768" then $single[0] else . end)' \
  "$base" > "$desired"
mv "$desired" storage/reports/feed.json

uv run python scripts/git_writer_lock.py commit \
  --actor codex-vscode \
  --message '[codex] repair K1378 COVID split inference' \
  -- \
  experiments/k1378/README.md \
  experiments/k1378/k1378.py \
  experiments/k1378/k1378_plot.py \
  experiments/k1378/k1378_results.json \
  experiments/k1378/k1378_losses_a4f.npy \
  experiments/k1378/k1378_losses_gjr.npy \
  experiments/k1378/k1378_valid_mask.npy \
  experiments/k1378/k1378_no_covid_mask.npy \
  experiments/k1378/k1378_dm_subperiods.png \
  experiments/k1378/review_verdict.json \
  experiments/k1378/review_certification_20260715.md \
  storage/drafts/k1378_general_draft.md \
  storage/drafts/assets/k1378_loss_gap_rolling.png \
  storage/drafts/assets/k1378_period_gap_bars.png \
  storage/reports/feed.json \
  storage/reports/mile_54f79768.json \
  storage/memory/knowledge.json \
  storage/memory/research_log.json \
  storage/publication_candidates.json \
  storage/ops/dm_hac_lag_baseline.json \
  scripts/build_publication_candidates.py \
  scripts/tests/test_dm_hac_lag_ratchet.py \
  scripts/tests/test_k1378_methodology_repair.py \
  tests/test_build_publication_candidates.py
