# K1625 - Perp Funding Pressure and BTC/ETH High-RV Regimes

## Verdict

**MIXED_WEAK_SINGLE_CELL.** Lagged Binance perpetual funding pressure contains one
BTC-only 5-day high-RV signal, but the result does **not** replicate in ETH and the
positive-vs-negative funding asymmetry test does not pass the Harvey `|t| >= 3`
publication bar. Treat this as a follow-up hypothesis, not a trading signal.

## Motivation

Perpetual funding rates are a direct, public proxy for leveraged positioning pressure:
positive funding means longs pay shorts, while negative funding means shorts pay
longs. The research question is whether extreme funding predicts the next BTC/ETH
realized-volatility regime, especially through an asymmetric long-crowding /
short-crowding liquidation channel.

Relevant prior local memory / experiments checked before running:

- `storage/memory/knowledge.json` has crypto-volatility entries such as K1620
  (crypto low-volatility anomaly regime dependence, NULL) and earlier BTC leverage
  / crypto volatility model notes, but no exact prior test of perp funding extremes
  forecasting BTC/ETH high-RV regimes.
- `docs/error_log.md` stresses three rules applied here: explicit lagging,
  horizon-aware inference, and no pooled asset-day iid claims.

Academic / market-microstructure references used to frame the test:

- He, Manela, Ross, and von Wachter, **Fundamentals of Perpetual Futures**,
  arXiv:2212.06888 / SSRN 4301150:
  <https://arxiv.org/abs/2212.06888>.
- Ackerer, Hugonnier, and Jermann, **Perpetual Futures Pricing**, NBER Working
  Paper 32936 / Mathematical Finance:
  <https://www.nber.org/papers/w32936>.
- Funding-rate arbitrage and market-structure work on cryptocurrency perpetual
  futures, used only as motivation for the funding-rate proxy, not as evidence
  for a volatility-forecasting claim:
  <https://www.sciencedirect.com/science/article/pii/S2096720925000818>.

## Data

Source: Binance USD-M Futures public API.

| Asset | Symbol | Daily sample | Daily rows with funding+RV | 8h funding obs | Annualized close-to-close vol |
|---|---:|---:|---:|---:|---:|
| BTC | BTCUSDT | 2019-09-10 -> 2026-07-04 | 2,490 | 7,467 | 62.03% |
| ETH | ETHUSDT | 2019-11-28 -> 2026-07-04 | 2,411 | 7,233 | 82.88% |

Funding-rate daily mean distribution, displayed as percent per 8h funding interval:

| Asset | Mean | Std | p10 | p90 |
|---|---:|---:|---:|---:|
| BTC | 0.01070% | 0.01931% | -0.00124% | 0.02488% |
| ETH | 0.01287% | 0.02510% | -0.00071% | 0.03126% |

Cached raw and processed files:

- `data/BTCUSDT_funding.csv`, `data/ETHUSDT_funding.csv`
- `data/BTCUSDT_klines_1d.csv`, `data/ETHUSDT_klines_1d.csv`
- `data/BTC_analysis_panel.csv`, `data/ETH_analysis_panel.csv`

## Method

All predictors are lagged by one daily row:

```python
funding_lag1 = funding_mean.shift(1)
```

Targets:

- `rv_fwd1[t] = r[t]^2`
- `rv_fwd5[t] = mean(r[t]^2, ..., r[t+4]^2)`

The predictor at date `t` uses funding observed at `t-1`, so the signal precedes the
first return in the target window.

Funding features:

- `funding_z_lag1`: 365-day rolling z-score of lagged daily mean funding.
- `pos_extreme_lag1`: lagged funding above its rolling 90th percentile.
- `neg_extreme_lag1`: lagged funding below its rolling 10th percentile.
- Controls: lagged log trailing 5-day RV and lagged absolute return.

High-RV regime:

- High RV is defined against a rolling 80th percentile threshold.
- For `h=5`, the threshold uses `rv_fwd5.shift(5)`, so every threshold label has a
  target window ending before the forecast date.

Inference:

- OLS / linear probability model with HAC covariance, `maxlags = horizon`.
- Positive-minus-negative asymmetry is a HAC Wald contrast.
- Conservative verdict gate: `SIGNAL_CANDIDATE` requires at least two h=5 high-RV
  regime cells with `|t| >= 3`. One such cell is only `MIXED_WEAK_SINGLE_CELL`.

## Main Results

### 5-Day High-RV Regime Linear Probability Model

| Asset | Term | Coef | HAC t | p |
|---|---:|---:|---:|---:|
| BTC | funding z | +0.0682 | **+3.79** | 0.00015 |
| BTC | positive funding extreme | -0.0024 | -0.05 | 0.961 |
| BTC | negative funding extreme | +0.1040 | +2.84 | 0.0045 |
| BTC | pos - neg asymmetry | -0.1064 | -1.58 | 0.114 |
| ETH | funding z | +0.0265 | +1.36 | 0.173 |
| ETH | positive funding extreme | +0.0191 | +0.42 | 0.675 |
| ETH | negative funding extreme | +0.0419 | +1.16 | 0.245 |
| ETH | pos - neg asymmetry | -0.0229 | -0.37 | 0.712 |

The only h=5 high-RV regime cell above Harvey `|t| >= 3` is BTC continuous funding
z-score. ETH does not replicate it, and the explicit positive-vs-negative asymmetry
test is not significant.

### 5-Day Log-RV Level Regression

| Asset | Term | Coef | HAC t | p |
|---|---:|---:|---:|---:|
| BTC | funding z | +0.1545 | **+4.07** | 0.000047 |
| BTC | positive funding extreme | -0.2652 | -1.96 | 0.050 |
| BTC | negative funding extreme | +0.1750 | +1.83 | 0.068 |
| BTC | pos - neg asymmetry | -0.4402 | -2.47 | 0.013 |
| ETH | funding z | +0.0306 | +0.72 | 0.473 |
| ETH | positive funding extreme | -0.0557 | -0.46 | 0.644 |
| ETH | negative funding extreme | +0.1601 | +1.72 | 0.085 |
| ETH | pos - neg asymmetry | -0.2158 | -1.35 | 0.178 |

The continuous BTC funding-z result is stronger on the log-RV level target, but this
is not the primary high-regime gate and still does not generalize to ETH.

### Descriptive Conditional High-RV Rates

For forward 5-day high-RV regimes:

| Asset | Base rate | Positive extreme | Negative extreme | Absolute extreme | Non-extreme |
|---|---:|---:|---:|---:|---:|
| BTC | 18.98% | 29.61% | 21.09% | 29.90% | 16.81% |
| ETH | 18.53% | 23.95% | 21.66% | 24.54% | 16.88% |

This descriptive table suggests high absolute funding days are followed by more high
RV, but the controlled asymmetry tests do not justify a strong directional liquidation
claim.

## Figures

- `figures/fig1_funding_vs_forward_rv.png`
- `figures/fig2_high_rv5_tstats.png`
- `figures/fig3_conditional_high_rv_rates.png`

## Limitations

1. Binance-only proxy. Cross-exchange funding fragmentation is not tested.
2. Funding is a reduced-form positioning proxy, not direct liquidation volume or
   account-level leverage.
3. Linear probability models are transparent but not a calibrated classifier.
4. The BTC signal may be a BTC-specific regime artifact; ETH non-replication prevents
   a broad crypto-perp claim.
5. API data is live public data; the CSV snapshots in `data/` pin this run's inputs.

## Reproduction

```bash
uv run python experiments/k1625/k1625.py
```

Main output:

- `experiments/k1625/k1625_results.json`
