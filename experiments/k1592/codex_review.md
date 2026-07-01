# Codex Review - K1592

Date: 2026-07-01

Verdict: CONDITIONAL_PASS

## Scope Reviewed

- `experiments/k1592/k1592.py`
- `experiments/k1592/k1592_results.json`
- `experiments/k1592/k1592_oos_losses.csv`
- `experiments/k1592/k1592_forecast_origin_decision_log.csv`
- `experiments/k1592/README.md`

## Checks

### Lookahead and Forecast Alignment

PASS.

At each origin, `k1592.py` fits on the prior 504 returns only. The block forecast uses the fitted last conditional variance and last training return to forecast the first OOS date. It then updates `last_eps` and `last_h` only after recording that day's forecast. This is equivalent to one-step target-aligned daily variance forecasting.

### QLIKE Direction

PASS.

The experiment imports `qlike` and `qlike_pointwise` from `volpred.stats.model_evaluation`, which implements the canonical Patton loss:

```text
actual / predicted - log(actual / predicted) - 1
```

No local inverse-QLIKE helper is used.

### DM and Panel Inference

PASS after one review fix.

The first implementation averaged losses by date but allowed BTC weekend-only dates to enter holdout/all-asset panels. This would have changed panel composition over time. The script now restricts panel inference to common dates only: each listed asset must have a valid loss on each panel date.

Asset-level DM uses HAC `h=1`. Panel-level DM uses date-clustered mean losses. The result table correctly labels all strict-superiority gates as failing when `|t| <= 3` or Holm `p >= 0.05`.

### Multiple Testing

PASS.

Asset-level pairwise tests receive Holm-adjusted p-values, and the results distinguish raw nominal p-values from strict Harvey/Holm pass flags.

### MCS

PASS.

The experiment uses the local Hansen-Lunde-Nason stationary-bootstrap implementation with `B=1000`. This is adequate for this hourly experiment artifact. A final paper table should rerun with a larger bootstrap count.

### Reproducibility

PASS.

The experiment uses a fixed seed (`1592`) and the paper-local frozen CSV. A rerun produced valid JSON, CSVs, and three figures. `py_compile` passes.

## Remaining Limitations

- The experiment uses only 8 assets because it intentionally avoids refreshing or mixing in live data. It does not satisfy the stronger 14/26-asset validation requested by the JBF review gate.
- Forecast parameters are refit every 21 trading days, not daily. This is acceptable for a bounded OOS diagnostic but should be disclosed if cited in the paper.
- Distributional VaR/ES and Student-t innovations are outside the scope.
- MCS bootstrap count is `B=1000`; use a larger count before final manuscript tables.

## Conclusion

K1592 supports the bounded conclusion in `README.md`: the pre-specified positive-gamma rule is not a JBF-grade OOS superiority result. It can be described as a model-selection diagnostic that is statistically indistinguishable from the best fixed GJR benchmark in the tested panels. The paper should not claim strict OOS forecasting gains from this experiment.
