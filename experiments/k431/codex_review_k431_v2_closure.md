# K431 v2 Closure Review

Reviewer: Codex
Date: 2026-06-16
Parent task: `paper_review_mile_764012ef_rerun_lookahead`
Article: `mile_764012ef`

## Verdict

CONDITIONAL_PASS

The v2 rerun fixes the critical lookahead/state issues identified in the original article review, and the article headline remains directionally supported: STGARCH does not beat GJR on the 2023-2024 SPY OOS slice. The pass is conditional because the DM implementation is still a conventional non-HAC, non-Harvey two-sided test and should be described as such.

## Critical Findings Closed

1. Lookahead in STGARCH-lagvol transition variable was closed by replacing full-sample GJR conditional volatility with walk-forward in-sample-only conditional volatility.
2. Baseline OOS forecast asymmetry was closed by fitting GARCH/GJR on `idx-lookback:idx` and using the one-step-ahead `forecast(horizon=1)` variance.
3. STGARCH OOS state propagation was closed by carrying forward `h_forecast` as the current variance state before updating `eps_t`.
4. In-sample likelihood scale mismatch was closed by adding the Gaussian normalizing constant to STGARCH log-likelihood/AIC/BIC.

## Remaining Caveats

1. DM tests use OOS-only QLIKE loss differentials and are two-sided, but they do not use HAC/Newey-West serial-correlation correction.
2. Harvey-Leybourne-Newbold correction is not implemented. The article should not call the p-values Harvey-confirmed.
3. The QLIKE target is daily squared return, not 5-minute realized variance.
4. "QLIKE ceiling" should be framed as project-level empirical evidence, not a theorem or universal proof.

## Final v2 Numbers

| Model | QLIKE | Difference vs GJR | DM p-value |
|---|---:|---:|---:|
| GJR-GARCH(1,1) | 0.5588 | baseline | -- |
| STGARCH-lagvol | 0.5870 | +5.05% | 0.0142 |
| STGARCH-VIX | 0.5882 | +5.26% | 0.0133 |
| GARCH(1,1) | 0.5890 | +5.40% | 0.0082 |
| STGARCH-|ret| | 0.5955 | +6.56% | 0.0014 |

## Article Corrections Applied

1. Replaced original STGARCH gaps of 9-12% with v2 gaps of 5.05-6.56%.
2. Changed the parameter-count claim from "about 7 extra parameters" to "4 extra free parameters" for this implementation: STGARCH 9 vs GJR 5.
3. Downgraded DM wording to conventional two-sided non-HAC/non-Harvey language.
4. Updated article figures from `k431_stgarch_v2_results.json`.
5. Added a 2026-06-16 v2 correction note explaining why the old numbers changed.

## Publication State

Local canonical files `storage/reports/feed.json` and `storage/reports/mile_764012ef.json` were updated through `scripts/publish_draft.py --update`, and both article images were uploaded to the article-images bucket. `uv run volpred ops feed-sync --apply` timed out twice with no output, so remote feed projection sync is not confirmed in this closure.
