# K1574: Tradable Factor ETF Implementation Shortfall

## Question

Academic factor papers usually study long-short paper portfolios. A tradable
investor often accesses the theme through long-only ETFs such as `MTUM`,
`VLUE`, `QUAL`, `USMV`, `RPV`, `IVE`, and `IWF`. This experiment asks whether
that translation shows up as lower factor alpha, diluted intended-factor
loading, higher residual risk, drawdown amplification, or tradability/cost
proxies.

## Motivation and Differentiation

Related in-project evidence already says factor ETF timing is hard:
`research_factor_timing_regime` found that monthly ETF factor timing did not
beat an equal-weight factor ETF basket after turnover and bootstrap tests.
K1522 found that a free ETF proxy did not rescue a corporate-bond factor-zoo
premium. K1574 is different: it is not a timing strategy and does not forecast
returns. It is an ex-post implementation audit of ETF returns against the
Kenneth French daily paper factors.

## Literature Setup

- Fama and French (2015), *A five-factor asset pricing model*: baseline
  market, size, value, profitability, and investment factor model.
- Carhart (1997), *On Persistence in Mutual Fund Performance*: momentum factor
  control.
- Frazzini, Israel, and Moskowitz, *Trading Costs of Asset Pricing Anomalies*:
  motivates measuring implementation cost and turnover drag.
- Novy-Marx and Velikov, *A Taxonomy of Anomalies and Their Trading Costs*:
  motivates not treating paper anomaly returns as directly tradable.

## Data

- ETF OHLCV: yfinance adjusted daily OHLCV.
- Paper factors: Kenneth French Data Library daily five-factor and momentum
  CSV files.
- Requested ETF window: `2013-01-01` to `2026-05-02` exclusive.
- Actual aligned window: `2013-07-19` to `2026-04-30`.
- Aligned daily rows: `3,215`.

## Method

For each ETF, daily excess return is regressed on:

`Mkt-RF, SMB, HML, RMW, CMA, Mom`

with an intercept. The intercept is interpreted as ETF alpha after exposure to
the paper factors. Inference uses Newey-West HAC standard errors and Holm
adjustment across the seven ETF alpha tests.

Primary directional factor mappings:

- `MTUM`: `Mom`
- `VLUE`, `RPV`, `IVE`: `HML`
- `IWF`: `-HML`
- `QUAL`: `RMW`
- `USMV`: no direct FF6 low-volatility factor

Additional diagnostics include realized volatility, residual volatility share,
tracking error versus SPY, max drawdown, median dollar volume, Amihud
illiquidity proxy, and daily high-low range.

## Integrity Notes

- This is an attribution exercise, not a tradable timing strategy.
- Same-day factor returns and ETF returns are aligned only because both are
  realized returns for the same date. No signal is formed and no same-day signal
  is multiplied by a same-day future return.
- Fixed seed: `42`.
- Bootstrap: stationary bootstrap over common date indices, 1,000 reps, mean
  block length 21 trading days.
- No `knowledge.json` write is performed by the experiment script.

## Results

Verdict: `EXPOSURE_DILUTION_WITHOUT_SIGNIFICANT_ALPHA_SHORTFALL`.

The ETFs mostly have the intended paper-factor exposure: all six scorable
primary mappings have positive directional beta, with HAC t-statistics above
15. But alpha does not support a strong implementation-shortfall claim.

| ETF | Alpha ann. | Alpha t | Holm p | Primary beta | Residual vol share | MDD |
|---|---:|---:|---:|---:|---:|---:|
| MTUM | -0.25% | -0.17 | 1.000 | 0.333 | 28.6% | -34.1% |
| VLUE | -0.33% | -0.24 | 1.000 | 0.293 | 31.3% | -39.5% |
| QUAL | -0.55% | -0.66 | 1.000 | 0.154 | 19.0% | -34.1% |
| USMV | -0.73% | -0.42 | 1.000 | n/a | 42.6% | -33.1% |
| RPV | -1.12% | -0.73 | 1.000 | 0.601 | 27.0% | -50.7% |
| IVE | -0.91% | -0.95 | 1.000 | 0.283 | 21.9% | -37.0% |
| IWF | +0.90% | +1.27 | 1.000 | 0.261 | 13.5% | -32.7% |

Aggregate diagnostics:

- Median annual alpha: `-0.55%`.
- Mean annual alpha: `-0.43%`.
- Negative alpha count: `6/7`, one-sided sign-test `p=0.0625`.
- Holm-significant negative alpha count: `0/7`.
- Alpha in the `-2%` to `-4%` shortfall band: `0/7`.
- Stationary-bootstrap median-alpha 95% CI: `[-2.03%, +0.80%]`.
- Median residual volatility share: `27.0%`.
- Median tracking error vs SPY: `7.57%`.

Interpretation: factor ETFs do appear to be diluted, long-only,
benchmark-constrained implementations of paper factors, but this sample does
not show a robust 2-4% annual negative-alpha implementation shortfall. The
stronger result is exposure and residual-risk decomposition, not alpha loss.

## Run

```bash
uv run python experiments/K1574/k1574.py
```

Outputs:

- `k1574_results.json`
- `figures/k1574_alpha_and_factor_loading.png`
- `figures/k1574_risk_and_cost_proxies.png`
