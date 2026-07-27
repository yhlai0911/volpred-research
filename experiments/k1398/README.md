# K1398 — MEM/AMEM vs GJR/HAR: Daily Volatility Forecasting

- Status: `NULL`
- Date: `2026-07-27`
- Motivation: MEM models directly target non-negative realized variance dynamics and let the conditional mean evolve through a persistence structure closer to variance processes than plain OLS. AMEM adds a downside asymmetry term so we can test whether negative-return days materially improve next-day volatility forecasts relative to symmetric MEM and standard GJR/HAR baselines.
- Method Summary: Daily log returns were computed from adjusted close prices for SPY, QQQ, and GLD, with realized variance defined as `RV_t = r_t^2`. Forecasts were evaluated in an expanding-window out-of-sample design with a 2000-observation initial window; HAR was refit by OLS each step, while MEM/AMEM/GJR parameters were refreshed every 100 OOS steps using the most recent 2500 training observations and cached state updates in between to keep the rolling experiment tractable without introducing lookahead.

## Results

| Asset | QLIKE MEM | QLIKE AMEM | QLIKE GJR | QLIKE HAR | MSE MEM | MSE AMEM | MSE GJR | MSE HAR | OOS N |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| SPY | -8.16861 | -8.10671 | -8.3524 | -8.2714 | 3.34855e-07 | 3.12094e-07 | 2.87564e-07 | 3.22128e-07 | 4678 |
| QQQ | -5.68773 | -7.55095 | -7.90016 | -7.84022 | 90484.9 | 3.59479e-06 | 2.94577e-07 | 3.13999e-07 | 4678 |
| GLD | -7.85434 | -6.93573 | -8.30469 | -8.28015 | 1.88924e-07 | 2.71707e-06 | 1.09108e-07 | 1.11042e-07 | 3452 |

## DM Test vs GJR (QLIKE loss differential)

| Asset | MEM t-stat | MEM p-value | AMEM t-stat | AMEM p-value |
|---|---:|---:|---:|---:|
| SPY | 9.1242 | 0.0000 | 14.0228 | 0.0000 |
| QQQ | 28.8635 | 0.0000 | 16.9945 | 0.0000 |
| GLD | 15.3775 | 0.0000 | 35.6193 | 0.0000 |

## Conclusion

MEM beats GJR on 0/3 assets by QLIKE; MEM pass count=0, AMEM pass count=0. Verdict rule outcome: `NULL`. This experiment should be treated as a direct forecasting comparison under the specified rolling protocol, not as structural evidence that MEM-family models dominate in all volatility settings.
