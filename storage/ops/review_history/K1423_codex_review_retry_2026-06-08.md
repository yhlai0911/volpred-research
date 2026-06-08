# K1423 Codex Review Retry — 2026-06-08

**Experiment**: `K1423_ewma_hurst_pilot`  
**Reviewer**: Codex CLI  
**Verdict**: **FAIL**

## Findings

1. **The code does not implement Lo (1991) modified R/S, despite labeling it that way throughout the artifact.**  
   `lo_modified_rs()` in [experiments/K1423_ewma_hurst_pilot/K1423_ewma_hurst_pilot.py](/Users/yhlai0911/Desktop/volpred-research/experiments/K1423_ewma_hurst_pilot/K1423_ewma_hurst_pilot.py:84) computes a classical R/S-style statistic using sample variance or weighted variance, but it does **not** include Lo’s long-run variance adjustment with autocovariance/Newey-West style correction. The function docstring admits this directly at lines 92-93, yet the config still records `"estimator": "Lo (1991) modified R/S"` at [214-219](/Users/yhlai0911/Desktop/volpred-research/experiments/K1423_ewma_hurst_pilot/K1423_ewma_hurst_pilot.py:214), and the README repeatedly calls the baseline “Lo modified R/S” at [31](/Users/yhlai0911/Desktop/volpred-research/experiments/K1423_ewma_hurst_pilot/README.md:31) and [140](/Users/yhlai0911/Desktop/volpred-research/experiments/K1423_ewma_hurst_pilot/README.md:140). That is a source-labeling failure, not a cosmetic nit.

2. **The H-VIX relationship is aligned with same-date VIX, even though the H series is constructed from returns only through `t-1`.**  
   `rolling_hurst()` writes `out.iloc[t] = lo_modified_rs(arr[t-window:t], ...)`, so the H value stamped at index `t` is based on returns ending at `t-1`; see [126-133](/Users/yhlai0911/Desktop/volpred-research/experiments/K1423_ewma_hurst_pilot/K1423_ewma_hurst_pilot.py:126). But both `corr_with_vix()` and `regime_table()` compare that H series to `df["vix"]` on the **same timestamp** at [184-194](/Users/yhlai0911/Desktop/volpred-research/experiments/K1423_ewma_hurst_pilot/K1423_ewma_hurst_pilot.py:184) and [161-180](/Users/yhlai0911/Desktop/volpred-research/experiments/K1423_ewma_hurst_pilot/K1423_ewma_hurst_pilot.py:161). That means the reported “H vs VIX” correlation/regime tables are using one-day-ahead VIX information relative to the information set that generated H. For a descriptive same-day association this may be salvageable if explicitly reframed, but the README currently treats it as a clean empirical finding and even suggests predictive follow-through.

3. **The README selectively highlights the insignificant `λ=0.94` regime test while suppressing that `λ=0.97` and `λ=0.99` are actually significant in `results.json`.**  
   The published README says “EWMA H 不適合 regime classification（χ² insignificant；太 noisy）” and only shows the `λ=0.94` table with `p=0.286` at [95-104](/Users/yhlai0911/Desktop/volpred-research/experiments/K1423_ewma_hurst_pilot/README.md:95). But `K1423_ewma_hurst_pilot_results.json` shows `ewma_lambda_0.97` has `chi2=12.24, p=0.0022` and `ewma_lambda_0.99` has `chi2=56.79, p=4.65e-13`, both strongly significant. That is not a harmless omission: it changes the substantive conclusion from “EWMA regime classification fails” to “the fastest EWMA fails, slower EWMAs do show regime dependence.” The current README conclusion is therefore materially incomplete.

## What Holds

1. **There is no obvious lookahead in the rolling H estimator itself.**  
   The H series at index `t` uses `arr[t-window:t]`, so it excludes return `t` and only uses prior returns; see [131-132](/Users/yhlai0911/Desktop/volpred-research/experiments/K1423_ewma_hurst_pilot/K1423_ewma_hurst_pilot.py:131).

2. **The stored summary statistics and correlations are internally consistent with the saved results artifact.**  
   The reported rolling baseline `mean≈0.504`, `std≈0.030`, and `ρ(H,VIX)≈0.317` match [K1423_ewma_hurst_pilot_results.json](/Users/yhlai0911/Desktop/volpred-research/experiments/K1423_ewma_hurst_pilot/K1423_ewma_hurst_pilot_results.json:1).

3. **The COVID responsiveness case study is directionally supported by the saved dates.**  
   The artifact does show `rolling` never drops below `0.45` in the selected window, while `ewma_094` and `ewma_097` first cross below on `2020-04-07` and `2020-04-13`; see [results json](/Users/yhlai0911/Desktop/volpred-research/experiments/K1423_ewma_hurst_pilot/K1423_ewma_hurst_pilot_results.json:1).

## Conclusion

This pilot should **not** be upgraded from `CONDITIONAL_PASS` to `PASS`. The safer interpretation is:

- the current artifact is a **useful exploratory pilot**,
- but the estimator is mislabeled as Lo modified R/S,
- the VIX association tables are not cleanly aligned to the H information set,
- and the README conclusion about EWMA regime classification is selectively framed.

Recommended disposition:

- keep `K1423` below PASS until the estimator label is corrected or the true Lo modified R/S is implemented;
- recompute all H-VIX correlations/regime tests with explicitly lagged VIX alignment;
- rewrite the README to report all λ results, not just `0.94`.
