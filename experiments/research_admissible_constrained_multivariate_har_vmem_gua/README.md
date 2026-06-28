# Admissible constrained multivariate HAR / vMEM-lite guardrail

**Status**: completed (2026-06-29)
**Task**: `research_admissible_constrained_multivariate_har_vmem_gua`

## Question

Does a multivariate HAR / vMEM-lite volatility system need parameter-space
constraints to avoid invalid variance forecasts?

This experiment uses a six-ETF panel (`SPY`, `QQQ`, `IWM`, `TLT`, `GLD`, `HYG`)
and predicts each asset's next-day squared percent return from all assets'
lagged daily, weekly, and monthly squared-return components.

## Design

- Data: yfinance adjusted daily closes, complete six-asset panel.
- Close panel: 2007-04-11 to 2026-06-27.
- Feature panel after lag construction: 2007-05-14 to 2026-06-26.
- OOS: 2020-01-02 to 2026-06-26.
- Refit: expanding window, every 63 trading days, minimum 1,500 train rows.
- Target: next-day `r_t^2` in squared percent-return units.

Models:

| Model | Definition |
|---|---|
| `OLS` | Unconstrained equation-by-equation OLS |
| `ProjectedNonnegative` | OLS coefficients clipped to nonnegative values |
| `AdmissibleNNLS` | NNLS coefficients with lag coefficients scaled so `sum(beta_lags) <= 0.995` |

This is a vMEM-inspired admissibility approximation, not full constrained vMEM
maximum likelihood.

## Lookahead controls

- Daily, weekly, and monthly RV features are all explicitly shifted by one trading day.
- Every refit uses only rows with `train_date < forecast_date`.
- The script asserts the training end date is strictly before the refit forecast date.
- Forecasts are generated for the block before target-day returns are evaluated.

## Results

| Model | Mean QLIKE | Total negative forecasts | Mean turnover | Mean MDD |
|---|---:|---:|---:|---:|
| `OLS` | 907,819,927.36 | 886 | 0.188 | -33.2% |
| `ProjectedNonnegative` | 2.091 | 0 | 0.043 | -13.4% |
| `AdmissibleNNLS` | 1.632 | 0 | 0.130 | -25.2% |

Per-asset QLIKE:

| Asset | OLS | Projected | Admissible |
|---|---:|---:|---:|
| SPY | 2,180,478,979.69 | 2.501 | 1.815 |
| QQQ | 979,126,541.51 | 1.952 | 1.669 |
| IWM | 370,450,725.95 | 1.619 | 1.690 |
| TLT | 120,825,570.21 | 1.286 | 1.219 |
| GLD | 225,881,823.65 | 1.633 | 1.533 |
| HYG | 1,570,155,923.17 | 3.556 | 1.867 |

Formal DM tests compare OLS QLIKE losses against each constrained alternative.
Positive t-statistics mean the constrained model has lower loss. After Holm
adjustment over 12 tests, SPY and GLD pass at 5%; QQQ/IWM/TLT/HYG are positive
but do not survive multiple-testing adjustment. Both constrained variants beat
OLS in all six assets by QLIKE sign test (`p=0.0156`).

## Interpretation

The result is a **guardrail finding**, not a broad forecast-alpha finding.
Unconstrained OLS produces many invalid negative variance forecasts in this
multivariate lag system. Evaluation-time flooring then causes QLIKE explosions.
Nonnegative/admissible constraints eliminate the invalid forecasts and stabilize
losses, but the formal per-asset evidence is not uniformly Harvey-level after
multiple-testing adjustment.

The strongest defensible statement is:

> In multivariate HAR/vMEM-lite variance systems, positivity/admissibility
> constraints are necessary engineering guardrails before QLIKE evaluation. They
> prevent invalid forecasts, but should not be sold as a universal accuracy
> improvement without asset-level DM evidence.

## Files

| File | Purpose |
|---|---|
| `research_admissible_constrained_multivariate_har_vmem_gua.py` | Experiment script |
| `research_admissible_constrained_multivariate_har_vmem_gua_results.json` | Full numeric output |
| `research_admissible_constrained_multivariate_har_vmem_gua_summary.png` | Mean QLIKE and negative-forecast count chart |

## References

- Corsi (2009), HAR-RV and heterogeneous volatility components.
- Engle and Gallo (2006), multiple-indicator MEM for nonnegative volatility measures.
- Cipollini, Engle, and Gallo (2013), vector MEM representation and inference.
- Karanasos et al. (2026), admissible parameter space and constrained estimation for vMEMs.
