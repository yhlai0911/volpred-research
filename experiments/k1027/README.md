# K1027: Drawdown Recovery Speed — K735 Corrected Methodology

## Problem & Motivation
K735 reported that VIX predicts drawdown depth (rho=-0.49) and duration (rho=+0.45), but Codex audit found two HIGH-severity bugs:
1. **Fake OOS**: used full-sample data while claiming out-of-sample results
2. **Lookahead bias**: strategy signal was not properly lagged

This experiment redoes the analysis with corrected methodology to determine whether VIX truly predicts drawdown characteristics.

## Method
- **Data**: SPY & VIX from yfinance, 2005-2026 (5,099 observations after feature engineering)
- **Drawdown definition**: peak-to-trough decline > 5% (identified 23 drawdowns total)
- **Features**: VIX level, VIX percentile (rolling 252d), VIX slope (5d), realized vol (20d), return momentum (20d)
- **Targets**: drawdown depth, days to trough, days to recovery
- **Strict IS/OOS split**: IS = 2005-2018 (12 drawdowns), OOS = 2019-2026 (11 drawdowns)
- **Correlation**: Spearman rank, with 5000-rep bootstrap 95% CIs
- **Strategy**: VIX-percentile-based de-leveraging overlay with explicit `signal.shift(1)`
- **Seed**: 42

## Key Results

### Correlation Analysis (IS vs OOS)
| Feature | Target | IS rho | OOS rho | Stable? |
|---------|--------|--------|---------|---------|
| VIX Level | Depth | +0.000 | -0.136 | YES |
| VIX Percentile | Depth | -0.357 | -0.337 | YES |
| RVol (20d) | Days to Trough | +0.477 | +0.600 | YES |
| VIX Slope (5d) | Depth | +0.615 | -0.245 | NO |
| Momentum (20d) | Days to Trough | -0.011 | -0.482 | NO |

- 9/15 feature-target pairs showed stable IS-to-OOS correlations
- **No single feature has statistically significant OOS predictive power** at conventional levels
- VIX percentile-depth correlation is the most consistent (IS rho=-0.357, OOS rho=-0.337) but p > 0.05 in both samples

### Strategy Performance (OOS 2019-2026)
| Strategy | Sharpe | Ann Return | Ann Vol | MDD |
|----------|--------|-----------|---------|-----|
| Buy & Hold SPY | 0.878 | 17.2% | 19.6% | -33.7% |
| **DD Protection (70pct)** | **0.914** | **12.6%** | **13.8%** | **-18.9%** |
| 12/VIX (lagged) | 1.014 | 9.6% | 9.5% | -14.4% |

- DM test vs BH: t=-1.552 (p=0.121) -- **NOT significant** at Harvey (2016) |t|>3.0 threshold
- DM test vs 12/VIX: t=1.459 (p=0.145) -- **NOT significant**
- Strategy Sharpe/BH ratio = 1.04x (well below 2x warning threshold)

### Drawdown Behavior During Major Events
- COVID-19 crash (2020, -33.7%): average weight 0.56 -- partial de-leveraging
- 2022 bear market (-24.5%): average weight 0.67 -- moderate de-leveraging
- 2025 correction (-18.8%): average weight 0.57

## Conclusions

1. **K735's VIX-drawdown correlation (rho=-0.49) was inflated by fake OOS**. Corrected IS rho for VIX level vs depth is 0.000, and OOS rho is -0.136. VIX percentile shows a more consistent but weak relationship (IS -0.357, OOS -0.337).

2. **No practical strategy advantage over 12/VIX**. The drawdown protection overlay achieves Sharpe 0.914 vs 12/VIX's 1.014 in OOS. The MDD improvement (18.9% vs 14.4%) does not compensate for the lower Sharpe.

3. **VIX is reactive, not predictive, for drawdowns**. VIX rises DURING drawdowns, not before them. The VIX level at the drawdown peak is not significantly correlated with subsequent depth or duration.

4. **Realized vol (20d) is the most consistent predictor of days-to-trough** (IS rho=+0.477, OOS rho=+0.600), but still not statistically significant (p=0.051 in OOS).

## Limitations
- Small drawdown sample (12 IS, 11 OOS) limits statistical power
- 5% threshold is arbitrary; different thresholds may yield different results
- COVID-19 is an extreme OOS outlier that dominates results
- VIX percentile uses rolling 252d lookback, introducing window dependency
- Strategy de-leveraging reduces downside but also misses upside recovery

## Files
- `k1027_drawdown_recovery.py` -- experiment script
- `k1027_results.json` -- full results
- `k1027_vix_vs_depth.png` -- VIX vs drawdown depth scatter (IS vs OOS)
- `k1027_oos_cumulative.png` -- OOS cumulative return comparison
- `k1027_drawdown_timeline.png` -- Full drawdown timeline with VIX overlay

## References
- K735: Original drawdown recovery study (Codex-invalidated)
- K648: Drawdown Recovery — Piecewise 7.7% monthly loss rate, Risk Parity fastest recovery
- K687/K697: VT = drawdown insurance, not alpha generator
