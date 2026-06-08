# Backlog Task Resolution — `research_adaptive_fractal_dynamics`

Date: 2026-06-08  
Resolver: Codex CLI

## Verdict

This backlog item is already substantively covered by existing experiment `K973`.

## Coverage mapping

Backlog task:
- `research_adaptive_fractal_dynamics`
- Source wording: `Adaptive Fractal Dynamics — Frontiers Applied Math 2025`

Existing experiment:
- [README.md](/Users/yhlai0911/Desktop/volpred-research/experiments/k973/README.md:1)
- [k973_hurst_vol.py](/Users/yhlai0911/Desktop/volpred-research/experiments/k973/k973_hurst_vol.py:1)
- [k973_hurst_vol_results.json](/Users/yhlai0911/Desktop/volpred-research/experiments/k973/k973_hurst_vol_results.json:1)

`K973` already tests the repo-local version of the same idea: a time-varying / adaptive Hurst-style state, smoothed with EWMA, added as a forecasting feature for volatility prediction.

## What K973 already answers

- Asset: `SPY`
- Data period: `2006-01-04` to `2026-04-06`
- OOS: `2019-2026`
- Seed: `42`
- Adaptive fractal feature set:
  - rolling `R/S Hurst`
  - rolling `Variogram Hurst`
  - EWMA smoothing of both H series
  - HAR-type forecast regressions with lagged H features

Recorded result from `k973_hurst_vol_results.json`:
- Best model: plain `HAR`
- `HAR` QLIKE: `1.526412`
- `HAR + H_rs_ewma`: `1.5275`
- `HAR + H_vario_ewma`: `1.5270`
- DM vs HAR:
  - `H_rs_ewma`: `-0.89`, `p=0.372`
  - `H_vario_ewma`: `-0.11`, `p=0.911`

Main conclusion:
- daily-frequency adaptive Hurst features do **not** improve OOS QLIKE
- rough-vol characteristics are not usefully recoverable from daily close-to-close data for forecast improvement

## Why this closes the backlog item

The backlog item asks for an adaptive fractal dynamics direction. `K973` already implements the natural repo-specific translation of that idea:
- estimate time-varying Hurst-style state
- smooth it adaptively
- lag it properly
- add it to a HAR volatility forecast
- test OOS with DM against the plain HAR baseline

That experiment has already returned a clear null. So this is not an open gap; it is a duplicate backlog entry.

## Remaining gap, if any

If this line is reopened, the next meaningful step is narrower:
- exact replication of the 2025 paper's algorithm if it differs materially from EWMA Hurst
- intraday or realized-volatility inputs rather than daily returns
- multi-asset validation after a stronger high-frequency data pipeline exists

Those are extensions, not reasons to keep this generic backlog task pending.
