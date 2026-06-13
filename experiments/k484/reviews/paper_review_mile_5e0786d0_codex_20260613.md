# Codex Review: `mile_5e0786d0`

**Article**: `mile_5e0786d0` — 波動率模型是不是加越多料越好？SPY 這次給的答案是：先學會刪

**Experiment**: `K484`

**Verdict**: PASS WITH PROVENANCE / SCOPE FIXES

## Checks

- Recomputed article claims from `experiments/k484/k484_ssvs_variance_eq_results.json`.
- Confirmed PIP claims: GJR asymmetry, VIX implied variance, Parkinson range, and absolute shock are 1.000; rolling negative semivariance is 0.094.
- Confirmed OOS QLIKE relative changes versus base GARCH: SSVS median -7.43%, kitchen sink -7.01%, GJR-GARCH -2.91%.
- Checked the script's timing convention. For close-to-close return from day `t` to `t+1`, VIX and Parkinson range are taken from day `t`, and return-derived predictors use prior returns. This is ex-ante at an end-of-day forecasting timestamp.
- Checked article for DM/Harvey overclaim. The article reports forecast improvement magnitudes but does not claim formal Harvey-adjusted superiority.

## Fixes Applied

- Replaced placeholder `experiments/k484/README.md` with a completed experiment README containing data source, period, method, results, and limitations.
- Corrected `experiments/k484/k484_ssvs_variance_eq.py` output path so reruns write to `experiments/k484/k484_ssvs_variance_eq_results.json`, matching the required experiment package.
- Added a reader-facing scope caveat to `storage/drafts/k484_general_draft.md`: the result is a SPY 2023-2024 OOS finding and broader regime claims require cross-OOS validation.
- Re-published the article locally through `scripts/publish_draft.py --update mile_5e0786d0`, creating `storage/reports/mile_5e0786d0.json` and appending errata history.
- Removed article-level anti-ai-style `not-but` phrasing. `validate_anti_ai_style.py --recent 5 --json` no longer flags `mile_5e0786d0`; the remaining recent severe flag is for a different article, `mile_5ef55c52`.

## Residual Risk

- The MCMC diagnostics show low effective sample size for several continuous parameters, including VIX, absolute shock, and some GARCH parameters. The article should therefore stay at the component-screening / single-window forecast-comparison level.
- K485 cross-OOS validation should be cited for broader robustness claims.
