# Codex Review

Review date: 2026-06-24

## Scope

Reviewed:

- `research_tips_breakeven_volatility_corporate_bond_return.py`
- `research_tips_breakeven_volatility_corporate_bond_return_results.json`
- `summary_table.csv`
- generated figures

## Findings

No blocking issues found.

## Checks

- Lookahead control: all non-target predictors are lagged one trading day in
  `build_features()` via `raw.shift(1)`. The target at date `t` is a forward
  window over `t..t+h-1`, while OOS training at forecast date `t` uses only rows
  whose target window ends no later than `t-1`.
- QLIKE orientation: `qlike(actual, forecast)` uses
  `actual / forecast - log(actual / forecast) - 1`, matching the Patton loss
  convention for variance forecasts.
- OOS comparison: baseline and augmented models share the same expanding
  samples, refit schedule, controls, target transformations, and loss functions.
- Treatment isolation: augmented columns add BEI realized-volatility terms on
  top of BEI levels, BEI daily changes, VIX, SPY risk, and own lagged target
  variance.
- Data provenance: result JSON records FRED/yfinance source ranges and sample
  counts. The OAS tests are correctly marked as short-sample diagnostics because
  the direct FRED CSV endpoint returned only 2023-06-26 onward.

## Residual Risks

- yfinance adjusted-close ETF data are sufficient for this screening experiment
  but not a final production volatility dataset.
- BEI-vol features are correlated across maturities and windows; the augmented
  model is intentionally a screening design rather than a structural risk-price
  estimate.
- Some ETF short-horizon cells show positive QLIKE improvement, but none reach
  the conservative `t > 3` threshold. These should not be described as a robust
  edge.
