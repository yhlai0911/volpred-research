# K1398 — MEM/AMEM vs GJR/HAR: Daily Volatility Forecasting

- Status: `NULL`
- Date: `2026-05-23`
- Motivation: MEM models directly target non-negative realized variance dynamics and let the conditional mean evolve through a persistence structure closer to variance processes than plain OLS. AMEM adds a downside asymmetry term so we can test whether negative-return days materially improve next-day volatility forecasts relative to symmetric MEM and standard GJR/HAR baselines.
- Method Summary: Daily log returns were computed from adjusted close prices for SPY, QQQ, and GLD, with realized variance defined as `RV_t = r_t^2`. Forecasts were evaluated in an expanding-window out-of-sample design with a 2000-observation initial window; MEM/AMEM were estimated by Gamma-MLE with SLSQP constraints, HAR was refit by OLS each step, and GJR-GARCH(1,1) used rolling one-step-ahead conditional variance forecasts.

## Results

| Asset | QLIKE MEM | QLIKE AMEM | QLIKE GJR | QLIKE HAR | MSE MEM | MSE AMEM | MSE GJR | MSE HAR | OOS N |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| SPY | -8.26221 | -8.28392 | -8.36207 | -8.27287 | 3.21029e-07 | 3.25599e-07 | 2.91149e-07 | 3.24417e-07 | 4643 |
| QQQ | -7.8522 | -7.50573 | -7.91671 | -7.85061 | 3.14502e-07 | 4.43399e-07 | 2.99739e-07 | 3.14576e-07 | 4643 |
| GLD | -7.46105 | -8.02676 | -8.32325 | -8.29659 | 2.98187e-06 | 1.70821e-07 | 1.08882e-07 | 1.10283e-07 | 3417 |

## DM Test vs GJR (QLIKE loss differential)

| Asset | MEM t-stat | MEM p-value | AMEM t-stat | AMEM p-value |
|---|---:|---:|---:|---:|
| SPY | 6.4240 | 0.0000 | 5.6553 | 0.0000 |
| QQQ | 6.2310 | 0.0000 | 22.2928 | 0.0000 |
| GLD | 25.6080 | 0.0000 | 11.2349 | 0.0000 |

## Conclusion

MEM beats GJR on 0/3 assets by QLIKE; MEM pass count=0, AMEM pass count=0. Verdict rule outcome: `NULL`. This experiment should be treated as a direct forecasting comparison under the specified rolling protocol, not as structural evidence that MEM-family models dominate in all volatility settings.
