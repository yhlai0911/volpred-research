# Codex 24h Source Review: mile_c5881a5b

**Article**: `mile_c5881a5b` - 把兩個模型加在一起，反而打敗了其中最強的那一個

**Experiment**: `K475`

**Date**: 2026-06-12

**Verdict**: FAIL, corrected with errata

## Scope

This review checked whether the production article's numerical claims and methodological framing are supported by:

- `storage/reports/feed.json`
- `storage/drafts/k475_general_draft.md`
- `experiments/k475/k475_validated_ensemble.py`
- `experiments/k475/k475_validated_ensemble_results.json`
- `experiments/k434/k434_bma_garch_results.json`
- `experiments/k467/k467_har_range_var_results.json`

## Findings

### HIGH: One period-rank claim overstated the result

The article originally said `Ens_GJR_HAR` ranked first in three r2-proxy OOS periods and was top-three in the other two. The results file shows r2-proxy ranks of `2, 1, 1, 1, 4`. The last period, 2023-2025, is rank 4 rather than top-three.

Impact: the article's main conclusion is not overturned because `Ens_GJR_HAR` still has the best five-period average rank and lowest average QLIKE. The public wording needed correction because "top-three in the other two" was false.

### MEDIUM: The final summary overclaimed VaR as "best"

The article's original closing sentence said `Ens_GJR_HAR` performed best in both volatility forecasting and VaR. The source supports best average QLIKE, but the VaR table supports "passes the 1% Trinity tests" rather than strict all-model VaR best. `Ens_HAR_Semi` has a lower 1% violation rate in the same window.

Impact: corrected wording now says `Ens_GJR_HAR` ranks first on average forecast accuracy and passes the 1% VaR backtest, without claiming global VaR dominance.

### LOW: Experiment README was placeholder-only

`experiments/k475/README.md` still contained planning placeholders even though the experiment had already produced a production article. The README was replaced with source-bound data, method, result, artifact, and review notes.

### PASS: Core article numbers are traceable

The following article claims match the K475 results file after the wording correction:

- Effective sample: 5319 SPY daily observations, 2005-02-02 to 2026-03-25.
- Rolling estimation window: 2000 observations.
- Five OOS periods covering 2015-2025.
- Average r2-proxy QLIKE: `Ens_GJR_HAR` 0.694465, HAR 0.736682, GJR 0.742422.
- Average Parkinson-proxy QLIKE: `Ens_GJR_HAR` 0.252176, HAR 0.267300, GJR 0.350452.
- 1% VaR 2021-2024: HAR violation rate 1.49%, Kupiec p=0.1436; `Ens_GJR_HAR` violation rate 1.59%, Kupiec p=0.0824; GJR violation rate 2.19%, Kupiec p=0.0011.
- DM comparisons are not significant at 5% for `Ens_GJR_HAR` versus the best single model under r2 proxy.

### PASS: Forecast timing is ex-ante

The source code estimates each OOS forecast using `feat.iloc[window_start:oos_loc]` and evaluates at `feat.iloc[oos_loc]`. HAR and semivariance forecasts use lagged rolling features from the estimation window; GJR uses returns ending before the target date. I did not find a same-day signal multiplied by same-day return pattern in K475.

## Actions Taken

- Corrected the rank-overstatement sentence in `storage/drafts/k475_general_draft.md`.
- Reworded the summary to avoid claiming strict VaR dominance.
- Clarified that cross-OOS forecast combinations average conditional variance forecasts.
- Added two figures generated from `k475_validated_ensemble_results.json`.
- Replaced the placeholder README with a reproducible experiment summary.

## Follow-Up

No new experiment is required for the corrected article. A future follow-up could test whether the `Ens_GJR_HAR` rank advantage survives post-2025 forward tracking or MCS-style model confidence set testing across the five-period loss vectors.
