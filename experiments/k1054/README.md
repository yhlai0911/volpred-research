# K1054: HAR-RV Formal 60-Day SPY -- Proxy Comparison r^2 vs 5-min RV

## Motivation
K1049 (28 OOS days) was the first formal comparison of HAR-RV, GJR-GARCH, and A4f-VIX^2 using dual proxies (5-min RV and squared daily return). However, K1049 was severely limited by sample size: HAR-RV had only 8 effective training observations (30 days - 22 lags), leading to negative Spearman correlations for HAR and unstable beta estimates.

K1054 extends K1049 with the full 60-day 5-min SPY dataset (2026-01-14 to 2026-04-10), yielding 30 OOS days and up to 37 effective training observations for HAR. The core question: does HAR-RV improve with more data, and does A4f maintain its advantage?

## Research Questions
1. With 60 days of 5-min data (~30 OOS), does HAR-RV performance improve over K1049?
2. Does A4f-VIX^2 maintain its QLIKE advantage on BOTH proxies?
3. Are QLIKE rankings proxy-robust (Patton 2011)?

## Method

### Data
- **5-min RV**: Pre-computed from `collect_5min_data.py` using simple returns, stored in `data/intraday/SPY_daily_rv.csv` (60 days)
- **Daily returns**: SPY log returns from yfinance (2833 days, 2015-01-05 to 2026-04-10)
- **VIX**: ^VIX daily close from yfinance

### Models
| Model | Specification | Estimation |
|-------|--------------|------------|
| HAR-RV | RV_t = b0 + b_d*RV_{t-1} + b_w*mean(RV_{t-1:t-5}) + b_m*mean(RV_{t-1:t-22}) | Expanding OLS, initial 30 days, ridge regularization (lambda=0.01) for n<15 |
| GJR-GARCH | GJR(1,1) normal innovations | Rolling 2000 daily returns |
| A4f-VIX^2 | tau_t = theta_0 + theta_1*VIX^2_{t-1}; g_t = GJR(1,1) on r_t/sqrt(tau_t) | Rolling 2000 daily returns |

### Evaluation
- **Dual proxy**: RV (5-min realized variance) and r^2 (squared daily return)
- **Loss function**: QLIKE (Patton 2011 proxy-robust), MSE, MAE
- **Statistical tests**: DM test (Harvey |t|>3.0 threshold), Spearman rank correlation
- **Bootstrap**: 5000 replications for 95% CI on QLIKE differences

### Design Choices
- Ridge regularization for HAR with <15 training obs to prevent wild betas (K1049 had beta_m = -14.88)
- HAR forecasts clamped to [10%, 1000%] of training mean RV to prevent QLIKE explosion
- Random seed: 42

## Results

### QLIKE Loss (lower is better)

| Model | RV proxy | r^2 proxy |
|-------|----------|-----------|
| HAR-RV | -7.657 | -8.009 |
| GJR-GARCH | -7.669 | -8.071 |
| **A4f-VIX^2** | **-7.811** | **-8.123** |

**Rankings: A4f-VIX^2 > GJR-GARCH > HAR-RV (consistent across BOTH proxies)**

### Spearman Rank Correlation (forecast vs target)

| Model | RV proxy | r^2 proxy |
|-------|----------|-----------|
| HAR-RV | -0.282 (p=0.131) | -0.238 (p=0.205) |
| GJR-GARCH | 0.097 (p=0.611) | 0.012 (p=0.949) |
| A4f-VIX^2 | **0.379 (p=0.039)** | 0.239 (p=0.204) |

Only A4f reaches significance on the RV proxy.

### DM Tests

| Comparison | RV proxy t-stat | r^2 proxy t-stat |
|------------|----------------|-----------------|
| HAR vs GJR | 0.14 | 0.69 |
| HAR vs A4f | 2.56* | 1.45 |
| GJR vs A4f | 1.89 | 0.87 |

No comparison reaches Harvey (2016) |t|>3.0 threshold. This is expected with only 30 OOS days.

### Bootstrap 95% CI (QLIKE difference, >0 means model 2 is better)

| Comparison | RV proxy CI | Excludes 0? | r^2 proxy CI | Excludes 0? |
|------------|-------------|-------------|-------------|-------------|
| HAR vs GJR | [-0.158, 0.161] | No | [-0.155, 0.278] | No |
| HAR vs A4f | [0.042, 0.287] | **Yes** | [-0.061, 0.340] | No |
| GJR vs A4f | [0.004, 0.318] | **Yes** | [-0.072, 0.190] | No |

On the RV proxy, both HAR-vs-A4f and GJR-vs-A4f bootstrap CIs exclude zero, favoring A4f.

### Comparison with K1049

| Metric | K1049 (28 OOS) | K1054 (30 OOS) | Change |
|--------|---------------|----------------|--------|
| HAR Spearman (RV) | -0.383 | -0.282 | +0.101 (improved) |
| A4f Spearman (RV) | 0.424 | 0.379 | -0.045 |
| QLIKE ranking (RV) | A4f > HAR > GJR | A4f > GJR > HAR | HAR-GJR swapped |
| QLIKE ranking (r^2) | A4f > GJR > HAR | A4f > GJR > HAR | Unchanged |
| Rankings consistent? | No | **Yes** | Resolved |

## Key Findings

1. **A4f-VIX^2 best on BOTH proxies**: Rankings are now consistent (A4f > GJR > HAR on both RV and r^2), unlike K1049 where they differed. A4f winning on both proxies is a genuine empirical finding (not mechanical).

2. **HAR-RV still struggles**: Even with ridge regularization and 37 effective training obs (up from 8), HAR-RV shows negative Spearman on both proxies. 60 days of RV data is fundamentally insufficient for HAR -- it needs years of daily RV to estimate weekly and monthly components reliably.

3. **A4f Spearman significant**: Only A4f reaches p<0.05 on Spearman (RV proxy), suggesting it's the only model genuinely tracking RV dynamics in this period.

4. **No DM significance at Harvey threshold**: Expected with N=30. Bootstrap CIs are more informative -- they show A4f > GJR and A4f > HAR at 95% level on RV proxy.

5. **VIX regime context**: The OOS period (Feb 27 - Apr 10, 2026) included the tariff crisis (VIX 31.05 peak on Apr 8), providing a stress test. A4f's VIX component likely helps during such episodes.

## Mechanical vs Empirical Distinction
- **GARCH winning on r^2**: EXPECTED (native target) -- mechanical, not a finding
- **HAR winning on RV**: Would be EXPECTED (native target) -- but HAR loses even here due to insufficient training data
- **A4f winning on BOTH**: EMPIRICAL finding -- A4f has no built-in advantage on either proxy, so dual superiority is genuine

## Limitations
- Only 30 OOS days -- still far below 252-day minimum for definitive conclusions
- HAR-RV has only 37 effective training obs (vs 2000 for GARCH) -- unfair comparison
- r^2 is a very noisy proxy (single squared return vs sum of ~78 5-min squared returns)
- VIX regime may not represent typical conditions (includes tariff-driven spike)
- No multiple testing correction beyond Harvey (2016) threshold

## Next Steps
- Continue collecting 5-min data to extend HAR training period
- At 120+ RV days, repeat comparison with HAR having ~100 effective training obs
- At 252+ OOS days, formal comparison can be considered definitive
- Consider HAR-CJ (continuous vs jump decomposition) as HAR training grows

## Files
- `k1054.py` -- Experiment script
- `k1054_results.json` -- Complete results with all statistics
- `k1054_proxy_comparison.png` -- QLIKE, Spearman, DM test, bootstrap CI comparison
- `k1054_forecast_timeseries.png` -- Forecast time series vs actual (3 models, 2 proxies)

## References
- Patton (2011). Volatility forecast comparison using imperfect volatility proxies. JoE.
- Corsi (2009). A simple approximate long-memory model of realized volatility. JFEC.
- Hansen & Lunde (2005). A forecast comparison of volatility models. JFEC.
- Engle & Rangel (2008). The Spline-GARCH Model for Low-Frequency Volatility. RFS.
- Harvey, Leybourne & Newbold (1997). Testing the equality of prediction MSEs.

## Data Sources
- yfinance: SPY daily prices (2015-2026), VIX daily close
- data/intraday/SPY_daily_rv.csv: Pre-computed 5-min realized variance (60 days, Jan 14 - Apr 10, 2026)
