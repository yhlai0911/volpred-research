# K951: Copula-GARCH Hedge on High-Corr ETF Pairs

## Question
Where is the correlation threshold for copula hedge to add value?
- K923: SPY-GLD (r=0.058) → NULL (HE<3%)
- K931: 0050-TSMC (r>0.9) → HE=0.855

Do ETF pairs with r=0.75-0.93 benefit from copula-based hedging?

## Pairs
1. **SPY-QQQ** (OOS r=0.937, high)
2. **GLD-SLV** (OOS r=0.759, mid-high)
3. **SPY-EWG** (OOS r=0.789, mid)

## Methods
1. **OLS (expanding)**: h = Cov/Var on all available data
2. **Rolling OLS (252)**: 252-day rolling window
3. **DCC-GARCH (proxy)**: GJR-GARCH marginals + rolling 252-day correlation
4. **Copula-GARCH**: GJR-GARCH marginals → PIT → Student-t copula → copula-implied h

Copula refit every 63 trading days. IS: 2006-2018, OOS: 2019-2025.

## Data Source
yfinance (SPY, QQQ, GLD, SLV, EWG), 2006-04-28 to 2025-12-30, 4950 trading days.

## Key Results (OOS)

| Pair | OOS r | OLS HE | Roll HE | DCC HE | Copula HE | Cop-OLS |
|------|-------|--------|---------|--------|-----------|---------|
| SPY-QQQ | 0.937 | 0.872 | **0.879** | 0.866 | 0.821 | -0.051 |
| GLD-SLV | 0.759 | 0.560 | **0.570** | 0.553 | 0.442 | -0.118 |
| SPY-EWG | 0.789 | 0.617 | **0.625** | 0.580 | 0.561 | -0.056 |

## DM Tests (OLS vs Copula, squared hedged returns)
- SPY-QQQ: t = -3.14 *** (Copula significantly worse)
- GLD-SLV: t = -3.28 *** (Copula significantly worse)
- SPY-EWG: t = -3.48 *** (Copula significantly worse)

All negative t-stats = OLS has lower loss (better hedging).

## Why Copula Underperforms

1. **Copula nu → 30 (near-Gaussian)**: Student-t copula converges to highest df in grid across all pairs, meaning negligible tail dependence. These ETF pairs do not have the asymmetric crash dependence that copulas capture well.

2. **Copula rho > rolling correlation**: Copula-implied rho (0.86-0.95) consistently exceeds the simpler rolling correlation, leading to systematically higher hedge ratios (over-hedging). Mean h for copula (0.56-0.90) exceeds OLS h (0.46-0.83).

3. **Model complexity penalty**: The copula introduces estimation noise (GARCH + PIT + copula MLE) without compensating benefit when tail structure is weak.

## Conclusion

**Copula-GARCH hedging does NOT add value for US-listed ETF pairs at any correlation level (r=0.76-0.94).**

- Simple Rolling OLS (252) is the best method across all 3 pairs
- The copula's advantage (tail dependence) is absent in these pairs (nu→30)
- Over-hedging from copula rho estimation is the main damage mechanism

**Combined with K923 (SPY-GLD r=0.06, NULL) and K931 (0050-TSMC r>0.9, HE=0.855):**
- Copula hedge works for individual stock pairs (strong firm-specific tail dependence)
- Copula hedge does NOT work for ETF pairs (diversified portfolios smooth out tail dependence)
- The distinction is not correlation level but asset type: individual stocks vs ETFs

## Limitations
- Student-t copula only (not Clayton/Gumbel/Joe for asymmetric tails)
- Nu grid search [3,4,5,6,8,10,15,20,30] may miss optimal values
- DCC approximated by rolling correlation, not true DCC-GARCH
- ETFs only; results may differ for individual stock pairs or futures

## References
- Patton (2006): Modelling asymmetric exchange rate dependence, IER
- Ederington (1979): The hedging performance of the new futures markets, JF
- Joe (1997): Multivariate models and dependence concepts
- Harvey (2016): ...and the cross-section of expected returns, RFS
