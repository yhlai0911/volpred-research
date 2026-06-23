# FX Predictability Complexity Penalty

## Verdict

**PARTIAL_RV_ONLY_NO_RETURN_PREDICTABILITY.**

Ridge-RFF has localized value for **monthly FX ETF realized variance** forecasts,
especially with a 60-month training window, but the experiment does **not**
support a claim that nonlinear complexity predicts FX returns. Across 108
ticker-target-window-model tests, only 2 model-vs-benchmark tests clear the
Harvey-style `t >= 3` gate, both on RV. Return forecasts have **0 Clark-West
passes**.

## Motivation

The backlog asks whether FX nonlinear forecasting complexity is real or a
small-sample mirage. The design follows the exchange-rate random-walk benchmark
tradition and tests whether a fixed Ridge-RFF complexity layer improves over
simple baselines in a free-data ETF setting.

This is a screen, not a replication of the FEDS paper.

## Prior Work

- Kiliç (2025), Federal Reserve FEDS 2025-089, "Virtue or Mirage? Complexity in
  Exchange Rate Prediction", motivates the complexity question using nonlinear
  Ridge-RFF models.
- Meese and Rogoff (1983), "Empirical Exchange Rate Models of the Seventies",
  motivates the robust random-walk benchmark.
- Clark and West (2007), "Approximately Normal Tests for Equal Predictive
  Accuracy in Nested Models", motivates adjusted return-forecast testing.
- Rossi (2013), "Exchange Rate Predictability", summarizes why exchange-rate
  predictability is sample-, horizon-, predictor-, and evaluation-dependent.
- Related internal findings: K1336 EM carry x own-FX-vol gate reduced exposure
  but did not prove timing alpha; K1439 UUP regime mostly reduced to oil/USO
  robustness; K1359 found returns-only tail-asymmetry proxies better at risk
  tagging than return premia.

## Data

- Price source: Yahoo Finance via `yfinance`, `auto_adjust=True`.
- Tickers: `FXE`, `FXY`, `FXB`, `FXA`, `UUP`, `CEW`.
- Period requested: 2006-01-01 to 2026-06-23.
- Monthly panels are generated from daily adjusted closes.
- Macro predictors: local FRED CSVs in `storage/macro/` for `DGS10`, `DGS2`,
  `EFFR`, and `T10YIE`.
- Data outputs:
  - `data/daily_close.csv`
  - `data/<ticker>_monthly_panel.csv`

## Method

Frequency is monthly. Forecast month `t` only uses features dated `t-1` or
earlier. The code explicitly applies `shift(1)` to ETF lag features, macro
features, and the left-tail threshold.

Targets:

- `return`: month `t` log return.
- `rv`: sum of daily squared log returns in month `t`.
- `left_tail`: month `t` return below the trailing 60-month 20th percentile
  known at `t-1`.

Benchmarks:

- Return: random-walk zero return forecast.
- RV: training-window historical mean RV.
- Left-tail: training-window historical event probability.

Models:

- `linear_ridge`: standardized feature Ridge, alpha 10.
- `rff_ridge`: 64 Random Fourier Features plus Ridge, alpha 10.

Training windows: 12, 60, and 120 months.

Tests:

- Newey-West t-stat of benchmark loss minus model loss.
- Clark-West adjusted t-stat for return forecasts.
- Bootstrap Sharpe difference for sign strategy vs buy-hold, seed 42.
- Publication gate: `t >= 3` after correct sign orientation.

## Results

High-level counts:

- OOS forecast records: 17,058.
- Test cells: 108.
- Model-vs-benchmark Harvey passes: 2.
- Return Clark-West passes: 0.
- RFF-vs-linear Harvey passes: 11.

Median MSPE improvement of `rff_ridge` vs benchmark:

| Target | 12m | 60m | 120m |
|---|---:|---:|---:|
| return | -11.55% | -2.78% | -1.83% |
| rv | +3.07% | +10.08% | +5.92% |
| left_tail | -0.25% | +0.10% | -2.11% |

The two benchmark-clearing cells are both RV forecasts:

| Ticker | Target | Window | MSPE improvement | DM t |
|---|---|---:|---:|---:|
| FXE | RV | 60m | +20.38% | 3.77 |
| FXY | RV | 60m | +10.18% | 3.25 |

Several `rff_ridge` cells beat `linear_ridge`, but that mostly reflects linear
Ridge overfitting relative to simple benchmarks. It is not evidence of tradable
return predictability because every return Clark-West statistic remains below
the Harvey gate.

## Interpretation

This supports a narrow conclusion:

1. Nonlinear complexity can help smooth monthly **RV** forecasts for some FX ETF
   proxies.
2. The same complexity does not validate monthly FX **return** predictability.
3. RFF beating linear Ridge is not enough; the proper benchmark remains the
   random walk or historical-mean forecast.

## Limitations

- ETF monthly proxy, not spot FX with real-time macro vintages.
- Hyperparameters are fixed ex ante but not tuned in a nested validation loop.
- Local macro predictors are end-of-month FRED levels shifted one month; this is
  not a real-time vintage macro forecast design.
- Multiple testing is substantial: 108 cells. The 2 RV passes should be treated
  as follow-up candidates, not publication-grade general evidence.

## Reproducibility

```bash
uv run python experiments/research_fx_predictability_complexity_penalty/research_fx_predictability_complexity_penalty.py
```

Core outputs:

- `research_fx_predictability_complexity_penalty.py`
- `research_fx_predictability_complexity_penalty_results.json`
- `forecast_records.csv`
- `figures/linear_ridge_median_mspe_improvement.png`
- `figures/rff_ridge_median_mspe_improvement.png`
- `figures/rff_vs_linear_median_improvement.png`
