# K1051: Taiwan TX Futures Overnight Gap Strategy (SPY-conditioned)

## Research Question
Can the overnight gap alpha found in K515 (SPY-conditioned 10.73bp/day, t=4.06) be profitably traded using TX futures (2-3bp round-trip cost) instead of ETF (18.55bp cost that killed the strategy)?

## Motivation
- K515 established that SPY positive returns predict positive Taiwan overnight gaps (10.73bp/day, t=4.06)
- ETF trading costs (18.55bp) exceeded the alpha, making it unprofitable
- TX futures costs (~2bp) are 9x lower, potentially making the strategy viable
- Research program lists this as high-priority under "台指期貨 Overnight Gap Strategy"

## Data Sources
- **TAIFEX tick data**: 3,484 TX files (2012-01-02 to 2026-04-10), Big5 encoding
- **SPY/VIX daily**: yfinance (2011-12 to 2026-04)

## Method
1. Built daily OHLC from tick data using most active contract by volume (roll-gap safe)
2. Computed overnight gap returns: (day_open_t - prev_close) / prev_close
3. SPY-conditioned strategy: go long overnight when SPY_{t-1} > 0
4. TX futures cost: 2bp per round trip

### Critical Timing Analysis
- **Pre-night session (2012-2017)**: Gap = day_close 13:45 → day_open 08:45 (~19 hours). SPY signal from D-1 US close (available 4.75h before Taiwan open). **Correctly lagged.**
- **Post-night session (2017+)**: Night session 15:00-05:00 Taiwan overlaps with US market 21:30-04:00 Taiwan. SPY information is priced in during the night session itself. Gap = early_morning 05:00 → day_open 08:45 (~3.75 hours). **SPY signal has no predictive power for this residual gap.**

## Results

### Descriptive Statistics (3,011 observations)
| Metric | Value |
|--------|-------|
| Mean gap | 1.76 bp |
| Std gap | 42.76 bp |
| Skewness | -0.303 |
| Kurtosis | 6.923 |
| % positive | 52.8% |

### Conditional Gap Analysis
| Condition | Mean Gap (bp) | N |
|-----------|--------------|---|
| SPY Up (all) | +10.40 | 1,675 |
| SPY Down (all) | -9.06 | 1,336 |
| **Spread** | **19.46** | — |
| t-stat (difference) | 12.734 | p<0.0001 |

### Key Finding: Structural Break at Night Session Introduction

| Period | Sharpe | SPY Up Gap (bp) | SPY Down Gap (bp) | Spread (bp) |
|--------|--------|-----------------|--------------------|-----------| 
| Pre-night (2012-2017) | **5.155** | +23.07 | -23.78 | 46.86 |
| Post-night (2017-2026) | **-0.590** | +0.68 | +2.69 | -2.01 |

### Cross-Period Validation (SPY-conditioned, net 2bp)
| Period | N | Sharpe | Avg Gap Signal=1 (bp) | t-stat |
|--------|---|--------|-----------------------|--------|
| 2012-2015 | 987 | 4.962 | 22.75 | 10.235 |
| 2016-2019 | 842 | 2.338 | 8.48 | 4.308 |
| 2020-2023 | 766 | 0.059 | 2.12 | 0.103 |
| 2024-2026 | 416 | -0.382 | 0.82 | -0.490 |

### Night Session Analysis (Post-2017)
| Signal | Sharpe | Note |
|--------|--------|------|
| Same-day SPY (LOOKAHEAD) | 6.947 | SPY trades during night session — not tradeable |
| Lag-corrected SPY (D-2) | -0.083 | No predictive power |
| Unconditional (B&H night) | 0.607 | Mean night return 4.86bp |

## Conclusion

**NULL RESULT for tradeable strategy.** The SPY-conditioned overnight gap alpha was real in the pre-night-session era (2012-2017) when the 19-hour trading gap allowed SPY information to accumulate unpriced. After TAIFEX introduced the night session (~2017-05-22), the gap shrunk to 3.75 hours and SPY information is incorporated in real-time during the overlapping night session. TX futures cost savings (2bp vs 18.55bp ETF) are irrelevant because the alpha itself has disappeared.

The full-sample Sharpe of 2.588 is **misleading** — driven entirely by pre-2017 data that no longer applies. This is a structural change in market microstructure (night session introduction), not a statistical fluke.

### Implications
1. **K515's finding is historically valid** but no longer actionable
2. **Night session eliminated the information asymmetry** — SPY info is now priced during the overlapping session
3. **For any future overnight strategy**: must account for the night session overlap with US market hours
4. **Warning**: same-day SPY conditioning on night returns gives artificially high Sharpe (6.95) due to temporal overlap — a subtle form of lookahead

## Files
- `K1051.py` — Main experiment script
- `K1051_results.json` — Full results with all metrics
- `K1051_daily_ohlc.csv` — Daily OHLC extracted from tick data (cached)
- `K1051_merged_data.csv` — Merged gap returns + SPY/VIX
- `K1051_night_returns.csv` — Night session returns (post-2017)
- `K1051_gap_returns.png` — Strategy comparison charts
- `K1051_yearly_analysis.png` — Yearly gap analysis

## References
- K515: Overnight gap alpha (SPY-conditioned 10.73bp/day, t=4.06)
- TAIFEX night session introduced ~2017-05-22
