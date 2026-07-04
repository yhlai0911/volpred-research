# K1634 Codex Methodology Review

Verdict: **CONDITIONAL_PASS**

## Scope

Reviewed `experiments/k1634/k1634.py`, `k1634_results.json`, README narrative, and generated charts for the Sell in May / Halloween indicator myth test.

## Checks

- **Lookahead**: PASS. Calendar month membership is deterministic before each month begins. Monthly returns are computed from prior month-end to current month-end; no same-month return is used to decide the position.
- **Baseline consistency**: PASS. Buy-and-hold and Sell-in-May strategy metrics use the same monthly return series and same 2011-07..2026-06 window.
- **Season sample balance**: PASS after fix. Main sample is exactly 180 complete months with 90 Nov-Apr and 90 May-Oct months per asset.
- **Inference**: PASS with caveat. Monthly returns are non-overlapping, and primary regression uses HAC maxlags=6. Year-block bootstrap and paired-season tests are reported as robustness, not as stronger evidence than HAC.
- **Multiple testing**: PASS. Primary SPY and ^TWII tests include BH-FDR q-values.
- **Seed / reproducibility**: PASS. Bootstrap uses `SEED=1634`; data are cached under `data/`.
- **Small sample disclosure**: PASS. README discloses 14 complete paired seasons and avoids overclaiming Taiwan's larger point estimate.

## Fixes Applied During Review

1. Changed pandas monthly resampling from deprecated `M` to `ME`.
2. Changed the main analysis window from 2011-01..2026-06 to 2011-07..2026-06 so both season buckets have equal month counts.
3. Corrected the Sharpe chart scaling bug; only return bars are multiplied by 100.
4. Corrected year-block bootstrap two-sided p-values to use a centered bootstrap distribution.

## Residual Caveats

- ^TWII is a price index, not a total-return index; Taiwan dividend return is not captured.
- Cash return is set to zero in the strategy test. This is conservative for recent high-rate USD cash but not necessarily for Taiwan cash equivalents.
- The test is intentionally recent-sample and reader-facing; it does not overturn global long-history Halloween-effect literature.
