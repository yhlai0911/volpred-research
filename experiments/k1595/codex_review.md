# Codex Review — K1595 Multi-Transformer-lite Volatility Forecast

verdict: CONDITIONAL_PASS

## Findings

| Severity | Location | Issue | Fix / Status |
|---|---|---|---|
| LOW | `k1595.py` | This is a lite pooled Transformer ensemble, not the full Multi-Transformer-GARCH / MTL-GARCH architecture from the cited literature. | Scope is disclosed in results and README; do not publish as a direct replication. |
| LOW | `k1595.py` | Neural models are trained with a fixed pre-OOS train/validation split, while GJR is annual-refit. | Acceptable as an operational benchmark, but architecture-only claims should not be made. |
| LOW | `k1595.py` | VaR/ES backtesting is not included. | Conclusion is limited to point volatility QLIKE, not risk-measure adequacy. |

## Checks

- Data provenance: uses frozen local `experiments/k1552/data/prices.parquet`; no live download.
- Lookahead control: tabular features are explicit `*_l1`; Transformer target date `t` uses sequence rows `[t-22, t-1]`; GJR annual recursion uses `return_{t-1}` for forecast date `t`.
- Train/OOS separation: feature standardization is fit only on 2005-2011 training rows; validation ends 2015-12-31; OOS starts 2016-01-01.
- Metric orientation: QLIKE uses canonical `actual / predicted - log(actual / predicted) - 1` through `volpred.stats.model_evaluation.qlike_pointwise`.
- Inference: per-asset DM tests are primary, with Holm adjustment across the per-asset pair family. Pooled asset-day DM is reported only as diagnostic.
- Alignment: OOS rows are not sorted until after Transformer predictions are assigned, so sequence-order predictions align with target rows.

## Result Integrity

Core JSON checks:

- `verdict = NULL_OR_NEGATIVE`
- `mt_best_mean_qlike_assets = 0`
- `mt_strict_holm_wins_vs_gjr = 0`
- `mt_strict_holm_losses = 15`
- `oos_rows = 15678`, exactly 2,613 rows per asset

The conclusion is appropriately conservative: the experiment rejects a local daily-ETF Transformer increment, but does not reject all possible Multi-Transformer volatility architectures.

