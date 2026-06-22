# K445 — Bitcoin Inverse Leverage Effect

**Status: source-review FAIL pending target-aligned rerun.**

K445 studies BTC inverse leverage and compares GARCH-family OOS volatility
forecasts over 2023-2024. The asymmetry/gamma findings remain useful
diagnostics, but the published OOS model-ranking claim is not source-review
safe.

## Source-Review Finding

The 2026-06-16 Codex review found that v1 used `arch` one-step forecasts with
the default origin alignment and compared them to same-index realized squared
returns. In `arch`, row `t` under origin alignment is the forecast made at
origin `t` for target `t+1`; same-index loss evaluation can therefore be
off-by-one for OOS ranking.

## Current Source Guard

The script now routes OOS forecasts through:

```python
target_aligned_variance_forecast(result, start)
```

which calls:

```python
forecast(..., align="target")
```

OOS QLIKE and DM pointwise losses use the canonical project helpers:

- `volpred.stats.model_evaluation.qlike(actual, predicted)`
- `volpred.stats.model_evaluation.qlike_pointwise(actual, predicted)`

## Required K445 Rerun

- Rerun K445 from source after this target-alignment fix.
- Regenerate `k445_btc_leverage_results.json` and charts from the rerun.
- Keep article language conditional until rerun review passes.
- Do not cite the v1 OOS model-ranking claim as reviewed evidence.
