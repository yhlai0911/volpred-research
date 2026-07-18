VERDICT: FAIL

## 1. New ES estimator

Checked the derivation and both production functions.

For an equal-weight posterior mixture \(F(y)=M^{-1}\sum_m F_m(y)\), let \(q_\alpha\) solve \(F(q_\alpha)=\alpha\). Then

\[
ES_\alpha
=
\frac{\frac1M\sum_m E_m[Y\,1\{Y>q_\alpha\}]}
     {\frac1M\sum_m P_m(Y>q_\alpha)}.
\]

For a GEV component, with \(t_m(q)=(1+\xi_m(q-\mu_m)/\sigma_m)^{-1/\xi_m}\),

\[
E_m[Y1\{Y>q\}]
=
(\mu_m-\sigma_m/\xi_m)(1-e^{-t_m})
+\frac{\sigma_m}{\xi_m}\gamma(1-\xi_m,t_m),
\]

with the implemented Gumbel limit at \(\xi=0\).

That is exactly what [k1731_models.py](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-bd00f90a-k1731/experiments/k1731/k1731_models.py:94) and [k1731_models.py](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-bd00f90a-k1731/experiments/k1731/k1731_models.py:153) compute. The numerator and denominator use the same posterior draws and the common reported mixture threshold. The main path passes that threshold at [k1731_gevreg_midas_ssvs_returns.py](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-bd00f90a-k1731/experiments/k1731/k1731_gevreg_midas_ssvs_returns.py:227).

The 1,120-case identity error is \(1.07\times10^{-14}\), and the deterministic production-path stress case agrees with Monte Carlo. Judgement: **the rev5 ES estimator is correct**.

## 2. `conclusion_flipped: false`

The narrow ES classification is honest. Rev5 records:

- 95%: 71 exceedances, mean ES 3.1648, residual 0.3386, p = 0.0181.
- 99%: 23 exceedances, mean ES 4.4092, residual 0.4276, p = 0.0876.

These are in the [primary artifact](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-bd00f90a-k1731/experiments/k1731/k1731_gevreg_midas_ssvs_returns_results_corrected_rev5.json:1600). README §3.1 and §3.5 explicitly say that part of the old 95% rejection was estimator artifact, quantify the weakening, and do not conceal the p-value’s roughly 25% relative increase ([README.md](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-bd00f90a-k1731/experiments/k1731/README.md:162), [README.md](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-bd00f90a-k1731/experiments/k1731/README.md:268)).

Judgement: **PASS for the ES-specific `conclusion_flipped` claim**. It does not rescue the broader macro conclusion, which has an independent nested-DM defect below.

## 3. The 99% case

The 99% p-value moved farther from 0.05, but it is based on only 23 exceedances and therefore remains low-power. README calls it a “non-rejection,” not proof of correct ES, and elsewhere states that DQ rejects every model and no VaR is well specified.

I found no absence-of-evidence/evidence-of-absence substitution. Judgement: **wording PASS**, with the existing small-tail-sample limitation.

## 4. Regression gate integrity

The imported allow-list is acceptable for this frozen snapshot:

- `FINALIZE_OWNED_KEYS` contains provenance/status, static audit narrative, finalization metadata, and `mcmc_convergence_assessment` ([k1731_finalize_report.py](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-bd00f90a-k1731/experiments/k1731/k1731_finalize_report.py:28)).
- The only derived narrative block is the MCMC assessment. Its underlying `refits[]` values remain outside the allow-list; only elapsed times are nondeterministic.
- The current comparison reports 3,834 shared leaves, 22 allowed changes, 19 nondeterministic changes, and zero unexpected drift ([k1731_regression_check_results.json](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-bd00f90a-k1731/experiments/k1731/k1731_regression_check_results.json:2)).
- Raw non-timing refit leaves and non-ES OOS leaves are therefore still capable of failing the gate.

Judgement: **PASS for this run**. The finalizer is not an independent trust boundary, but the presently imported keys are provably narrative/status-only and cannot hide changed raw estimates.

## 5. Disclosed false-fail

The explanation is supported. The frozen baseline contains finalized `armA_engine_issues`, `mcmc_convergence_assessment`, `cross_arm_comparison`, and `finalized_by`; raw production does not emit those blocks. Their leaf counts are 34 + 17 + 5 + 1 = 57, exactly the disclosed removed-field failure.

Comparison with the prior committed corrected artifact found only two updated narrative strings and `finalized_utc`; no estimate changed. The repair was stage alignment plus checker changes—the candidate was finalized, the key list was centralized, and list-prefix matching was fixed—not alteration of estimated data ([k1731_armB_esfix.json](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-bd00f90a-k1731/experiments/k1731/k1731_armB_esfix.json:41)).

Judgement: **PASS on “false fail, no data fix.”** Strictly, the bytes do not show a baseline-selection-only fix; they show pipeline-stage/checker correction.

## 6. Provenance invariant

Verified directly in the three JSON files:

- Rev5: `is_primary=true`, `do_not_cite=false` ([rev5 JSON](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-bd00f90a-k1731/experiments/k1731/k1731_gevreg_midas_ssvs_returns_results_corrected_rev5.json:5219)).
- Corrected rev4: `is_primary=false`, `do_not_cite=true`, superseded by rev5 with an ES reason ([corrected JSON](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-bd00f90a-k1731/experiments/k1731/k1731_gevreg_midas_ssvs_returns_results_corrected.json:5236)).
- Original: likewise superseded by rev5, with all three defects named ([original JSON](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-bd00f90a-k1731/experiments/k1731/k1731_gevreg_midas_ssvs_returns_results.json:5183)).

Judgement: **PASS**.

## 7. Earlier-round fixes and rev5 regressions

The substantive earlier fixes remain: IP exclusion, GARCH lag, NFP caveat, per-artifact MCMC statistics, PIP exceptions, arm-A quick-mode caveat, provenance, and corrected ES.

However, stale prose remains:

- §3.7 quotes superseded original-run full-week losses, whereas rev5 reports GARCH 0.13325, SSVS 0.14225, Empirical 0.16559—not 0.1305/0.1433/0.1656.
- §4 says the state lookup resolves to the origin day, but rev5 has `garch_origin_lag_trading_days=1`; the final state used is one trading day before the origin.
- §10 begins “Two Codex review rounds” and then documents four rounds.

Judgement: **FAIL**.

## 8. Whole-README claim–evidence matching

There are two substantive failures.

First, the headline bounded macro null uses raw DM/HAC inference for an explicitly nested comparison. GEV-HAR is constructed by switching off the macro block ([main script](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-bd00f90a-k1731/experiments/k1731/k1731_gevreg_midas_ssvs_returns.py:163)), but the primary comparison is ordinary `dm_with_diagnostics` on unadjusted pinball-loss differences ([main script](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-bd00f90a-k1731/experiments/k1731/k1731_gevreg_midas_ssvs_returns.py:382)). HAC handles serial correlation; it does not remove nested-model estimation bias. The resulting \([-0.74\%,4.41\%]\) interval therefore cannot support the formal “bounded null” in the header or §6 under the standing repository rule.

Second, direct byte mismatches remain:

- README twice says 3,776 leaves, while the current gate says 3,834.
- The self-report nevertheless claims every §3.1/§3.5 number was checked with zero mismatches.
- “Any difference between the two arms is attributable to the target and nothing else” is too broad: the README itself records different macro sets, GARCH information sets, and quick/production modes.
- “Every file below” carries provenance fields is false for `k1731_quickmode_results.json`.
- The synthetic scenarios establish a constructed range, not a universal “worst case.”
- The supposedly fixed seed for `posterior_like` uses Python’s randomized `hash(name)` at [k1731_es_mixture_check.py](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-bd00f90a-k1731/experiments/k1731/k1731_es_mixture_check.py:200). With `PYTHONHASHSEED` 1/2/3, its 95% bias changed to 3.910%, 4.392%, and 3.873%. The exact 3.85–22.77% range is not reproducible from the declared seed.

Judgement: **FAIL**.

## Blocking issues

- [k1731_gevreg_midas_ssvs_returns.py:163](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-bd00f90a-k1731/experiments/k1731/k1731_gevreg_midas_ssvs_returns.py:163), [README.md:3](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-bd00f90a-k1731/experiments/k1731/README.md:3), [README.md:478](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-bd00f90a-k1731/experiments/k1731/README.md:478): the bounded macro null is based on raw DM/HAC inference for the nested SSVS-vs-GEV-HAR comparison. Implement a general-loss recursive-bootstrap/nested-forecast correction for pinball loss and regenerate the bound, or downgrade raw DM to diagnostic-only and retract “bounded null.”

- [README.md:169](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-bd00f90a-k1731/experiments/k1731/README.md:169), [README.md:665](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-bd00f90a-k1731/experiments/k1731/README.md:665), [k1731_armB_esfix.json:168](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-bd00f90a-k1731/experiments/k1731/k1731_armB_esfix.json:168): README says 3,776 leaves while the current result says 3,834; the “zero mismatches” traceability claim is therefore false. Update both occurrences and extend the traceability checker to cover gate/meta numbers.

- [README.md:343](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-bd00f90a-k1731/experiments/k1731/README.md:343): §3.7 cites superseded original-run values. Replace them with rev5’s 0.13325/0.14225/0.16559 values and source the statement solely from rev5.

- [README.md:360](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-bd00f90a-k1731/experiments/k1731/README.md:360): the origin-day state-lookup claim contradicts rev5’s lag-one path. State that the natural lookup resolves to the origin, then rev5 deliberately steps back one trading day.

- [README.md:93](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-bd00f90a-k1731/experiments/k1731/README.md:93): “any difference between arms” exceeds the evidence. Restrict it to week keys, boundaries, origins, filter, and HAR covariate construction; explicitly exclude macro-set, GARCH-lag, and estimation-mode differences.

- [k1731_es_mixture_check.py:200](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-bd00f90a-k1731/experiments/k1731/k1731_es_mixture_check.py:200), [README.md:294](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-bd00f90a-k1731/experiments/k1731/README.md:294): replace `hash(name)` with a fixed per-scenario seed or stable digest, regenerate the proof JSON, and describe 3.85–22.77% as the range of the constructed scenarios—not a worst-case bound.

- [README.md:541](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-bd00f90a-k1731/experiments/k1731/README.md:541), [README.md:614](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-bd00f90a-k1731/experiments/k1731/README.md:614): narrow the provenance sentence to the three production artifacts and correct the review-trail count from two to four.
