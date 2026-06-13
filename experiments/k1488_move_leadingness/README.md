# K1488 — MOVE leadingness for SPY volatility and stock-bond allocation

## Motivation

The backlog question asks whether MOVE, a Treasury-market implied-volatility proxy,
leads equity volatility and stock-bond allocation regimes.

This is adjacent to two recent VolPred results, so the experiment is deliberately
incremental:

- `K1442`: MOVE/VIX around CPI events found no statistically significant vol-crush pattern.
- `K1460`: a simple lagged stock-bond correlation regime rule did not beat static 60/40 with IEF.

K1488 therefore tests whether MOVE adds out-of-sample information beyond VIX and
recent realized volatility, rather than repeating a descriptive MOVE/VIX snapshot.

## Literature pre-check

Three relevant papers motivated the design:

- Rubin and Ruzzi (2020), "Equity Tail Risk in the Treasury Bond Market":
  option-implied equity tail risk can predict Treasury excess returns and is priced in Treasury markets.
- Lacava and Otranto (2026), "Trade uncertainty impact on stock-bond correlations":
  U.S. stock-bond correlations are time-varying; constant-correlation models are rejected.
- Mallory (2026), "Two-Step Regularized HARX to Measure Volatility Spillovers":
  cross-market volatility spillovers can be identified while preserving HAR persistence, but point forecasts may not beat a univariate HAR.
- Park and Sarantsev (2024), "Zero-Coupon Treasury Rates and Returns using the Volatility Index":
  equity implied volatility can help model Treasury-rate dynamics, supporting cross-market volatility links.

## Hypotheses

H1: Adding lagged MOVE signals to a HAR+VIX model improves next-day SPY variance
forecasts under QLIKE, with Diebold-Mariano `t < -3.0` for
`HAR_VIX_MOVE` versus `HAR_VIX`.

H2: A lagged MOVE stress regime improves monthly stock-bond allocation versus the
best static 60/40 benchmark, with a moving-block bootstrap 95% CI for Sharpe
difference strictly above zero.

## Data

- Yahoo Finance via `yfinance`, `auto_adjust=True`
- Tickers: `SPY`, `TLT`, `IEF`, `^VIX`, `^MOVE`
- Download window: 2003-01-01 to 2026-06-13 exclusive
- Snapshot pinned in `close_prices.csv`

## Methods

### Forecast test

Target: SPY close-to-close squared log return at day `t`.

Models:

- `HAR_RV`: lagged 1-day, 5-day, and 22-day realized variance proxies.
- `HAR_VIX`: `HAR_RV` plus lagged daily VIX-implied variance.
- `HAR_VIX_MOVE`: `HAR_VIX` plus lagged trailing-252d MOVE z-score and lagged 5-day MOVE log change.

Implementation details:

- All features use explicit `shift(1)`.
- Rolling OLS window: 1,260 trading days.
- OOS starts 2010-01-04.
- Primary loss: Patton QLIKE on `r^2`.
- Formal comparison: DM/HAC test from `volpred.stats.model_evaluation`, Harvey threshold `|t| > 3.0`.

### Allocation test

Monthly strategies from 2010 onward:

- `static_60_40_tlt`: 60% SPY + 40% TLT.
- `static_60_40_ief`: 60% SPY + 40% IEF.
- `move_duration_switch`: if prior-month MOVE z-score > 1, use IEF instead of TLT.
- `move_defensive_switch`: if prior-month MOVE z-score > 1, use 40% SPY + 60% IEF.

The MOVE month-end signal is shifted one month before use.
Bootstrap uses seed 42, 1,000 reps, and 6-month moving blocks.

## Results

Run:

```bash
uv run python experiments/k1488_move_leadingness/k1488_move_leadingness.py
```

The authoritative numeric output is `k1488_move_leadingness_results.json`.

### Forecast test

| Model | OOS QLIKE |
|---|---:|
| `HAR_RV` | 4.0696 |
| `HAR_VIX` | **3.6195** |
| `HAR_VIX_MOVE` | 3.6619 |

Formal tests:

- `HAR_VIX` beats `HAR_RV`: DM t = -3.013, p = 0.0026, just past the Harvey `|t| > 3.0` threshold.
- `HAR_VIX_MOVE` does **not** beat `HAR_VIX`: DM t = +1.572, p = 0.116. Positive t means the MOVE-augmented model has higher loss.

Diagnostic full-sample HAC regression does show a positive MOVE z-score coefficient
(`t = 2.56`, `p = 0.010`), but that descriptive association does not survive the
OOS QLIKE test once VIX and recent realized volatility are already in the model.

### Allocation test

Sample: 2010-01 to 2026-06, 198 monthly observations.

| Strategy | CumRet | Sharpe | MaxDD |
|---|---:|---:|---:|
| `static_60_40_tlt` | +377.9% | 1.014 | -26.2% |
| `static_60_40_ief` | +363.1% | **1.092** | **-20.5%** |
| `move_duration_switch` | +420.1% | 1.087 | -21.9% |
| `move_defensive_switch` | +365.5% | 1.060 | -21.1% |

MOVE stress months (`MOVE z > 1`) occur in 18.7% of months. The dynamic rules do
not beat the best static benchmark (`static_60_40_ief`) under block bootstrap:

- `move_duration_switch - static_60_40_ief`: Sharpe diff = -0.006, 95% CI `[-0.212, +0.216]`.
- `move_defensive_switch - static_60_40_ief`: Sharpe diff = -0.033, 95% CI `[-0.283, +0.239]`.

## Verdict

`NULL`.

MOVE contains some descriptive information about next-day SPY variance, but the
increment is already absorbed by VIX and recent realized volatility in the OOS
forecasting test. As an allocation regime signal, MOVE does not improve simple
60/40 rules against the static short-duration bond sleeve.

Practical implication: use MOVE as a context/risk-monitoring variable, not as a
standalone trading or allocation switch under this reduced-form setup.

## Limitations

- MOVE is proxied by Yahoo Finance `^MOVE`; vendor construction and revisions may
  differ from Bloomberg/ICE terminal data.
- Forecast target is close-to-close SPY `r^2`, not intraday realized variance.
- Allocation rules are deliberately simple falsification rules; a richer regime
  model could still be tested separately.
- Monthly ETF allocation does not include transaction costs or tax effects.

## Anti-lookahead checks

- Forecast features: `r2.shift(1)`, rolling RV `.shift(1)`, VIX variance `.shift(1)`,
  MOVE z-score `.shift(1)`, MOVE 5-day change `.shift(1)`.
- Allocation signal: month-end MOVE z-score `.shift(1)` before applying to next month.
- No same-day signal is multiplied by same-day return.

## Files

- `k1488_move_leadingness.py`
- `k1488_move_leadingness_results.json`
- `close_prices.csv`
- `fig_a_forecast_loss_diff.png`
- `fig_b_allocation_nav.png`
