# K1637 — Markov-switching multifractal volatility forecasting

## Research question

Can a Calvet-Fisher / Lux style Markov-switching multifractal (MSM) volatility mechanism work as a practical "third explanation" between rough volatility and long-memory volatility, and improve one-day-ahead variance forecasts out of sample?

This experiment is deliberately narrower than the full literature version. It tests a reproducible free-data, daily close-to-close proxy:

- target: next trading day's close-to-close squared log return `r_t^2`
- assets: `SPY`, `QQQ`, `GLD`, `TLT`, `0050.TW`
- data source: local `data/cache/price_cache.db`
- 0050.TW cleaning: `volpred.utils.clean_tw50_data`
- OOS starts after 750 initial training rows

## Literature motivation

- Calvet and Fisher / Lux MSM models generate volatility persistence through multiple Markov components.
- Lux, Morales-Arias and Sattarhoff propose RV-MSM as an alternative mechanism for realized-volatility forecasting.
- Recent realized-volatility forecast reviews still emphasize HAR as a strong baseline, so any MSM claim must beat simple persistence baselines, not just a weak model.

## Method

Models compared on the same one-day `r_t^2` target:

| Model | Role |
|---|---|
| `HAR` | log-variance HAR with `shift(1)` d/w/m features |
| `FIGARCH_lite` | fractional-decay log-variance baseline, d selected by in-sample QLIKE |
| `MS_vol_lite` | two-state Gaussian HMM on log variance |
| `MSM_GMM` | 4-component binary MSM, GMM-lite moment match on log `r^2` variance and ACF(1,5,22,66), then exact finite-state filter |
| `CONST` / `EWMA_094` | sanity baselines to test whether HAR is simply weak on noisy daily `r^2` |

Lookahead policy:

- HAR predictors are explicitly built from `y.shift(1)`.
- MSM and HMM forecasts use `posterior_{t-1} @ transition` before observing return `r_t`.
- Initial model parameters are fit on the first 750 rows only.
- Pooled inference aggregates loss differentials by date before DM tests, not by stacked asset-day iid.

## Results

Primary verdict from `k1637_results.json`:

`CONDITIONAL_NULL_MSM_BEATS_HAR_BUT_LOSES_TO_EWMA`

Pooled QLIKE, lower is better:

| Model | QLIKE |
|---|---:|
| `EWMA_094` | 1.5556 |
| `MSM_GMM` | 1.7696 |
| `MS_vol_lite` | 1.8438 |
| `CONST` | 1.9452 |
| `HAR` | 2.2671 |
| `FIGARCH_lite` | 2.2934 |

Formal pooled DM-HAC results:

- `MSM_GMM` beats `HAR`: QLIKE improvement +21.94%, t=-7.32, Harvey-pass.
- `MSM_GMM` beats `MS_vol_lite`: QLIKE improvement +4.02%, t=-3.34, Harvey-pass.
- `MSM_GMM` loses to `EWMA_094`: QLIKE improvement -13.76%, t=+3.70, Harvey-pass against MSM.

Per-asset summary:

| Asset | OOS n | HAR QLIKE | EWMA QLIKE | MSM QLIKE | MSM vs HAR t | MSM vs EWMA t |
|---|---:|---:|---:|---:|---:|---:|
| SPY | 1888 | 2.1881 | 1.5781 | 1.6432 | -6.33 | +1.01 |
| QQQ | 1888 | 2.1111 | 1.5395 | 1.5526 | -10.33 | +0.42 |
| GLD | 1888 | 1.8727 | 1.5395 | 1.9577 | +0.58 | +3.35 |
| TLT | 1888 | 1.7000 | 1.2364 | 1.4187 | -3.40 | +2.12 |
| 0050.TW | 1799 | 3.5228 | 1.9007 | 2.3009 | -7.49 | +3.49 |

## Interpretation

MSM does capture volatility persistence better than the HAR / fractional / two-state Markov-volatility baselines in this daily proxy design. But it does **not** pass the stricter practical gate, because a one-line EWMA(0.94) forecast has the best pooled QLIKE and significantly beats MSM.

The honest conclusion is not "MSM is a superior deployable forecaster." It is:

> A multifrequency regime mechanism helps relative to HAR on noisy daily `r_t^2`, but the free-data daily implementation does not beat simple EWMA. MSM remains an interesting structural explanation, not an actionable VolPred model upgrade from this test.

## Files

- `k1637.py` — reproducible experiment script
- `k1637_results.json` — byte-traceable outputs
- `data/*_oos_forecasts.csv` — OOS actual/prediction/loss rows
- `figures/k1637_qlike_improvement_vs_har.png`
- `figures/k1637_pooled_qlike.png`

## Limitations

- `MSM_GMM` is a transparent GMM-lite moment-matching implementation, not full Calvet-Fisher simulated GMM or exact MLE.
- `FIGARCH_lite` and `MS_vol_lite` are mechanism baselines, not production package implementations.
- This tests close-to-close daily variance, not high-frequency realized-volatility MSM.
- The result should not be written to knowledge as a strong pass; it is a conditional null for practical model improvement.
