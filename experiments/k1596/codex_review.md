# Codex Review — K1596 Multiplicative Volatility Factor-lite

verdict: CONDITIONAL_PASS

## Findings

| Severity | Location | Issue | Fix / Status |
|---|---|---|---|
| MED | `k1596.py` | MVF paper uses high-frequency stock realized variances; K1596 uses daily ETF squared-return proxies. | Scope is explicitly disclosed; do not publish as a direct replication. |
| LOW | `k1596.py` | `MVF_LogARExposure` is unstable and performs badly for several assets. | This is reported as evidence against the lite design, not hidden or tuned away. |
| LOW | `k1596.py` | VaR/ES adequacy is not tested. | Conclusion is limited to point volatility QLIKE. |

## Checks

- Data provenance: uses frozen local `experiments/k1552/data/prices.parquet`; no live download.
- Lookahead control: common-factor HAR features use shifted values; static exposure is rolling 252-day ratio shifted to `t-1`; log-AR exposure uses lagged ratio features; GJR recursion forecasts date `t` from `return_{t-1}`.
- Metric orientation: QLIKE uses canonical `actual / predicted - log(actual / predicted) - 1` via `volpred.stats.model_evaluation.qlike_pointwise`.
- Inference: per-asset DM tests are primary; Holm adjustment is applied across all per-asset MVF-vs-baseline tests. Pooled asset-day DM is diagnostic only.
- Artifact completeness: script, JSON, CSV forecasts, exposure summary, three figures, and README are present.

## Result Integrity

Core JSON checks:

- `verdict = NULL_OR_NEGATIVE`
- `mvf_best_mean_qlike_assets = 0`
- `mvf_strict_holm_wins_vs_gjr = 0`
- `mvf_strict_holm_losses = 66`
- `oos_rows = 31608`, exactly 2,634 rows per asset

The conclusion is appropriately conservative: K1596 rejects this local daily-ETF MVF-lite implementation, not the full high-frequency MVF model.

