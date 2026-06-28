# K1560: Quadratic-Variation Estimator Disagreement as Forecast Uncertainty

## Research Question

Can disagreement among realized-variance and OHLC volatility estimators at date
`t` predict next-day volatility forecast loss, model-confidence uncertainty, or
vol-target sizing risk at `t+1`?

This experiment is a short-window pilot. yfinance 5-minute ETF bars are only
available for a recent rolling window, so the result is a diagnostic screen, not
a publication-grade long-sample conclusion.

## Motivation and Differentiation

K1558 showed that direct OHLC candlestick spot-vol estimators do not beat a
GARCH baseline for one-day-ahead QLIKE on SPY/QQQ/IWM/TLT/GLD/HYG. K1560 asks a
different question: not whether any estimator is best, but whether estimator
disagreement itself is a measurement-uncertainty signal.

Related prior axes:

- `K1558`: OHLC estimators as direct forecasts.
- `K1259`: model-confidence-set / DM multiple-testing discipline.
- `K1533`: realized-volatility covariates in GARCH-style forecasting.

## Literature Preamble

- Andersen, Bollerslev, Diebold, and Labys (2003), Econometrica: realized
  volatility measurement and forecasting.
- Hansen and Lunde (2006), JBES: realized variance and market microstructure
  noise.
- Barndorff-Nielsen, Hansen, Lunde, and Shephard (2009), Econometrics Journal:
  realized kernels in practice.
- Patton (2011), Journal of Econometrics: robust volatility forecast comparison
  with imperfect proxies.
- Hansen, Lunde, and Nason (2011), Econometrica: Model Confidence Set.

## Data

- Source: yfinance daily OHLCV from `2018-01-01` to request date
  `2026-06-29`; effective last daily date is `2026-06-26`.
- Intraday source: yfinance `5m` bars, `period=60d`, `prepost=False`.
- Intraday effective window: `2026-04-01` to `2026-06-26`.
- Assets: `SPY, QQQ, IWM, TLT, GLD, HYG`.
- Evaluation rows: 354 total, 59 per asset.
- Median bars per intraday session: 78.
- Random seed: 42.

## Measurement Proxies

At each origin date, the script computes:

- 5-minute realized variance.
- 10-minute two-grid subsampled realized variance.
- Bartlett realized-kernel-lite proxy with lags 1-3.
- Close-to-close squared return.
- Parkinson, Garman-Klass, Rogers-Satchell, and Yang-Zhang daily OHLC
  estimators.
- Total 5-minute RV target = overnight squared return plus intraday 5-minute
  RV.

The main signal is the cross-estimator log standard deviation after clipping
variance proxies at a small positive floor.

## Lookahead Control

The signal and direct OHLC/RV forecasts are computed at origin date `t` and
shifted to target date `t+1`. The final audit in `k1560_results.json` checks six
examples and confirms that each target date uses a strictly earlier origin date
with available intraday dispersion.

GARCH forecasts are manually indexed by target date. The code does not rely on
an origin-aligned `arch` forecast table for QLIKE evaluation.

## Forecast Baselines

- HAR on log close-to-close realized variance, trained only on rows whose next
  return target is already known by the origin date.
- GARCH(1,1), Normal innovations, mean zero, refit every 10 target origins and
  manually filtered through the origin date.
- EWMA baseline.
- Direct OHLC / RV persistence forecasts: Parkinson, Garman-Klass,
  Rogers-Satchell, Yang-Zhang, EqualOHLC, and RV5mPersist.

All QLIKE values use canonical Patton direction:

`actual / predicted - log(actual / predicted) - 1`.

## Formal Tests

Panel regressions use HAC standard errors with maxlags 5 and asset fixed
effects:

`target ~ signal_dispersion + log_origin_rv_total + origin_abs_return + origin_log_dollar_volume + C(asset)`

Targets:

- HAR next-day QLIKE.
- GARCH next-day QLIKE.
- EWMA next-day QLIKE.
- HAR and GARCH vol-target excess realized variance.
- GARCH vol-target absolute log sizing error.
- Future five-day near-MCS proxy size.

Holm-Bonferroni correction is applied across the seven signal tests.

The script also reports pairwise DM tests and full-sample per-asset HLN MCS
using stationary bootstrap with `B=1000`, seed 42.

## Result

Verdict: `NULL_SHORT_WINDOW`.

The dispersion signal has the expected positive sign for GARCH QLIKE and GARCH
vol-target sizing error, but none of the signal tests survive Holm correction.

Primary tests:

| Target | Coef | HAC t | Raw p | Holm p |
|---|---:|---:|---:|---:|
| GARCH QLIKE | 0.236 | 1.72 | 0.0847 | 0.512 |
| GARCH vol-target abs log sizing error | 0.141 | 1.79 | 0.0731 | 0.512 |
| GARCH vol-target excess realized variance | 0.285 | 1.14 | 0.253 | 1.000 |
| HAR QLIKE | 0.772 | 0.75 | 0.454 | 1.000 |
| Future 5d near-MCS proxy size | -0.104 | -0.77 | 0.443 | 1.000 |

Per-asset rank signs are also mixed. GARCH QLIKE has positive Spearman signs in
5/6 assets, but HAR QLIKE is positive in only TLT and the vol-target excess-risk
target is positive only in SPY/TLT.

## Model Ranking Diagnostics

Average QLIKE by asset shows the same broad lesson as K1558: smoothed
low-frequency baselines are hard to beat in direct one-day-ahead variance
forecasting.

| Asset | Best model | Best QLIKE |
|---|---|---:|
| SPY | GARCH | 0.380 |
| QQQ | GARCH | 0.394 |
| IWM | GARCH | 0.259 |
| TLT | EWMA | 0.307 |
| GLD | GARCH | 0.503 |
| HYG | EWMA | 0.416 |

HLN MCS sizes are 3 for GLD and 5 for the other five assets. The larger MCS
sets mostly contain Yang-Zhang, EqualOHLC, RV5mPersist, EWMA, and GARCH, while
raw Parkinson/GK/RS and HAR are often eliminated in this short window.

DM diagnostics are included for transparency: 216 asset-model pairs, 107 with
Harvey `|t| > 3`, and 42 Holm-significant at 5%.

## Interpretation

Supported:

- Estimator disagreement is directionally associated with higher GARCH loss and
  sizing error in this 60-day window.
- The direction is not strong enough for a robust claim after multiple-testing
  correction.
- K1560 should be treated as a null / underpowered pilot, not as a deployable
  vol-target de-leveraging rule.

Not supported:

- A claim that RV estimator risk bands reliably predict next-day QLIKE error.
- A claim that high estimator disagreement should mechanically reduce
  vol-target leverage.
- A long-sample statement about realized-kernel disagreement; the yfinance
  intraday window is too short.

## Caveats

- yfinance intraday history is short and vendor-revisable.
- The realized-kernel-lite proxy is a simple Bartlett autocovariance estimator,
  not a full noise-optimized realized kernel.
- The future near-MCS size is a descriptive near-best loss proxy. Formal HLN MCS
  is reported only as a full-sample per-asset diagnostic.
- Daily OHLC estimators and intraday RV measure different day components; the
  target adds overnight variance to reduce, not eliminate, this mismatch.

## Files

- `k1560.py`: experiment script.
- `k1560_results.json`: full results artifact.
- `k1560_dispersion_timeseries.png`: shifted origin-date disagreement signal.
- `k1560_dispersion_vs_loss.png`: loss and sizing-error by dispersion quartile.
