# Codex 24h Source Review: mile_b65e01ee

**Article**: `mile_b65e01ee` — 波動率預測最準的模型，為什麼算風險卻輸得最慘？

**Experiments**: `K467`, with premise checks against `K465` and `K469`

**Date**: 2026-06-12

**Verdict**: PASS after provenance correction

## Scope

This review checked whether the production article's claims are supported by:

- `storage/reports/feed.json`
- `experiments/k467/k467_har_range_var.py`
- `experiments/k467/k467_har_range_var_results.json`
- `experiments/k465/k465_har_range_cross_oos.py`
- `experiments/k465/k465_har_range_cross_oos_results.json`
- `experiments/k469/k469_har_r2_proxy_results.json`

## Findings

### MEDIUM: K465 premise needed K469 provenance

The original article said K465 showed HAR took a 10/10 cross-asset volatility forecasting score. That is numerically traceable to K465, but K465 is also explicitly followed by K469, whose title and background describe it as correcting the K465 Parkinson-proxy tautology concern.

Impact: the article's main K467 conclusion is not overturned, because K469 still finds HAR robust under r^2 proxy evaluation. The public article needed to cite K469 so the "best volatility forecaster" premise is not presented as relying only on the range-proxy K465 setup.

### LOW: Experiment README was placeholder-only

`experiments/k467/README.md` still contained planning placeholders. It has been replaced with source-bound data, method, result, timing, and limitation notes.

### LOW: Article source path label was stale

The article footer pointed to `experiments/k467/k467.py`, but the actual script is `experiments/k467/k467_har_range_var.py`. The updated article now names the real script and result paths.

### PASS: K467 table numbers are traceable

The article's method pass counts match `k467_har_range_var_results.json`:

- `GJR-Normal`: 6/6 Trinity passes.
- `GJR-SkewT`: 6/6 Trinity passes.
- `RS_neg-Normal`: 3/6 Trinity passes.
- `Hybrid-GARCH+HAR`: 2/6 Trinity passes.
- `HAR-Range-Normal`: 0/6 Trinity passes.
- `HAR+Semi-Combined`: 0/6 Trinity passes.

The highlighted violation counts also match the results file: SPY HAR-Range 1% has 21 violations, and EEM HAR-Range 1% has 50 violations, each against a 1% expected rate over 502 observations.

### PASS: K467 VaR forecast timing is ex-ante

The K467 rolling loop evaluates target date `date_t` using `feat.loc[feat.index < date_t]` for the HAR window before computing `actual_return = returns_arr[t_idx]`. GJR and RS-negative methods similarly use `returns_arr[is_start:t_idx]` before the target return. I did not find same-day signal usage in the K467 VaR backtest.

K465's cross-OOS script has a same-row proxy-alignment ambiguity in its HAR forecasting path, which is why the article now points readers to K469's r^2-proxy correction when citing the volatility-forecasting premise.

## Actions Taken

- Rewrote the article through `scripts/publish_draft.py --update` to cite K469, add two chart references, and fix the K467 script path.
- Added K469 to `details.experiment_refs`.
- Replaced the K467 placeholder README with a reproducible experiment summary.
- Added this review record under `experiments/k467/reviews/`.

## Follow-Up

No new experiment is required for the corrected article. A useful follow-up is a K467 extension over 2020-2022 and a Student-t or EVT overlay for HAR VaR, because the current VaR OOS window is only 2023-2024.
