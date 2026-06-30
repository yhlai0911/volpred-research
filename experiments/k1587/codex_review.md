# Codex Review - K1587

## Verdict

**PASS_WITH_NULL_FINDING**.

The artifact is reproducible and lookahead-safe. The conclusion must remain NULL: lagged NYC PM2.5 does not improve SPY realized-volatility forecasts after HAR/VIX controls, and high-pollution buckets do not show elevated subsequent RV in this sample.

## Checks

- Required experiment files present: `README.md`, `K1587.py`, `K1587_results.json`.
- Source transparency: EPA AirData URL template, NYC counties, SPY/VIX local source, panel dates, and sample sizes are recorded in the JSON.
- Lookahead guard is explicit:
  - `pm25_mean.shift(1)`.
  - `high_aqi100_raw.shift(1)`.
  - `high_aqi150_raw.shift(1)`.
  - OOS training excludes overlapping forward targets by using rows `j <= i-h`.
- Seed is fixed at 42 for block bootstrap routines.
- Forecast comparison uses QLIKE and DM tests rather than only bucket plots.

## Findings

### F1 - Correct null forecast interpretation

The augmented model is worse than the HAR/VIX baseline:

| Horizon | Baseline QLIKE | PM2.5 QLIKE | Improvement | DM t |
|---|---:|---:|---:|---:|
| 1d | 1.752521 | 1.761369 | -0.505% | 1.072 |
| 5d | 0.318720 | 0.323605 | -1.533% | 1.480 |

Since negative improvement means the PM2.5 model has higher loss, no positive forecast claim is available.

### F2 - High-pollution evidence is underpowered and opposite-signed

There are only 5 shifted AQI>=100 trading days and 1 shifted AQI>=150 trading day. The AQI>=100 5-day RV ratio is 0.303x vs control with one-sided p=1.000 for treated greater than control. Top-decile PM2.5 also has lower RV than control, not higher.

### F3 - Scope is narrower than the motivating literature

This experiment does not replicate the NBER same-day Manhattan PM2.5 return design. It tests lagged daily PM2.5 as a forecasting feature for SPY realized variance. The README correctly states this distinction and avoids claiming that the NBER behavioral channel fails.

## Recommendation

Keep as a null experiment and do not write a positive knowledge entry. A stronger v2 would need intraday NYSE-hour pollution alignment, intraday spreads/RV, exact Manhattan monitor selection, and a 47-city placebo/control design.
