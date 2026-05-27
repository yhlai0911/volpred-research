# K562/K560 Lag-Fix Reapply Note — 2026-05-27

## Scope

- Re-applied the missing `t-1 -> t` lag patch to:
  - `experiments/k562/k562_k560_sector_validation.py`
  - `experiments/k560/k560_sector_rotation_vt.py`
- Did **not** overwrite either `*_results.json` in this session.

## What Changed In Source

### K562

- `compute_strategy_returns()` now:
  - skips `i=0`
  - uses `prev = i - 1`
  - applies `vt_weights[prev]` to day-`i` returns
  - reads sector momentum from `sec_mom_arr[t][prev]`
  - keeps benchmark and strategy on the same lag convention
- bi-weekly validation block now uses the same `prev` lag.

### K560

- Main daily strategy loop now:
  - skips `i=0`
  - uses `sig_idx = i - 1`
  - applies `vt_weights[sig_idx]`
  - reads `sec_moms / sec_vols / sec_rs` from `sig_idx`
- Return arrays initialize with `NaN` so the skipped first row does not pollute metrics.

## Local Reproduction Blocker

Local smoke test failed before any rerun could finish:

- command: `python experiments/k562/k562_k560_sector_validation.py`
- failure: `curl: (6) Could not resolve host: guce.yahoo.com`
- implication: this sandbox cannot reach Yahoo Finance, and `experiments/k560/data/` / `experiments/k562/data/` contain no local price snapshot.

Because the rerun could not execute, updating `*_results.json` in this session would violate research-honesty rules.

## Historical Evidence Found In Repo

Although the canonical results JSONs were never committed, the repo still contains archived post-patch narrative evidence:

- `docs/error_log.md` entry dated `2026-05-06`
  - K562 lag-fix rerun recorded as `Sharpe 2.16 -> 0.7247`, benchmark `0.9359`, `1/8` pass, bootstrap `P(win)=1.2%`
- `storage/reports/feed.json.bak_d716099a_pre_rewrite`
  - archived content for `mile_91af7c48` (K562 lookahead interception article)
  - archived content for `mile_4ec7b75e` (K560 rewrite article)
- `storage/drafts/k560_sector_rotation_rewrite_draft.md`
  - records post-patch K560 rewrite narrative, including:
    - benchmark Sharpe `0.944`
    - momentum_top1 Sharpe `0.734`
    - statement that all Harvey tests fail
- `experiments/k560/figures/make_rewrite_figs.py`
  - explicitly states it was written for a post-patch `2026-05-07` K560 results file

These files are evidence that the patch/rerun historically existed, but they are **not** a substitute for committed experiment artifacts.

## Required Next Step

- Run the patched K562 and K560 scripts in an environment with network access or with a pinned local CSV snapshot.
- Only after that rerun succeeds should:
  - `k562_k560_sector_validation_results.json`
  - `k560_sector_rotation_vt_results.json`
  be overwritten and cited as canonical.
