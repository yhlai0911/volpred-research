# K1566 Codex Source Review

Review date: 2026-06-29  
Artifact verdict: `CONDITIONAL_PASS`  
Research verdict: `WEAK_RAW_ONLY` / corrected-primary NULL

## Scope

Reviewed:

- `experiments/k1566/k1566.py`
- `experiments/k1566/k1566_results.json`
- `experiments/k1566/README.md`

## Findings

- A1 lookahead lag: PASS. Tested signals are explicitly lagged with `df[f"{sig}_lag1"] = df[sig].shift(1)` in `k1566.py:196-199`.
- A2 forward target: PASS. Forward RV / cumulative return targets are built only from `ret.shift(-i)` for `i=1..H`, so row `t` uses `[t+1, t+H]` in `k1566.py:205-210`.
- A3 signal construction: PASS. Shock baselines use rolling mean/std shifted once, so same-day shock is scored versus history ending at `t-1` in `k1566.py:160-165`.
- A4 current-day bars: PASS after remediation. The merged panel is cut at `LAST_COMPLETE_UTC_DATE` to avoid incomplete current-day crypto bars in `k1566.py:48-50` and `k1566.py:184-185`.
- B1 HAC: PASS. HAC maxlags equals forecast horizon in `k1566.py:261-267`.
- B2 Spearman CI: PASS. Moving-block bootstrap uses `block=H`, `B=1000`, fixed seed in `k1566.py:279-308`.
- B3 AUC CI: PASS. AUC uses the Mann-Whitney rank formulation and Hanley-McNeil SE in `k1566.py:311-331`.
- C1 multiple testing: PASS. Primary family is 12 HAC tests, with Bonferroni and Holm-Bonferroni in `k1566.py:335-363`; no survivor in `k1566_results.json`.
- D1 overclaim control: PASS. README and results identify Etherscan average gas price as a proxy, not true priority-fee / mempool data.

## Caveat

This is a reduced-form predictive screen, not a full OOS forecasting-model comparison. It does not run expanding-window QLIKE/DM against a price-only HAR or AR baseline. Therefore the artifact can be accepted as a screened experiment, but the conclusion must remain weak/null and non-trading.

## Verification

- `uv run python -m py_compile experiments/k1566/k1566.py`
- `uv run python experiments/k1566/k1566.py`
- `jq '{sample, multiple_testing, verdict_assessment}' experiments/k1566/k1566_results.json`

No blocking source-code-level issue remains for the stated weak/null claim.
