FAIL

1. H4 lag bug: `run()` already creates `shock = shock_raw.shift(1)` and passes that lagged series into `controlled_regression()`, but H4 then uses `shock.shift(1)` again. Thus `shock_lag` is effectively t-2, while `abs_r_xle_lag`, `abs_r_tlt_lag`, and `vix_lag` are t-1. This violates the stated H4 spec and makes beta1 interpretation inconsistent.

2. H4 VIX control is not the stated VIX level. The panel stores returns/RV, not raw VIX close. Because `rv_VIX` exists, H4 sets `vix_lag = panel["rv_VIX"].shift(1)`; fallback is `rv_SPY.shift(1)`. This is lagged, but it is not `vix_{t-1}` as specified.

3. CPI/PPI +15 calendar-day lag is implemented, but the CPI event window uses `rolling(..., center=True)`, which marks pre-release days from a future release mark. After one lag, several pre-release observations can still be flagged using a future detected event. Acceptable only if explicitly treated as a known scheduled-event window; otherwise it is lookahead.

4. Hypothesis-test mechanics pass: paired one-sided t p-value derivation is correct, Wilcoxon uses `alternative="less"`, and H3 applies Fisher z after clipping bounded correlations.

5. Bonferroni passes: `7 * 4 = 28`, `0.05 / 28 = 0.0017857142857142859`.

6. Seed reproducibility passes: `np.random.seed(42)` is set and no unseeded RNG/random sampling is used.

Bottom line: H1-H3 testing code is mostly acceptable, but H4 must be rerun after fixing the double shock lag and VIX-level control before results can be trusted.

## Round 2

ROUND2_PASS

The three round-1 issues are correctly fixed.

1. H4 now passes unlagged `shock_raw` from `run()` and `subperiod_h4()` into `controlled_regression()`, where `shock_lag = shock_raw.reindex(panel.index).shift(1)` is applied exactly once.
2. `vix_lag` is now `panel["vix_level"].shift(1)`, with `vix_level` joined from raw `prices["^VIX"]`; it is no longer `rv_VIX` or a VIX return.
3. CPI event windows now use causal right-aligned `cpi_release_marks.rolling(6, min_periods=1).sum() > 0`; no `center=True` remains.

Focused lookahead sweep: remaining `rolling()` calls are for RV/semivariance/correlation outcomes, monthly CPI/PPI trailing means, or causal release windows. H4 predictors are all explicitly `.shift(1)`. I do not see a remaining rolling predictor used as t-1 without lag.
