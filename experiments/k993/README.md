# K993: VIX Term Structure Medium-Frequency Strategy (5-22 day Horizon)

## Problem & Motivation
K975 found that VIX/VIX3M slope provides +2.2% incremental R-squared for 5-day realized volatility prediction (DM p=0.0002). However, K976 showed that adding slope to daily MF2-GARCH yields NULL results due to horizon mismatch. The slope's predictive power lives at 5-22 day horizons, not daily.

**Question**: Can we design a medium-frequency (weekly or monthly rebalance) strategy that exploits the slope's predictive power?

## Method
- **Signal**: VIX/VIX3M slope ratio (< 1 = contango/normal, > 1 = backwardation/stress)
- **Strategies tested**:
  1. **Slope VT (Weekly)**: Regime-based weights from slope, rebalanced every 5 days
  2. **Slope VT (Monthly)**: Same but rebalanced every 22 days
  3. **Slope+12/VIX (Weekly)**: 12/VIX base weight adjusted by slope, weekly rebalance
  4. **Slope+12/VIX (Monthly)**: Same but monthly rebalance
  5. **Benchmarks**: Buy & Hold, Daily 12/VIX, Weekly 12/VIX (no slope)
- **Lookahead prevention**: `signal.shift(1)` applied before rebalance logic
- **Transaction cost**: 0.05% per weight change
- **IS**: 2010-2018, **OOS**: 2019-2026
- **Data**: yfinance (SPY, ^VIX, ^VIX3M), 4088 common trading days
- **Seed**: np.random.seed(42)

## Key Results

### OOS Performance (2019-2026)
| Strategy | Sharpe | MDD | Avg Weight |
|----------|--------|-----|------------|
| Buy & Hold | 0.654 | -33.7% | 1.00 |
| Daily 12/VIX | 0.531 | -14.6% | 0.72 |
| Weekly 12/VIX | 0.477 | -15.6% | 0.72 |
| **Slope VT (Weekly)** | **0.759** | -25.8% | 1.09 |
| Slope VT (Monthly) | 0.726 | -28.2% | 1.09 |
| Slope+12/VIX (Weekly) | 0.485 | -15.5% | 0.75 |
| Slope+12/VIX (Monthly) | 0.493 | -18.6% | 0.75 |

### DM Tests vs Daily 12/VIX (OOS)
| Strategy | DM stat | p-value | Harvey |
|----------|---------|---------|--------|
| Slope VT (Weekly) | 2.549 | 0.011 | NOT sig (|t|<3) |
| Slope VT (Monthly) | 2.321 | 0.020 | NOT sig |
| Slope+12/VIX (Weekly) | -0.412 | 0.680 | NOT sig |
| Slope+12/VIX (Monthly) | 0.371 | 0.711 | NOT sig |

### Stress Period Performance
- **COVID 2020**: Slope VT (Weekly) lost -20.7% vs B&H -33.4% and Daily 12/VIX -12.6%
- **Bear 2022**: Slope VT (Weekly) lost -25.3% vs B&H -24.1% -- slope FAILED here (2022 was contango bear market, slope didn't flag risk)
- **Key insight**: Slope only signals via backwardation. The 2022 bear was a slow grind in contango, making slope useless.

## Conclusion: NULL RESULT

**The slope's +2.2% R-squared for 5d RV does NOT translate to tradeable alpha.**

Key findings:
1. **Slope VT (Weekly) has highest OOS Sharpe (0.76)** but this is misleading -- it runs with avg weight 1.09 (leveraged), so higher Sharpe comes from higher market exposure, not from slope timing.
2. **Slope+12/VIX combinations are WORSE than plain 12/VIX** -- the slope adjustment adds noise rather than signal.
3. **DM tests fail Harvey (2016) threshold** (|t| > 3.0) for all strategies.
4. **2022 bear market reveals fatal flaw**: slope stays in contango during slow bear markets (avg slope 0.93), so it signals "risk-on" during drawdowns.
5. **Weekly rebalance loses ~0.05 Sharpe vs daily 12/VIX** -- confirming that 12/VIX's smooth daily weights are optimal.

**Interpretation**: Slope predicts *volatility level* (5d RV), not *return direction*. High future RV can mean either crash (slope helps) or high-vol rally (slope hurts). This is why R-squared for vol prediction doesn't convert to strategy alpha.

## Limitations
- SPY only (single asset)
- Simple regime thresholds (not optimized, but optimization would be overfitting)
- Transaction costs may differ in practice
- Slope signal could potentially work in a volatility-targeting framework (risk management) rather than return-seeking strategy

## Files
- `k993_slope_medium_freq.py` -- Main experiment script
- `k993_slope_medium_freq_results.json` -- Full results
- `k993_cumulative_returns.png` -- Cumulative returns chart (IS/OOS)
- `k993_slope_regime.png` -- Slope regime and strategy weights time series
