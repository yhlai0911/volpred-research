# K1381: Taiwan Tech Sector Vol as Leading Indicator for 0050.TW

**Verdict: MIXED** — Granger causality significant (both TSMC and MTK → 0050, p<0.01) but OOS QLIKE improvement is economically trivial (+0.06%) and does not pass Harvey (1997) |t|>3.0 threshold. VIX significantly hurts OOS performance when added.

## Experiment Summary

| Item | Value |
|------|-------|
| Experiment ID | k1381 |
| Date Range | 2009-02-18 to 2026-04-17 |
| n_total | 3,935 |
| n_train (70%) | 2,754 (to 2021-01-13) |
| n_test (30%) | 1,181 (2021-01-14 to 2026-04-17) |
| RV Proxy | Squared log return r² (Patton 2011) |
| Outlier Filter | \|log-return\| > 0.5 masked as NaN (1 obs removed: 2014-01-02 split) |

## Motivation

Taiwan's 0050.TW ETF tracks the TAIEX Top 50 index, heavily weighted toward technology. TSMC (2330.TW) alone constitutes ~30-35% of the index; MediaTek (2454.TW) is another major component. The question: does tech-sector realized volatility lead broad market volatility with a 1-day lag, beyond what the HAR model already captures from 0050's own lags?

## Models

All models estimated via OLS (numpy lstsq). **All features lagged by 1 day** to prevent lookahead.

| Model | Features |
|-------|----------|
| HAR | const + rv_0050_{t-1} + mean(rv_0050_{t-5:t-1}) + mean(rv_0050_{t-22:t-1}) |
| HAR_X_TSMC | HAR + rv_TSMC_{t-1} |
| HAR_X_MTK | HAR + rv_MTK_{t-1} |
| HAR_X_TECH | HAR + rv_TSMC_{t-1} + rv_MTK_{t-1} |
| HAR_X_VIX | HAR + VIX²_{t-1}/(100²×252) |
| HAR_X_ALL | HAR + TSMC + MTK + VIX |

## Results

### OOS QLIKE (70/30 split, lower is better)

| Model | OOS QLIKE | vs HAR |
|-------|-----------|--------|
| **HAR** | **9.334553** | baseline |
| HAR_X_TSMC | 9.329219 | **+0.06% better** |
| HAR_X_MTK | 9.358599 | -0.26% worse |
| HAR_X_TECH | 9.351835 | -0.18% worse |
| HAR_X_VIX | 9.691537 | -3.83% worse |
| HAR_X_ALL | 9.694772 | -3.86% worse |

### DM Tests vs HAR (Harvey 1997 threshold: |t| > 3.0)

| Comparison | DM t-stat | p-value | Harvey Pass | Direction |
|------------|-----------|---------|-------------|-----------|
| HAR_X_TSMC vs HAR | +0.422 | 0.673 | FAIL | HAR_X_TSMC marginally better |
| HAR_X_MTK vs HAR | -1.223 | 0.222 | FAIL | HAR better |
| HAR_X_TECH vs HAR | -0.807 | 0.420 | FAIL | HAR better |
| **HAR_X_VIX vs HAR** | **-8.822** | **<0.001** | **PASS** | **HAR significantly better** |
| **HAR_X_ALL vs HAR** | **-8.472** | **<0.001** | **PASS** | **HAR significantly better** |

### Granger Causality F-test (lag=5, n=3,913)

| Test | F-stat | p-value | Significant (p<0.05) |
|------|--------|---------|----------------------|
| TSMC → 0050 | 4.016 | 0.0012 | YES |
| MTK → 0050 | 4.708 | 0.0003 | YES |

## Key Findings

1. **Granger causality is real but economically small**: Both TSMC and MTK Granger-cause 0050 at p<0.01 (lag=5), indicating linear predictive content. However, the OOS QLIKE improvement from TSMC is only +0.06% — statistically insignificant under Harvey (DM t=+0.42).

2. **VIX as an exogenous regressor significantly hurts OOS**: HAR_X_VIX has DM t=-8.82 (Harvey PASS) indicating it is significantly *worse* than plain HAR. VIX is a US-market implied vol measure that adds noise rather than signal for Taiwan. This result is robust.

3. **Tech volatility spillover to 0050 is largely subsumed by 0050's own lags**: The HAR model's weekly/monthly components already capture the slow-moving component of volatility that tech stocks also exhibit. Adding tech lags provides marginal incremental content.

4. **Adding more predictors generally degrades OOS performance**: HAR_X_ALL is the worst OOS model, consistent with overfitting in the high-correlation tech-sector feature space.

5. **Data quality note**: One extreme outlier on 2014-01-02 (0050.TW stock split artifact: price ~37→9.3, log-return = -1.39) was masked as NaN before RV computation. Without this cleaning, QLIKE values explode to >50,000.

## Annualised Volatility Estimates

| Asset | Annualised Vol (from r²) |
|-------|--------------------------|
| 0050.TW | 18.88% |
| TSMC (2330.TW) | 25.35% |
| MediaTek (2454.TW) | 35.55% |

## Methodology Notes

- **RV proxy**: r² = (log(P_t/P_{t-1}))². Standard choice for daily data under Patton (2011) proxy robustness framework.
- **VIX scaling**: VIX²/(100²×252) converts annualised percentage vol² to daily variance units (consistent with r² scale).
- **Lookahead prevention**: All features constructed with `.shift(1)`. Verified manually: rv_d at date t equals rv_0050 at t-1 for all observations.
- **Forecast positivity**: OLS predictions clamped at 1e-10 to ensure valid QLIKE computation.
- **Granger test design**: Restricted model = HAR(target). Unrestricted = HAR(target) + predictor lags 1..5. F-stat computed as ((RSS_r - RSS_u)/5) / (RSS_u/(n-k_u)).
- **DM sign convention**: d = loss_HAR - loss_X; positive t-stat means HAR-X beats HAR.
- **seed**: 42 (no stochastic elements in this experiment beyond numpy.random seed set at top).

## Files

- `k1381.py` — experiment script (OLS, QLIKE, DM, Granger, plots)
- `k1381_results.json` — all numerical results
- `k1381_forecast_comparison.png` — 2×3 subplot: full/OOS QLIKE, DM t-stats, improvement %, Granger F-stats
- `k1381_run.log` — execution log

## Data Source

`paper/taiwan-vt/data/0050_tw_twii_2330_tw_2317_tw_2454_tw_0056_tw_spy_vix_2008-2026.csv`

Columns used: `0050_tw_adj_close`, `2330_tw_adj_close`, `2454_tw_adj_close`, `vix_adj_close`.
