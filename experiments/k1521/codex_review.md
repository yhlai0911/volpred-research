# Codex Source Review — K1521

- Review date: 2026-06-17
- Code reviewed: `experiments/k1521/k1521.py`
- Scientific verdict: `NULL_INSUFFICIENT_DATA`
- Code-integrity verdict: `PASS_WITH_NULL_RESULT`

## Findings

No blocking implementation defect found.

## Timing / Lookahead

PASS. The script computes intraday `RV_t` and `RK_t` from local 5-minute bars at date `t`, then defines the target as average `RV_{t+1}` through `RV_{t+5}`. Expanding OOS forecasts fit on `clean.iloc[:i]` and predict `clean.iloc[[i]]`, so forecast-row target information is not in the fitted sample.

The task's standard trading-rule `signal.shift(1)` convention is not directly applicable because this is a forecast experiment, not a same-day strategy. The equivalent protection is the target shift and strict expanding split.

## DM / Harvey

PASS. QLIKE is computed pointwise with `volpred.stats.model_evaluation.qlike_pointwise`; DM uses `dm_test(..., h=5)`. The results JSON reports Harvey-style `|DM t| > 3` but the experiment verdict refuses PASS because OOS sample sizes are far below 252.

## Claim-Evidence Match

PASS. The README numbers match `k1521_results.json`:

- SPY: OOS `n=51`, full-sample QLIKE improvement `-8.70%`, DM `t=+0.295`.
- 0050.TW: OOS `n=38`, full-sample QLIKE improvement `-0.63%`, DM `t=+0.142`.
- SPY high-lagged-RV bucket: `n=25`, improvement `+29.90%`, DM `t=-3.396`; explicitly labeled suggestive and too small.

## Overclaim Check

PASS. The experiment does not claim that RK works. It states that the available local intraday panel is insufficient and that the only positive sub-bucket is hypothesis-generating. The `0050.TW` proxy limitation is explicit; the result does not pretend to be a true TAIEX 5-minute study.

## Residual Risks

- The local 5-minute CSVs are yfinance-style snapshots, not exchange-certified tick data.
- The OOS sample is too short for stable multi-regime inference.
- The model omits realized skewness/jumps because adding more predictors would be unjustified in this sample.

Conclusion: K1521 can be used as a reproducible pipeline prototype and backlog closure, but not as a publication-grade evidence item until a multi-year intraday panel is available.
