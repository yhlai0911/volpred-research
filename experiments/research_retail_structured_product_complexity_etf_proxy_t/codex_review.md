# Codex Review

## Verdict

Conditional pass. The experiment is suitable as a free-data proxy diagnostic and the positive cells justify causal follow-up. It should not be used as evidence that retail structured-note issuance directly causes tail-risk mispricing.

## Checks

- Reproducibility: pass. The experiment script regenerates `README.md`, result JSON, regression CSV, signal CSV, raw yfinance CSVs, and figures from a fixed script path.
- Data transparency: pass. The result JSON records yfinance OHLCV as the source, the requested start date, the effective sample, valid tickers, and missing/short ticker diagnostics.
- Lookahead control: pass. Predictive regressions use `signal_lag = signals.shift(1)`, while realized-variance and return targets start at the current date.
- Randomness: pass. The moving-block bootstrap uses `SEED = 42`.
- Formal inference: pass. The main table reports HAC(4) t-statistics, raw p-values, Benjamini-Hochberg q-values, Bonferroni-adjusted p-values, and Harvey-style `|t| >= 3` flags.
- Multiple-testing interpretation: pass with caution. Three of 33 regressions pass both Harvey and Bonferroni screens, and four pass BH at 5%.
- Output completeness: pass. The experiment includes the required `README.md`, executable script, and `_results.json`; it also includes tables, figures, and raw downloaded data.

## Main Evidence

The strongest cells are concentrated in single-stock leveraged ETF demand proxies:

- `single_stock_leveraged -> COIN_rv5`: HAC t = 3.77, BH q = 0.0053, Bonferroni p = 0.0053.
- `single_stock_leveraged -> NVDA_rv5`: HAC t = 3.60, BH q = 0.0053, Bonferroni p = 0.0107.
- `single_stock_TSLA -> TSLA_rv5`: HAC t = 3.19, BH q = 0.0154, Bonferroni p = 0.0463.

The top-cell moving-block bootstrap also keeps a positive 95% interval for the COIN realized-variance coefficient.

## Limitations

- The proxy is ETF dollar-volume heat, not product-level OTC structured-note sales, AUM, payoff terms, or investor holdings.
- Single-stock leveraged ETF signals may capture attention, volatility regimes, or underlying-specific demand rather than a clean complex-product channel.
- The product universe is current-ticker based and does not correct for delisted products or unavailable historical AUM.
- Daily OHLCV cannot identify intraday rebalancing pressure or late-day trading impact.
- The result is predictive association only; a publishable claim needs launch-date/event controls, attention controls, and preferably higher-frequency or issuer-level data.

## Follow-up Gate

Before using this result in an article or paper narrative, run at least one robustness pass that separates product-launch timing, underlying attention/turnover, and market-wide volatility controls from the complex-payoff demand proxy.
