---
# K1137 Codex Primary-Path Review

**Reviewer**: Codex (gpt-5.4, codex-cli 0.121.0, ChatGPT account mode)
**Date**: 2026-05-13
**Verdict**: FAIL

## Blocking Issues (HIGH)
- Regime quantile window is off by one extra lag in `build_rolling_vix_regimes()` ([k1137.py:505-531](/Users/yhlai0911/Desktop/volpred-research/experiments/k1137/k1137.py:505)). The code first sets `vix_lag1 = vix_series.shift(1)` at line 510, so `v[i]` already equals `VIX[t-1]`, then computes `past = v[i-window:i]` at line 518, which corresponds to raw `VIX[t-253..t-2]`, not the specified `VIX[t-252..t-1]`. This is not lookahead, but it does mean the experiment did not implement the stated primary-path regime definition, so the regime labels, cell counts, and all downstream DM/BH results are not the intended K1137 design.

## Non-blocking Issues (MEDIUM/LOW)
- The 10% regime-coverage safeguard is documented as an abort condition in the script header and README, but the implementation only emits a warning at [k1137.py:691-695](/Users/yhlai0911/Desktop/volpred-research/experiments/k1137/k1137.py:691) and still proceeds. This did not affect the recorded run because all reported regime shares are comfortably above 10%, but the code path does not enforce the stricter spec it claims.
- Data ingestion depends entirely on `yfinance` at [k1137.py:94](/Users/yhlai0911/Desktop/volpred-research/experiments/k1137/k1137.py:94) and [k1137.py:111-112](/Users/yhlai0911/Desktop/volpred-research/experiments/k1137/k1137.py:111). That is acceptable for this review, but it leaves the experiment exposed to rate limits, vendor revisions, and ETF-only coverage conventions that should be acknowledged when treating the JSON outputs as reproducible research artifacts.

## Verdict Justification
The core anti-lookahead intent is mostly respected elsewhere: HAR uses lagged realized-vol and lagged VIX features ([k1137.py:398-406](/Users/yhlai0911/Desktop/volpred-research/experiments/k1137/k1137.py:398)), the DM-HLN test uses a Newey-West style HAC variance estimator ([k1137.py:460-486](/Users/yhlai0911/Desktop/volpred-research/experiments/k1137/k1137.py:460)), BH-FDR is applied to adjusted p-values before thresholding ([k1137.py:825-853](/Users/yhlai0911/Desktop/volpred-research/experiments/k1137/k1137.py:825)), underpowered regimes are skipped below 30 bars ([k1137.py:762-772](/Users/yhlai0911/Desktop/volpred-research/experiments/k1137/k1137.py:762)), and refits use only pre-`t_abs` data slices ([k1137.py:590-649](/Users/yhlai0911/Desktop/volpred-research/experiments/k1137/k1137.py:590)). However, the regime-construction bug changes the experiment’s defining treatment assignment, so K1137 should not be primary-path closed or propagated to `knowledge.json` until that windowing logic is corrected and the experiment is rerun.
---
