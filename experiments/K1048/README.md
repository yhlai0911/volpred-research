# K1048: Threshold GARCH-X with Variable Selection

## Motivation
Combines K1031's SSVS variable selection insight (VIX9D^2 PIP=1.000, VIX^2 PIP=0.995) with K813's threshold/regime-switching concept. Tests whether GARCH parameters and optimal exogenous variables differ between high/low VIX regimes.

**Research Questions:**
1. Do GARCH parameters significantly differ between high/low VIX regimes?
2. Does the optimal exogenous variable differ by regime?
3. Can a threshold GARCH-X model beat A4f (GJR+VIX^2) out-of-sample?
4. What is the optimal VIX threshold?

## Related Experiments
- **K1031**: Bayesian SSVS for GARCH-X -- VIX9D^2 PIP=1.000, VIX^2 PIP=0.995
- **K813**: Smooth Transition GARCH -- In-sample LR=252 sig, but OOS DM=-0.11 NS (11 params too many)
- **K1019**: MS(2)-GJR -- Regime dynamics real (DM t=-3.20), but lost to A4f

## Method
- **Threshold GJR-GARCH-X**: Split variance equation by lagged VIX level (no lookahead)
- **Threshold candidates**: VIX = {15, 20, 25, 30, 35}
- **Variable selection**: BIC-based per-regime selection from {VIX^2, VIX_level, log_VIX, VIX_change, VIX_percentile}
- **OOS**: Rolling window=2000, refit every 63 days, 2019-2026

## Data
- **Asset**: SPY (2004-04-02 to 2026-04-10, N=5,540)
- **Source**: yfinance (SPY, ^VIX, ^VIX9D)
- **In-sample**: 2004--2018 (N=3,712)
- **OOS**: 2019--2026 (N=1,828)
- **Seed**: 42

## Key Findings

### 1. Threshold Effect is Statistically Significant In-Sample
- Optimal threshold: **VIX = 15**
- LR test: LR=135.23, p<0.001 (chi2_6)
- BIC improvement: 85.9 (pooled: -24737.5, threshold: -24823.4)

### 2. Parameter Differences Across Regimes are Substantial

| Parameter   | Pooled | Low (VIX<=15) | High (VIX>15) |
|-------------|--------|---------------|----------------|
| omega       | 2e-6   | 7e-6          | 5e-6           |
| alpha       | 0.053  | 0.038         | 0.000          |
| **gamma**   | 0.085  | 0.038         | **0.168**      |
| beta        | 0.882  | 0.718         | 0.879          |
| persistence | 0.978  | 0.775         | 0.964          |

**Interpretation**: In the high VIX regime, the leverage effect (gamma) is 4.5x larger, alpha drops to zero (all asymmetric response), and persistence is much higher. The low VIX regime has lower persistence (0.775 vs 0.964) -- volatility shocks dissipate faster when VIX is calm.

### 3. Optimal Exogenous Variables Differ by Regime
- **Low VIX regime**: VIX_change (momentum) improves BIC by 20.3
- **High VIX regime**: VIX_percentile (relative level) improves BIC by 6.0
- **Interpretation**: In calm markets, VIX momentum captures short-term shifts. In stressed markets, the relative VIX level (vs 252-day history) captures mean-reversion pressure.

### 4. OOS: Threshold Models Improve QLIKE but NOT Significantly

| Model           | QLIKE     | DM vs GJR | DM vs A4f |
|-----------------|-----------|-----------|-----------|
| GJR (baseline)  | -8.2586   | --        | --        |
| GJR+VIX^2 (A4f) | -8.2788  | t=-0.995 NS | -- |
| Threshold GJR   | -8.2817   | t=-1.016 NS | t=-0.211 NS |
| Threshold GJR-X | **-8.2831** | t=-0.900 NS | t=-0.246 NS |

**No DM test passes the Harvey (2016) |t|>3.0 threshold.** The threshold model achieves the best QLIKE numerically but cannot be considered statistically superior.

### 5. VaR Backtest: Threshold Models Better at 5% Level

| Model           | VaR 5% (Kupiec) | VaR 1% (Kupiec) |
|-----------------|-----------------|-----------------|
| GJR             | FAIL (p=0.015)  | FAIL (p<0.001)  |
| GJR+VIX^2      | FAIL (p=0.002)  | FAIL (p<0.001)  |
| **Threshold GJR** | **PASS (p=0.864)** | FAIL (p<0.001) |
| Threshold GJR-X | PASS (p=0.154)  | FAIL (p<0.001)  |

**Notable**: Only the threshold models pass VaR 5% Kupiec. All models fail at 1% (under Normal distribution). This suggests regime-specific parameters improve tail calibration at the 5% level, but a Student-t distribution is needed for 1%.

## Conclusion
- **In-sample**: Threshold effect is highly significant (LR=135.23), with substantial parameter differences. VIX=15 is the optimal threshold.
- **OOS QLIKE**: Threshold GJR-X achieves the best QLIKE (-8.2831) but the improvement is **not statistically significant** (DM t=-0.246 vs A4f).
- **VaR performance**: Threshold models are the **only ones passing Kupiec at 5%**, indicating practical value for risk management even without QLIKE significance.
- **K813 lesson confirmed**: Even with a more parsimonious threshold structure (10-12 params vs K813's 11), the OOS improvement over simple models remains statistically insignificant. The in-sample complexity does not translate to OOS gains in point forecasts.
- **New insight**: The regime-specific variable selection reveals that VIX momentum matters in calm markets while VIX percentile matters in stressed markets -- a potential research direction for adaptive models.

## Limitations
- Normal distribution assumed (explains VaR 1% failures)
- VIX9D not tested in OOS due to shorter sample
- Threshold estimated on in-sample then fixed for OOS (could be adaptive)
- Only 5 discrete threshold candidates tested

## Files
- `k1048.py` -- Experiment script
- `k1048_results.json` -- Full results
- `k1048_regime_parameters.png` -- Regime-specific parameter plots
- `k1048_qlike_comparison.png` -- OOS QLIKE comparison

## References
- Gonzalez-Rivera (1998, JBES) - Threshold GARCH
- Chen & So (2006) - Threshold heteroscedastic models
- So, Chen, Liu (2006, JRSS-C) - SSVS for GARCH
- Patton (2011) - QLIKE loss function
- Harvey (2016) - t>3.0 threshold for multiple testing
