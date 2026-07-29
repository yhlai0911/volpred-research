# K1694 primary-path review — ROUND 2 (re-review after the round-1 FAIL was repaired)

You reviewed this experiment on 2026-07-29 and returned **VERDICT: FAIL**. Your round-1
verdict is at `storage/ops/codex_reviews/k1694_verdict.md` and the round-1 commissioning
prompt at `storage/ops/codex_reviews/k1694_prompt_round1.md`. Read the verdict first; it is
the checklist this round must be judged against. Write this round's verdict to stdout only
(the harness captures it to `k1694_verdict_round2.md`).

The experiment has been repaired and **re-run**. Your job is the primary path again: does
the code actually estimate what the write-up claims, is each round-1 defect really fixed
(not merely relabelled), and is the NULL trustworthy?

**Working tree**: you are inside a git worktree at the repo root of this checkout. Every
path below is relative to it. The canonical checkout at `~/volpred-research` still holds
the OLD round-1 bytes — do not read it; review the files in *this* tree.

## Files

- `experiments/K1694/K1694.py` — analysis script (the only compute path)
- `experiments/K1694/test_K1694.py` — the author's mechanical gates for the 8 defects
- `experiments/K1694/lag_sensitivity.py` — publication-lag robustness check
- `experiments/K1694/K1694_results.json` — main result
- `experiments/K1694/reproduce_spec.json` — run-time provenance spec
- `experiments/K1694/K1694_lag_sensitivity.json` — lag grid result
- `experiments/K1694/README.md` — status and the defect-by-defect repair table
- `experiments/K1694/data/*.csv` — cached inputs (FCM monthly, DCOT weekly, RV monthly)

## What was changed this round, and where to look

Each item is claimed to close one of your round-1 findings. Treat every claim as unproven.

1. **Bootstrap / spec1 mismatch (your blocking defect).**
   `build_spec_frame()` (K1694.py) is now the single owner of the estimation sample, and
   `SPEC1_RHS` is a module constant. `panel_regression()` and `bootstrap_spec1()` both
   consume them, so the time trend `t` and the row set are shared by construction rather
   than by two hand-maintained lists.
   The bootstrap no longer calls `PanelOLS` per replicate; it uses `_within_ols()`, a
   numpy entity-demeaned OLS, and asserts at run time that it reproduces the PanelOLS
   spec1 coefficient before drawing any replicate
   (`bootstrap_spec1.*.point_estimator_identity_check`).
   **Check**: is the within estimator really the same estimator PanelOLS fits (entity
   effects, no constant, no time effects)? Does the identity assertion actually run on the
   real sample, and would it fire if the two diverged? Is the resampled design matrix —
   including `t` — the one spec1 reports?

2. **`highvol` mislabelled 0 when RV is missing.**
   Now `s.gt(s.median()).astype(float).where(s.notna())`. Same treatment for the new
   point-in-time label.
   **Check**: any remaining path where a missing input silently becomes a valid regressor
   value (including `rv_z`, `conc4_z`, `hhi_seg_pit_z`, and the `dlog_oi` log of a
   non-positive OI).

3. **Bootstrap naming.** Both were implemented and both are named for what they resample:
   `stationary_block_by_month` (Politis-Romano, geometric block length, circular) is the
   headline; `month_cluster_iid` is kept as a labelled contrast that explicitly says it is
   NOT a block bootstrap.
   **Check**: is `_month_blocks_stationary()` a correct stationary bootstrap (mean block
   length, wrap-around, no systematic edge bias)? Is the mean block length defensible for
   T = 149 months given the FCM series' autocorrelation? Does the headline CI use it?

4. **Partial months.** `monthly_coverage()` is the single owner of a date-free
   completeness rule: a DCOT month needs >= 4 weekly reports AND its last as-of date
   within 6 days of month end; an RV month needs >= 15 trading days. DCOT-incomplete rows
   are dropped; RV-incomplete months keep their DCOT row but have `rv` masked to NaN. An
   adjacency check voids any first difference whose previous retained row is not the
   immediately preceding calendar month.
   **Check**: is the rule genuinely reproducible and free of hidden date knowledge? Does
   it drop only what it should (2026-07 and 2006-06 here) and would it generalise? Does
   masking `rv` (rather than dropping the row) change the within-commodity moments in a
   way that biases the regime labels? Is the adjacency guard complete — is there any
   difference or lag that escapes it?

5. **Methodology description vs code.**
   (a) `_acf_bandwidth()` is gone; `_hac_bandwidth_rule(nmonths)` returns
   `max(ceil(T^(1/3)), 4)` and the docstring/results say explicitly it is a fixed rule,
   NOT ACF-derived. A Driscoll-Kraay bandwidth grid 1..24 is now a recorded result
   (`dk_bandwidth_sensitivity_spec1`).
   (b) The docstring's promised fully-lagged predictive spec now exists as
   `spec4_predictive_fully_lagged`: the FCM report is as-of merged on the outcome month's
   **start**, the volatility regime label uses point-in-time expanding moments at t-1, and
   every control is a t-1 quantity.
   **Check**: is spec4 actually free of the look-ahead you flagged? The expanding
   moments include month t itself when labelling month t — is that legitimate given the
   label is then lagged one month? Does the month-start as-of merge really guarantee the
   signal predates the whole outcome window? Is `PIT_MIN_MONTHS = 24` doing anything
   suspicious to the sample (n falls 3278 -> 2750)?

6. **Results JSON overstatement.** `bootstrap_interaction_spec1` and
   `primary_interaction.bootstrap_ci95` are removed; CIs are now under explicit names.
   `panel_span` is complete-months-only and `sample.completeness` discloses the rule and
   the excluded months. `claim_type: ex_post_association` plus a `claim_language_rule`
   forbid predictive/causal/known-before-outcome language for spec1-3. `limitations` now
   lists synthetic publication dates, the within-month timing overlap (disclosed as
   affecting 3278/3278 estimation rows), full-sample regime labels, and the IID
   bootstrap's failure to preserve serial correlation.
   **Check**: read `README.md` as the surface through which an overclaim reaches a human.
   Does anything in the README or the JSON still assert more than the code estimates?

7. **NULL scope.** `verdict_scope` restricts NULL to the negative, binary high-vol
   hypothesis and states that the continuous `fcm_x_rvz` interaction is positive and
   significant; `secondary_findings` carries its coefficient and t-stats.
   **Check**: is the scoping accurate and is it stated everywhere the verdict is stated?

8. **Provenance.** `reproduce_spec.json` is now produced at run time by
   `volpred.research.reproduce_spec.finalize_experiment()`, in the same `trace_file()`
   call as the results.
   **Check**: do `reproduce_spec.entrypoint.sha256`, `results.code_trace.sha256` and the
   sha of `K1694.py` on disk all agree? Does `canonical_result_identity` match the result
   bytes? Could this spec have been written after the fact?

## Reported result (re-run, 2026-07-29)

- Verdict: **NULL**, scoped to the negative binary high-vol crowding-out hypothesis
- Sample: 3278 rows, 22 commodities, 149 months, 2014-02..2026-06 (complete months only)
- spec1 `fcm_x_highvol`: coef +3.1575e-04, t_DK +1.56, t_cluster_month +1.60
- spec2 `fcm_x_rvz`: coef +2.9624e-04, t_DK +2.59, t_cluster_month +2.61 (POSITIVE)
- spec3 `conc4_x_highvol`: coef -1.7016e-04, t_DK -0.67
- spec4 `fcm_pre_x_highvol_lag` (predictive): coef +4.4153e-05, t_DK +0.18, n 2750
- Stationary block bootstrap (mean block 6 months, 2000 reps): point 3.1575e-04,
  95% CI [-7.076e-05, 7.793e-04], p 0.117
- IID month-cluster bootstrap (2000 reps): 95% CI [-6.773e-05, 7.106e-04], p 0.119
- DK bandwidth 1..24: |t| in [1.56, 1.71], none reaches 1.96
- Aggregate time-series `hhi_x_volfrac`: t 0.41 (HAC lag 6, resid acf1 -0.045)
- Lag grid 30/45/60/75/90d: t_DK in [1.28, 1.56], none reaches 1.96

## Questions that carry over from round 1 and are NOT closed by the above

- **Is the NULL manufactured?** The point estimate is *positive* while the hypothesis
  predicts negative, and the continuous analogue is positive and significant. Is that a
  coherent picture, or a symptom of a construction error (regressor scaling, the
  `nonrep_lag` / `d_nonrep_lag` dynamic-panel Nickell bias with entity effects, the
  common-factor structure of FCM HHI, `dlog_oi` being a bad control)? Note the author did
  NOT address dynamic-panel bias — judge whether it matters for the interaction term.
- **Effective degrees of freedom.** FCM HHI is one system-wide monthly series: 149 months,
  not 3278 independent observations. Are DK + month clustering + the block bootstrap
  enough, and is the limitation stated at the right strength?
- **Publication dates are still synthetic.** Nothing this round verified a real CFTC
  release date. Is the disclosure adequate, or should that block any claim at all?

## Verdict contract

Write your review to stdout. End it with a line of exactly this form:

`VERDICT: PASS` — the NULL is trustworthy and may be written to knowledge.json, or
`VERDICT: FAIL` — with the specific defect(s) that must be fixed first.

If you PASS, the machine-readable certificate is generated by the repo's own gate, not by
hand:

```
uv run python scripts/experiment_gates.py verdict-template \
  --path experiments/K1694 --out experiments/K1694/review_verdict.json
```

Do not restate its schema and do not hand-write that file; only `verdict`, `reviewer`,
`reviewed_at`, `reviewed_commit`, `review_artifact` and `blocking_defects` are filled in.
(You are read-only here; the author runs the command and fills those fields from your
verdict. Say clearly in your review which verdict you are certifying.)

Be adversarial. A NULL that comes from a broken estimator is worse than no result, because
it closes a research direction that was never actually tested. A repaired experiment that
merely renames its defects is worse still, because it also spends a review round.
