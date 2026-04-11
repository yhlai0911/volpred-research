# K1050: Earnings Season Volatility Patterns — Does A4f Capture Earnings Vol?

## Research Question
Is A4f's QLIKE improvement over GJR-GARCH concentrated during earnings seasons (Jan/Apr/Jul/Oct reporting windows), or is it uniform across all periods?

## Motivation
- K964 found earnings season vol patterns exist at the per-quarter level (Q1/Q3 more volatile, Q4 less) but cancel out in aggregate
- K988 found A4f (multiplicative GARCH-X with VIX^2 and free omega) beats GJR with DM t=+4.48
- If A4f's VIX component specifically captures forward-looking earnings uncertainty, the improvement should be LARGER during earnings season
- If improvement is uniform, VIX is a general fear gauge, not an earnings anticipation tool
- This informs Paper 9's source decomposition narrative

## Method
- **Data**: SPY daily returns + VIX, 2005-01-04 to 2026-04-10 (n=5,350), from yfinance
- **Earnings season**: K964 definition (Jan 10-Feb 15, Apr 10-May 15, Jul 10-Aug 15, Oct 10-Nov 15)
- **Models**: A4f (sigma^2 = tau * g, tau = theta0 + theta1 * VIX_{t-1}^2, free omega) vs GJR-GARCH(1,1)
- **OOS**: 2019-01-01 to 2026-04-10, n=1,828, refit every 63 days, window=2,000
- **Evaluation**: QLIKE on r^2 (Patton 2011), DM test (Harvey |t| > 3.0), bootstrap concentration test
- **Random seed**: 42

## Key Results

### Overall
| Model | QLIKE | Spearman rho |
|-------|-------|-------------|
| GJR   | 1.4930 | 0.367 |
| A4f   | 1.4084 | 0.417 |
| **Improvement** | **5.66%** | **DM t = -4.09** |

### Seasonal Decomposition
| Period | n | QLIKE GJR | QLIKE A4f | Improve | DM t |
|--------|---|-----------|-----------|---------|------|
| Earnings | 749 | 1.5379 | 1.4705 | 4.38% | -2.68 |
| Non-earnings | 1,079 | 1.4619 | 1.3654 | **6.60%** | **-3.10** |

A4f improvement is actually LARGER during non-earnings season (6.60% vs 4.38%).

### Per-Quarter Breakdown
| Quarter | n | Improve | DM t |
|---------|---|---------|------|
| Q4 Earnings (Jan-Feb) | 202 | 5.54% | -1.97 |
| Q1 Earnings (Apr-May) | 177 | 4.21% | -2.06 |
| Q2 Earnings (Jul-Aug) | 185 | 0.13% | -0.05 |
| Q3 Earnings (Oct-Nov) | 185 | 6.87% | -1.76 |

Q2 earnings (Jul-Aug) shows nearly zero improvement. Q3 (Oct-Nov) shows the largest improvement but low statistical significance due to small sample.

### Concentration Test (Bootstrap, n=5,000)
- Contrast (earnings - non-earnings): 0.0296
- Bootstrap t-stat: 0.721
- Bootstrap p-value: 0.471
- 95% CI: [-0.048, 0.113]
- **NOT significant**: Improvement is uniform across seasons

### VIX Level During Earnings
- VIX during earnings: mean 19.80 (median 18.04)
- VIX non-earnings: mean 20.51 (median 18.56)
- Welch t = -1.96, p = 0.050
- VIX is actually slightly LOWER during earnings season, consistent with K964's finding that aggregate earnings vol cancels out

## Conclusion

**A4f improvement is UNIFORM across earnings/non-earnings seasons** (bootstrap p=0.471). VIX captures GENERAL volatility information, not earnings-specific uncertainty. This supports the interpretation that VIX is a broad fear gauge rather than an earnings anticipation tool.

For Paper 9: This means A4f's advantage comes from VIX's continuous tracking of market-wide risk perceptions (geopolitical, macro, liquidity), not from any specific calendar event. The source decomposition should emphasize VIX as a forward-looking summary statistic of ALL risk factors, consistent with the VIX sufficiency finding (confirmed 30+ times across experiments).

Notable nuance: Q2 earnings (Jul-Aug) shows near-zero A4f improvement (0.13%, DM t=-0.05). This could reflect summer low-vol regime where both models converge, rather than an earnings-specific effect.

## Limitations
- Earnings season covers ~41% of trading days, which is broad and may dilute true earnings-specific effects
- Per-quarter subsets have 177-202 OOS days each, limiting DM test power (no individual quarter reaches Harvey |t|>3.0)
- Calendar-based definition, not tied to actual earnings filing dates
- Only tested on SPY; individual stocks may show different patterns
- OOS period 2019-2026 includes COVID (2020) which dominates volatility during Q1/Q2 earnings windows

## Files
- `K1050.py` - Main experiment script
- `K1050_results.json` - Complete results
- `K1050_seasonal_qlike.png` - Bar chart: A4f vs GJR QLIKE by season/quarter
- `README.md` - This file

## References
- Patton (2011). Volatility forecast comparison. J Econometrics 160:246-256.
- Harvey et al. (2016). t > 3.0 threshold.
- Engle, Ghysels & Sohn (2013). Stock Market Volatility and Macroeconomic Fundamentals. RES 95(3):776-797.
- Patell & Wolfson (1984). Earnings announcements and intraday volatility.
- Savor & Wilson (2016). Earnings announcements and systematic risk.

## Data Source
yfinance: SPY (2005-2026), ^VIX (2005-2026). n=5,350, n_oos=1,828.
