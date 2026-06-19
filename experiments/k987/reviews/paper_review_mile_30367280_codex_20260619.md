# K987 / mile_30367280 Codex 24h Publication Review

- Article: `mile_30367280` - "市場最危險的時候，VIX 不是變高而已，它會開始彎"
- Task: `paper_review_mile_30367280`
- Source experiment: `experiments/k987/`
- Reviewer: Codex
- Review date: 2026-06-19
- Verdict: **PASS**

## Bottom Line

The public article is supported by the committed K987 artifacts. The headline convexity claim, OOS R2 comparison, GJR baseline comparison, and non-overclaiming language around M2 Quadratic all match `experiments/k987/k987_vix_nonlinear_results.json`.

No article update, retraction, or results change is required.

## Claim-Evidence Match

| Article claim | Source check | Status |
|---|---:|---|
| VIX high-regime slope is about 5.5x the low-regime slope | `convexity_analysis.convexity_ratio = 5.5379`, median VIX `17.12` | PASS |
| Linear VIX OOS R2 is about 0.202; Quadratic VIX+VIX2 rises to about 0.258 | `evaluation.M1_Linear.oos_r2 = 0.2022`; `evaluation.M2_Quadratic.oos_r2 = 0.2581` | PASS |
| The experiment compares 8 model variants including GJR-GARCH | Results contain M1-M7 plus `GJR_GARCH` | PASS |
| VIX-based models beat GJR; GJR has negative OOS R2 | `evaluation.GJR_GARCH.oos_r2 = -0.3390`; all `dm_test_vs_gjr_mse` entries are significant in favor of VIX-based models | PASS |
| M2 Quadratic is highest by OOS R2, but not a unique statistically decisive winner over M4/M7 | `best_model_r2 = M2_Quadratic`; M2 vs M4 p=0.5114 and M2 vs M7 p=0.1015 | PASS |
| Residual nonlinear structure remains | RESET p-values for M1-M4 are effectively zero; results conclusions state residual nonlinearity persists even with quadratic/spline | PASS |
| OOS period and sample size | `oos_period = 2019-01-01 to 2026-04-07`, `n_oos = 1824` | PASS |

## Lookahead / Timing Audit

No lookahead issue was found.

- VIX features are explicitly lagged with `.shift(1)` before the IS/OOS split: `vix_lag`, `vix2_lag`, `log_vix_lag`, and `vix_pw_lag`.
- All OOS VIX models use the lagged OOS design matrices to predict `r2_t`.
- The GJR baseline loop uses `ret_full[:idx]` at each OOS index, so the fitted baseline excludes the target-day return.

This satisfies the project convention: feature information from `t-1`, realized squared return at `t`.

The generic `scripts/lookahead_audit.py` scan does not flag `experiments/k987/k987_vix_nonlinear.py` as part of its weights-times-returns pattern family.

## DM / Harvey / Statistical Claims

The article does not overclaim statistical significance. It says M2 Quadratic ranks first by OOS R2 but avoids calling it the sole decisive winner, which matches the stored pairwise DM results:

- M2 vs M4: p=0.5114, not significant.
- M2 vs M7: p=0.1015, not significant.
- M2 vs M5: p=0.0640, marginal only.

K987 uses MSE-based DM tests because several variance forecasts are clipped near zero and their QLIKE values become unreliable. The public article does not misuse the clipped QLIKE comparisons.

## Reproducibility / Provenance Caveat

K987 has the required experiment triad:

- `experiments/k987/README.md`
- `experiments/k987/k987_vix_nonlinear.py`
- `experiments/k987/k987_vix_nonlinear_results.json`

The script depends on live yfinance downloads and does not pin raw local price snapshots. I did not rerun the full pipeline during this review because a fresh vendor pull could change the target artifact. This review verifies committed source/results/article consistency.

One minor source-doc caveat: the README calls M5 a natural cubic spline, while the implementation uses a truncated-power spline basis without explicit natural-boundary constraints. The public article only says "spline", so this is not a reader-facing content issue.

## Verification

- `uv run python -m py_compile experiments/k987/k987_vix_nonlinear.py` passed.
- Deterministic JSON checks confirmed the article's convexity ratio, OOS R2 figures, GJR negative R2, M2-vs-M4/M7 DM p-values, and OOS sample size.
- `uv run python scripts/lookahead_audit.py --json` reported no K987 finding.

## Verdict

`PASS`.

The public article can remain published. No source or content correction is required.
