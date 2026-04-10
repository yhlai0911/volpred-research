# K1029: Financial Stock Early Warning System - Fubon/Financial ETF -> TSMC/0050.TW Vol Transmission

## Motivation
K757 discovered Granger causality from Fubon (2881.TW) to TSMC (2330.TW) with F=6.11. This experiment extends that finding to test whether Taiwan financial stock volatility can serve as an early warning system for 0050.TW (Taiwan 50 ETF) volatility, and whether this information adds value beyond what VIX already provides.

## Research Questions
1. Do Taiwan financial stocks (2881 Fubon, 0055 Financial ETF) volatility lead 0050.TW/TSMC?
2. Can financial stress indicators serve as regime overlay for Taiwan VT (8.63/VIX)?
3. How much overlap with VIX information?

## Method
- **Data**: yfinance, 2015-01-01 to 2026-04-09 (2646 common trading days)
- **Assets**: 0050.TW, 2330.TW, 2881.TW, 0055.TW, ^VIX
- **Granger Causality**: On squared returns (volatility proxy), lags 1-5
- **Partial Granger**: Controlling for VIX (3 lags) via nested F-test
- **FinStress Indicator**: 22-day rolling vol of 0055.TW, high stress = expanding P80
- **GARCH-X**: Two-step approach: GJR-GARCH(1,1) base + delta * lagged FinStress
- **VT Overlay**: 8.63/VIX * (1 - 0.3 * I(FinStress > P80)), with signal.shift(1)
- **Evaluation**: QLIKE on r^2, DM test (Harvey t>3.0), Sharpe/MDD comparison
- **Seed**: 42

## Key Results

### Granger Causality (All Highly Significant)
| Pair | Best Lag | F-stat | p-value |
|------|---------|--------|---------|
| Fubon -> 0050 | 1 | 12.15 | 0.0005 |
| FinETF -> 0050 | 1 | 24.35 | <0.0001 |
| Fubon -> TSMC | 1 | 39.34 | <0.0001 |
| FinETF -> TSMC | 1 | 77.73 | <0.0001 |
| VIX -> 0050 | 1 | 65.28 | <0.0001 |
| 0050 -> Fubon (reverse) | 1 | 8.56 | 0.0035 |

### Partial Granger (VIX-Controlled) -- All Survive
| Pair | F-stat | p-value |
|------|--------|---------|
| Fubon -> 0050 | 3.82 | 0.0096 |
| FinETF -> 0050 | 18.98 | <0.0001 |
| Fubon -> TSMC | 11.73 | <0.0001 |

### Financial Stress Conditional Analysis
- High stress 0050 avg r^2: 0.000350 vs low stress: 0.000105
- **Volatility ratio: 3.33x** (t=10.52, p<0.0001)

### GARCH-X Evaluation (OOS, 505 days)
| Metric | GJR Base | GJR-X |
|--------|---------|-------|
| QLIKE | **1.974** | 2.056 |
| DM t-stat | -- | -4.43 (base sig. better) |

- delta (FinStress) t-stat = -1.20, p=0.23 (NOT significant in IS)
- GARCH-X **hurts** OOS forecasting (base significantly better at Harvey threshold)

### VT Strategy Overlay
| Strategy | Ann Return | Ann Vol | Sharpe | Max DD |
|----------|----------|---------|--------|--------|
| BH 0050 | 18.24% | 19.17% | 0.951 | -33.0% |
| VT 8.63/VIX | 12.15% | 8.75% | 1.389 | -14.3% |
| VT + FinStress | 11.71% | 8.30% | **1.410** | **-13.4%** |

### VIX vs FinStress Overlap
- Correlation: 0.507
- Jaccard similarity (high regimes): 0.323
- Unique FinStress signals (stress high, VIX not): 175 days

### Robustness (best settings: P70, R50%)
- Sharpe ranges from 1.340 (P90/R50) to 1.469 (P70/R50)
- All configurations with P70-P80 beat baseline (1.389)
- Lower percentile thresholds (more frequent signals) work better

## Conclusions

**Overall: MIXED** -- Granger causality survives VIX control (3/3 pairs significant), but two-step GARCH-X actually HURTS OOS forecasting (DM t=-4.43, base significantly better). FinStress has predictive information for regime identification but NOT for improving point variance forecasts. VT overlay shows marginal Sharpe improvement (1.389 -> 1.410) via MDD reduction (-14.3% -> -13.4%), not alpha generation.

1. **Q1: Financial vol does Granger-cause 0050/TSMC volatility**, even after controlling for VIX. The FinETF->0050 channel (F=18.98) is stronger than Fubon->0050 (F=3.82), suggesting sector-wide financial stress matters more than individual stock vol. This confirms and extends K757.

2. **Q2: FinStress works as a regime indicator but not as a GARCH-X regressor.** The delta coefficient is not significant (t=-1.20, p=0.23), and adding it to GARCH actually degrades OOS performance. However, as a binary regime overlay for VT, it provides marginal improvement (~1.5% Sharpe gain, ~6% MDD improvement).

3. **Q3: VIX and FinStress capture partially overlapping but distinct information** (corr=0.507, Jaccard=0.323). There are 175 days where FinStress signals high stress but VIX does not -- these are Taiwan-specific financial stress events not reflected in US VIX.

## Implications
- FinStress is a **weak but real** signal for Taiwan VT overlay
- The improvement is via risk reduction (lower vol, lower MDD) not alpha
- Consistent with VIX sufficiency thesis (VIX captures most of the story; FinStress adds marginal edge)
- For practitioners: monitoring 0055.TW vol can flag Taiwan-specific stress events

## Limitations
- Two-step GARCH-X is approximate (not joint MLE)
- 0055.TW has 13 zero-volume days (low liquidity concern)
- Expanding percentile threshold may adapt slowly to regime changes
- Only tested on Taiwan market
- VT overlay improvement is modest (~1.5% Sharpe, within estimation error SE~0.23)

## Files
- `k1029.py` -- Experiment script
- `k1029_results.json` -- Complete results
- `k1029_granger_causality.png` -- Granger causality heatmap + partial Granger bars
- `k1029_finstress_timeline.png` -- FinStress timeline vs 0050 drawdown
- `k1029_strategy_comparison.png` -- Strategy comparison + robustness heatmap

## References
- Granger (1969) -- Causality framework
- Patton (2011) -- QLIKE evaluation, proxy-robust
- Harvey (2016) -- |t| > 3.0 threshold for multiple testing
- K757 -- Fubon->TSMC Granger F=6.11 (prior finding)
- K55/K82/K88 -- Taiwan VT guide, 8.63/VIX optimal
