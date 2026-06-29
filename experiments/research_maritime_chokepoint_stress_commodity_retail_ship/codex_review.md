# Codex Review

Experiment:
`research_maritime_chokepoint_stress_commodity_retail_ship`

Verdict: **CONDITIONAL_PASS**

## Checks

- **Three-piece requirement**: PASS. The experiment has `README.md`, the main
  script, and `_results.json`, plus figures and cached source data.
- **Lookahead**: PASS. GSCPI is delayed by month-end + 10 business days and all
  forecast inputs are shifted before forecasting. Future RV uses returns from
  `t+1..t+H`.
- **Target/loss match**: PASS. The RV forecasts are evaluated with QLIKE on
  future realized variance, and the correlation-spike test uses MSE on
  correlation.
- **Formal inference**: PASS. Forecast-loss differences use
  `volpred.stats.model_evaluation.dm_test`; Harvey pass is `DM t < -3`, and
  Holm p-values are reported across the 40 RV cells.
- **Multiple testing / conclusion strength**: PASS. Only one Holm-positive
  cell is claimed, and the broad chokepoint/composite claim is explicitly not
  supported.
- **Sparse event dummy handling**: PASS after fix. The first run exposed a
  20+ sigma event z-score from sparse dummies; `_rolling_z` now clips forecast
  inputs to +/-5 before rerun.
- **Reproducibility**: PASS. `SEED=42`, data caches are written under
  `experiments/.../data/`, and `py_compile` passes.

## True Finding

Only one formal RV forecast cell passes:

- `XRT`, `H=5`, `gscpi_z`: QLIKE improvement +2.94%, DM t=-4.00,
  Holm p=0.0026.

The composite maritime signal has 0 Holm-positive cells. The cross-asset
correlation-spike test is worse than baseline. Therefore the correct conclusion
is narrow partial support for short-horizon retail-vol forecasting from GSCPI,
not a broad maritime chokepoint volatility signal.

## Residual Risk

- `BDRY` is a limited public dry-bulk proxy, not container freight or vessel
  flow data.
- The manual event calendar is useful for diagnostics but not enough for causal
  claims.
- The GSCPI/XRT hit should be replicated with exact GSCPI release dates and a
  longer retail/supply-chain panel before publishing as anything stronger than
  a narrow hint.
