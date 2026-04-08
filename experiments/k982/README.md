# K982: Sector Dispersion & Correlation Regime Analysis

## Research Question
Do sector dispersion and inter-sector correlation have predictive power for SPY volatility beyond VIX?

## Motivation
SPY volatility is composed of individual sector volatilities and their correlations. When all sectors move together (high correlation), SPY vol rises (2008, 2020). When sectors rotate independently (high dispersion, low correlation), SPY vol may remain moderate. This experiment tests whether these structural decomposition signals add forecasting value beyond VIX.

## Data
- **Source**: yfinance
- **Period**: 2018-06-20 to 2026-03-04 (limited by XLC availability from 2018)
- **Assets**: 11 SPDR sector ETFs (XLK, XLF, XLV, XLC, XLY, XLI, XLP, XLE, XLU, XLRE, XLB) + SPY + VIX
- **Observations**: 1,936 (after alignment and rolling window warmup)
- **IS/OOS split**: 2021-01-01 (IS: 616 obs, OOS: 1,297 obs)

## Method
1. **Cross-sectional dispersion**: daily std of 11 sector returns
2. **Average pairwise correlation**: rolling 22-day window, mean of 55 unique pairs
3. **Target**: 22-day forward realized volatility (annualized)
4. **All predictors lagged by 1 day** (shift(1)) to prevent lookahead
5. **Models**: OLS regression with IS/OOS evaluation + DM test

## Key Results

### Predictive Regressions (OOS R2)
| Model | OOS R2 | Delta vs M1 |
|-------|--------|-------------|
| M1: VIX only | 0.2649 | baseline |
| M2: VIX + Dispersion | 0.2582 | -0.0067 |
| M3: VIX + Avg Correlation | 0.2631 | -0.0018 |
| M4: VIX + Disp + Corr | 0.2563 | -0.0086 |
| M5: Dispersion only | -0.1934 | -- |
| M6: Avg Correlation only | -0.0961 | -- |

**Neither dispersion nor correlation improves OOS prediction beyond VIX.** All DM tests insignificant (p > 0.12). VIX already captures the information in these signals.

### Correlation Regime Analysis
| Regime | Mean Future RV | Obs |
|--------|---------------|-----|
| High (corr > 0.6) | 0.2223 | 453 |
| Medium | 0.1540 | 851 |
| Low (corr < 0.4) | 0.1364 | 609 |

High vs low regime difference is highly significant (t=13.73, p<0.0001, passes Harvey threshold). Correlation spikes (top 10% 5-day change) also predict higher future RV (t=4.05).

### Strategy Backtest (OOS 2021-2026)
| Strategy | Sharpe | Ann. Return | MDD |
|----------|--------|-------------|-----|
| Buy & Hold | 0.774 | 13.1% | -26.2% |
| 12/VIX | 0.805 | 7.6% | -15.2% |
| 12/VIX + Corr Overlay | 0.785 | 6.7% | -12.7% |

Correlation overlay slightly reduces Sharpe (0.805 -> 0.785) but improves MDD (-15.2% -> -12.7%). The effect is minor.

## Conclusions
1. **VIX already captures sector correlation information** -- adding dispersion/correlation to VIX does not improve OOS forecasts (incremental R2 is negative)
2. **Correlation regimes are real** -- high-corr periods have 63% higher future RV than low-corr periods (t=13.73)
3. **But VIX already reflects this** -- VIX rises in high-corr regimes (mean VIX 27.2 vs 16.5), making the signal redundant
4. **Dispersion is weaker than correlation** as a standalone predictor (OOS R2 = -0.19 vs -0.10)
5. **Correlation overlay on 12/VIX** offers marginal MDD improvement but no Sharpe improvement

## Limitations
- XLC only available from 2018, limiting sample to ~8 years
- Equal-weighted dispersion (not market-cap weighted)
- 22-day rolling window; results may be sensitive to window choice
- OOS period includes COVID (extreme high correlation) and 2022 rate hikes
- No transaction costs in strategy backtest

## References
- Solnik & Roulet (2000), "Dispersion as cross-sectional volatility", FAJ
- Pollet & Wilson (2010), "Average correlation and stock market returns", JFE
- Stivers (2003), "Firm-level return dispersion and the future volatility", JFQA

## Files
- `k982_dispersion.py` -- main experiment script
- `k982_dispersion_results.json` -- full results
- `k982_correlation_regime.png` -- rolling correlation vs VIX
- `k982_dispersion_analysis.png` -- dispersion vs future volatility scatter
