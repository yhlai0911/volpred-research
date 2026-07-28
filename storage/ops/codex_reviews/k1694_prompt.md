# K1694 primary-path review — ROUND 3 (re-review after the round-2 FAIL was repaired)

You have reviewed this experiment twice, both times **VERDICT: FAIL**:

- round 1 → `storage/ops/codex_reviews/k1694_verdict.md` (prompt: `k1694_prompt_round1.md`)
- round 2 → `storage/ops/codex_reviews/k1694_verdict_round2.md`

**Read the round-2 verdict first** — its four "Required before PASS" items are the primary
checklist for this round. The round-1 verdict is the secondary checklist: confirm nothing
it fixed has regressed. Write this round's verdict to stdout only.

The experiment has been repaired again and **re-run**. Your job is the primary path: does
the code actually estimate what the write-up claims, is each round-2 requirement really met
(not merely relabelled), and is the NULL trustworthy?

## What round 2 required, and what was done — verify each

Round 2 confirmed the estimator repairs were sound and that the NULL does not appear
manufactured, then failed the artifact on four items. Treat every claim below as unproven.

**R2-A — "either build a genuinely ex-ante spec4 ... or remove all predictive/
no-predictability claims".** Both halves were done, minus the impossible one:
- Controls moved from t-1 to **t-2** DCOT aggregates (`nonrep_lag2`, `d_nonrep_lag2`,
  `dlog_oi_lag2`), because a t-1 monthly aggregate is not fully published before month t
  begins. The point-in-time regime label stays at t-1 on the argument that realized vol is
  computed from same-day public closes and carries no publication lag — **check that
  argument**.
- New `build_lagged_frame()` selects spec4's sample from spec4's own regressors, so it is
  no longer conditioned on the contemporaneous `rv_z` it never uses.
- The spec is renamed `spec4_lagged_timing_hardened` and **all** predictive /
  "no predictability" claims are removed; its null now reads "no association survives this
  timing", explicitly conditional on the synthetic availability constant.
- **Check**: is any predictive or ex-ante claim left anywhere — README, results JSON, code
  docstrings? Does t-2 actually clear the publication overlap, or is there a case where a
  t-2 aggregate is still not public before month t? Is the t-1 PIT vol label really free of
  a publication lag?

**R2-B — "replace 不成立 with 未獲支持 everywhere and describe the temporal effective
sample accurately".** Null wording is now "未獲支持 / NOT SUPPORTED" throughout, with an
explicit statement that the estimators cannot establish absence. `sample.
effective_temporal_dof` now reports the FCM z-score ACF (1/3/6/12 = 0.964 / 0.918 / 0.817 /
0.584) and states the effective d.o.f. are below the calendar-month count, without claiming
to quantify how far below.
- **Check**: any remaining place that asserts independence or overstates the null. Is
  "we do not quantify it" an adequate disclosure, or does it need a number?

**R2-C — "guard non-positive/non-finite OI explicitly".** `oi` is masked to NaN unless
finite and strictly positive before `np.log`, and any non-finite `dlog_oi` is cleared
afterwards; `sample.oi_invalid_rows_guarded` records the count (0 on this cache).
- **Check**: is the guard actually on the path that feeds the regression, and is the
  after-the-fact non-finite sweep redundant or load-bearing?

**R2-D — "strengthen completeness checks so they detect interior weekly gaps and
independently truncated RV months".**
- DCOT is now a three-part continuity test: first report within 8 days of month start,
  no gap between consecutive reports over 9 days, last report within 6 days of month end.
  A skipped week at head, middle or tail stretches one gap to ~14 days.
- RV now needs three things: >= 15 trading days, no more than 5 short of the month's
  business-day count, and no more than 3 short of the best-covered commodity that month
  (shared U.S. calendar, so a lone shortfall is that commodity's own truncated download).
- Thresholds were calibrated on the cache: observed maximum interior gap 8 days and head
  gap 7 days (holiday shifts), RV shortfall 0-2 days normally and 10/11/13 when truncated.
- This dropped 2 more rows (3278 -> 3276): 2014-04 and 2016-03 were independently
  truncated RV months.
- **Check**: are those thresholds calibrated or fitted? Could a real gap hide under 9 days?
  Is `MAX_RV_CROSS_SHORTFALL` circular when a whole month is truncated for every commodity
  (the cross-sectional max is then also truncated)? Does the business-day anchor handle
  holiday-heavy months without dropping legitimate ones?

**Working tree**: you are inside a git worktree at the repo root of this checkout. Every
path below is relative to it. The canonical checkout at `~/volpred-research` still holds
the OLD round-1 bytes — do not read it; review the files in *this* tree.

## Files

- `experiments/K1694/K1694.py` — analysis script (the only compute path)
- `experiments/K1694/test_K1694.py` — the author's mechanical gates, one per defect from rounds 1 and 2
- `experiments/K1694/lag_sensitivity.py` — publication-lag robustness check
- `experiments/K1694/K1694_results.json` — main result
- `experiments/K1694/reproduce_spec.json` — run-time provenance spec
- `experiments/K1694/K1694_lag_sensitivity.json` — lag grid result
- `experiments/K1694/README.md` — status and the defect-by-defect repair table
- `experiments/K1694/data/*.csv` — cached inputs (FCM monthly, DCOT weekly, RV monthly)

## The round-1 repairs, unchanged since round 2 — confirm no regression

You already verified these in round 2 ("The main estimator repairs are sound"). Spot-check
that they still hold after this round's edits rather than re-deriving them.

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
   completeness rule. **Its content was replaced this round — judge the current rule under
   R2-D above, not this bullet.** Unchanged from round 2: DCOT-incomplete rows are dropped
   entirely; RV-incomplete months keep their DCOT row but have `rv` masked to NaN; an
   adjacency check voids any first difference whose previous retained row is not the
   immediately preceding calendar month.
   **Check**: does masking `rv` (rather than dropping the row) change the within-commodity
   moments in a way that biases the regime labels? Is the adjacency guard complete — is
   there any difference or lag that escapes it, including the new t-2 lags?

5. **Methodology description vs code.**
   (a) `_acf_bandwidth()` is gone; `_hac_bandwidth_rule(nmonths)` returns
   `max(ceil(T^(1/3)), 4)` and the docstring/results say explicitly it is a fixed rule,
   NOT ACF-derived. A Driscoll-Kraay bandwidth grid 1..24 is a recorded result
   (`dk_bandwidth_sensitivity_spec1`).
   (b) The docstring's promised fully-lagged spec exists; **its timing and sample were
   rebuilt this round — judge it under R2-A above.** The FCM report is as-of merged on the
   outcome month's start; the regime label uses point-in-time expanding moments at t-1.
   **Check**: the expanding moments include month t itself when labelling month t — is
   that legitimate given the label is then lagged one month? Is `PIT_MIN_MONTHS = 24`
   doing anything suspicious to the sample (n 3276 -> 2749)?

6. **Results JSON overstatement.** `bootstrap_interaction_spec1` and
   `primary_interaction.bootstrap_ci95` are removed; CIs are now under explicit names.
   `panel_span` is complete-months-only and `sample.completeness` discloses the rule and
   the excluded months. `claim_type: ex_post_association` plus a `claim_language_rule`
   forbid predictive/causal/known-before-outcome language for spec1-3. `limitations` now
   lists synthetic publication dates, the within-month timing overlap (disclosed as
   affecting 3276/3276 estimation rows), full-sample regime labels, and the IID
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

## Reported result (re-run, 2026-07-29, round-3 artifacts)

- Verdict: **NULL**, worded as NOT SUPPORTED, scoped to the negative binary high-vol
  crowding-out hypothesis
- Sample: 3276 rows, 22 commodities, 149 calendar months, 2014-02..2026-06 (complete
  months only); spec4 has its own 2749-row sample
- spec1 `fcm_x_highvol`: coef +3.0553e-04, t_DK +1.51, t_cluster_month +1.55, p_DK 0.130
- spec2 `fcm_x_rvz`: coef +2.8750e-04, t_DK +2.54, t_cluster_month +2.56 (POSITIVE, p 0.011)
- spec3 `conc4_x_highvol`: coef -1.9119e-04, t_DK -0.76
- spec4 `fcm_pre_x_highvol_lag`: coef +6.6741e-05, t_DK +0.27, t_cluster +0.34, n 2749
- Stationary block bootstrap (mean block 6 months, 2000 reps): 95% CI
  [-7.418e-05, 7.684e-04], p 0.126
- IID month-cluster bootstrap (2000 reps): 95% CI [-7.458e-05, 7.014e-04], p 0.126
- DK bandwidth 1..24: |t| in [1.51, 1.64], none reaches 1.96
- Aggregate time-series `hhi_x_volfrac`: t 0.34, p 0.733 (HAC lag 6, resid acf1 -0.039)
- Lag grid 30/45/60/75/90d: t_DK in [1.24, 1.51], none reaches 1.96
- `test_K1694.py`: 31 mechanical gates, all passing

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
