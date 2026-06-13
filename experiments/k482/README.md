# K482: MCS p-value weighted ensemble vs equal weight

- Experiment ID: `K482`
- Status: completed, article corrected after Codex 24h review
- Created At: 2026-04-16T09:39:31.573301+00:00
- Script: `experiments/k482/k482_mcs_weighted_ensemble.py`
- Results: `experiments/k482/k482_mcs_weighted_ensemble_results.json`
- Source article: `mile_97e0bb31`
- Review record: `experiments/k482/reviews/paper_review_mile_97e0bb31_codex_20260612.md`

## Research Question

K481 identified a superior volatility-model set with MCS p-values. K482 tests whether turning those p-values into ensemble weights improves out-of-sample SPY volatility forecasts relative to naive equal weighting.

## Data And Setup

- Asset: SPY from yfinance.
- Sample after feature construction: 5,319 daily observations, 2005-02-02 to 2026-03-25.
- In-sample window: 2,000 trading days.
- Refit interval: 63 trading days for GARCH models.
- OOS periods: 2015-2016, 2017-2018, 2019-2020, 2021-2022, 2023-2025.
- Loss: QLIKE against an `r2_proxy` realized-variance proxy.

## Models And Weighting Schemes

Component models:

- GJR-GARCH(1,1) Student-t.
- EGARCH(1,1) Normal.
- HAR log-range.
- HAR semivariance.

Weighting schemes:

- `Equal_Weight`: one quarter per model.
- `MCS_PValue`: proportional to K481 MCS p-values.
- `MCS_Subperiod`: proportional to K481 subperiod MCS p-values.
- `Inv_QLIKE`: oracle inverse current-period QLIKE, included only as an upper-bound diagnostic.
- `Inv_QLIKE_Prev`: inverse previous-period QLIKE, no lookahead but only available after the first period.
- `Best_Single`: best component model within each period, an ex-post benchmark.

## Main Result

Equal weight beats MCS p-value weighting on average QLIKE:

| Scheme | Average QLIKE | Average Rank |
|---|---:|---:|
| Equal_Weight | 0.721023 | 2.6 |
| MCS_PValue | 0.735633 | 3.8 |
| MCS_Subperiod | 0.729557 | 2.8 |
| Inv_QLIKE_Prev | 0.755654 | 3.5 |

The period-level comparison is not a clean sweep:

- Equal weight has lower QLIKE in 2015-2016, 2017-2018, and 2019-2020.
- MCS p-value weighting has slightly lower QLIKE in 2021-2022 and 2023-2025.
- Only the 2017-2018 Volmageddon period is significant at 5% for Equal vs MCS (`DM=-2.6034`, `p=0.0092`).
- The five-period Wilcoxon test is not significant (`W=3.0`, `p=0.3125`).

## Timing / Lookahead Check

The core daily forecasts are ex-ante: each target day uses `feat.iloc[is_start:pos]` for estimation and compares the forecast to realized variance at `pos`.

`Inv_QLIKE` is explicitly an oracle diagnostic because it uses current-period QLIKE. `Inv_QLIKE_Prev` uses the previous period's component QLIKE and is therefore lookahead-safe at the period level, but it performs worse than equal weight on average.

## Review Correction

The original production article overstated the result as if equal weight won all five periods. Codex review on 2026-06-12 corrected the article title/body to distinguish average advantage from a period-by-period clean sweep.
