# K1596 — Multiplicative Volatility Factor-lite

## Verdict

`NULL_OR_NEGATIVE`

The MVF-lite family does not pass the local VolPred gate. Across 12 ETF OOS cells, no MVF variant is the best mean-QLIKE model, no MVF variant records a strict Holm-adjusted win against annual GJR-GARCH, and the MVF family records 66 strict Holm-adjusted losses across the per-asset pairwise DM family.

This is a daily-ETF, squared-return-proxy adjudication. It is not a high-frequency stock-universe replication of Ding, Engle, Li, and Zheng (2025).

## Motivation

Ding, Engle, Li, and Zheng (2025) propose a multiplicative volatility factor model where each stock variance is represented by a common variance factor times a multiplicative idiosyncratic exposure. The local question here is operational:

Can a transparent common-factor decomposition of ETF daily variance improve next-day variance forecasts beyond simple HAR, EWMA, and annual-refit GJR-GARCH under Patton QLIKE?

## Literature Checked

- Ding, Engle, Li, and Zheng (2025), "Multiplicative factor model for volatility," *Journal of Econometrics*, 249, 105959. DOI: https://doi.org/10.1016/j.jeconom.2025.105959
- Conrad and Engle (2025), "Modelling Volatility Cycles: The MF2-GARCH Model," *Journal of Applied Econometrics*, 40(4), 438-454. DOI: https://doi.org/10.1002/jae.3118
- Calvet, Fisher, and Thompson (2006), "Volatility comovement: A multifrequency approach," *Journal of Econometrics*, 131(1-2), 179-215. DOI: https://doi.org/10.1016/j.jeconom.2005.01.008
- Patton (2011), "Volatility forecast comparison using imperfect volatility proxies." https://public.econ.duke.edu/~ap172/Patton_vol_proxies_JoE_2011.pdf

## Data

- Frozen local cache: `experiments/k1552/data/prices.parquet`
- Assets: `SPY`, `QQQ`, `IWM`, `XLB`, `XLE`, `XLF`, `XLI`, `XLK`, `XLP`, `XLU`, `XLV`, `XLY`
- Training history starts: 2005-01-01
- OOS: 2016-01-01 to 2026-06-26
- OOS rows: 31,608 asset-days, 2,634 per asset
- Target: next-day close-to-close squared log return

## Models

- `EWMA94`: RiskMetrics-style recursive EWMA, lambda 0.94
- `HAR_LogOLS`: annual-refit log-HAR using lagged 1d / 5d / 22d / 66d variance terms
- `GJR_GARCH_Annual`: annual-refit GJR-GARCH(1,1), recursive one-step forecast
- `CommonFactorOnly`: common ETF variance factor forecast applied to every asset
- `MVF_StaticExposure`: common factor forecast times trailing 252-day exposure
- `MVF_LogARExposure`: common factor forecast times annual-refit log-AR exposure forecast

The common factor is the cross-sectional average of ETF squared returns. All common-factor, exposure, and HAR features are shifted to information available at `t-1`.

## Primary Results

Mean QLIKE, lower is better:

| Asset | Best model | GJR | EWMA | HAR | Common | MVF Static | MVF LogAR |
|---|---:|---:|---:|---:|---:|---:|---:|
| IWM | GJR | 1.388 | 1.420 | 3.111 | 1.764 | 1.633 | 6.827 |
| QQQ | GJR | 1.551 | 1.618 | 3.903 | 1.872 | 1.933 | 6.379 |
| SPY | GJR | 1.580 | 1.674 | 4.137 | 1.635 | 2.175 | 3.872 |
| XLB | GJR | 1.417 | 1.453 | 3.314 | 1.579 | 1.578 | 5.240 |
| XLE | GJR | 1.501 | 1.522 | 3.353 | 2.565 | 1.603 | 10.874 |
| XLF | GJR | 1.537 | 1.608 | 3.817 | 1.787 | 1.791 | 5.835 |
| XLI | GJR | 1.472 | 1.529 | 3.658 | 1.572 | 1.751 | 4.580 |
| XLK | GJR | 1.541 | 1.582 | 4.041 | 2.063 | 1.887 | 7.730 |
| XLP | GJR | 1.493 | 1.522 | 3.517 | 1.494 | 1.517 | 2.895 |
| XLU | GJR | 1.479 | 1.493 | 3.378 | 1.542 | 1.516 | 4.346 |
| XLV | GJR | 1.429 | 1.466 | 3.720 | 1.465 | 1.516 | 3.561 |
| XLY | GJR | 1.415 | 1.447 | 3.478 | 1.677 | 1.659 | 5.785 |

Summary gates:

- MVF best mean-QLIKE assets: 0 / 12
- Strict Holm wins vs annual GJR-GARCH: 0
- Strict Holm wins across all MVF-vs-baseline pairs: 25
- Strict Holm losses across all MVF-vs-baseline pairs: 66

The 25 wins are mostly against `HAR_LogOLS`, which is weak in this daily squared-return setup. They do not support a positive MVF finding because GJR and EWMA dominate the economically relevant benchmark set.

## Interpretation

The common volatility factor is informative as a ranking/comovement object, but the daily ETF implementation does not convert that comovement into better calibrated one-step variance forecasts. The simplest robust forecast remains annual GJR-GARCH, with EWMA close behind.

Safe claim:

> In a 12-ETF 2016-2026 OOS test using daily squared-return variance proxies, MVF-lite common-factor forecasts did not beat annual GJR-GARCH or EWMA under Patton QLIKE.

Unsafe claim:

> The JoE 2025 MVF model is disproven.

That would overstate the evidence. The original MVF setting uses high-frequency observations and a large cross-section of stocks; this experiment uses daily ETF proxies and transparent lite estimators.

## Artifacts

- `k1596.py`
- `k1596_results.json`
- `k1596_oos_forecasts.csv`
- `k1596_exposure_summary.csv`
- `figures/fig1_relative_qlike_vs_har.png`
- `figures/fig2_cumulative_loss_diff_vs_gjr.png`
- `figures/fig3_average_exposures.png`
- `codex_review.md`

