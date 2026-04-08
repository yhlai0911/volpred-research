# K947: Threshold GARCH with VIX as Threshold Variable

## Problem
K942 showed MF-GJR(VIX) improvement varies hugely across VIX regimes: Low(VIX<15) +8.7%, Medium(15-25) +0.5%, High(>=25) +17.3%. This suggests GARCH parameters may differ by VIX regime. Threshold GARCH allows parameters to switch based on VIX level, potentially capturing regime-dependent dynamics better than the smooth multiplicative structure of MF-GJR.

## Models Compared
1. **GARCH(1,1)** - baseline
2. **GJR(1,1,1)** - asymmetric baseline
3. **MF-GJR(VIX)** - current best (smooth multiplicative factor tau = exp(theta0 + theta1*log(VIX)))
4. **T-GJR(c)** - Threshold GJR: separate GJR parameters for VIX < c and VIX >= c
5. **T-MF(c)** - Threshold MF-GJR: separate MF-GJR parameters for each regime

## Data & Method
- **Asset**: SPY (2005-01-05 to 2025-12-31, yfinance)
- **OOS**: 2016-01-04 to 2025-12-31 (2514 days)
- **Window**: 2000 days, refit every 21 days
- **Threshold grid**: c in {15, 18, 20, 22, 25}
- **OOS forecasting**: Recursive (h[t] = f(h[t-1], r^2[t-1])), regime selected by VIX_{t-1}
- **Evaluation**: QLIKE on r^2 (Patton 2011), Spearman rho, DM test (Harvey |t| > 3.0)

## Key Results

### Overall QLIKE (lower is better)
| Model | QLIKE | Spearman rho |
|-------|-------|-------------|
| GARCH | 1.5876 | 0.3803 |
| GJR | 1.5644 | 0.4119 |
| **MF-GJR** | **1.4782** | **0.4553** |
| T-GJR(c=18) [best] | 1.5174 | 0.4287 |
| T-MF(c=25) [best] | 1.5043 | 0.4523 |

### DM Tests
- GJR vs MF-GJR: t = +3.52 *** (significant at Harvey threshold)
- GJR vs T-GJR(c=18): t = +1.77 (not significant)
- MF-GJR vs T-GJR(c=18): t = -3.00 (favors MF-GJR, borderline)
- GJR vs T-MF(c=25): t = +2.20 (not significant at Harvey)
- MF-GJR vs T-MF(c=25): t = -1.83 (favors MF-GJR, not significant)

### Regime-Specific Analysis
| Regime | n | MF-GJR improvement | Best T-GJR | Best T-MF |
|--------|---|-------------------|------------|-----------|
| Low (VIX<15) | 923 | +4.3% | T-GJR(c=15) +2.3% | T-MF(c=22) +5.1% |
| Medium (15-25) | 1228 | +3.6% | T-GJR(c=18) +1.3% | T-MF(c=25) +1.5% |
| High (VIX>=25) | 363 | +15.4% | T-GJR(c=22) +12.5% | T-MF(c=15) +16.1% |

## Conclusion

**MF-GJR(VIX) remains the best overall model.** Neither Threshold GJR nor Threshold MF-GJR can significantly outperform it at the Harvey |t|>3.0 threshold.

Key insights:
1. **Smooth beats discrete**: The smooth multiplicative structure of MF-GJR handles regime transitions better than the hard threshold models. Threshold models suffer from abrupt parameter switching.
2. **T-MF outperforms T-GJR**: When thresholds are used, combining them with the multiplicative factor (T-MF) is better than pure threshold (T-GJR). The best T-MF(c=25) achieves QLIKE=1.504 vs T-GJR(c=18) at 1.517.
3. **High VIX regime**: Both threshold models improve significantly in high-VIX regimes (up to +16% for T-MF(c=15)), but this isn't enough to overcome the penalty from worse medium-regime performance.
4. **T-MF instability**: Some T-MF configurations show very high MSE (e.g., T-MF(c=18) MSE=1481), indicating numerical instability when fitting MF-GJR on small subsamples.
5. **Optimal threshold**: For T-GJR, c=18 is optimal; for T-MF, c=25 is optimal. The fact that different model structures prefer different thresholds suggests the threshold location interacts non-trivially with model complexity.

## Limitations
- Threshold estimated via grid search, not formal inference (Hansen 1996 sup-LR test not implemented)
- Regime-specific estimation uses smaller samples, potentially less reliable
- Only SPY tested; results may differ for other assets
- T-MF has numerical instability issues for some threshold values

## References
- Chen, Liu, So (2013): Threshold Variable Selection for Asymmetric SV
- Hansen (2011): Threshold Autoregressive Models
- Patton (2011): Volatility forecast comparison using imperfect proxies
- K942: VIX regime analysis
- K889: MF-GJR(VIX) best model

## Files
- `k947.py` - Experiment script
- `k947_results.json` - Complete results
- `k947_comparison.png` - Comparison plots
