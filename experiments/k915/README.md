# K915: DCC-GARCH Dynamic Correlation — SPY/GLD/TLT Portfolio

## Question
Does dynamic conditional correlation (DCC-GARCH) capture time-varying SPY-GLD-TLT correlations,
and can DCC-based portfolio allocation improve upon the static 50/50 SPY/GLD baseline?

## Motivation
- 50/50 SPY/GLD assumes constant correlation — but correlations shift (flight to quality in crises)
- Engle (2002) DCC-GARCH is the standard dynamic conditional correlation model
- Moves from single-asset volatility to multi-asset correlation modeling

## Method
1. **Stage 1**: Fit GJR-GARCH(1,1) to each asset (SPY, GLD, TLT) — extract standardized residuals
2. **Stage 2**: Estimate DCC parameters (a, b) via MLE on standardized residuals
3. **Analysis**: Dynamic correlations over time, across VIX regimes, during crisis periods
4. **Portfolio**: DCC Min-Var and DCC Risk Parity vs static 50/50, with turnover and net Sharpe

## Data
- SPY, GLD, TLT daily prices from yfinance (2005-01-01 to 2026-04-01)
- VIX for regime classification

## References
- Engle (2002): Dynamic Conditional Correlation, JBES 20(3):339-350
- Engle & Sheppard (2001): Theoretical and Empirical Properties of DCC

## Key Results

### DCC Parameters
- a = 0.0324, b = 0.9553, persistence = 0.988 (highly persistent correlations)

### Dynamic Correlation Statistics
| Pair | Mean | Std | Range | AR(1) |
|------|------|-----|-------|-------|
| SPY-GLD | 0.069 | 0.199 | [-0.640, 0.579] | 0.985 |
| SPY-TLT | -0.245 | 0.225 | [-0.729, 0.330] | 0.989 |
| GLD-TLT | 0.191 | 0.176 | [-0.367, 0.610] | 0.982 |

### Crisis Behavior
- **GFC 2008-09**: SPY-GLD drops to -0.01 (diversification benefit), SPY-TLT deepens to -0.44
- **COVID 2020**: SPY-GLD = -0.07, SPY-TLT = -0.50 (strongest flight to safety)
- **Rate Hike 2022**: SPY-TLT correlation rises to -0.03 (stocks and bonds fall together!)

### VIX Regime Correlations
- SPY-GLD turns **negative** only in extreme VIX (>35): -0.030
- SPY-TLT monotonically decreases with VIX: -0.19 (low) to -0.44 (extreme)

### Portfolio Performance (net of 10bps costs)
| Strategy | Sharpe | AnnRet | AnnVol | MDD | Turnover |
|----------|--------|--------|--------|-----|----------|
| 50/50 SPY/GLD | 0.763 | 10.3% | 13.5% | -36.1% | 0.02% |
| 1/3 Each | 0.811 | 7.9% | 9.8% | -24.0% | 0.02% |
| DCC Min-Var (2) | 0.637 | 7.9% | 12.4% | -36.1% | 7.3% |
| DCC Min-Var (3) | 0.703 | 6.0% | 8.5% | -26.9% | 7.2% |
| DCC Risk Parity | 0.782 | 6.9% | 8.8% | -24.2% | 3.4% |

### DM Test vs 50/50 (Harvey |t|>3.0)
No strategy passes the Harvey threshold. All DM |t| < 2.0.

## Conclusions
1. **DCC captures real correlation dynamics** — correlations swing dramatically (SPY-GLD range: -0.64 to +0.58)
2. **Correlations are regime-dependent** — SPY-TLT hedge strengthens in crises, SPY-GLD weakens
3. **2022 was anomalous** — stocks and bonds fell together (SPY-TLT correlation near zero)
4. **DCC-based allocation does NOT beat static 50/50** at Harvey threshold
5. **High turnover kills DCC strategies** — 7% daily turnover vs 0.02% for static
6. **Static 1/3 each has best Sharpe (0.811) and lowest MDD (-24.0%)**
7. **Null result for DCC allocation, but positive result for correlation modeling**

This confirms the "50/50 irreducible baseline" finding from K687/K702/K846:
static simplicity wins over dynamic complexity due to turnover costs.

## Files
- `k915_dcc_garch_dynamic_correlation.py` — Main experiment script
- `k915_dcc_garch_dynamic_correlation_results.json` — Results
- `k915_dynamic_correlation.png` — SPY-GLD, SPY-TLT dynamic correlation time series
- `k915_portfolio_comparison.png` — Cumulative returns comparison
- `k915_regime_correlation.png` — Correlation by VIX regime
