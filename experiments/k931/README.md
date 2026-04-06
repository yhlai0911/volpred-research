# K931: Copula-GARCH Hedge — 0050.TW Hedged with 2330.TW (TSMC)

## Problem
K923 confirmed copula hedging is ineffective for low-correlation pairs (SPY-GLD, r=0.058, HE<3%).
**Does copula hedging work on high-correlation pairs like 0050.TW-2330.TW (expected r>0.85)?**

## Motivation
- K923: Copula hedge NULL for SPY-GLD (r=0.058, too low for any hedging method)
- K923 suggested: copula hedging needs r>0.90 pairs
- 0050.TW contains ~50% TSMC weight → structurally high correlation
- User's expertise: copula-GARCH/hedging (Lai & Sheu 2010)
- Paper 2 relevance: hedging Taiwan ETF with its largest constituent

## Method
1. Data: 0050.TW (TAIEX 50 ETF) and 2330.TW (TSMC) daily from yfinance, 2006-2026
   - 0050.TW requires `clean_tw50_data()` for split correction
2. Descriptive stats: ADF, ARCH LM, correlation analysis
3. Rolling 250d correlation to verify stability
4. Five hedge ratio methods (same as K923):
   - OLS (expanding window)
   - Rolling OLS (250d window)
   - DCC-GARCH
   - Copula-GARCH (Student-t copula)
   - Copula Quantile Hedge (minimize VaR via simulation)
5. IS (2006-2018) / OOS (2019-2026) evaluation
6. Metrics: HE, VaR 1%/5% reduction, ES 1%/5% reduction, CRRA utility, turnover
7. Cross-comparison with K923 SPY-GLD results

## Error Log Rules Applied
- Fixed seed: `np.random.seed(42)`
- 0050.TW: must use `clean_tw50_data()`
- Hedge ratio uses `shift(1)` — no lookahead
- Student-t scale: `sqrt((df-2)/df)` correction
- Hedging uses hedging metrics (HE/VaR/Utility), NOT Sharpe/CAGR

## Results

### Data
- Period: 2009-01-05 to 2026-04-02, N=4218
- IS: 2006-2018 (N=2463), OOS: 2019-2026 (N=1755)
- Pearson r = 0.7259, Spearman r = 0.7933
- Rolling 250d Pearson: mean=0.8135, range [0.349, 0.955]

### OOS Hedging Effectiveness
| Method | HE | VaR 5% Ratio | ES 5% Ratio | Turnover |
|--------|-----|-------------|-------------|----------|
| OLS | 0.8223 | 0.4372 | 0.4462 | 0.000087 |
| Rolling OLS | 0.8402 | 0.4332 | 0.4317 | 0.001415 |
| DCC | 0.8527 | 0.4200 | 0.4058 | 0.010806 |
| **Copula** | **0.8550** | **0.4139** | **0.4014** | 0.010948 |
| Copula Quantile | 0.8147 | 0.4359 | 0.4565 | 0.001106 |

### Key Findings
1. **Copula hedging is EFFECTIVE** for high-correlation pairs (HE=0.855 OOS)
2. **Copula beats OLS** by 3.27 pp in HE (0.855 vs 0.822), modest but consistent
3. **VaR reduced by ~58%** (ratio 0.41), **ES reduced by ~60%** (ratio 0.40)
4. **Contrast with K923**: TW HE=0.855 vs US HE=0.029 -- correlation is the key driver
5. Copula rho mean=0.818, nu=5.74 (significant tail dependence)
6. IS HE much lower (~0.33) due to regime changes pre-2019; OOS benefits from higher, more stable correlation

### Conclusion
Copula-GARCH hedging is highly effective for high-correlation pairs (0050.TW-TSMC).
The best OOS method is Copula (HE=0.855), beating OLS by 3.27 pp.
This confirms K923's hypothesis: correlation is the prerequisite for copula hedging benefit.
At r=0.73 (Pearson), all methods work well, with copula offering marginal tail improvement.

### Limitations
- 0050.TW data starts 2009 (after clean_tw50_data split fix), shorter IS period
- 2330.TW is ~50% of 0050.TW -- this is a structural relationship, not a general finding
- Rolling correlation varies widely (0.35--0.96); hedging may underperform in low-correlation regimes
- No transaction costs included

## References
- Ederington (1979): The Hedging Performance of the New Futures Markets, JF
- Lai & Sheu (2010): Copula-based hedging
- Hsu, Tseng & Wang (2008): Dynamic Hedging with Futures, JFM
- Patton (2006): Modelling Asymmetric Exchange Rate Dependence, IER

## Prior Work
- K923: SPY-GLD copula hedge (r=0.058, HE<3%, NULL result)
- K920: Student-t copula best for SPY-GLD
- K534: Copula-DCC analysis
