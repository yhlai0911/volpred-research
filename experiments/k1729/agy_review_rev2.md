# Independent Adversarial Audit Report: K1729 Rev2

**Experiment Title**: K1729: Self-owned TAIFEX tick (5-min realized variance) beats daily-only information for next-day TX day-session realized variance forecasting
**Auditor**: Antigravity (Independent Adversarial Auditor)
**Date**: 2026-07-21

This review evaluates the volatility-forecasting experiment K1729 rev2 (located at [README.md](file:///Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-30aeb902-taifexrv/experiments/k1729/README.md), [k1729.py](file:///Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-30aeb902-taifexrv/experiments/k1729/k1729.py)) and addresses two specific questions concerning target-side lookahead repair (Rule E) and the nested vs. non-nested model classification.

---

## Q1. Is Rule E Fitted to the Data?

### 1. Verification of Selection Rules
We implemented both roll conventions independently on the canonical data [taifex_5min_rv.csv](file:///Users/yhlai0911/volpred-research/data/intraday/taifex_5min_rv.csv) over the whole file (3,550 trading days) and the out-of-sample (OOS) window (2,550 trading days, starting from row index 1,000, i.e., `date >= 2016-01-20`), using `date <= 2026-07-16` as the cutoff:

*   **Rule E (Pure / Path-Independent)**:
    *   **Whole-File Agreement**: 3,512 / 3,550 (98.93%)
    *   **OOS Agreement**: 2,545 / 2,550 (99.80%)
    *   **OOS Disagreement Dates (5 days)**: `2016-03-16`, `2016-05-18`, `2016-08-17`, `2017-01-18`, `2017-02-15`.
    *   **In-Sample Disagreement Dates (33 days)**: `2012-02-15`, `2012-03-21`, `2012-05-16`, `2012-07-18`, `2012-09-19`, `2012-10-17`, `2012-11-21`, `2012-12-19`, `2013-01-16`, `2013-02-20`, `2013-03-20`, `2013-04-17`, `2013-05-15`, `2013-07-17`, `2013-08-22`, `2013-09-18`, `2013-10-16`, `2013-11-20`, `2013-12-18`, `2014-01-15`, `2014-02-19`, `2014-03-19`, `2014-04-16`, `2014-06-18`, `2014-09-17`, `2014-10-15`, `2014-11-19`, `2014-12-17`, `2015-01-21`, `2015-02-24`, `2015-03-18`, `2015-04-15`, `2015-06-17`.

*   **Nearest Contract Convention** (choose nearest contract whose settlement date is $\geq$ current date):
    *   **Whole-File Agreement**: 3,511 / 3,550 (98.90%)
    *   **OOS Agreement**: 2,545 / 2,550 (99.80%)
    *   **OOS Disagreement Dates (5 days)**: `2016-03-16`, `2016-05-18`, `2016-08-17`, `2017-01-18`, `2017-02-15`.
    *   **In-Sample Disagreement Dates (34 days)**: Same 33 days as Rule E plus `2012-01-02`.

### 2. Disagreements Between Conventions
*   **OOS Window**: The two conventions agree with each other on **every single row** (0 disagreements).
*   **Whole File**: The two conventions disagree with each other on **exactly one date**: `2012-01-02` (the first row of the dataset).
*   **Root Cause of Boundary Disagreement**: Because the dataset begins on `2012-01-02`, there is no historical calendar data before this date. As a result, the computed settlement date for the `201112` contract gets mapped to `2012-01-02` (since it is the first available trading day $\geq$ the actual settlement date of `2011-12-21`), making the Nearest Contract rule think the `201112` contract has not yet passed. With complete historical trading calendar data, the two rules would align perfectly. Therefore, they are logically equivalent.

### 3. Assessment of Fit
The claim that "another equally natural convention... selects the same contract on every row of this sample, so no choice between conventions was made against the data" is **fully verified and true** (100% agreement over the OOS window, and $99.97\%$ agreement overall, with the lone boundary mismatch explained by data availability limits). There is no evidence of reverse-engineering or post-hoc parameter tuning to favor Rule E over Nearest Contract.

### 4. Alternative Conventions
We tested a third natural roll convention—**Calendar Month Roll** (roll to month $M$ on the first trading day of calendar month $M$). This convention achieves only **59.22% agreement** (1510 / 2550) over the OOS window. 

This confirms that choosing a roll rule tied to contract expiration (such as Rule E or Nearest Contract) is mathematically necessary to capture the contract held by the market's primary liquidity. However, because both natural expiration-based conventions match identically on all OOS rows, the pre-specification of Rule E is sound and is not fitted to the data.

---

## Q2. Are the Two Models Nested or Non-Nested?

### 1. Parameter Restrictability
Two models are nested if one is a parameter-restricted special case of the other. In [k1729.py](file:///Users/yhlai0911/volpred-research/experiments/k1729/k1729.py), the models are formulated as:
$$\text{HAR-RV5} : y_t \sim \beta_0 + \beta_d \text{RV5}_{t-1} + \beta_w \overline{\text{RV5}}_{t-5..t-1} + \beta_m \overline{\text{RV5}}_{t-22..t-1}$$
$$\text{HAR-DAILY} : y_t \sim \alpha_0 + \alpha_d r^2_{t-1} + \alpha_w \overline{r^2}_{t-5..t-1} + \alpha_m \overline{r^2}_{t-22..t-1}$$

The regressor sets for the two models are **completely disjoint**:
*   $\text{RV5}$ is built from 5-minute intraday realized variance.
*   $r^2$ is built from daily open-to-close squared returns.

Neither model's regressors form a subset of the other's, and neither can be obtained by applying parametric constraints (e.g., setting coefficients to 0 or equal) to the other. They are distinct regression models representing disjoint information sets.

### 2. Degeneracy of the Loss Differential Variance
The standard argument for why the raw Diebold-Mariano (1995) test fails under a nested null is that under the null hypothesis, the parameters on the additional (unrestricted) variables are zero. Consequently, the two models' forecasts coincide exactly in population, causing the forecast error difference (and thus the loss differential $d_t$) to collapse to an identical zero on every row. The variance of the loss differential degenerates ($\sigma^2(d_t) \to 0$), invalidating the standard DM test statistic because the denominator converges to zero.

This degeneracy is impossible under the K1729 setup:
1.  Because the models use disjoint regressors, no parameter restriction makes their forecasts coincide under the null.
2.  The results from the results ledger (`nondegeneracy` metrics) empirically verify this non-degeneracy:
    *   **Forecast correlation**: 0.778 (Target A) and 0.791 (Target B), which is far from 1.0.
    *   **Mean absolute relative gap**: 20.6% (Target A) and 17.7% (Target B).
    *   **Loss differential standard deviation**: 0.364 (Target A) and 0.713 (Target B), which is strictly positive and bounded away from zero.
    *   **Fraction of exact zero loss differences**: 0.0%.

### 3. Appropriate Test Choice
Because the models are non-nested and their forecasts do not coincide under the null, the standard Diebold-Mariano test (with Newey-West HAC adjustment) is asymptotically valid. Clark-West (2007) is specifically designed to adjust for the parameter estimation noise of nested alternatives under the null and is **not required or appropriate** here. The routing of this experiment through the allowlist in [nested_dm_misuse_baseline.json](file:///Users/yhlai0911/volpred-research/storage/ops/nested_dm_misuse_baseline.json) under `reviewed_nonnested` (adjudicated at 2026-07-21, as detailed in [nested_dm_fp_narrowing_audit.md](file:///Users/yhlai0911/volpred-research/docs/governance/2026-07/nested_dm_fp_narrowing_audit.md)) is mathematically correct.

---

## Confirmation pass on final bytes (2026-07-21)

We have verified the fixes applied to the experiment K1729 rev2 dataset and code:

### Verification of FIX 1 (Convention-Agreement Wording)
We confirmed that the updated convention-agreement wording in section 3 of [README.md](file:///Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-30aeb902-taifexrv/experiments/k1729/README.md), the module docstring of [k1729.py](file:///Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-30aeb902-taifexrv/experiments/k1729/k1729.py), and the field `target_contract_selection_audit.rule_is_a_convention_not_a_fit` in [k1729_results.json](file:///Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-30aeb902-taifexrv/experiments/k1729/k1729_results.json) matches the empirical measurements exactly:
- The two ex-ante conventions (Rule E and Nearest Contract) agree with each other on every OOS row (100% agreement, 0 disagreements).
- The sole difference over the whole file occurs on row 0 (`2012-01-02`), which is a dataset-boundary artifact in the warmup period and is never scored.
- A third non-expiry-tied convention (calendar-month roll) achieves only 59.22% agreement on the OOS window.

The restatements are correct, and there is no overstatement or misattribution of these findings.

### Verification of FIX 2 (Machine-Readable Verdict Derivation)
We audited the verdict derivation logic in [k1729.py](file:///Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-30aeb902-taifexrv/experiments/k1729/k1729.py) and [k1729_results.json](file:///Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-30aeb902-taifexrv/experiments/k1729/k1729_results.json):
- The `verdict` field in [k1729_results.json](file:///Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-30aeb902-taifexrv/experiments/k1729/k1729_results.json) is derived using a stricter rule that checks both proxy targets under the full ledger (`full_a` and `full_b`) and the ex-ante contract ledger (`exante_a` and `exante_b`).
- The logic requires all four component verdicts to agree (i.e. `agree` and `exante_concurs` must both be True) for a robust win to be declared. Otherwise, it degrades to `PROXY_DEPENDENT_INCONCLUSIVE` or suffixes `_EXANTE_LEDGER_DISAGREES`.
- In the current results, all four components are indeed `HAR_RV5_WINS`, meaning the stricter rule is fully satisfied and binds.
- The stated `decision_rule` text in the JSON matches the python logic exactly.

The fixes are correct and introduce no regressions or new overclaims.

FINAL_VERDICT: PASS
