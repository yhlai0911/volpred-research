# K1664: 0050.TW 5-minute HAR-RV pilot

## Motivation

`research_program.md` had an open item for Taiwan 5-minute HAR-RV once enough 0050.TW intraday snapshots had accumulated.  The local archive now contains 108 yfinance-style 5-minute files for 0050.TW from 2026-01-20 to 2026-07-08, so this experiment tests whether a strictly lagged HAR-RV model has any out-of-sample signal versus simple persistence.

This is intentionally a pilot, not a paper-grade long-history HAR-RV replication.  The usable out-of-sample window after the 22-day HAR lag and a 60-row expanding training minimum is only 26 trading days.

## Literature Anchor

- Corsi (2009): HAR-RV as a parsimonious long-memory realized volatility model.
- Andersen, Bollerslev, Diebold and Labys (2003): high-frequency realized volatility as the core empirical measure.
- Patton (2011): QLIKE as a robust volatility forecast loss under imperfect volatility proxies.
- Liu, Patton and Sheppard (2015): 5-minute RV is a strong benchmark for realized-measure work.

## Data

- Source: local `data/intraday/0050_TW_5min_*.csv`.
- Valid days: 108.
- Period: 2026-01-20 to 2026-07-08.
- Rows per day: min 53, median 53, max 54.
- RV definition: intraday RV = sum of squared 5-minute close-to-close log returns within the Taiwan regular session.
- Important limitation: overnight return is excluded, so this measures intraday realized variance rather than full close-to-close risk.

Generated snapshots:

- `experiments/k1664/data/K1664_daily_5min_rv.csv`
- `experiments/k1664/data/K1664_har_design_matrix.csv`
- `experiments/k1664/data/K1664_oos_forecasts.csv`

## Lookahead Policy

The design matrix uses `raw_signal.shift(1)` in `K1664.py::add_forecast_features`.  For target day `t`, `rv_d`, `rv_w`, `rv_m`, and `EWMA20` are all known no later than day `t-1`.  Expanding OOS fits use only rows strictly before the forecast row.

## Method

Models:

- Persistence: `RV_{t-1}`
- EWMA20: shifted 20-day exponentially weighted RV
- HAR_DW_log: log-RV OLS with lagged daily and weekly RV
- HAR_DWM_log: log-RV OLS with lagged daily, weekly, and monthly RV

Evaluation:

- One-step expanding OOS.
- Minimum training rows: 60.
- OOS rows: 26.
- Primary loss: Patton QLIKE via `volpred.stats.model_evaluation.qlike_pointwise`.
- Formal model improvement gate: DM/HAC t-stat below -3.0 versus persistence.

## Main Results

Descriptive intraday RV:

- Mean annualized intraday vol: 15.33%.
- Median annualized intraday vol: 14.74%.
- Max annualized intraday vol: 34.78% on 2026-05-28.
- Lag-1 RV autocorrelation: 0.287.

OOS QLIKE:

| Model | QLIKE | Improvement vs persistence | DM t vs persistence | Harvey pass |
|---|---:|---:|---:|---|
| Persistence | 0.1933 | 0.0% | — | — |
| EWMA20 | 0.1424 | +26.3% | -1.09 | No |
| HAR_DW_log | 0.1333 | +31.0% | -1.64 | No |
| HAR_DWM_log | 0.1577 | +18.4% | -1.03 | No |

The best model by QLIKE is HAR_DW_log, but the DM statistic is far below the project Harvey gate.  The result is therefore directional only.

## Verdict

`PILOT_DIRECTIONAL_HAR_EDGE_NO_HARVEY_PASS`

The local 0050.TW 5-minute archive is now usable for HAR-RV diagnostics.  In this short sample, HAR(d,w) improves QLIKE versus persistence, but the OOS window is only 26 days and no HAR model passes the formal Harvey threshold.  The right conclusion is "promising pilot, keep accumulating data", not "HAR-RV is proven for Taiwan".

## Outputs

- `experiments/k1664/K1664.py`
- `experiments/k1664/K1664_results.json`
- `experiments/k1664/figures/K1664_fig1_daily_5min_rv.png`
- `experiments/k1664/figures/K1664_fig2_oos_qlike.png`
- `experiments/k1664/codex_review.md`
