# K1670: Interval-Valued OHLC Range Forecasts

## Motivation

This experiment tests a narrow version of the interval-valued volatility idea: instead of collapsing daily OHLC data into one scalar realized-volatility proxy, forecast the next day's full price interval directly.

The recent Journal of Forecasting / fuzzy interval-valued literature argues that interval time series can preserve information in high-low price ranges. K1670 asks whether this survives a conservative VolPred free-data OOS test against a calibrated scalar point-HAR interval baseline.

## Evidence Package

- Script: `K1670.py`
- Results: `K1670_results.json`
- Data:
  - `data/prices_yfinance_auto_adjust.csv`
  - `data/interval_design_matrix_shifted.csv`
  - `data/oos_interval_forecasts.csv`
  - `data/aggregate_interval_comparison_summary.csv`
- Figures:
  - `figures/K1670_fig1_interval_mse_improvement.png`
  - `figures/K1670_fig2_interval_coverage.png`
- Review note: `codex_review.md`

## Data

- Source: Yahoo Finance via `yfinance.download(auto_adjust=True)`.
- Assets: SPY, QQQ, IWM, TLT, GLD, HYG.
- Request start: 2005-01-01.
- OOS periods:
  - SPY/QQQ/IWM/TLT/GLD: 2009-01-27 to 2026-07-09, 4,389 OOS days each.
  - HYG: 2011-05-02 to 2026-07-09, 3,819 OOS days.

Daily target interval:

```text
lower_t = log(Low_t / Close_{t-1})
upper_t = log(High_t / Close_{t-1})
```

This interval includes overnight gaps because it is measured relative to the previous adjusted close. It is a daily OHLC proxy, not intraday realized volatility.

## Method

All models forecast the next-day interval `[lower_t, upper_t]` and are calibrated on the expanding training set to target 80% full-interval containment.

Models:

- `point_har`: scalar log-HAR forecast of interval half-width, zero center. This is the point-HAR baseline converted into an interval.
- `center_radius_interval`: OLS HAR center forecast plus scalar log-HAR radius forecast.
- `bounds_direct_interval`: separate OLS forecasts for lower and upper bounds using lagged interval features.

Anti-lookahead policy:

- Raw interval features are indexed by the date through which inputs are observed.
- The code explicitly applies `signal = raw_signal.shift(1)`.
- OOS row `i` is fit on `work.iloc[:i]`; the forecast row is excluded from training.
- Refit frequency is 21 trading days; initial training window is 1,000 rows.

Primary evaluation:

- `interval_mse = (forecast_lower - actual_lower)^2 + (forecast_upper - actual_upper)^2`
- Date-clustered DM test on daily average losses across assets.
- Harvey pass requires challenger-better DM `t < -3`.

Secondary evaluation:

- Full-interval containment coverage.
- Mean interval width.
- Interval score with `alpha = 0.20`.

## Main Results

Date-clustered aggregate:

| Challenger | Interval MSE improvement vs point HAR | DM t | DM p | Coverage | Interval score improvement | Verdict |
|---|---:|---:|---:|---:|---:|---|
| Center-radius interval | +0.034% | -0.318 | 0.751 | 78.34% | -0.096% | no edge |
| Direct bounds interval | -1.347% | +0.902 | 0.367 | 77.80% | +0.100% | no edge |

Asset-level detail:

| Asset | Center-radius IMSE improvement | Center-radius DM t | Direct-bounds IMSE improvement | Direct-bounds DM t |
|---|---:|---:|---:|---:|
| SPY | +0.38% | -1.63 | -3.81% | +1.22 |
| QQQ | +0.60% | -4.08 | -0.60% | +0.43 |
| IWM | -0.45% | +2.42 | -1.24% | +0.55 |
| TLT | +0.20% | -1.87 | +0.65% | -0.48 |
| GLD | -0.37% | +3.03 | -0.95% | +1.41 |
| HYG | +0.17% | -0.57 | -9.92% | +3.23 |

QQQ alone shows a statistically large center-radius improvement, but it is small in magnitude and does not survive pooled date-clustered inference. GLD moves in the opposite direction with similar magnitude. The direct lower/upper bounds model is mostly worse in interval MSE.

Coverage after expanding 80% train calibration:

| Model | Aggregate coverage |
|---|---:|
| Point HAR | 78.41% |
| Center-radius interval | 78.34% |
| Direct bounds interval | 77.80% |

All models under-cover slightly out of sample. The interval-valued models do not buy materially better coverage.

## Verdict

`NULL_NO_INTERVAL_EDGE`

The daily OHLC interval-valued models do not improve next-day interval forecasts beyond a calibrated scalar point-HAR interval baseline. The best aggregate point estimate is center-radius interval HAR at only +0.034% interval-MSE improvement, with DM t=-0.318 and slightly worse interval score.

## Caveats

- This is daily OHLC interval forecasting, not 5-minute realized-volatility forecasting.
- The baseline is strong because it is calibrated to the same 80% train containment target.
- The direct-bounds model is simple OLS; more complex fuzzy/deep interval models may behave differently.
- Interval-MSE and scalar RV QLIKE are different questions. This null should not be used to reject scalar range estimators or HAR-RV models.
- Daily high-low data include split-adjustment and ETF vehicle effects. Adjusted OHLC helps, but it is still a public-data proxy.

## References

- Huarng, Yu and Li (2025), *A Dynamic Fuzzy Modeling Method for Interval Time Series and its Application to Financial Market Forecasting*, Journal of Forecasting.
- *A Fuzzy Framework for Realized Volatility Prediction*, Journal of Forecasting, 2026.
- Martens, van Dijk and de Pooter (2009), *Forecasting S&P 500 volatility*, International Journal of Forecasting.
- Christensen and Podolskij (2007), *Realized range-based estimation of integrated variance*, Journal of Econometrics.
