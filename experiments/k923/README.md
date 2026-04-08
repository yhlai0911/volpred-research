# K923: Copula-Based Optimal Hedge Ratio -- SPY Hedged with GLD

## Problem
K920 confirmed SPY-GLD has Student-t copula structure (lambda=0.14, crisis coupling).
K918 BEKK shows no cross-spillover. K915 DCC conditional correlation predicts r=0.88.
**Does a copula-based hedge ratio outperform OLS/DCC hedge ratios, especially in tail events?**

## Motivation
- User's core expertise: copula-GARCH/hedging (Lai & Sheu 2010)
- K920: Student-t copula, lambda=0.14, nu=3.05 (strong tail dependence)
- K915: DCC dynamic correlation
- K918: BEKK no cross-asset spillover
- Face I (futures hedging) core methodology
- Academic contribution: Does copula-implied hedge ratio add value over linear methods?

## Method

### Data
- SPY + GLD daily returns, 2005-01-04 to 2026-04-02, 5345 observations (yfinance)
- IS: 2005-2018 (3522 obs), OOS: 2019-2026 (1823 obs)
- Hedge portfolio: R_h = R_SPY - h * R_GLD

### 5 Hedge Ratio Methods
1. **OLS (expanding)**: h = expanding-window Cov/Var
2. **Rolling OLS (250 days)**: Rolling window Cov/Var
3. **DCC-GARCH**: h_t = rho_DCC * sigma_SPY / sigma_GLD
4. **Copula-GARCH**: GJR-GARCH marginals -> Student-t copula -> copula-implied h
5. **Copula Quantile Hedge**: Minimize 5% VaR via 10,000 copula simulations

### Evaluation (Hedging metrics, NOT trading metrics!)
- HE (Ederington 1979), VaR/ES Reduction (5% and 1%), CRRA Utility, Turnover
- DM test on squared hedged returns (OOS)
- Tail event analysis: SPY drops > 2*sigma

## Results

### Key Findings (NULL RESULT)

**All methods produce extremely low HE due to SPY-GLD correlation of only 0.058.**
Gold is not an effective daily-frequency variance hedge for equities.

| Method | OOS HE | OOS VaR 5% Red. | OOS ES 5% Red. | Turnover |
|--------|--------|-----------------|----------------|----------|
| OLS | 0.0071 | 1.0026 | 1.0006 | 0.000140 |
| Rolling OLS | -0.0070 | 1.0349 | 1.0074 | 0.005713 |
| DCC | **0.0269** | 1.0145 | 1.0068 | 0.011292 |
| Copula | 0.0176 | 1.0023 | 1.0065 | 0.006253 |
| Copula Quantile | 0.0000 | 1.0098 | **0.9982** | 0.001592 |

- **Best OOS HE**: DCC (2.7%) -- but still negligible
- **No method achieves economically significant hedging** (all HE < 3%)
- VaR/ES reduction ratios near 1.0 for all methods (no meaningful tail protection)
- **No DM test reaches Harvey (2016) |t| > 3.0 threshold** -- no significant differences
- Copula Quantile Hedge is the only method with ES reduction < 1 (OOS: 0.9982), but marginally

### Tail Event Analysis (OOS, 46 events with SPY < -2.47%)
- **Copula has best variance ratio during tail events**: 0.902 (10% variance reduction)
- OLS: variance ratio 0.986
- Other methods: variance ratio > 1.0 (worse than unhedged!)
- Loss reduction minimal for all methods (< 1%)

### DM Tests (OOS, none significant at Harvey t>3.0)
| Comparison | t-stat | Significant? |
|------------|--------|-------------|
| OLS vs DCC | +2.37 | No |
| DCC vs Copula | -1.27 | No |
| DCC vs Copula_Quantile | -2.37 | No |
| Copula vs Copula_Quantile | -1.34 | No |

### Interpretation
1. SPY-GLD correlation is too weak (r=0.058) for any method to produce meaningful hedging
2. Copula does show a small tail-event advantage (variance ratio 0.902 in OOS tail events)
3. The theoretical advantage of copula (capturing non-linear tail dependence) exists but is
   economically negligible when the underlying linear correlation is near zero
4. DCC achieves the "best" HE (2.7%) but this is not practically significant
5. The copula quantile hedge correctly targets tail risk but the benefit is minimal

### Limitations
- Daily frequency only; monthly rebalancing might show different results
- Gold's role is diversification (low correlation) not hedging (high negative correlation)
- Copula parameters refitted every 63 days; more frequent refit might help
- Student-t copula assumed; time-varying copula (Patton 2006) could be different

## Conclusion
**NULL RESULT**: Copula-based hedge ratios do not significantly outperform linear methods
for SPY-GLD at daily frequency. The fundamental issue is that SPY-GLD correlation (~0.06) is
too weak for any hedging method to be effective. Gold's value is in portfolio diversification
(K846: three moats), not in variance hedging. This is consistent with the finance literature:
hedging requires high negative correlation (e.g., futures on the same underlying).

For the copula hedging paper, the appropriate application is commodity futures (oil, gold)
or currency hedging where spot-futures correlation > 0.90.

## References
- Ederington (1979): The Hedging Performance of the New Futures Markets, JF
- Lai & Sheu (2010): Copula-based hedging
- Hsu, Tseng & Wang (2008): Dynamic Hedging with Futures, JFM
- Patton (2006): Modelling Asymmetric Exchange Rate Dependence, IER
- K920: Student-t copula, lambda=0.14, nu=3.05
- K915: DCC-GARCH dynamic correlation
- K918: BEKK no cross-spillover
- K846: 50/50 three moats (diversification, rebalancing, crisis alpha)

## Files
- `k923_copula_hedge_ratio.py` -- Main experiment script
- `k923_copula_hedge_ratio_results.json` -- Full results
- `k923_hedge_comparison.png` -- IS/OOS comparison of 5 methods
- `k923_tail_hedging.png` -- Tail event hedging performance
- `k923_hedge_ratios_ts.png` -- Time series of hedge ratios
