# Codex Review

Review date: 2026-06-24

## Scope

Reviewed:

- `research_hedge_fund_alpha_dispersion_regime_strategy_etf.py`
- `research_hedge_fund_alpha_dispersion_regime_strategy_etf_results.json`
- `summary_table.csv`
- generated figures

## Findings

No blocking issues found.

## Checks

- Lookahead control: strategy ETF dispersion and all market controls are lagged
  one trading day in `build_features()` via `raw.shift(1)`.
- Target alignment: each target at date `t` is a forward 22-trading-day
  variance quantity. OOS training at forecast date `t` excludes rows whose
  forward target window would not have ended by `t-1`.
- QLIKE orientation: `qlike(actual, forecast)` uses
  `actual / forecast - log(actual / forecast) - 1`.
- Baseline parity: baseline and augmented models share the same expanding
  samples, log-target transformation, refit schedule, and controls. The only
  augmented terms are lagged 21d/63d strategy ETF dispersion.
- Data provenance: result JSON records S&P 500 constituent source, yfinance
  download counts, ETF top holdings, and strategy ETF coverage.

## Residual Risks

- Current S&P 500 constituents create survivorship bias. This is acceptable for
  a public-proxy screening experiment but not a final index-membership study.
- IWM/IWR tests use yfinance top holdings only; they should be treated as
  diagnostics, not full Russell 2000 / Russell Midcap evidence.
- Strategy ETFs are noisy public proxies for hedge-fund style returns. A null
  result here rejects this proxy, not the full concept of hedge-fund return
  dispersion.
- yfinance had several failed S&P ticker downloads during the run, but the final
  universe still retained 494 constituents and each target date required at
  least 400 valid names.
