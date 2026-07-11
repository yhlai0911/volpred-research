# K1682 post-run result verification

Date: 2026-07-11
Verdict: **PASS**

The verifier read `k1682_results.json` directly and independently checked the
implementation and cached inputs. It did not rely on an agent summary.

## Numerical checks

- All eight pre-specified cells reproduce the reported baseline loss,
  augmented loss, improvement percentage, HLN-DM direction, BH-FDR q-value,
  and pass flag.
- The aggregate verdict is internally consistent: zero primary passes and one
  positive loss direction imply `NULL_NO_ROBUST_OOS_INCREMENT`.
- OOS counts are 407 for h=1 and 399 for h=5. The latest eligible training row
  satisfies the stated strict condition `j + h < i`.
- All four quantile paths report zero fit failure, zero convergence warning,
  and zero iteration-limit hit.
- Every one of the seven cached CSV files matches the byte count and SHA-256
  recorded in the results JSON.
- A cache-only rerun produced the identical canonical JSON after removing the
  volatile `run_utc` field.

## Interpretation gate

The sole favorable cell is BTC h=1 tail pinball (+0.3734%), but its HLN-DM
t=-0.3063 and BH q=0.8328 do not support incremental predictive content. The
claim therefore remains a scoped empirical null for a lagged daily close-price
dispersion proxy, not a statement about synchronized executable arbitrage.

No blocking or major issue remained after completion metadata was updated.
