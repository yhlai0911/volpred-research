# K926: TSMC Earnings/Revenue Announcement Volatility — 0050.TW Event Study

## Problem
TSMC quarterly earnings calls and monthly revenue announcements are major events for
Taiwan's stock market. Given that TSMC accounts for ~50% of 0050.TW's weight, how do
these announcements affect 0050.TW volatility?

## Motivation
- TSMC Q1 2026 earnings call on 04/16, revenue announcement ~04/10
- TSMC is ~50% of 0050.TW weight — individual stock events may dominate
- Compare with K925 (CPI → SPY was non-event at 1.06x NS)

## Method
1. Collected TSMC quarterly earnings dates (2015-2026, 46 events)
2. Generated monthly revenue announcement dates (~10th of each month, 113 non-overlapping)
3. Downloaded 0050.TW and 2330.TW daily data (2014-2026, ~2982 days)
4. Event window analysis: [-5, +5] trading days around each event
5. Compared |return| on event days vs non-event days (Welch's t-test)
6. Analyzed TSMC→0050 beta transmission (bootstrap CI for beta difference)
7. Directional analysis and pre-event drift

## Data Sources
- yfinance: 0050.TW, 2330.TW (2014-01-02 to 2026-04-02)
- TSMC IR: manually compiled quarterly earnings dates
- Revenue dates: ~10th of each month (matched to nearest trading day)

## Key Results

### Volatility Impact on 0050.TW
| Event Type | |Return| Ratio | t-stat | p-value | Significant? |
|-----------|---------------|--------|---------|-------------|
| Quarterly Earnings | 1.16x | 1.32 | 0.190 | NO |
| Monthly Revenue | 1.24x | 2.41 | 0.017 | YES |
| All TSMC Events | 1.21x | 2.71 | 0.007 | YES |

### TSMC's Own Volatility
| Event Type | |Return| Ratio | t-stat | p-value | Cohen's d |
|-----------|---------------|--------|---------|----------|
| Earnings (2330.TW) | 1.54x | 3.66 | 0.0004 | 0.46 |
| Revenue (2330.TW) | 1.19x | 2.44 | 0.016 | 0.18 |

### TSMC → 0050.TW Transmission
- Overall beta: 0.616, corr: 0.879
- **Earnings days beta: 0.455** (significantly LOWER than non-event 0.619)
- Revenue days beta: 0.704 (higher than non-event)
- Beta difference (earnings - non-event): -0.166, 95% CI [-0.252, -0.081] **SIGNIFICANT**

### Pre-Event Drift
- Pre-event CAR [-5,-1]: +0.95% (t=2.25, p=0.029, **significant**)
- Post-event CAR [0,+4]: +0.33% (NS, p=0.384)

### Directional: 59% positive on earnings days (binomial p=0.302, NS)

## Key Findings (200-300 words)
TSMC event study on 0050.TW reveals a nuanced picture. TSMC earnings days show
strong volatility for TSMC itself (1.54x, highly significant) but only moderate
amplification for 0050.TW (1.16x, not significant at 5%). This is a **dampening
effect**: 0050.TW's diversification absorbs TSMC-specific shocks.

Surprisingly, monthly revenue announcements have a LARGER impact on 0050.TW
(1.24x, p=0.017) than quarterly earnings (1.16x, p=0.190). This may reflect
the fact that revenue announcements are more frequent and provide more granular
information about semiconductor demand trends.

The most striking finding is the **lower beta on earnings days** (0.455 vs 0.619).
During TSMC earnings events, the TSMC→0050 transmission weakens — suggesting that
other stocks in 0050.TW move independently or in opposite directions, providing
natural hedging.

A significant pre-event drift of +0.95% in the 5 days before earnings is consistent
with positive anticipation (market expectations of good results). However, the
post-event CAR is not significant, suggesting the drift is priced in by the time
results are announced.

Year-by-year analysis shows 2024 was an outlier (2.03x ratio), likely due to AI/
semiconductor boom making TSMC earnings more market-moving.

Compared to CPI→SPY (K925: 1.06x NS), TSMC events have a larger effect on
0050.TW — supporting the hypothesis that single-stock events matter more for
concentrated ETFs than macro data does for broad indices.

## Limitations
- Earnings dates manually compiled (may differ from actual by 1-2 days)
- Monthly revenue dates approximated as 10th
- TSMC's weight in 0050.TW changed over time (25% → 50%+)
- No control for concurrent US/global events
- Small sample for quarterly earnings (46 events)

## References
- MacKinlay (1997) Event studies in economics and finance, JEL
- Patell & Wolfson (1984) The intraday speed of adjustment

## Output Files
- `k926_tsmc_earnings_vol.py` — main analysis script
- `k926_tsmc_earnings_vol_results.json` — structured results
- `k926_event_window.png` — event window |return| and CAR
- `k926_earnings_vs_revenue.png` — TSMC→0050 beta scatter and comparison
