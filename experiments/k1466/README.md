# K1466 — SE Asia / Frontier EM Vol Decoupling from Developed Markets

**Verdict**: `CONDITIONAL_PASS`
**One-liner**: 4 SE Asia frontier ETFs (VNM/EIDO/THD/EPHE) sit at materially lower median 60-day correlation with SPY than broad EM (EEM), and an equal-weight basket delivers a bootstrap-significant diversification ratio of **1.25 [1.21, 1.31]**. Decoupling is real on average but **fully breaks down in crisis (VIX > 25)** — every EM-SPY pair shows Fisher-z-significant correlation jumps of +0.31 to +0.39.

## Motivation

The "decoupling hypothesis" for emerging and frontier markets has been contested for two decades. Bekaert & Harvey (2003, *Journal of Empirical Finance*) document time-varying market segmentation; Carrieri, Errunza, and Hogan (2007, *Journal of Financial and Quantitative Analysis*) argue that apparent decoupling often reflects measurement issues rather than true segmentation; Bekaert, Ehrmann, Fratzscher, and Mehl (2014, *Journal of Finance*) show global crises sharply integrate previously segmented markets. Most prior work focuses on broad EM aggregates (EEM, MSCI EM); the **smaller SE Asia / frontier ETFs (VNM, EIDO, THD, EPHE)** have received less systematic vol-structure attention despite being marketed to retail investors as portfolio diversifiers. This K asks: do these 4 ETFs deliver the decoupling their marketing implies, and does it survive crisis regimes?

## Data & Sample

- **Source**: yfinance `auto_adjust=True` daily Adjusted Close.
- **Period**: common-start 2010-09-29 (latest IPO = EPHE, 2010-09-28) through 2026-06-09.
- **N obs (returns)**: 3,946 trading days.
- **Tickers**:
  - SE Asia EM: VNM (Vietnam), EIDO (Indonesia), THD (Thailand), EPHE (Philippines).
  - Benchmarks: SPY (US), EFA (developed ex-US), EEM (broad EM).
  - Regime classifier: ^VIX (concurrent).
- Daily log returns. Joint-NaN rows dropped to maintain a balanced panel.

## Methodology

| Step | Method | Lag / Lookahead Guard |
| --- | --- | --- |
| Realized vol | 21-day rolling std of log returns × √252 | Uses returns `r_{t-20..t}` (past info), reported at t. No peek. |
| Rolling correlation | 60-day Pearson | Same window construction. |
| Unconditional correlation | Pearson + Spearman on full sample | Descriptive. |
| Regime conditional | Concurrent VIX split: high > 25, low < 15 | **Descriptive, not a forecast** — VIX_t is concurrent. Explicitly documented; for forecasting work VIX would need t-1 lag. |
| Fisher z test | H0: ρ_high = ρ_low, two-sided | Standard parametric Fisher transform with SE = √(1/(n_h-3) + 1/(n_l-3)). |
| Diversification ratio | DR = (Σ w_i σ_i) / σ_portfolio for equal-weight 4-EM basket | Full-sample point + block bootstrap. |
| Bootstrap | Stationary block bootstrap, block=20, B=1000, **seed=42** | RNG seeded both at module level and in bootstrap function. |

**Lookahead audit**: This is a *structural decoupling* study, not a forecasting backtest. There is no signal-to-return mapping that requires `signal.shift(1)`. All rolling statistics use the trailing window (no centered or forward-looking windows). VIX-regime classification is concurrent and labeled descriptive.

## Results

### Table 1 — Descriptive stats (annualized RV21)

| Ticker | Mean Ann. Vol | Median Ann. Vol | Excess Kurtosis (daily ret) | N |
| --- | ---: | ---: | ---: | ---: |
| VNM | 22.9% | 20.6% | 4.8 | 3,946 |
| EIDO | 23.5% | 20.5% | 8.6 | 3,946 |
| THD | 20.2% | 18.0% | 14.8 | 3,946 |
| EPHE | 19.9% | 17.9% | 29.5 | 3,946 |
| SPY | 14.5% | 12.2% | 13.3 | 3,946 |
| EFA | 15.8% | 13.9% | 11.0 | 3,946 |
| EEM | 19.3% | 17.6% | 6.9 | 3,946 |

SE Asia ETFs sit 3-8 pp above SPY mean vol. EPHE has the heaviest tail (kurt 29.5) — consistent with low-liquidity name risk.

### Table 2 — Rolling 60-day correlation with SPY (median, IQR)

| Ticker | Median | IQR (25-75) | Min | Max |
| --- | ---: | ---: | ---: | ---: |
| VNM | **0.45** | — | — | — |
| EIDO | **0.55** | — | — | — |
| THD | **0.54** | — | — | — |
| EPHE | **0.51** | — | — | — |
| (benchmark) **EEM vs SPY** | **0.75** | — | — | — |

All 4 EM ETFs sit 20-30 pp below EEM's median correlation with SPY. This is the core decoupling evidence.

### Table 3 — Regime-conditional correlation (concurrent VIX)

n_low (VIX<15) = 1,438; n_high (VIX>25) = 490.

| Pair | ρ (VIX<15) | ρ (VIX>25) | Δ | Fisher z p-value | Sig 5% |
| --- | ---: | ---: | ---: | ---: | --- |
| VNM-SPY | 0.29 | 0.68 | +0.39 | < 0.001 | YES |
| EIDO-SPY | 0.40 | 0.75 | +0.35 | < 0.001 | YES |
| THD-SPY | 0.44 | 0.74 | +0.31 | < 0.001 | YES |
| EPHE-SPY | 0.41 | 0.72 | +0.31 | < 0.001 | YES |

**Every pair shows crisis correlation convergence.** Average corr nearly doubles when moving from low-VIX to high-VIX regimes — consistent with Bekaert et al. (2014) "global crisis integration."

### Table 4 — Diversification ratio (equal-weight 4-EM basket)

| Statistic | Value |
| --- | ---: |
| Point DR | 1.254 |
| Bootstrap mean | 1.256 |
| Bootstrap SD | 0.025 |
| 95% CI | **[1.209, 1.307]** |
| Bootstrap B | 1,000 |
| Block size | 20 |
| Seed | 42 |

CI strictly excludes 1.0 → there *is* statistically meaningful diversification across the 4 ETFs.

### Figures

- `figs/fig1_vol_series.png` — Annualized 21d RV time series, EM vs SPY.
- `figs/fig2_rolling_corr_spy.png` — 60d rolling Pearson correlation with SPY.
- `figs/fig3_regime_corr_bar.png` — Regime-conditional corr bar chart with p-values.
- `figs/fig4_diversification_ratio.png` — Rolling 252-day DR over time.

## Verdict & interpretation

**`CONDITIONAL_PASS`** — partial decoupling:

1. **Decoupling exists on average**: all 4 EM medians (0.45-0.55) sit well below the EEM-SPY benchmark (0.75), and the DR bootstrap CI [1.21, 1.31] excludes 1.0.
2. **Decoupling weakens sharply in crisis**: VIX > 25 regimes show every EM-SPY pair jumping +0.31 to +0.39, with Fisher z p < 0.001 in all 4 cases. Crisis-time correlation lands at 0.68-0.75, close to the broad-EM benchmark range, but the experiment does not run a direct equality test against EEM.
3. **Practical implication**: SE Asia frontier ETFs do offer real diversification in normal-vol regimes but should not be sized as a hedge against systemic equity drawdowns. The "decoupling" headline is true on average but breaks when investors most need it.

## Limitations

- **Liquidity / stale prices**: VNM, EIDO, THD, EPHE have thinner trading than EEM. Stale-quote bias inflates idiosyncratic vol and depresses synchronous correlation — meaning the *unconditional* decoupling number is mildly overstated. The crisis-regime correlation is less affected (high-vol days have more genuine trading).
- **yfinance vendor**: Adjusted-close splits / dividends imputed by Yahoo; not cross-validated against TAIFEX-quality source.
- **VIX regime is concurrent**: descriptive only. A forecasting version of this study must lag VIX to VIX_{t-1}.
- **DCC-GARCH deferred**: Engle (2002) DCC-GARCH would deliver continuous correlation dynamics and proper time-varying inference. Marked as future work.
- **Bootstrap robustness**: Block size 20 is conventional. Sensitivity to block ∈ {10, 30, 40} not formally verified.
- **Single basket weighting**: Equal weight only. Inverse-vol or minimum-variance weights might yield different DR.

## Files

- `k1466.py` — end-to-end script (seed=42, stdlib + numpy/pandas/yfinance/scipy/matplotlib).
- `k1466_results.json` — full results, descriptive, crisis windows, all correlations, bootstrap.
- `figs/` — 4 figures.

## References

- Bekaert, G., & Harvey, C. R. (2003). Emerging markets finance. *Journal of Empirical Finance*, 10(1-2), 3-55.
- Carrieri, F., Errunza, V., & Hogan, K. (2007). Characterizing world market integration through time. *Journal of Financial and Quantitative Analysis*, 42(4), 915-940.
- Bekaert, G., Ehrmann, M., Fratzscher, M., & Mehl, A. (2014). The global crisis and equity market contagion. *Journal of Finance*, 69(6), 2597-2649.
- Engle, R. (2002). Dynamic conditional correlation. *Journal of Business & Economic Statistics*, 20(3), 339-350.

## Ready for Codex review

`ready_for_codex_review: true`. Main thread will run Codex pass before writing to `knowledge.json`.
