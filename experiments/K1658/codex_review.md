# K1658 — primary-path review record

## Reviewers
- **Codex primary path** (`scripts/codex_exec_bounded.sh --timeout 300`, gpt-5.x) on K1658.py.
- **Second reviewer**: feed collect_completed interpretation agent (opus/medium) — full triplet honesty audit + reran the experiment's own unit tests.

## Codex verdict (on pre-fix bytes): CONDITIONAL
Codex confirmed the core statistical machinery is sound and raised 5 issues, all
scope-precision / labelling nuances — none is a lookahead, seed, or Holm error,
and none manufactures a positive finding (0/6 tests survive Holm, so no claim
rests on any of them):

1. No direct lookahead; bootstrap seed deterministic; Holm over the 6 declared HAC hypotheses is correct.
2. "free data" is slightly overbroad (only cached yfinance was evaluated); N=2 is the union across assets, joint 3-asset intraday coverage is N=1.
3. The asymptotic paired-mean power calc (N>=13) does not exactly match the next-day-RV regression design (it bounds the intraday case-study design).
4. `p_boot_two_sided` is a supplementary stress-test, not a null-imposed/centered bootstrap p-value.
5. **`beta_pct_effect_on_vol`**: the outcome is log realized VARIANCE (log Parkinson var), so `exp(beta)-1` is a variance %-effect, not a volatility %-effect.
6. Terminology: an infeasibility (data-insufficiency) should not be called a "NULL".

## Corrections applied (commit c8d0295b9)
- Issue 5 fixed: field renamed `beta_pct_effect_on_vol` -> `beta_pct_effect_on_variance`
  in both K1658.py and K1658_results.json. **Values unchanged** — the stored number
  is a correct variance %-effect; only the label was wrong.
- Issue 6 fixed: README now keeps `INFEASIBLE` (separation cannot be tested,
  N=2) distinct from `NULL` (aggregate tested, 0/6 survive Holm).
- Issues 2–4 are honest scope caveats already disclosed in the results.json
  `scope_caveat` / `caveat` fields and in the README; they are limitations, not
  defects, and are left as-is (no overclaim results from them).

## Verification (second reviewer)
- Lookahead-clean: K1658.py L337–350 uses explicit `.shift(1)` + a runtime
  `assert X["FOMC_lag1"].equals(...)` alignment guard; bootstrap path L430 also
  lags. `test_K1658.py::test_regression_uses_lagged_predictor_not_contemporaneous`
  independently reconstructs the alignment. 9/9 unit tests pass.
- seed=42 fixed for bootstrap; Holm applied over a pre-declared family of 6.
- No overclaim: verdict/README never claim statement-vs-presser separation;
  Part 2 is descriptive-only; Part 3 explicitly scoped as the COMBINED effect.

## Resulting verdict: PASS
All CONDITIONAL findings that were actual defects (labelling, issues 5–6) are
resolved in the certified bytes; the remainder are disclosed limitations. The
research honesty (an INFEASIBLE core + a clean aggregate NULL) is intact.
