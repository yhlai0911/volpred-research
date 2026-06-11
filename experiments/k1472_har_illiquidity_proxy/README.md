# K1472: Low-Frequency Illiquidity Proxies in HAR Volatility Forecasts

## Research Question

Can daily OHLCV illiquidity proxies add out-of-sample forecasting value on top of a simple HAR volatility baseline for US and Taiwan equities?

This task was queued as `research_tick_realized_illiquidity_vol`, but the repo does not pin a long-sample intraday RV panel for SPY, QQQ, and 0050.TW in one canonical location. Following the repo's "honest proxy" rule, this experiment uses a daily close-to-close variance proxy instead of inventing unavailable 5-minute RV history.

## Motivation and Differentiation

Prior nearby experiments already cover adjacent ideas:

- `K150`: Amihud as GARCH-X exogenous variable, mostly null.
- `K265` / `K266`: liquidity-proxy extension with a later rolling-validation reversal lesson.
- `K862`: Corwin-Schultz spread has some incremental correlation, but little model-level forecasting gain.

K1472 is narrower and cleaner:

1. Same low-frequency predictors, but inside a strict lagged HAR framework.
2. Rolling-window pseudo-OOS only, to avoid the K266 "expanding-window artifact" failure mode.
3. Primary evaluation is OOS QLIKE plus Diebold-Mariano tests against HAR.

## Data

- `SPY`: `experiments/k1206/data/SPY.csv`
- `QQQ`: `experiments/k1206/data/QQQ.csv`
- `0050.TW`: `experiments/k1090/data/0050.TW.csv`

Sample ranges after snapshot availability:

- SPY: 2000-01-03 to 2026-04-16
- QQQ: 2000-01-03 to 2026-04-16
- 0050.TW: 2018-01-02 to 2024-12-30

## Target and Predictors

- Target: next-day close-to-close squared log return, `r_t^2`
- HAR baseline:
  - `RV_{t-1}`
  - 5-day mean of lagged `RV`
  - 22-day mean of lagged `RV`
- Illiquidity proxies:
  - Amihud (2002): 22-day mean of `|r| / dollar_volume`, then lagged one day
  - Corwin-Schultz (2012): 5-day mean of the daily OHLC spread estimate, then lagged one day

All predictors are strictly lagged. No same-day signal multiplies same-day returns.

## OOS Protocol

- Rolling training window:
  - 1000 observations for SPY / QQQ
  - 700 observations for 0050.TW if needed by sample length
- OOS start: `max(train_window, floor(0.7 * sample_size))`
- Refit every 21 observations
- Models:
  - `HAR`
  - `HAR + Amihud`
  - `HAR + Corwin-Schultz`
  - `HAR + Both`

## Evaluation

- OOS QLIKE
- Relative QLIKE improvement vs HAR
- Diebold-Mariano test on pointwise QLIKE loss
- HAC full-sample coefficient audit for incremental predictors

## References

- Amihud, Y. (2002). Illiquidity and stock returns. *Journal of Financial Markets*.
- Corwin, S. A., & Schultz, P. (2012). A simple way to estimate bid-ask spreads from daily high and low prices. *Journal of Finance*.
- Corsi, F. (2009). A simple approximate long-memory model of realized volatility. *Journal of Financial Econometrics*.
- Patton, A. J. (2011). Volatility forecast comparison using imperfect volatility proxies. *Journal of Econometrics*.

## Main Result

Cross-asset evidence stays weak. Corwin-Schultz does not beat HAR on any asset at conventional DM levels. Amihud is mixed: it helps QQQ in this HAR setup, but fails on SPY and 0050.TW, and the pooled cross-asset average still does not support a robust "low-frequency illiquidity beats HAR" claim.

That means the queued hypothesis does not pass as a general result. The most honest reading is:

- broad incremental-illiquidity claim: **not supported**
- one-asset niche signal (QQQ Amihud): **promising but not general**

## Files

- `k1472.py`: experiment script
- `k1472_results.json`: results artifact
- `k1472_qlike_improvement.png`: OOS relative-Qlike chart
