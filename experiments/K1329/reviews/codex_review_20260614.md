# Codex Review — K1329

- Date: `2026-06-14`
- Reviewer: Codex
- Verdict: `PASS_WITH_NULL_FORECAST_EDGE`

## Scope

Reviewed:

- `experiments/K1329/K1329.py`
- `experiments/K1329/K1329_results.json`
- `experiments/K1329/README.md`
- Generated figures and CSV audit outputs

## Checks

- Experiment three-piece exists: `README.md`, `K1329.py`, `K1329_results.json`.
- `seed=42` is fixed.
- All forecast features use explicit `.shift(1)`.
- Granger tests use lagged predictors via `statsmodels.grangercausalitytests`.
- `CL=F` non-positive close on `2020-04-20` is excluded from CL log returns.
- Rolling returns / RV / vol-of-vol are computed on each asset's own valid trading-day series before reindexing to the union panel. This avoids holiday `NaN` contamination.
- OOS sample is chronological 70/30; all targets have at least `1395` OOS observations.
- Formal forecast conclusion uses QLIKE plus DM-HLN; Harvey-style gate requires `|t| > 3`.

## Findings

No blocking issues after the data-alignment fix.

Initial implementation computed rolling features on the union calendar, so U.S. holidays with partial ticker coverage caused downstream rolling `NaN` gaps. The final script fixes this by computing each asset's return and rolling features on its own valid observations before reindexing.

## Result Interpretation

The final result is not a forecast edge:

- No target passes the Harvey `|t| > 3` OOS QLIKE improvement gate.
- Best SPY OOS improvement is only `+0.297%` with `DM-HLN t=-0.522`, `p=0.602`.
- Energy names are mixed and mostly worse than the HAR+VIX baseline.

The Granger result is real but should be framed narrowly:

- `14` family-Bonferroni-adjusted pairs pass, mostly lag-1 CL/USO volatility shock and OVX level.
- `CL_vov` and `USO_vov` do not pass for any target.
- Adding OVX to the forecast model worsens OOS QLIKE for all targets.

Recommended knowledge wording: oil volatility shocks are statistically detectable in lag-1 daily Granger tests, but they do not add robust OOS forecasting value beyond own-vol HAR + VIX.

