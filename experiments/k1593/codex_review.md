# Codex Review - K1593

Review date: 2026-07-01

Verdict: `CONDITIONAL_PASS`

## Scope

Reviewed:

- `experiments/k1593/k1593.py`
- `experiments/k1593/k1593_results.json`
- `experiments/k1593/README.md`

The review focuses on whether the experiment is internally valid as a fixed,
small-scale CNN-Transformer vs same-information HAR-X adjudication.

## Findings

### PASS - Data provenance

The script uses only the frozen local CSV:

`paper/leverage-direction/data/spy_qqq_gld_tlt_eem_iwm_slv_btc_usd_vix_2010-2026.csv`

No live data download occurs.

### PASS - Lookahead control

Each OOS row predicts `target_date` with features through `feature_date`.
The JSON records `oos_feature_before_target_all_rows = true` for every asset.
The train/validation/OOS split is based on target dates, not row positions.

### PASS - Information symmetry

`CNNTransformer`, `HAR-X`, and `Ridge-HAR-X` use the same feature family:

`log_rv1`, `log_rv5`, `log_rv22`, `log_vix_var`, `abs_ret`, `neg_ret`

This is the correct design for testing architecture value rather than feature
access.

### PASS - QLIKE direction

The script imports the canonical project implementation:

`from volpred.stats.model_evaluation import dm_test, qlike, qlike_pointwise`

The loss direction is canonical Patton QLIKE:

`actual / predicted - log(actual / predicted) - 1`

Lower is better. Negative DM for `CNNTransformer_minus_HAR-X` favors
`CNNTransformer`.

### PASS - Multiple testing and panel inference

Asset-level `CNNTransformer` vs `HAR-X` p-values are Holm-adjusted across
assets. Panel inference first averages losses by common target date, then runs
DM/MCS on the date series. This avoids treating stacked asset-day rows as iid.

### PASS - Result interpretation

The conclusion is appropriately conservative:

- CNNTransformer best mean loss in 1/7 assets.
- CNNTransformer strict Holm win vs HAR-X in 1/7 assets, TLT only.
- All-asset panel best model is RollingMean22.
- All-asset panel CNNTransformer vs HAR-X DM t = +1.34, p = 0.180.
- All-asset MCS retains all four models.

The reported verdict `NULL_VS_HARX` is supported.

## Caveats

1. This is a smoke/adjudication run, not a faithful replication of a published
   CNN-Transformer volatility paper.
2. Only h=1 and Parkinson RV are tested.
3. Only one seed and one compact neural architecture are used.
4. The TLT positive cell is real in this run but fragile as a contribution:
   it is one asset, and the cross-asset panel does not confirm superiority.
5. The rolling/econometric baseline family is HAR-X/Ridge/naive only; no
   GJR-GARCH-t or Realized-GARCH is included because the target is range-based
   daily RV and the task was scoped to architecture value over same-information
   HAR baselines.

## Required Wording

Acceptable:

> In a fixed 2023-2026 OOS test across seven ETFs, a compact CNN-Transformer
> does not robustly outperform same-information HAR-X/Ridge baselines. A TLT
> positive cell appears, but the panel test and MCS do not support a general
> architecture edge.

Not acceptable:

> CNN-Transformer improves volatility forecasting.

Not acceptable:

> Deep learning beats HAR/GARCH.

## Recommendation

Record as a null/weak experiment and do not write a reader-facing article unless
the article is explicitly about the ML ceiling or the single TLT anomaly is
followed up with multi-seed, multi-target, and GJR/Realized-GARCH robustness.
