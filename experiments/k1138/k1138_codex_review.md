# K1138 Codex Primary-Path Review

**Reviewer**: Codex (gpt-5.4, codex-cli 0.121.0, ChatGPT account mode)
**Date**: 2026-05-13
**Verdict**: FAIL

## Blocking Issues (HIGH)
- `BH-FDR` is not enforced consistently in the asset/model-level conclusion logic, which overstates significance. The 9-cell PASS rule correctly uses adjusted p-values at [experiments/k1138/k1138.py](/Users/yhlai0911/Desktop/volpred-research/experiments/k1138/k1138.py:828) (`is_pass = (c['DM_HLN_t'] > 2.0) and (c['DM_HLN_p_BH'] < 0.05)`), but the later asset/model summaries drop the BH condition entirely at [experiments/k1138/k1138.py](/Users/yhlai0911/Desktop/volpred-research/experiments/k1138/k1138.py:840) and [experiments/k1138/k1138.py](/Users/yhlai0911/Desktop/volpred-research/experiments/k1138/k1138.py:848), using only `max_t > 2.0`. This misclassifies IWM as `PASS` even though [experiments/k1138/k1138_results.json](/Users/yhlai0911/Desktop/volpred-research/experiments/k1138/k1138_results.json:919) shows `DM_HLN_t = 2.0636` but [experiments/k1138/k1138_results.json](/Users/yhlai0911/Desktop/volpred-research/experiments/k1138/k1138_results.json:924) shows `DM_HLN_p_BH = 0.0706`, so the fair-test/BH gate is not met. The same overclaim is repeated in the README at [experiments/k1138/README.md](/Users/yhlai0911/Desktop/volpred-research/experiments/k1138/README.md:95) and [experiments/k1138/README.md](/Users/yhlai0911/Desktop/volpred-research/experiments/k1138/README.md:151).

## Non-blocking Issues (MEDIUM/LOW)
- `README.md` contains an internal contradiction on IWM: it calls IWM a near miss because `p_BH=0.071` at [experiments/k1138/README.md](/Users/yhlai0911/Desktop/volpred-research/experiments/k1138/README.md:87), but later still reports `IWM` as asset-level `PASS` at [experiments/k1138/README.md](/Users/yhlai0911/Desktop/volpred-research/experiments/k1138/README.md:95). This is downstream of the blocking aggregation issue, but the writeup itself is not self-consistent.
- `k1138_results.json` records the methodology OOS string as `2021-01-01 to 2026-04-10` at [experiments/k1138/k1138_results.json](/Users/yhlai0911/Desktop/volpred-research/experiments/k1138/k1138_results.json:24), while the realized OOS start stored per asset is `2021-01-04` at [experiments/k1138/k1138_results.json](/Users/yhlai0911/Desktop/volpred-research/experiments/k1138/k1138_results.json:42). This is minor, but it should be harmonized for reproducibility metadata.

## Verdict Justification
Primary path methodology is mostly sound on the requested checks: HAR and VIX regressors are lagged, the OOS split is chronological, refits use only past data, and DM-HLN is implemented with HAC rather than plain variance. However, the experiment’s asset/model-level inference layer ignores the BH-adjusted significance gate that the 9-cell design itself defines, which materially overstates the equity PASS narrative; that is a blocking methodology issue, so this cannot be used for `knowledge.json` closure yet.
