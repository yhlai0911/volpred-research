# K1268b — GDELT 5-min vs SPY 5-min RV (Paid Intraday Re-run Scaffold)

**Status**: Scaffold only; experiment not executed
**Date**: 2026-05-25
**Seed**: 42
**Parent**: K1268 (`experiments/k1268/`)
**Motivation**: K1268 validated that GDELT 2.0 public-bulk data can be fetched and aggregated to 5-minute bars, but the core hypothesis could not be tested because `yfinance` does not provide backtest-grade 1-minute/5-minute SPY history for the 2020/2023/2024 crisis dates. K1268b keeps the original crisis-day design and swaps only the equity data source.

## Research question

Conditional on having a backtest-grade intraday SPY data source, do 5-minute GDELT event/sentiment intensity bars lead subsequent 5-minute SPY realized volatility on crisis days?

## Why this scaffold exists

1. Preserve the original K1268 question without retrofitting the sample to the last 30/60 days.
2. Make the paid-data prerequisite explicit before any agent tries to run the experiment.
3. Stage a reviewable implementation skeleton so the main thread can wire Polygon / Databento / self-hosted archive without redesigning the methodology.

## Data sources

- **GDELT 2.0**: `experiments/k1268/gdelt_5min_bars.parquet`
- **SPY intraday bars**: not bundled in this scaffold; expected from one of:
  - Polygon paid historical minute bars
  - Databento historical OHLCV
  - self-hosted SPY 1-minute archive exported to CSV / parquet

## Planned sample

- 2024-08-05 (Nikkei flash-crash spillover)
- 2020-03-12 (COVID crash)
- 2023-03-13 (SVB stress)

No date substitution is allowed merely to fit a free-data window.

## Method outline

1. Load the pre-fetched GDELT 5-minute bars from K1268.
2. Load SPY intraday bars from a paid or self-hosted source.
3. Compute 5-minute realized variance from intraday returns.
4. Build causal GDELT predictors with lags `1, 2, 3, 6` bars.
5. Evaluate cross-correlation / predictive regressions only with lagged predictors.
6. Apply multiple-testing discipline from K1268 (headline threshold adjusted for the pre-registered lag grid).

## Lookahead policy

- **Hard rule**: predictor at time `t` must use only information observed by `t-1`.
- In code this is enforced by explicit `signal.shift(1)` when constructing lagged GDELT predictors.
- SPY realized variance at bar `t` is the target; same-bar GDELT signal must never be multiplied against same-bar RV.

## Expected outputs

The future executed run should populate:

- `k1268b_results.json` with:
  - data provenance and sample counts
  - per-date SPY / GDELT coverage diagnostics
  - lag-by-lag test statistics and p-values
  - experiment verdict (`PASS` / `CONDITIONAL_PASS` / `NULL` / `FAIL_NO_DATA`)
- optional charts:
  - GDELT intensity vs SPY 5-minute RV overlay
  - lagged cross-correlation heatmap

## Current scaffold contents

- `README.md`: experiment contract and constraints
- `k1268b.py`: initial implementation skeleton with data gate, seed, and lookahead-safe feature builder
- `k1268b_results.json`: placeholder schema for the eventual executed run

## Success criteria for the eventual run

1. Use the original three crisis dates.
2. Report exact SPY intraday source and bar count per date.
3. Keep GDELT and SPY aligned on a common 5-minute grid.
4. Preserve `signal.shift(1)` discipline for every predictive specification.
5. If the paid data source is still unavailable or incomplete, report `FAIL_NO_DATA` honestly.
