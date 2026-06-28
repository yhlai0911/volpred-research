# K1560 Codex Source Audit

Audit verdict: PASS_WITH_NULL_RESULT_CAVEAT.

Reviewed `experiments/k1560/k1560.py` after the final run that produced
`k1560_results.json` with `verdict=NULL_SHORT_WINDOW`.

## Checklist

1. Lookahead absence: PASS.
   The experiment shifts all direct OHLC/RV forecasts and the estimator
   disagreement signal by one trading row before target-day evaluation
   (`k1560.py:403-418`). The final evaluation table also requires origin-day
   intraday dispersion and non-missing shifted signals (`k1560.py:434-443`).
   The saved audit checks strict `origin_date < target_date` and origin-day
   intraday availability (`k1560.py:714-750`).

2. GARCH target alignment: PASS.
   GARCH forecasts are generated in a manual loop where `target_pos` and
   `origin_pos = target_pos - 1` are explicit (`k1560.py:334-339`). The forecast
   value is stored under the target date after filtering returns only through
   the origin (`k1560.py:371-378`). This avoids the `arch.forecast` origin-vs-
   target alignment ambiguity.

3. Patton QLIKE direction: PASS.
   Pointwise losses call `qlike_pointwise(actual, forecast)` with
   `actual_total_rv` as the first argument (`k1560.py:460-466`). Aggregate model
   metrics also call `qlike(actual, fc)` (`k1560.py:589-600`), matching the
   canonical `actual/predicted - log(actual/predicted) - 1` implementation from
   `volpred.stats.model_evaluation`.

4. Formal tests / multiple testing: PASS.
   Panel tests use asset fixed effects, lagged origin RV, origin return, and
   dollar-volume controls with HAC(maxlags=5) standard errors (`k1560.py:515-565`).
   Holm-Bonferroni correction is implemented once and applied to the seven
   signal tests (`k1560.py:503-512`, `k1560.py:560-565`). Pairwise DM tests and
   full-sample HLN MCS diagnostics are also computed with Holm correction for DM
   p-values (`k1560.py:605-669`).

5. Seed / reproducibility / convergence handling: PASS_WITH_VENDOR_CAVEAT.
   Python and NumPy seeds are fixed at 42 (`k1560.py:50-72`), MCS bootstrap seed
   is fixed (`k1560.py:636-641`), and the daily request end date is pinned to
   `2026-06-29` (`k1560.py:53-56`). GARCH fit attempts, failures, convergence
   warnings, and EWMA fallbacks are counted (`k1560.py:76-81`, `k1560.py:342-360`)
   and saved in each asset summary (`k1560.py:445-454`). Residual caveat:
   yfinance 5-minute bars are a rolling vendor window, so future reruns may not
   reproduce the same intraday sample unless the data are separately cached.

## Result Integrity

The code does not overstate the finding. `decide_verdict()` requires at least
two Holm-significant positive primary hits plus broad positive rank signs before
returning a conditional pass (`k1560.py:754-777`). The actual result has no
Holm-significant signal tests, so `NULL_SHORT_WINDOW` is the correct verdict.
