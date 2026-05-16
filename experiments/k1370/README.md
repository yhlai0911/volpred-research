# K1370: Paper 2 Block-Bootstrap CI — Canonical Full-Sample BW-Robust Spec

- **Experiment ID**: K1370
- **Status**: compute_enqueued
- **Created At**: 2026-05-16
- **Paper**: Paper 2 (Taiwan VT)
- **Priority**: P2

## Problem Statement

Paper 2 §3.2 reports a diversification amplification ratio of ~5.0× (TAIEX γ / mean individual stock γ)
with 90% bootstrap CI [2.8, 8.1]. However, this CI was computed under the **draft rolling-window spec**
(w=2000, 9-stock average γ ≈ 0.054). The canonical K1302+K1302b estimates under **full-sample BW-robust spec**
yield an average individual γ ≈ 0.027, giving a revised point estimate of ~10× (0.272/0.027).

The CI must be recomputed under the canonical spec. Paper 2 currently flags this as `(stale)` with a K1370 forward-ref.

## Method

- **Stocks**: 9 individual Taiwanese stocks (excluding 0056.TW which is itself a diversified ETF):
  - From K1302: 2317.TW (Hon Hai), 2454.TW (MediaTek), 2886.TW (Mega Financial), 2383.TW (ELITE Material)
  - From K1302b: 2882.TW (Cathay Financial), 2891.TW (CTBC), 2412.TW (Chunghwa Telecom), 2885.TW (Yuanta), 2881.TW (Fubon)
- **Index**: TAIEX (^TWII / twii_adj_close)
- **Sample**: 2008-01-01 to 2024-12-31 (aligning with K1302/K1302b canonical sample)
- **Model**: GJR-GARCH(1,1), constant mean, Normal distribution, Bollerslev-Wooldridge robust SE
- **Bootstrap**: Moving block bootstrap, B=10000, block_length=252, seeds 42..10041
- **Joint resampling**: All series (TAIEX + 9 stocks) share the same block structure per replicate
- **Amplification ratio**: γ_TAIEX / mean(γ_i, for converged i with γ_i > 0)
- **CI**: 5th and 95th percentiles of the ratio distribution → 90% CI

## Data Sources

- TAIEX + 2317.TW + 2454.TW: `paper/taiwan-vt/data/0050_tw_twii_2330_tw_2317_tw_2454_tw_0056_tw_spy_vix_2008-2026.csv`
- 2886.TW + 2383.TW: `experiments/k1302/data/{2886,2383}_tw.csv` (adj_close)
- K1302b stocks: `experiments/k1302b/data/{2882,2891,2412,2885,2881}_tw.csv` (Close)

## Expected Output

- `k1370_results.json`: point estimates, 90% CI [low, high], median, full ratio distribution
- Revised CI replaces the stale [2.8, 8.1] in Paper 2 §3.2

## Canonical γ Values (Point Estimates from K1302/K1302b)

| Ticker | γ (full-sample canonical) | Source |
|--------|--------------------------|--------|
| TAIEX (TWII) | 0.272 | Paper 2 (rolling w=2000; recomputed full-sample in this script) |
| 2317.TW | 0.0320 | K1302 TWA |
| 2454.TW | 0.0406 | K1302 TWA |
| 2886.TW | 0.0379 | K1302 TWA |
| 2383.TW | 0.0095 | K1302 TWA |
| 2882.TW | 0.0384 | K1302b |
| 2891.TW | 0.0396 | K1302b |
| 2412.TW | 0.0011 | K1302b |
| 2885.TW | 0.0199 | K1302b |
| 2881.TW | 0.0217 | K1302b |
| **9-stock avg** | **0.0267** | K1302+K1302b (excl. 0056.TW) |

Implied point estimate amplification ratio: 0.272 / 0.0267 ≈ **10.2×**

## Compute Queue

Enqueued via `scripts/compute_queue.py enqueue`. B=10000 with parallel processing
(8 cores) takes approximately 45-90 minutes. Worker cron runs every 15 minutes.

## Lookahead-Free Certification

Block bootstrap resamples historical returns only; GARCH is fit on bootstrap replicates
without any future information. No lookahead risk.
