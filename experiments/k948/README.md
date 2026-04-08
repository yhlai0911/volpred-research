# K948: Weekly Return Predictability

## Problem
K924 confirmed daily returns are unpredictable (all 10 SSVS candidates PIP < 0.5). Meanwhile, K143/K943 showed volatility signal-to-noise ratio peaks at h=5 (weekly). Does return predictability also improve at the weekly horizon?

## Motivation
- Fama & French (1988) and Campbell & Shiller (1988) suggest longer-horizon return predictability
- Welch & Goyal (2008) show most predictors fail OOS
- If weekly vol is more predictable (K943: +18.4% improvement at h=5), maybe weekly returns are too

## Method
- **Asset**: SPY (2004-2026, yfinance)
- **Target**: 5-day cumulative log return (non-overlapping weekly samples)
- **OOS**: 2016-01-01 to 2025-12-31 (514 weekly observations)
- **Features** (all lagged by 1 day):
  1. log(VIX)
  2. VIX 5-day change
  3. 20-day momentum
  4. 5-day momentum
  5. VIX/VIX_MA20 ratio
  6. GARCH(1,1) conditional variance (expanding window, recursive OOS)
  7. 5-day realized volatility
  8. TLT 5-day return (yield curve proxy)
- **Models**: OLS, Ridge, LASSO, Random Forest, Historical Mean (baseline)
- **Protocol**: Expanding window, retrain every ~21 days, features standardized

## Key Results (OOS 2016-2026)

| Model | OOS R² | Dir. Acc. | Sharpe (net) | DM t-stat |
|-------|--------|-----------|-------------|-----------|
| OLS | -0.0157 | 53.9% | 0.496 | 0.53 |
| Ridge | -0.0155 | 53.5% | 0.413 | 0.52 |
| LASSO | -0.0129 | 57.2% | 0.663 | 0.54 |
| RandomForest | **0.0097** | **60.9%** | **0.988** | -1.06 |
| HistMean | 0.0000 | 61.9% | 0.810 | — |
| Buy & Hold | — | — | 0.810 | — |

## Conclusion: NULL

**Weekly returns are also largely unpredictable out-of-sample.**

1. **OOS R²**: Only RF achieves positive R² (0.0097), but DM test t=-1.06 is far below the Harvey (2016) threshold of |t|>3.0 — statistically insignificant.
2. **Directional accuracy**: RF's 60.9% is actually below the HistMean's 61.9% (which simply reflects that the market goes up ~62% of weeks). No model predicts direction better than "always predict up."
3. **Strategy Sharpe**: RF achieves 0.988 net, but with only 31 trades over 10 years (97% long) — it's essentially buy-and-hold with rare timely shorts, not robust predictability.
4. **Linear models all fail**: OLS, Ridge, LASSO all have negative OOS R² — they're worse than the historical mean.
5. **Feature importance**: RF relies most on realized_vol_5d (34%) and TLT returns (15%), but the overall predictive power is negligible.

This is consistent with Welch & Goyal (2008): standard return predictors fail OOS even at the weekly horizon. The vol predictability improvement at weekly frequency (K943) does not translate to return predictability.

## Implications
- **Vol predictability ≠ Return predictability**: K943 showed vol improves at weekly horizon, but returns don't follow
- **Efficient market hypothesis holds**: At least for SPY with standard predictors, both daily (K924) and weekly returns are unpredictable
- **VT strategies justified**: Since returns aren't predictable but vol is, volatility-targeting (not return-targeting) remains the correct approach

## Limitations
- Single asset (SPY only)
- Standard linear/tree predictors only (no deep learning, no alternative data)
- Feature set limited to VIX, momentum, vol, TLT
- 2016-2026 OOS period is predominantly bullish

## Files
- `k948.py` — Experiment script
- `k948_results.json` — Complete results with all metrics
- `k948_comparison.png` — 4-panel comparison chart

## References
- Fama & French (1988) — Dividend yields and expected stock returns, JFE
- Campbell & Shiller (1988) — Stock prices, earnings, and expected dividends, JF
- Welch & Goyal (2008) — A comprehensive look at the empirical performance of equity premium prediction, RFS
