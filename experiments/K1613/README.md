# K1613 - Noise-robust realized measures as HAR-RV inputs

## Question

Do microstructure-noise / jump-robust realized measures improve one-day-ahead HAR forecasts beyond the standard 5-minute realized-variance HAR baseline?

Task brief:

- `K1613`: Realized Kernel / Two-Scale RV / MedRV as replacement HAR inputs.
- Required comparison: OOS QLIKE / DM / Harvey against standard RV-HAR.
- Main data: local TAIFEX 5-minute tick-derived bars plus local SPY 5-minute archive.

## Motivation and prior evidence

The motivation is measurement, not a new trading strategy. Realized-kernel and two-scale estimators were designed to reduce microstructure-noise bias, and MedRV was designed to reduce jump contamination. The open empirical question is whether those cleaner ex-post measures improve forecast inputs once the target is held fixed.

Prior VolPred evidence is cautious:

- K1582 found HARQ / SHARK-like measurement-error corrections directionally improved TAIFEX TX active-contract day-session QLIKE, but did not pass the project Harvey threshold.
- Rough-volatility and non-Gaussian extensions on the same TAIFEX 5-minute panel also found visible measurement structure but no robust Harvey-level forecasting edge beyond HAR/HARQ.
- SPY local 5-minute data remain too short for formal inference, so SPY is only a diagnostic in this run.

## Literature checked before design

- Barndorff-Nielsen, Hansen, Lunde, and Shephard (2008), Econometrica, "Designing Realized Kernels to Measure the Ex-Post Variation of Equity Prices in the Presence of Noise": realized-kernel motivation.
- Zhang, Mykland, and Ait-Sahalia (2005), JASA, "A Tale of Two Time Scales": two-scale realized volatility.
- Andersen, Dobrev, and Schaumburg (2012), Journal of Econometrics, "Jump-Robust Volatility Estimation Using Nearest Neighbor Truncation": MedRV.
- Corsi (2009), Journal of Financial Econometrics, "A Simple Approximate Long-Memory Model of Realized Volatility": HAR-RV benchmark.
- Patton (2011), Journal of Econometrics, "Volatility forecast comparison using imperfect volatility proxies": QLIKE comparison.

## Data

Formal primary market:

- Market: `TAIFEX_TX_day_K1100h`
- Source: `experiments/k1100h/data/_taifex_5min_2017-2021.parquet`
- Date range: `2017-05-16` to `2021-12-30`
- Daily rows after dropping third-Wednesday settlement days: `1,082`
- Feature rows after 22-day HAR warmup: `1,060`
- OOS forecasts: `464`
- OOS period: `2020-01-02` to `2021-12-30`
- Median intraday returns per day: `59`

Important TAIFEX limitation:

- The primary cache is K1100h's TX1-derived 5-minute day-session bar cache after the endpoint-bin fix.
- K1613 explicitly drops third-Wednesday settlement days before forecasting.
- This is not the newer K1582 full-TX active-contract 2017-2026 aggregate cache, because K1582 does not retain intraday return paths needed to recompute RK / TSRV / MedRV.

Diagnostic market:

- Market: `SPY_2026_local_5min`
- Source: `data/intraday/SPY_5min_2026-*.csv`
- Date range: `2026-01-14` to `2026-07-02`
- Daily rows: `116`
- OOS forecasts: `49`
- Gateable? no, below the 252-OOS minimum.

## Method

Realized measures from 5-minute returns:

- `RV`: sum of squared 5-minute log returns.
- `MedRV`: Andersen-Dobrev-Schaumburg nearest-neighbor median realized variance.
- `RK`: Bartlett realized kernel / HAC variance estimator with bandwidth `5`.
- `TSRV`: two-scale realized variance with `5` sparse subgrids.

Primary target:

- All models forecast the same target: next-day standard 5-minute `RV`.
- Robust measures replace the HAR input series only.
- This prevents a mechanical advantage where each estimator forecasts its own target.

Models:

| Model | HAR input series |
|---|---|
| `HAR_RV` | standard 5-minute RV |
| `HAR_MedRV_input` | MedRV |
| `HAR_RK_input` | Bartlett RK |
| `HAR_TSRV_input` | TSRV |

Feature timing:

- Daily feature at forecast date `t`: `measure.shift(1)`.
- Weekly feature: 5-day rolling mean after `shift(1)`.
- Monthly feature: 22-day rolling mean after `shift(1)`.
- Expanding OOS fits use rows strictly before the forecast row.

Evaluation:

- Primary loss: QLIKE on standard 5-minute `RV_t`.
- Pairwise test: repo `dm_test`, horizon `h=1`.
- Strict pass: lower QLIKE and DM `t < -3`.
- MCS: alpha `0.10`, bootstrap `1,000`, seed `42`.

## Results

Verdict: `DIRECTIONAL_ONLY_NO_HARVEY_PASS`.

Formal TAIFEX results:

| Model | QLIKE | QLIKE improvement vs HAR_RV | DM t vs HAR_RV | p-value |
|---|---:|---:|---:|---:|
| `HAR_RV` | `0.2443` | baseline | baseline | baseline |
| `HAR_MedRV_input` | `0.2380` | `+2.58%` | `-0.79` | `0.432` |
| `HAR_RK_input` | `0.2428` | `+0.62%` | `-0.24` | `0.809` |
| `HAR_TSRV_input` | `0.2463` | `-0.83%` | `+0.37` | `0.712` |

MCS result:

- Members: all four models.
- No model eliminated at alpha `0.10`.
- Shared stopping p-value: `0.427`.

Measure diagnostics on TAIFEX:

- `MedRV / RV` median ratio: `0.9499`.
- `RK / RV` median ratio: `0.9237`.
- `TSRV / RV` median ratio: `0.8345`.
- Correlation with standard `RV`: MedRV `0.9915`, RK `0.9688`, TSRV `0.9619`.

SPY diagnostic:

- `HAR_RV` remains best by QLIKE: `0.3368`.
- `HAR_MedRV_input` QLIKE: `0.3382`, improvement `-0.41%`, DM `t=0.15`.
- `HAR_RK_input` QLIKE: `0.3736`, improvement `-10.93%`, DM `t=1.37`.
- `HAR_TSRV_input` QLIKE: `0.4058`, improvement `-20.49%`, DM `t=1.57`.
- SPY has only `49` OOS forecasts, so this is a pipeline diagnostic only.

## Interpretation

K1613 does not support a robust forecasting edge from replacing standard RV-HAR inputs with fixed-parameter MedRV, realized-kernel, or TSRV inputs.

The strongest result is MedRV on TAIFEX: average QLIKE improves by `2.58%`, but the DM statistic is only `-0.79`, far below the Harvey `|t| > 3` gate. RK is nearly tied with the baseline; TSRV is worse. MCS keeps every model.

The safe conclusion is:

> Jump/noise-robust realized measures are useful diagnostics, and MedRV may be a reasonable candidate for future feature engineering, but K1613 does not find a statistically robust replacement for standard 5-minute RV-HAR.

This is consistent with K1582: measurement corrections can point in the right direction, but the observed edge is not yet strong enough for a research claim.

## Files

- `K1613.py`: reproducible script.
- `K1613_results.json`: full results and metadata.
- `data/TAIFEX_TX_day_K1100h_daily_measures.csv`: formal daily realized measures.
- `data/TAIFEX_TX_day_K1100h_oos_forecasts.csv`: formal OOS forecasts.
- `data/SPY_2026_local_5min_daily_measures.csv`: SPY diagnostic daily realized measures.
- `data/SPY_2026_local_5min_oos_forecasts.csv`: SPY diagnostic OOS forecasts.
- `figures/TAIFEX_TX_day_K1100h_realized_measures.png`: TAIFEX realized-measure time series.
- `figures/taifex_qlike_improvement_vs_har.png`: TAIFEX QLIKE improvements.
- `figures/taifex_cumulative_loss_difference.png`: cumulative candidate-minus-baseline QLIKE loss.
- `figures/SPY_2026_local_5min_realized_measures.png`: SPY diagnostic realized-measure time series.

## Limitations

- The formal TAIFEX panel uses K1100h TX1-derived bars rather than a full-TX active-contract intraday-return cache. K1613 mitigates known contamination by dropping settlement days, but a cleaner future rerun should retain active-contract intraday paths from the K1582 loader.
- RK and TSRV use fixed transparent settings, not optimal bandwidth or noise-variance estimation.
- The primary target is standard 5-minute RV. The experiment answers input-substitution value, not which estimator best measures latent integrated variance.
- SPY local 5-minute data are too short for formal inference.
