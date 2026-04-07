# K972: MF2-VIX Taiwan Validation — 0050.TW with VIX Lead-Lag

## Problem / Motivation
K970 showed MF2-VIX (sigma2 = tau_VIX * g_GJR) improved GJR QLIKE by 9.55% on SPY. Taiwan's stock market has a natural lead-lag with U.S. VIX (Taiwan opens when U.S. is closed), which should strengthen the VIX signal. This experiment validates MF2-GARCH on 0050.TW to test whether the cross-market VIX lead-lag amplifies performance.

## Method
- **Asset**: 0050.TW (Taiwan Top 50 ETF), cleaned with `clean_tw50_data()` for split artifact
- **VIX alignment**: VIX[t-1] (prior US close) reindexed to Taiwan trading days + ffill. Total lag for tau = 2 days (VIX[t-2] -> tau[t-1] -> forecast sigma2[t])
- **Models**: GJR baseline, MF2-RV (22d rolling r2), MF2-VIX (cross-market VIX), MF2-EMA (EMA r2)
- **IS/OOS**: 2009-02-13 to 2018-12-28 (IS: 2441 obs) / 2019-01-02 to 2026-04-02 (OOS: 1756 obs)
- **Evaluation**: QLIKE (Patton 2011), DM test (Harvey 2016 |t|>3.0), MZ regression, VaR backtesting

## Key Results

### QLIKE Performance (OOS)
| Model   | QLIKE  | Improvement vs GJR | MZ-R2  |
|---------|--------|-------------------|--------|
| GJR     | 1.4551 | baseline          | 0.0775 |
| MF2-RV  | 1.4380 | +1.18%            | 0.0652 |
| MF2-VIX | 1.4396 | +1.07%            | 0.1438 |
| MF2-EMA | 1.4011 | +3.71%            | 0.0920 |

### DM Tests
No pairs pass Harvey (2016) |t| > 3.0 threshold. Best: MF2-EMA vs GJR (t=2.566, p=0.010).

### VaR Backtesting
All models pass Kupiec test at both 1% and 5% levels. MF2-RV achieves closest-to-expected violation rate at 1% (0.97% vs expected 1.0%).

### Cross-Market Comparison (K970 SPY vs K972 0050.TW)
| Model   | SPY QLIKE | TW QLIKE | SPY improvement | TW improvement |
|---------|-----------|----------|-----------------|----------------|
| GJR     | 0.9383    | 1.4551   | baseline        | baseline       |
| MF2-RV  | 0.9805    | 1.4380   | -4.49%          | +1.18%         |
| MF2-VIX | 0.8487    | 1.4396   | +9.55%          | +1.07%         |
| MF2-EMA | 0.9267    | 1.4011   | +1.24%          | +3.71%         |

## Conclusions

1. **MF2-VIX is WEAKER on Taiwan (+1.07%) vs SPY (+9.55%)**. The VIX lead-lag hypothesis is NOT confirmed — the extra lag (total 2 days for TW vs 1 day for SPY) dilutes the VIX signal rather than amplifying it.

2. **MF2-EMA is the best model for Taiwan (+3.71%)**, outperforming MF2-VIX. The EMA of own-market squared returns captures Taiwan's volatility dynamics better than cross-market VIX.

3. **MF2-RV improves on TW (+1.18%) but worsens on SPY (-4.49%)** — an interesting reversal, suggesting RV smoothing benefits Taiwan's noisier returns.

4. **No model passes Harvey threshold** — improvements are economically meaningful but not statistically significant at |t| > 3.0. Best candidate: MF2-EMA (t=2.566).

5. **Taiwan's higher volatility** (kurtosis 18.0 vs SPY ~typical 5-10) means more noise in r2 proxy, making it harder for any model to achieve significance.

## Limitations
- VIX is a U.S. market indicator; Taiwan-specific fear measures (e.g., TAIEX VIX equivalent) might perform better
- Total VIX lag of 2 days may be too stale for fast-moving markets
- Single split point IS/OOS; rolling window or cross-OOS would be more robust
- 0050.TW data starts 2009 (vs SPY 2006), shorter IS period

## Files
- `k972_mf2_taiwan.py` — experiment script
- `k972_mf2_taiwan_results.json` — full results JSON
- `k972_volatility_components.png` — long-run component plots
- `k972_oos_comparison.png` — OOS forecast comparison

## References
- Conrad, C. & Engle, R. (2025). Two-component GARCH models with exogenous long-run dynamics. J. Applied Econometrics.
- Patton, A.J. (2011). Volatility forecast comparison using imperfect volatility proxies. J. Econometrics.
- Harvey, C.R., Liu, Y., & Zhu, H. (2016). ...and the cross-section of expected returns. Review of Financial Studies.
