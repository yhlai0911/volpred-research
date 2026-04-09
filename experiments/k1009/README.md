# K1009: TXO Put-Call Ratio Fear Indicator for Taiwan Market

## Research Question
Can fear proxies (analogous to TXO Put/Call ratio) predict 0050.TW returns or improve volatility prediction?

## Motivation
Taiwan's options market is dominated by retail traders (~60-70%). Extreme Put/Call ratios may signal excessive hedging (contrarian buy signal). This experiment tests whether fear-based indicators have predictive power for Taiwan ETF returns.

## Method
Since TAIFEX P/C ratio data is not easily downloadable programmatically, we construct proxy fear indicators from 0050.TW and VIX:

1. **Down-Day Ratio (20d)**: Rolling proportion of negative return days
2. **RV Z-Score**: How elevated current 20d realized vol is vs 1-year mean
3. **VIX Z-Score**: Global fear proxy (lagged 1 day for Taiwan)
4. **Combined Fear**: Average z-score of all three

### Strategies Tested
- **Contrarian (discrete)**: fear > 90th pctl -> weight=1.0; fear < 10th pctl -> weight=0.3; else 0.7
- **Smooth fear weight**: weight = 0.7 + 0.3 * fear_z, clipped [0.1, 1.5]
- **Predictive regression**: fear -> next-day return
- **Vol prediction**: AR(1) RV20 + fear vs AR(1) RV20 baseline

All signals lagged 1 day (`signal.shift(1)`) to prevent lookahead. TC = 10bps per leg.

## Data
- Source: yfinance (0050.TW, ^VIX)
- Period: 2013-02-04 to 2026-04-07 (3,204 observations)
- OOS: 2019-01-01 onwards (1,756 obs)
- 0050.TW cleaned via `clean_tw50_data()` for split artifact

## Results: NULL

### Strategy Performance (all vs Buy & Hold Sharpe 1.03)
| Strategy | Sharpe | vs B&H t-stat | Significant? |
|----------|--------|---------------|-------------|
| Down-Day Ratio Contrarian | 0.89 | -2.30 | No |
| RV Z-Score Contrarian | 0.98 | -0.95 | No |
| VIX Contrarian | 0.93 | -1.76 | No |
| Combined Fear Contrarian | 0.91 | -2.15 | No |
| Smooth Combined Fear | 0.70 | -3.36 | Yes (LOSES) |
| Smooth RV Fear | 0.88 | -1.58 | No |
| Smooth VIX Fear | 0.71 | -3.22 | Yes (LOSES) |

### Predictive Regression (fear -> next-day return)
| Predictor | t-stat | p-value | R-squared | OOS R-squared |
|-----------|--------|---------|-----------|---------------|
| Down-Day Ratio | -0.82 | 0.41 | 0.0002 | 0.0001 |
| RV Z-Score | 1.90 | 0.06 | 0.0011 | -0.0002 |
| VIX Z-Score | 0.37 | 0.71 | 0.00004 | -0.0007 |
| Combined Fear | 0.76 | 0.45 | 0.0002 | -0.0008 |

None significant at Harvey (2016) |t| > 3.0.

### Volatility Prediction (OOS)
- Baseline AR(1) MSE: 0.0110
- Enhanced (AR1 + Fear) MSE: 0.0100 (9.3% improvement)
- DM t-stat: 0.42 (not significant)

### Cross-OOS Robustness: 2/5 wins (FAIL)

## Conclusion
**NULL RESULT.** Fear proxies do not significantly predict 0050.TW returns or improve strategies at Harvey (2016) |t|>3.0. Smooth fear-based strategies actually significantly underperform Buy & Hold, suggesting contrarian fear timing destroys value in Taiwan's structurally bullish ETF market. The RV z-score shows marginal predictive power (t=1.90, p=0.06) but fails Harvey threshold and has negative OOS R-squared.

## Limitations
- Proxy fear indicators used instead of actual TXO P/C ratio (which may have stronger signal)
- Down-day ratio and RV z-score overlap with target variable
- VIX is global, not local fear measure
- TC assumed 10bps for ETF
- No leverage or short-selling considered

## Files
- `k1009.py` - Experiment script
- `k1009_results.json` - Full results
- `k1009_results.png` - Charts
