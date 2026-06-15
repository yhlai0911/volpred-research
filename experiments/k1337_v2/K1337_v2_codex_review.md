# K1337-v2 Codex Review

**Date:** 2026-06-15
**Reviewer:** Codex
**Review verdict:** PASS for implementation integrity
**Research verdict:** NULL

## Scope

This review checks whether K1337-v2 correctly fixes the K1337 v1
forward-label lookahead and whether the NULL conclusion is supported by the
new results.

## Findings

1. **Lookahead fix: PASS**
   - The script documents the required fix directly: a training row is allowed
     only when `target_end_pos(j) < forecast_pos(i)` (`K1337_v2.py:3-6`).
   - Forward targets use returns strictly after the forecast date,
     `i+1 ... i+H`, and record `target_end_pos=i+H`
     (`K1337_v2.py:198-213`).
   - The expanding OLS implementation trains only on
     `df["target_end_pos"] < forecast_pos` (`K1337_v2.py:229-285`,
     especially `K1337_v2.py:255-265`). This is the required `j+H<i`
     cutoff and fixes the v1 `df.iloc[:i]` bug.

2. **Signal and regime lag: PASS**
   - HAR features are shifted by one day before modeling
     (`K1337_v2.py:216-226`).
   - The augmented model uses `feats[sig_col].shift(1)` as `dslope_lag1`
     (`K1337_v2.py:428-436`).
   - Regime summaries also start from `feats[sig_col].shift(1)`
     (`K1337_v2.py:377-385`).
   - Rolling regime quantile thresholds exclude the current row via
     `vals[i-window:i]` before classifying the current lagged signal
     (`K1337_v2.py:352-374`).

3. **Symmetric model-class baseline: PASS**
   - Both baseline and augmented forecasts call the same
     `expanding_log_ols_forecast()` engine (`K1337_v2.py:440-443`).
   - Both models forecast log variance and are clipped to the same annualized
     variance range (`K1337_v2.py:261-273`).
   - The only model difference is whether `dslope_lag1` is included
     (`K1337_v2.py:440-443`), satisfying the task requirement.

4. **Seed and bootstrap: PASS**
   - Global seed is fixed at `SEED = 42` (`K1337_v2.py:34-35`).
   - Stationary block bootstrap uses `np.random.default_rng(seed)`, 1000 reps,
     and geometric blocks (`K1337_v2.py:317-349`).
   - Each spec uses deterministic seed offsets from 42 (`K1337_v2.py:484-489`).

5. **DM-HAC and overlapping horizons: PASS**
   - DM uses a Newey-West-style HAC variance estimator over the loss
     difference (`K1337_v2.py:295-314`).
   - The call uses `lag=max(H-1,1)`, which is the mechanical overlap length for
     H-day forward variance targets (`K1337_v2.py:476-484`).

6. **Verdict integrity: PASS**
   - PASS requires `dm_t < -3`, bootstrap CI upper below zero, and positive
     QLIKE improvement (`K1337_v2.py:638-645`).
   - CONDITIONAL_PASS requires suggestive negative DM t and bootstrap support
     (`K1337_v2.py:646-653`).
   - The results have 0 PASS specs, 0 CONDITIONAL specs, 1/18 positive
     improvement specs, and the only positive-improvement cell is tiny
     (+0.052%, DM t=-0.218, bootstrap CI crosses zero). The NULL verdict in
     `K1337_v2_results.json` is therefore accurate.

## Residual Caveats

- This is daily close-to-close squared-return variance, not intraday realized
  variance.
- Yahoo yield index data are cached for reproducibility but are still a public
  proxy for the Treasury curve, not a full SOFR/OIS curve.
- The result rejects this linear lagged-dV/dt augmentation, not every possible
  nonlinear macro-rate interaction.

## Conclusion

K1337-v2 fixes the K1337 v1 lookahead issue and fairly compares the augmented
model against a same-class log-HAR baseline. The corrected evidence supports a
NULL conclusion: yield-curve steepening-rate dV/dt does not add robust
out-of-sample SPY forward variance forecasting power in this design.
