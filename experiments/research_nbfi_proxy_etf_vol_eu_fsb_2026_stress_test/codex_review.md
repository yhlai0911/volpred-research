# Codex Review

Review date: 2026-06-24

## Scope

Reviewed:

- `research_nbfi_proxy_etf_vol_eu_fsb_2026_stress_test.py`
- `research_nbfi_proxy_etf_vol_eu_fsb_2026_stress_test_results.json`
- `summary_table.csv`
- `daily_panel.csv`
- generated figures

## Findings

No blocking issues found.

## Checks

- Lookahead control: the composite NBFI pressure signal is used only through
  `panel["run_pressure_lag1"] = panel["run_pressure_index"].shift(1)`.
- Target alignment: variance targets at date `t` are forward sums over
  `t..t+h-1`; OOS training at forecast date `t` excludes rows whose target
  window would not have ended by `t-1`.
- QLIKE orientation: variance targets use
  `actual / forecast - log(actual / forecast) - 1`.
- Baseline parity: baseline and augmented models share the same expanding
  samples, refit cadence, target transformation, and controls. The only
  augmented variable is lagged NBFI pressure.
- Scope versus K1538: this experiment extends from bond-fund run pressure to a
  broader NBFI proxy including MMF flows, bank credit, SOFR-IORB, and bank ETF
  targets. It is not a duplicate of K1538.
- Data provenance: result JSON records yfinance ranges and every FRED series
  range used in the proxy.

## Residual Risks

- The proxy is intentionally public and imperfect. It cannot replicate full ICI
  MMF flows, supervisory NBFI exposures, TRACE liquidity, or fund NAV discounts.
- `MMMFFAQ027S` is quarterly and forward-filled; it is useful as a slow cash
  migration component, not a daily flow observation.
- ETF price and volume stress may reflect broad risk-off beta rather than NBFI
  liquidity stress. Baseline controls reduce this risk but do not eliminate it.
- The cross-sector correlation target is a diagnostic MSE cell, not a
  Patton-style variance QLIKE cell.
