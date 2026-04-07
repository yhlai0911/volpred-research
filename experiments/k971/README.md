# K971: CAViaR-based Volatility Targeting vs GARCH-VT

## Research Question
If CAViaR (Asymmetric Slope) produces superior VaR forecasts compared to GARCH (as shown in K967, DM t=3.079), does using CAViaR's implied volatility for Volatility Targeting yield better risk-adjusted returns than GARCH-based VT?

## Motivation
- K967 established that CAViaR AS beats GARCH Student-t on VaR prediction (all 6 quantile levels, Kupiec p>0.35)
- Natural extension: use CAViaR's volatility estimate (extracted from VaR) for portfolio allocation
- CAViaR directly models tail quantile dynamics without distributional assumptions -- potentially more responsive to asymmetric shocks

## Method

### CAViaR Asymmetric Slope Model
```
Q_t(alpha) = b0 + b1 * Q_{t-1}(alpha) + b2 * max(r_{t-1}, 0) + b3 * min(r_{t-1}, 0)
```
- Estimated via quantile regression (pinball loss) with Nelder-Mead optimizer, 5 restarts
- Re-estimated every 3 months in OOS (45 refits total)

### Implied Volatility Extraction
```
sigma_t = |Q_t(0.05)| / 1.645  (Normal quantile assumption)
```

### Strategies Compared (OOS: 2015-01 to 2026-04, ~2830 days)
1. **Buy & Hold**: 100% SPY
2. **GARCH-VT**: GJR-GARCH(1,1) rolling sigma, target 15%, w in [0.2, 1.5]
3. **CAViaR-VT**: CAViaR AS implied sigma, same target/bounds
4. **12/VIX**: w = 12/VIX, same bounds

All strategies use **signal.shift(1)** -- yesterday's weight applied to today's return.

## Data
- **Source**: yfinance (SPY, ^VIX)
- **Period**: 2006-01-01 to 2026-04-07 (5094 trading days)
- **IS**: 2006-2014 (initial estimation)
- **OOS**: 2015-2026 (2830 days, includes COVID crash, 2022 bear, Japan carry unwind)

## Results

### OOS Performance Metrics

| Strategy   | AnnRet | AnnVol | Sharpe | Sortino | MDD    | VaR5%   | ES5%    | Turnover |
|-----------|--------|--------|--------|---------|--------|---------|---------|----------|
| Buy & Hold | 13.6%  | 17.7%  | 0.769  | 0.940   | -33.7% | -1.67%  | -2.70%  | 0.000    |
| GARCH-VT  | 11.7%  | 15.0%  | 0.778  | 0.973   | -19.7% | -1.54%  | -2.34%  | 0.066    |
| CAViaR-VT | 10.8%  | 14.7%  | 0.735  | 0.910   | -21.7% | -1.47%  | -2.30%  | 0.088    |
| 12/VIX    | 8.2%   | 9.4%   | 0.866  | 1.153   | -14.4% | -1.03%  | -1.43%  | 0.038    |

### DM Tests (squared return loss)

| Comparison             | t-stat | p-value | Interpretation          |
|----------------------|--------|---------|------------------------|
| CAViaR-VT vs GARCH-VT | -4.717 | 0.0000  | CAViaR lower sq. loss   |
| CAViaR-VT vs 12/VIX   | 14.348 | 0.0000  | 12/VIX lower sq. loss   |
| CAViaR-VT vs B&H      | -4.539 | 0.0000  | CAViaR lower sq. loss   |
| GARCH-VT vs 12/VIX    | 16.731 | 0.0000  | 12/VIX lower sq. loss   |

### Crisis Period Returns

| Crisis               | B&H    | GARCH-VT | CAViaR-VT | 12/VIX  |
|---------------------|--------|----------|-----------|---------|
| COVID (24d)          | -33.4% | -16.0%   | -16.3%    | -12.5%  |
| 2022 Bear (196d)     | -24.1% | -19.1%   | -20.8%    | -14.0%  |
| 2018 Q4 (59d)        | -18.9% | -18.5%   | -17.8%    | -12.2%  |
| Aug 2024 Carry (16d) | -7.6%  | -7.9%    | -7.4%     | -5.3%   |

### Volatility Estimates Comparison (OOS)
- CAViaR sigma: mean=15.6%, std=9.5%, range [4.9%, 119.4%]
- GARCH sigma: mean=15.3%, std=9.8%, range [7.2%, 140.4%]
- Correlation: 0.967 (very high -- they produce similar vol estimates)

## Conclusion

**Partial null result with nuanced findings:**

1. **CAViaR-VT does NOT beat GARCH-VT on Sharpe** (0.735 vs 0.778), despite CAViaR's superior VaR prediction (K967). Better tail modeling does not automatically translate to better portfolio allocation.

2. **CAViaR-VT has lower squared-return loss** (DM t=-4.717, significant at Harvey threshold), meaning it produces lower variance portfolio returns day-to-day. But this comes at the cost of lower returns (10.8% vs 11.7%).

3. **CAViaR-VT has higher turnover** (0.088 vs 0.066) -- the asymmetric response to positive/negative returns creates more weight changes.

4. **Crisis performance is nearly identical** -- COVID crash losses within 0.3% of each other (GARCH -16.0% vs CAViaR -16.3%). The 0.967 correlation between their vol estimates explains this convergence.

5. **12/VIX remains the best risk-adjusted strategy** (Sharpe 0.866, Sortino 1.153) with lowest turnover (0.038) -- confirming the "smooth-weight" design principle.

**Key insight**: CAViaR's advantage is in VaR prediction accuracy (distributional tails), not in volatility level estimation. For VT purposes, both models extract essentially the same signal (corr=0.967), so the simpler GARCH is preferred.

## Files
- `k971_caviar_vt.py` -- main experiment script
- `k971_caviar_vt_results.json` -- full results
- `k971_cumulative_returns.png` -- cumulative return comparison
- `k971_weights_comparison.png` -- weight time series
- `k971_drawdowns.png` -- drawdown comparison

## References
- Engle & Manganelli (2004) "CAViaR: Conditional Autoregressive Value at Risk", JBES
- Glosten, Jagannathan & Runkle (1993) "On the Relation between Expected Value and Volatility", JoF
- K967: CAViaR AS beats GARCH Student-t on VaR (DM t=3.079 at alpha=0.95)
