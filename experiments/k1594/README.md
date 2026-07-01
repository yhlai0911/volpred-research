# K1594 - KOWCPI-Lite Conformal VaR

Status: completed smoke/adjudication run

Task: `research_kowcpi_kernel_optimally_weighted_conformal`

Verdict: `MIXED_WEAK`

## Motivation

KOWCPI proposes kernel-based optimally weighted conformal prediction intervals
for dependent time series. The research question here is narrower and
finance-specific:

Can a kernel-weighted conformal lower-tail quantile produce better daily ETF
VaR than simple rolling historical simulation or a VIX-regime conformal
baseline?

This experiment is a KOWCPI-style mechanism test, not a full replication of the
paper's algorithm.

## Literature Checked

1. Lee, Xu and Xie (2024), "Kernel-based optimally weighted conformal prediction
   intervals", arXiv:2405.16828. <https://arxiv.org/abs/2405.16828>
2. Tibshirani et al. (2019), "Conformal Prediction Under Covariate Shift".
   <https://www.stat.cmu.edu/~ryantibs/papers/weightedcp.pdf>
3. Gibbs and Candes (2021), "Adaptive Conformal Inference Under Distribution
   Shift". <https://arxiv.org/abs/2106.00170>
4. Kupiec (1995) and Christoffersen (1998) for VaR coverage and independence
   backtesting.

## Data

Frozen local input:

`experiments/k1571/data_cache.parquet`

Source of that cache: yfinance adjusted closes, created by K1571.

Assets:

- `TLT`
- `HYG`

Covariates, all shifted one day:

- own 5-day realized vol
- own 22-day realized vol
- own absolute return
- VIX level
- HYG/IEF 5-day credit proxy change
- IEF 5-day momentum
- LQD 5-day momentum

Splits:

- Bandwidth validation: 2013-01-01 to 2014-12-31
- OOS: 2015-01-01 to 2026-06-30
- Calibration window: trailing 1000 trading days

## Methods

Compared models:

- `HS250`: trailing 250-day historical simulation quantile.
- `HS1000`: trailing 1000-day historical simulation quantile.
- `VIXRegime1000`: trailing 1000-day quantile split by lagged VIX > 20.
- `KOWCPI-lite`: Gaussian-kernel weighted lower-tail quantile over the trailing
  1000 observations.

KOWCPI-lite details:

- Feature vectors are standardized using pre-OOS data only.
- Bandwidth is selected on 2013-2014 validation from
  `[0.35, 0.50, 0.75, 1.00, 1.50, 2.25, 3.50]`.
- Kernel weights are shrunk toward uniform weights if Kish effective sample size
  falls below 125.
- Forecast on date `t` uses only observations before `t` and features known by
  `t-1`.

## Evaluation

For VaR alpha in `{5%, 1%}`:

- Mean pinball loss.
- Average VaR width (`-VaR`).
- Kupiec unconditional coverage.
- Christoffersen independence of violations.
- Exact-binomial Basel-style traffic-light classification.
- DM tests on pinball loss, with Holm adjustment across the 4 cells x 3 pairwise
  KOWCPI comparisons.

## Results

| Cell | Best mean pinball | KOWCPI width | KOWCPI violation rate | KOWCPI Kupiec p | KOWCPI Christoffersen p | KOWCPI Trinity |
|---|---:|---:|---:|---:|---:|---:|
| TLT 5% | HS250 | 0.0142 | 5.99% | 0.0175 | 0.0426 | no |
| TLT 1% | KOWCPI-lite | 0.0205 | 1.56% | 0.0053 | 0.7334 | no |
| HYG 5% | KOWCPI-lite | 0.0065 | 5.26% | 0.5170 | 0.0030 | no |
| HYG 1% | KOWCPI-lite | 0.0110 | 1.21% | 0.2672 | 0.0007 | no |

Key points:

- KOWCPI-lite has the lowest mean pinball loss in 3 of 4 cells.
- It is often narrower than HS/VIX-regime alternatives.
- It has 0 of 4 Trinity passes because either Kupiec coverage or violation
  independence fails.
- No KOWCPI-lite DM comparison survives the project strict `|t| > 3` and Holm
  screen.
- The VIX-regime conformal baseline remains stronger for TLT 5% because it is
  the only method with a Trinity pass in that cell.

## Interpretation

KOWCPI-style kernel weighting is promising as a width/loss improvement device,
especially for HYG, but it does not solve the central VaR risk-management
problem: exceedance hits remain clustered. This is not a deployable VaR upgrade
over the existing conformal/regime toolkit.

Safe wording:

> A KOWCPI-style kernel weighting rule narrows daily ETF VaR and lowers pinball
> loss in several cells, but it fails the full VaR backtesting gate because
> violations remain clustered.

Unsafe wording:

> KOWCPI improves VaR.

## Artifacts

- `k1594.py`: reproducible script.
- `k1594_results.json`: full results.
- `k1594_oos_var_forecasts.csv`: OOS VaR forecasts and losses.
- `figures/fig1_mean_pinball.png`
- `figures/fig2_violation_rates.png`
- `figures/fig3_mean_var_width.png`

## Reproduce

```bash
uv run python experiments/k1594/k1594.py
```

## Limitations

- KOWCPI-lite is not the full Lee-Xu-Xie algorithm.
- Only two ETFs and two VaR levels are tested.
- The validation window is short for 1% tail tuning.
- No ES or Fissler-Ziegel joint VaR/ES scoring is included.
- Coverage is evaluated on daily close-to-close returns, not intraday risk.
- A full follow-up should include SPY/QQQ/GLD/BTC and rolling conditional
  coverage diagnostics by VIX regime.
