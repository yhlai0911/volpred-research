# Codex 24h Source Review: mile_97e0bb31

**Article**: `mile_97e0bb31` - K482: MCS p-value weighted ensemble vs equal weight

**Experiment**: `K482`

**Date**: 2026-06-12

**Verdict**: FAIL, corrected with errata

## Scope

This review checked whether the published article's claims are supported by:

- `storage/reports/feed.json`
- `experiments/k482/k482_mcs_weighted_ensemble.py`
- `experiments/k482/k482_mcs_weighted_ensemble_results.json`
- `experiments/k481/k481_model_confidence_set_results.json`

## Findings

### HIGH: The headline overstated the period-level result

The article title and H1 said MCS p-value weighting lost to equal weight in all five market regimes. The source results do not support a clean sweep. `Equal_Weight` has lower QLIKE in three periods, while `MCS_PValue` is numerically lower in 2021-2022 and 2023-2025.

The corrected framing is: equal weight wins on average QLIKE (`0.721023` vs `0.735633`, a 2.03% MCS penalty), with a period-level count of Equal 3 vs MCS 2.

### MEDIUM: The article overstated the adaptive inverse-QLIKE scheme

The original summary described `Inv_QLIKE_Prev` as close to equal weight. It is useful as the only no-lookahead adaptive inverse-QLIKE variant, and it wins the 2017-2018 Volmageddon period, but its average QLIKE is `0.755654`, worse than both equal weight and MCS p-value weighting.

### MEDIUM: Statistical strength needed clearer qualification

The article correctly reported the Volmageddon DM result (`DM=-2.6034`, `p=0.0092`) and overall Wilcoxon non-significance (`W=3.0`, `p=0.3125`). The conclusion needed to state that the cross-period evidence is an average-loss result rather than a formally significant five-period sweep.

### LOW: Experiment README was placeholder-only

`experiments/k482/README.md` still contained planning placeholders. It has been replaced with data, method, result, timing, and correction notes.

### PASS: Forecast timing is ex-ante for the main schemes

The daily loop forecasts target day `pos` using estimation data ending before `pos` (`feat.iloc[is_start:pos]`). I did not find a same-day signal multiplied by same-day return pattern in the core Equal, MCS p-value, or MCS subperiod forecasts.

`Inv_QLIKE` is correctly labelled as oracle because it uses current-period QLIKE. `Inv_QLIKE_Prev` uses previous-period component QLIKE and is lookahead-safe at the period level.

## Actions Taken

- Rewrote the article title/body through `scripts/publish_draft.py --update`.
- Added errata metadata to the article update.
- Replaced the K482 placeholder README with a reproducible experiment summary.
- Added this review record under `experiments/k482/reviews/`.

## Follow-Up

No new experiment is required for the correction. A useful future task is to test monthly or rolling-window adaptive weights, because K482 only evaluates static MCS p-value weights plus period-level inverse-QLIKE variants.
