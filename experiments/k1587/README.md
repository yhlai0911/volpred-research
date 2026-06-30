# K1587 - NYC PM2.5 as a Volatility Regime Regressor

## Motivation

K1587 tests whether local air pollution can act as a behavioral volatility regressor. The motivating paper is Heyes, Neidell, and Saberian, "The Effect of Air Pollution on Investor Behavior: Evidence from the S&P 500", NBER Working Paper 22753. That paper links short-term Manhattan PM2.5 variation to same-day S&P 500 return behavior and interprets the channel as local investor mood or cognition.

This experiment asks a stricter forecasting question:

1. Does lagged NYC PM2.5 improve next-day or next-week SPY volatility forecasts after controlling for VIX and lagged realized volatility?
2. Do high-pollution days, including wildfire-related AQI spikes, have higher subsequent SPY realized variance?

## Data

- EPA AirData daily PM2.5 files: `https://aqs.epa.gov/aqsweb/airdata/daily_88101_{year}.zip`.
- EPA parameter: `88101`, PM2.5 - Local Conditions.
- EPA sample years: 2018-2025.
- NYC counties: Bronx, Kings, New York, Queens, Richmond.
- Market data: `paper/garch-x-vix/data/spy_vix_qqq_eem_fez_2000-2026.csv`.
- Final panel: 2,011 SPY trading rows from 2018-01-02 to 2025-12-31.
- Regression rows: 1,755 for 1-day RV and 1,753 for 5-day RV.

The committed cache files are:

- `data/nyc_pm25_daily.csv`: NYC daily monitor aggregation.
- `data/k1587_panel.csv`: merged market and pollution panel.

Raw EPA annual ZIP files are not committed because they are large and reproducible from the public URL template above. The script downloads them only when the derived NYC PM2.5 cache is missing.

## Method

The experiment uses daily SPY close-to-close realized variance as the target. This is not an intraday RV or bid-ask spread replication; it is a lower-frequency pilot.

Lookahead policy:

```python
panel["pm25_signal"] = panel["pm25_mean"].shift(1)
panel["high_aqi100_signal"] = panel["high_aqi100_raw"].shift(1)
panel["high_aqi150_signal"] = panel["high_aqi150_raw"].shift(1)
```

EPA daily summaries are end-of-day aggregates, so same-day pollution is not used as a predictive signal.

Forecast models:

- Baseline: VIX, lagged close-to-close RV, lagged Parkinson range variance, 5-day return, 5-day absolute return.
- Augmented: baseline plus PM2.5 z-score, 3-day PM2.5 z-score, AQI>=100 flags, 3-day high-AQI count, and PM2.5 x VIX interaction.
- Targets: forward 1-day and 5-day SPY realized variance.
- OOS design: expanding OLS in log-RV space, retransformed with residual-variance correction.
- OOS guard: for horizon `h`, forecast row `i` trains only on rows `j <= i-h`.
- Primary loss: Patton QLIKE.
- Strong gate: augmented model must improve QLIKE with DM `t < -3` and have a PM2.5 HAC term with `|t| > 3`.

Seed: 42.

## Results

Verdict: **NULL**.

PM2.5 does not improve OOS volatility forecasts beyond HAR/VIX controls. Pollution-bucket evidence is also weak or opposite in sign.

### Pollution coverage

- PM2.5 signal rows: 2,010.
- AQI signal rows: 638.
- Mean lagged PM2.5: 7.593.
- Maximum lagged AQI: 155.
- AQI>=100 signal days: 5.
- AQI>=150 signal days: 1.
- PM2.5 top-decile signal days: 209.

The AQI>=150 test is underpowered by construction because only one shifted trading day clears the threshold.

### OOS forecast test

| Horizon | Baseline QLIKE | PM2.5 augmented QLIKE | QLIKE improvement | DM t | DM p |
|---|---:|---:|---:|---:|---:|
| 1d | 1.752521 | 1.761369 | -0.505% | 1.072 | 0.284 |
| 5d | 0.318720 | 0.323605 | -1.533% | 1.480 | 0.139 |

Negative improvement means the PM2.5 augmented model is worse. Positive DM t also means augmented losses exceed baseline losses.

In-sample adjusted R2 also declines:

- 1d delta adjusted R2: -0.00149.
- 5d delta adjusted R2: -0.00111.

### Pollution bucket tests

High AQI days do not show elevated future RV in this sample:

| Bucket | Target | Treated n | Ratio vs control | One-sided p for treated > control |
|---|---:|---:|---:|---:|
| AQI>=100 | 1d RV | 5 | 0.284x | 1.000 |
| AQI>=100 | 5d RV | 5 | 0.303x | 1.000 |
| Top-decile PM2.5 | 1d RV | 209 | 0.458x | 1.000 |
| Top-decile PM2.5 | 5d RV | 209 | 0.597x | 0.998 |

The top shifted AQI signal date is 2023-06-09, reflecting the 2023 wildfire smoke episode. Its following SPY RV was not high enough to support a general high-pollution volatility claim.

## Conclusion

K1587 does not support adding NYC PM2.5 to a daily SPY volatility forecast model. This does not refute Heyes-Neidell-Saberian's same-day return/mood result because the target here is different: lagged daily pollution predicting future realized variance, not contemporaneous returns or intraday behavior.

The useful output is a reproducible EPA AirData pipeline and a null boundary: free daily NYC PM2.5 is not enough to create a robust SPY RV forecasting feature after VIX and lagged volatility controls.

## Files

- `K1587.py`: experiment script.
- `K1587_results.json`: machine-readable output.
- `data/nyc_pm25_daily.csv`: NYC daily PM2.5 aggregation.
- `data/k1587_panel.csv`: merged panel.
- `figures/k1587_pm25_vol_diagnostics.png`: diagnostics.
- `codex_review.md`: adversarial review.

## Reproducibility

Run from the repository root:

```bash
uv run python experiments/k1587/K1587.py
```
