# K964: Earnings Season Volatility Patterns — SPY 20yr Analysis

## Research Question
Does SPY exhibit systematically different volatility during earnings seasons (the ~5-week windows when most S&P 500 companies report quarterly results)?

## Motivation
- K531 confirmed VIX sufficiency (32+ times) for index-level sentiment indicators
- Earnings season represents a **structural** calendar effect (not a sentiment indicator) — worth testing separately
- Literature suggests individual-stock IV spikes around earnings, but does this aggregate to index-level?

## Method
- **Data**: SPY and VIX daily data from yfinance, 2006-01-03 to 2026-04-06 (5,075 observations after NaN removal)
- **Earnings windows** (approximate): Q4=Jan 10-Feb 15, Q1=Apr 10-May 15, Q2=Jul 10-Aug 15, Q3=Oct 10-Nov 15
- **Metrics**: |return|, squared return, 5d/20d rolling RV, VIX level
- **Tests**: Welch t-test, Mann-Whitney U, OLS regression with VIX control, per-quarter dummies
- **Conditional**: High VIX (>20) vs Low VIX (<=20), rolling 5-year stability

## Key Results

### Descriptive Statistics
| Metric | Earnings | Non-Earnings | Ratio |
|--------|----------|-------------|-------|
| \|Return\| | 0.00772 | 0.00787 | 0.981 |
| RV20 (ann) | 0.0370 | 0.0378 | 0.981 |
| VIX | 19.22 | 19.71 | 0.975 |

Earnings season days are actually **slightly less volatile** than non-earnings days (ratio < 1.0).

### Statistical Tests
- Welch t-test (|return|): t = -0.557, p = 0.578 — **NOT significant**
- Welch t-test (RV20): t = -0.301, p = 0.763 — **NOT significant**
- Mann-Whitney U (|return|): p = 0.883 — **NOT significant**
- OLS with VIX control: earnings dummy beta = 0.0028, t = 1.795, p = 0.073 — **NOT significant at Harvey (2016) |t| > 3.0 threshold**

### Per-Quarter Regression (interesting heterogeneity)
| Quarter | Coef | t-stat | p-value |
|---------|------|--------|---------|
| Q4 earnings (Jan-Feb) | -0.0079 | -4.191 | 0.000 |
| Q1 earnings (Apr-May) | +0.0095 | +4.338 | 0.000 |
| Q2 earnings (Jul-Aug) | -0.0010 | -0.710 | 0.478 |
| Q3 earnings (Oct-Nov) | +0.0106 | +2.765 | 0.006 |

Individual quarters show significant effects in opposite directions — Q4 earnings are **less volatile** while Q1/Q3 are **more volatile** — but these cancel out in aggregate. This likely reflects calendar seasonality (March/October tend to be volatile months) rather than an earnings-specific effect.

### Conditional Analysis
- **High VIX (>20)**: ratio = 1.002, t = 0.050, p = 0.960 — No effect
- **Low VIX (<=20)**: ratio = 1.041, t = 1.269, p = 0.205 — No effect
- **Rolling 5-year**: Effect is unstable — positive in 2006-2013, negative in 2016-2024, positive again in recent years

## Conclusion
**NULL RESULT**: There is no systematic earnings season volatility effect at the SPY index level after controlling for VIX. This further confirms VIX sufficiency — VIX already incorporates any aggregate earnings-related uncertainty.

**Strategy implication**: Calendar-based VT overlay for earnings seasons is NOT justified. The existing VIX-based strategies (12/VIX, GARCH VT) already capture this information.

## Limitations
- Uses approximate earnings windows (fixed calendar dates), not actual filing dates
- Index-level analysis — individual stocks may show stronger effects
- Earnings season definition covers ~41% of trading days, which may dilute the signal
- Per-quarter heterogeneity suggests calendar seasonality confounds

## Files
- `k964_earnings_vol.py` — Main analysis script
- `k964_earnings_vol_results.json` — Complete results
- `k964_monthly_vol.png` — Monthly average volatility bar chart
- `k964_earnings_vs_non.png` — Earnings vs non-earnings box plots
- `k964_rolling_effect.png` — Rolling 5-year effect stability

## References
- Patell & Wolfson (1984) — Earnings announcements and intraday volatility
- Savor & Wilson (2016) — Earnings announcements and systematic risk
- Dubinsky et al. (2019) — Aggregate earnings surprises and market volatility
- Harvey (2016) — |t| > 3.0 threshold for multiple testing
