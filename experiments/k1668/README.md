# K1668: Climate Policy Uncertainty and Commodity ETF RV

## Motivation

This experiment tests whether a free monthly climate-policy-uncertainty signal adds out-of-sample value for commodity volatility forecasting.

The backlog hypothesis came from the 2026 Journal of Futures Markets evidence that a news-based global climate policy uncertainty index amplifies commodity futures volatility risk, especially in agriculture and metals, and from NBER w34762's finding that U.S. climate policy uncertainty behaves like a supply shock. K1668 asks a narrower VolPred question: with free public data only, does lagged CPU improve next-month realized-variance forecasts beyond a monthly HAR baseline for commodity ETFs?

## Evidence Package

- Script: `K1668.py`
- Results: `K1668_results.json`
- Data snapshots:
  - `data/cpu_2026-05_gkrs.dta`
  - `data/cpu_gkrs_2026_05_snapshot.csv`
  - `data/cpu_all_countries_monthly.csv`
  - `data/gcpu_equal_weight_proxy_snapshot.csv`
  - `data/prices_yfinance_auto_adjust.csv`
  - `data/monthly_commodity_etf_rv.csv`
  - `data/monthly_design_matrix_shifted.csv`
- Forecast panels:
  - `data/oos_forecasts_har_cpu.csv`
  - `data/oos_forecasts_har_gcpu_proxy.csv`
- Figures:
  - `figures/K1668_fig1_cpu_commodity_rv.png`
  - `figures/K1668_fig2_oos_qlike_improvement.png`
- Review note: `codex_review.md`

## Data

Primary CPU source:

- Gavriilidis, Kanzig, Raghavan and Stock U.S. Climate Policy Uncertainty dataset from the official GitHub repository linked by NBER w34762.
- Primary field: `cpu_index_narrow`.
- Available monthly observations: 1985-01 to 2026-04.

Commodity ETF prices:

- Source: Yahoo Finance via `yfinance.download(auto_adjust=True)`.
- Tickers: USO, UNG, DBA, CORN, WEAT, GLD.
- Daily price cache runs from each ETF's available start date through 2026-07-09.
- Monthly realized variance target: sum of daily adjusted-close log-return squares in the month, annualized by `252 / monthly trading-day count`.

GCPU proxy robustness:

- `policyuncertainty.com` public multi-country CPU file, transformed into an equal-weight cross-country CPU proxy when at least 3 country series are available.
- This file ends in 2019, so it is a historical robustness check only. It is not the same as the GKRS U.S. CPU index.

## Method

Forecast target:

- Next-month annualized realized variance for each commodity ETF.

Baseline:

- Monthly log-HAR: lagged 1-month, 3-month, and 12-month realized variance.

CPU challenger:

- Baseline HAR plus lagged log U.S. CPU and lagged monthly log CPU change.

Anti-lookahead policy:

- Raw monthly RV and CPU features are indexed by the month through which inputs are observed.
- The script explicitly applies `signal = raw_signal.shift(1)`.
- Target month `t` uses only signals through month `t-1`.
- Expanding OOS row `i` is fit on `work.iloc[:i]`; the forecast row is excluded from training.

Evaluation:

- OOS one-step monthly forecasts.
- Loss: QLIKE pointwise losses from `volpred.stats.model_evaluation.qlike_pointwise`.
- Inference: Diebold-Mariano HAC with `h=1`.
- Practical Harvey gate: challenger-better DM `t < -3`.
- Cross-asset inference: date-clustered monthly mean loss across assets before DM, not asset-month iid pooling.

## Main Results: U.S. CPU

Overall date-clustered result:

| Comparison | OOS months | HAR QLIKE | HAR+CPU QLIKE | Improvement | DM t | DM p | Harvey pass |
|---|---:|---:|---:|---:|---:|---:|---|
| All assets | 161 | 0.2361 | 0.2420 | -2.49% | +1.56 | 0.120 | no |

Sector results:

| Sector | OOS months | QLIKE improvement | DM t | DM p | Harvey pass |
|---|---:|---:|---:|---:|---|
| Energy | 158 | -1.51% | +0.76 | 0.449 | no |
| Agriculture | 149 | -2.87% | +1.39 | 0.167 | no |
| Metal | 161 | -2.88% | +0.90 | 0.371 | no |

Asset results:

| Ticker | Sector | Forecast period | OOS n | QLIKE improvement | DM t | DM p |
|---|---|---:|---:|---:|---:|---:|
| USO | energy | 2013-04 to 2026-05 | 158 | -1.00% | +0.37 | 0.711 |
| UNG | energy | 2014-05 to 2026-05 | 145 | -2.47% | +1.45 | 0.148 |
| DBA | agriculture | 2014-01 to 2026-05 | 149 | -3.31% | +1.81 | 0.072 |
| CORN | agriculture | 2017-06 to 2026-05 | 108 | -6.11% | +1.41 | 0.162 |
| WEAT | agriculture | 2018-10 to 2026-05 | 92 | +1.89% | -0.40 | 0.691 |
| GLD | metal | 2013-01 to 2026-05 | 161 | -2.88% | +0.90 | 0.371 |

Only WEAT has a positive point estimate, and it is far from the Harvey threshold.

## GCPU Proxy Robustness

The equal-weight multi-country CPU proxy is available only through 2019. On the shorter historical sample, it also fails:

| Comparison | OOS months | HAR QLIKE | HAR+GCPU-proxy QLIKE | Improvement | DM t | DM p | Harvey pass |
|---|---:|---:|---:|---:|---:|---:|---|
| All assets | 85 | 0.2207 | 0.2313 | -4.77% | +1.60 | 0.114 | no |

Sector improvements are also negative: energy -2.37%, agriculture -3.39%, metal -5.96%.

## Verdict

`NULL_NO_OOS_CPU_INCREMENT`

The free-data ETF proxy does not support the claim that lagged U.S. CPU improves next-month commodity ETF realized-variance forecasts beyond a monthly HAR baseline. This does not refute the futures-level JFutMkt evidence, because this experiment changes the object: ETF proxies instead of futures contracts, monthly OOS forecasting instead of connectedness/regression evidence, and a conservative one-month signal lag.

## Caveats

- Commodity ETFs contain roll, fee, collateral and vehicle effects; they are not pure futures contracts.
- The primary signal is U.S. CPU, not a full global GCPU futures-market measure.
- The multi-country GCPU proxy ends in 2019 and is only a robustness check.
- Monthly CPU may affect contemporaneous commodity prices or volatility around policy events without being useful as a lagged next-month OOS predictor.
- CORN and WEAT have shorter samples; WEAT's positive point estimate is too weak for inference.

## References

- Gavriilidis, K., Kanzig, D. R., Raghavan, R. and Stock, J. H. (2026), *The Macroeconomic Effects of Climate Policy Uncertainty*, NBER Working Paper 34762.
- GKRS official CPU dataset: `https://github.com/dkaenzig/Climate-Policy-Uncertainty-Index`.
- Zhu, S., Wu, F., Wan, Y. and Li, Y. (2026), *The Chaos of Climate Ambitions: Climate Policy Uncertainty and the Volatility Risk in Commodity Markets*, Journal of Futures Markets 46(1), 197-220.
- Bakas, D. and Triantafyllou, A. (2018), *The Impact of Uncertainty Shocks on the Volatility of Commodity Prices*, Journal of International Money and Finance 87, 96-111.
