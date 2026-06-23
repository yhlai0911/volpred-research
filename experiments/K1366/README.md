# K1366 — Structural VIRF Shock Library Pilot

## Motivation

This task comes from the 2026-06-22 journal-discovery backlog:

> Structural VIRF shock library: turn major historical shocks into volatility
> impulse response templates for SPY/TLT/UUP/GLD/HYG, measuring volatility and
> covariance persistence after 2018Q4, 2020-03, 2022 rate shock, and 2025
> tariff shock.

The narrow VolPred question is:

**Can public ETF close-to-close data produce a defensible historical
second-moment response library for risk scenarios?**

This is a pilot. It deliberately does **not** claim full structural BEKK/DCC
identification.

## Related Project Context

- Prior DCC / BEKK work found that dynamic correlations are real, but often do
  not improve allocation decisions enough to beat simple portfolios.
- K628b and later connectedness experiments established broad cross-asset
  spillover diagnostics, but those are not event-level covariance response
  templates.
- K1355 error-log guidance says cross-asset inference must not stack asset-day
  observations as iid. K1366 therefore tests event-level summary statistics
  against placebo event dates, rather than treating asset-day cells as
  independent observations.

## Literature Checked

- Hafner and Herwartz (2006), *Volatility impulse response functions for
  multivariate GARCH models*:
  <https://econpapers.repec.org/RePEc:eee:econom:v132y2006i2p381-402>
- Fengler and Polivka (2025), *Structural Volatility Impulse Response
  Analysis*, Journal of Financial Econometrics:
  <https://academic.oup.com/jfec/article/23/2/nbae036/7994364>
- Bauwens, Laurent, and Rombouts (2006), *Multivariate GARCH models: a survey*:
  <https://ideas.repec.org/a/jae/japmet/v21y2006i1p79-109.html>
- *Volatility impulse response analysis for DCC-GARCH models* (2020):
  <https://ideas.repec.org/a/wly/jforec/v39y2020i5p788-796.html>

## Data

- Source: yfinance adjusted close, cached under `data/`.
- Assets:
  - SPY: US equity
  - TLT: long Treasury
  - UUP: US dollar
  - GLD: gold
  - HYG: high-yield credit
- Requested start: 2016-01-01.
- Event dates:
  - 2018-10-10: Q4 2018 equity / credit selloff shock.
  - 2020-03-16: COVID liquidity crash shock.
  - 2022-06-13: inflation / rate repricing shock before the June FOMC.
  - 2025-04-03: tariff-policy repricing shock.

## Method

1. Compute daily log returns from adjusted closes.
2. Build an EWMA conditional covariance filter with `lambda=0.94`. The
   covariance stored for date `t` uses only returns through `t-1`.
3. For each event, define the baseline as the EWMA covariance forecast before
   the event-day return.
4. Track the post-shock EWMA covariance path for 0 to 60 trading days after
   the shock update.
5. Summarize total covariance-trace lift, asset-level vol lift, and average
   off-diagonal correlation change.
6. Draw 1,000 placebo pseudo-event dates, excluding 63 trading days around the
   real events, to build empirical bands and p values for peak response,
   average 0-20 day response, and correlation-matrix change.

This is a historical response template. It is VIRF-inspired, but the script
does not estimate structural BEKK/DCC parameters or causal shock
identification.

## Lookahead Policy

- The EWMA covariance baseline at date `t` is computed from information through
  `t-1`.
- Event response paths are descriptive post-shock templates, not trading
  signals.
- The only predictive carryover diagnostic explicitly lags the event signal:

```python
lagged_signal = signal.shift(1)
```

- Random placebo sampling uses `SEED = 42`.

## Success Criteria

Strong scenario-library evidence requires:

1. At least two events have positive peak total-variance response with
   `p_peak_vs_placebo <= 0.05`.
2. Those events have half-life at least 5 trading days, or do not decay below
   half peak inside the 60-day horizon.
3. At least one event has `p_peak_corr_vs_placebo <= 0.05`.

If only one event passes, the verdict should be a narrow single-shock template.
If none pass, the result is null. No DM / Harvey forecast-race claim is made.

## Results

Verdict: `PARTIAL_VARIANCE_TEMPLATE_CORR_NULL`.

Sample: 2016-01-05 to 2026-06-22, 2,630 daily return rows. The EWMA
covariance sample starts after the 252-day initialization window on
2017-01-04.

Two events clear the total-variance placebo gate:

| Event | Trading date | Peak total-variance lift | Peak horizon | p vs placebo | Half-life |
|---|---:|---:|---:|---:|---:|
| 2018Q4 equity / credit | 2018-10-10 | +360.5% | 58d | 0.026 | not decayed within 60d |
| 2025 tariff shock | 2025-04-03 | +476.6% | 5d | 0.015 | 24d |

The 2020 COVID and 2022 rate-shock event dates do not exceed the same
placebo gate in this setup:

| Event | Trading date | Peak total-variance lift | p vs placebo |
|---|---:|---:|---:|
| 2020 COVID liquidity | 2020-03-16 | +66.2% | 0.324 |
| 2022 rate shock | 2022-06-13 | +41.8% | 0.469 |

No event clears the correlation-response placebo gate (`p_peak_corr_vs_placebo`
ranges from 0.175 to 0.740). The supported statement is therefore narrow:
public ETF data can form a **variance response scenario template** for some
historical shocks, but this experiment does **not** support a structural
covariance-network VIRF claim.

Run:

```bash
uv run python experiments/K1366/K1366.py
```

Primary artifacts:

- `K1366_results.json`
- `data/K1366_response_templates.csv`
- `data/placebo_summary.csv`
- `data/placebo_bands_by_horizon.csv`
- `figures/k1366_total_variance_response.png`
- `figures/k1366_asset_peak_vol_lifts.png`
- `figures/k1366_correlation_response.png`

## Limitations

- EWMA covariance is a feasible public-data filter, not a structural MGARCH
  model.
- Event dates are manually selected and should be rechecked before any
  publication-grade scenario library.
- Placebo-date bands are empirical diagnostics, not asymptotic VIRF confidence
  intervals.
- Close-to-close ETF returns omit intraday realized variance, option-implied
  volatility, and exact policy announcement timestamps.
