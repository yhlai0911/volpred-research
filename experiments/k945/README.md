# K945: Quadratic vs Minimum-Variance Hedging under GARCH

## Problem
Traditional minimum-variance (MV) hedging minimizes Var(R_h). Quadratic hedging (QH) minimizes E[R_h^2] = Var(R_h) + E[R_h]^2, simultaneously accounting for variance and mean deviation. Under GARCH dynamics, does QH outperform MV?

## Motivation
Ma (2026, J. Futures Markets) proposes quadratic hedging under GARCH as an improvement over standard MV hedging. The key theoretical difference is:
- h_MV = Cov(S,F) / Var(F)
- h_QH = (Cov(S,F) + mu_S * mu_F) / (Var(F) + mu_F^2)

When daily mean returns are near zero, the QH correction term vanishes. This experiment tests whether the difference is economically meaningful.

## Method
- **Asset pairs**: SPY-QQQ, GLD-SLV, SPY-IWM (high-correlation ETFs, no futures data available)
- **5 methods**: Static OLS, Rolling OLS (252d), MV-GARCH, QH-GARCH, Naive 1:1
- **OOS period**: 2016-01-01 to 2025-12-31 (~2,500 obs)
- **Evaluation**: HE, VaR/ES reduction, turnover, DM test (Harvey |t| > 3.0)
- **Extensions**: monthly frequency analysis, high-vol vs low-vol regime analysis
- **Data source**: yfinance

## Key Results

### Daily Frequency (Main Result)
| Pair | Method | HE | VaR5% Red. | ES5% Red. |
|------|--------|-----|-----------|-----------|
| SPY-QQQ | MV-GARCH | 0.8709 | 0.6445 | 0.6581 |
| SPY-QQQ | QH-GARCH | 0.8711 | 0.6450 | 0.6585 |
| GLD-SLV | MV-GARCH | 0.5785 | 0.3510 | 0.3506 |
| GLD-SLV | QH-GARCH | 0.5782 | 0.3511 | 0.3501 |
| SPY-IWM | MV-GARCH | 0.7519 | 0.4637 | 0.5298 |
| SPY-IWM | QH-GARCH | 0.7519 | 0.4630 | 0.5299 |

- QH-MV hedge ratio correlation > 0.9999 for all pairs
- Mean absolute difference: < 0.001
- DM test: No pair shows |t| > 3.0 for QH vs MV

### Monthly Frequency
- QH-MV difference becomes larger (h_diff ~0.001-0.014) but still economically negligible
- QH objective (E[R_h^2]) improvement: < 0.15% for all pairs
- mu^2/Var ratio at monthly: 0.016-0.079 (vs ~10^-4 at daily)

### Regime Analysis
- High-vol and low-vol regimes: QH-MV difference remains negligible in both
- No evidence that QH is more valuable during market stress

## Conclusions
1. **QH ≈ MV at daily frequency**: The QH correction term is negligible because daily mean returns are ~O(10^-5) while variance is ~O(10^-4). The mu^2/Var ratio is ~O(10^-4).
2. **Monthly frequency**: Difference measurable but economically insignificant (< 0.15% improvement).
3. **Cross-pair**: HE scales with correlation (SPY-QQQ 87% > SPY-IWM 75% > GLD-SLV 58%).
4. **Practical implication**: MV hedging is sufficient for daily rebalancing. QH adds complexity without meaningful improvement.
5. **NULL result as predicted**: This confirms the theoretical expectation that QH = MV when mu ≈ 0.

## Limitations
- ETF pairs used as proxy for spot-futures (no actual futures data)
- Rolling 252-day covariance as simplified proxy for GARCH conditional covariance
- No transaction costs modeled
- 10-year OOS may not capture rare extreme regimes where QH could differ more

## References
- Ederington (1979) - The hedging performance of the new futures markets
- Baillie & Myers (1991) - Bivariate GARCH estimation of the optimal commodity futures hedge
- Ma (2026) - Quadratic hedging under GARCH, Journal of Futures Markets

## Files
- `k945.py` - Experiment script
- `k945_results.json` - Full results
- `k945_hedge_comparison.png` - Comparison chart
