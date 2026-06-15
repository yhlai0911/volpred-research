# Codex Review - K1336

Review date: 2026-06-15

Reviewer: Codex

## Verdict

Experiment integrity: PASS

Research hypothesis: NULL

The implementation uses lagged signals, conservative FRED availability delays,
stale-rate masking, fixed seed bootstrap, and a documented FX spot outlier
filter. The final verdict is correctly downgraded to NULL because the gate's
mean return improvement is not statistically significant and the bootstrap
Sharpe-difference CI crosses zero.

## Checklist

1. Lookahead bias: PASS.
   - FRED observations are converted to conservative availability dates before
     daily alignment (`K1336.py:87-103`).
   - Daily rate alignment masks stale values after a maximum allowed age
     (`K1336.py:106-112`).
   - Carry uses `carry_available.shift(1)` and daily carry return is based on
     that lagged value (`K1336.py:145-147`).
   - FX realized volatility uses a rolling 60-day window shifted by one day
     (`K1336.py:148`).
   - Carry and volatility thresholds are rolling historical thresholds shifted
     by one day (`K1336.py:149-150`).
   - Strategy weights are built from the lagged carry/vol/threshold variables,
     and date `t` returns use those pre-date-`t` weights (`K1336.py:152-180`).

2. Random seed: PASS.
   - `SEED = 42` is set at `K1336.py:20`.
   - Moving-block bootstrap uses `np.random.default_rng(SEED)`
     (`K1336.py:248-275`).
   - `main()` calls `np.random.seed(SEED)` at `K1336.py:333-335`.

3. Formal testing: PASS.
   - Strategy comparison uses HAC(21) for mean daily return differences
     (`K1336.py:234-245`, `K1336.py:343-348`).
   - Sharpe difference is tested with a 1,000-rep 21-day moving-block bootstrap
     (`K1336.py:248-275`).
   - Success and partial gates are explicitly coded before result serialization
     (`K1336.py:352-368`).

4. Data quality controls: PASS.
   - yfinance FX spot is cached from the stated tickers at `K1336.py:115-126`.
   - Extreme daily spot log returns are filtered as data errors at
     `K1336.py:141-143`, with the threshold defined at `K1336.py:30`.
   - Outlier counts are written into `data_quality`
     (`K1336.py:186-194`) and into the generated results.

5. Verdict integrity: PASS.
   - Final results report `NULL`, not PARTIAL or SUPPORT.
   - The gate improves MDD from -33.53% to -9.28%, but average exposure falls
     from 88.15% to 13.21%, so the drawdown improvement is mostly an admission
     filter/cash effect.
   - The return edge is not significant: HAC annualized mean difference is
     -0.14%, t=-0.065, p=0.948; bootstrap Sharpe-diff CI is [-0.429, +0.689].
   - The coded partial gate requires bootstrap `p_gt_0 >= 0.80`; observed
     `p_gt_0=0.67`, so NULL is the correct label.

6. Reproducibility: PASS.
   - Results record sources, tickers, rate series, sample bounds, data quality,
     method settings, tests, figures, literature, and caveats
     (`K1336.py:370-452`).
   - Results are written directly from computed objects at `K1336.py:454-456`.

## Residual Risk

This is not a true FX forward carry backtest. It approximates carry with
spot-plus-short-rate differentials and uses FRED/OECD rate proxies that differ
in frequency and update latency. A production-quality test would need
institutional forward points, investable execution costs by currency, and
vintage-aware rate-release data.
