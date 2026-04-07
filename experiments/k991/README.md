# K991: Taiwan VT Sensitivity Analysis — k/VIX Parameter Stability

## Problem & Motivation
The Taiwan VT strategy uses `w = 8.63/VIX` to determine equity exposure. The constant 8.63 targets ~15% annualized volatility. **Listing criterion #4 requires that the strategy's Sharpe ratio does not drop more than 30% when the k parameter varies by +-20%.**

This experiment systematically tests the sensitivity of the k parameter across a wide range (5 to 16), with a fine grid (6 to 12, step 0.5) around the baseline.

## Method
- **Data**: 0050.TW (yfinance, 2009-2026, 4219 trading days) + VIX (previous day, shift(1))
- **Strategy**: `w = k/VIX_prev`, clipped to [0.2, 1.5], lagged by 1 day
- **Transaction cost**: 0.585% round-trip when weight changes > 10%
- **k grid**: [5, 6, 7, 8, 8.63, 9, 10, 11, 12, 14, 16] + fine grid [6.0, 6.5, ..., 12.0]
- **Periods**: Full sample (2009-2026), OOS (2019-2026)

## Key Results

### Sensitivity within +-20% (k = 6.90 to 10.36)

| k | Sharpe (Full) | Change | Sharpe (OOS) | Change |
|---:|---:|---:|---:|---:|
| 7.00 | 0.842 | -1.8% | 1.275 | -0.5% |
| 8.00 | 0.833 | -0.7% | 1.271 | -0.1% |
| **8.63** | **0.827** | **0.0%** | **1.269** | **0.0%** |
| 9.00 | 0.820 | +0.8% | 1.268 | +0.1% |
| 10.00 | 0.809 | +2.2% | 1.263 | +0.4% |

**Max Sharpe drop within +-20%: 2.2% (full) / 0.5% (OOS) — far below the 30% threshold.**

### Listing Criterion #4: **PASS**

### Broader Range Observations
- Sharpe decreases monotonically as k increases (higher leverage = more volatility drag)
- Optimal k is around 5-6 (lower leverage), but the curve is very flat from k=5 to k=10
- MDD worsens linearly with k: from -9.5% (k=5) to -29.5% (k=16)
- The strategy is very parameter-insensitive — the entire k=[5,12] range shows Sharpe between 0.78-0.85

### Buy-and-Hold Comparison
- BH Sharpe (OOS): 1.208 vs VT k=8.63 OOS Sharpe: 1.269
- BH MDD: -33.8% vs VT k=8.63 MDD: -15.9%
- VT significantly reduces drawdown while maintaining comparable Sharpe

## Conclusion
The Taiwan VT strategy with k=8.63 is **highly robust** to parameter changes. Within the +-20% range, Sharpe drops by at most 2.2%, far below the 30% threshold. The strategy passes listing criterion #4 with a wide margin.

The optimal k based on Sharpe alone would be lower (5-6), but k=8.63 provides a better balance of return generation and risk management with MDD around -16% vs BH's -34%.

## Files
- `k991_vt_sensitivity.py` — Main experiment script
- `k991_vt_sensitivity_results.json` — Full results with all metrics
- `k991_sharpe_vs_k.png` — Sharpe & MDD vs k parameter
- `k991_fine_grid_sharpe.png` — Fine grid Sharpe curve
- `k991_annual_comparison.png` — Annual Sharpe heatmap by k parameter
