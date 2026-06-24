# Hedge-Fund Alpha-Dispersion Proxy via Strategy ETF Dispersion

## Purpose

This experiment tests whether a free public proxy for hedge-fund strategy
dispersion can lead next-month stock cross-sectional risk. The proxy is built
from alternative-strategy ETF returns, not from stock-side dispersion itself.

The backlog question is deliberately distinct from prior stock/sector dispersion
work: here the signal is strategy-side dispersion across QAI, MNA, CTA, DBMF,
MRGR, HFXI, and RPAR. The main target is next-month cross-sectional return
variance among current S&P 500 constituents.

## Pre-Experiment Context

Targeted memory search found earlier dispersion work on sector or stock-side
dispersion, including null or unstable market-timing results. That does not
answer this task because strategy-side alternative ETF dispersion is a different
information set.

References checked before design:

- J.P. Morgan Alternative Investments Outlook 2026.
- Wellington, "Goldilocks and the three drivers of hedge fund outperformance".
- ECB Working Paper 1658, "Commonality in hedge fund returns".

## Design

Signal:

- Download adjusted-close prices for QAI, MNA, CTA, DBMF, MRGR, HFXI, and RPAR.
- Compute daily log returns.
- Compute daily cross-sectional standard deviation across available strategy ETF
  returns, requiring at least five ETFs.
- Smooth the daily strategy dispersion as 21d and 63d rolling means.
- Apply `raw.shift(1)` before any predictive regression.

Targets:

- Current S&P 500 constituents from Wikipedia, adjusted-close yfinance data:
  next-22-trading-day cross-sectional return variance.
- Current S&P 500 constituents: next-22-trading-day average individual realized
  variance.
- IWM/IWR yfinance top holdings: next-22-trading-day average individual realized
  variance as auxiliary diagnostics only.

Forecast comparison:

- Baseline: own lagged target plus SPY 22d return, SPY 22d realized variance,
  VIX level, and VIX 22d change.
- Augmented: baseline plus lagged 21d and 63d strategy ETF dispersion.
- Expanding OLS on log target, refit every 21 observations.
- At forecast date `t`, training excludes rows whose forward 22d target window
  would not have ended by `t-1`.
- QLIKE orientation is `actual / predicted - log(actual / predicted) - 1`.
- DM/HAC test uses baseline loss minus augmented loss; positive t-stat favors
  strategy-dispersion augmentation. Conservative threshold: `|t| > 3`.

## Run

```bash
uv run python experiments/research_hedge_fund_alpha_dispersion_regime_strategy_etf/research_hedge_fund_alpha_dispersion_regime_strategy_etf.py
```

## Required Outputs

- `research_hedge_fund_alpha_dispersion_regime_strategy_etf.py`
- `research_hedge_fund_alpha_dispersion_regime_strategy_etf_results.json`
- `results.json`
- `summary_table.csv`
- `figures/strategy_dispersion_timeseries.png`
- `figures/oos_qlike_dm_tstats.png`
- `codex_review.md`

## Success Criteria

Evidence for a real leading indicator requires positive OOS QLIKE improvement
with Harvey-level DM support in the core S&P 500 cross-sectional target after
market-volatility and own-target persistence controls. IWM/IWR top-holdings
diagnostics are not sufficient by themselves because they are partial universe
proxies.

## Results

Final run: 2026-06-24 local session.

Aggregate OOS result:

- Valid OOS cells: 4.
- Positive Harvey-level QLIKE cells: 0.
- Negative Harvey-level QLIKE cells: 0.
- Median QLIKE improvement from adding strategy-dispersion features: -10.44%.
- Mean QLIKE improvement from adding strategy-dispersion features: -9.81%.
- Verdict: `null_or_mixed_negative`.

The augmented model underperformed the baseline in every OOS cell. The core
S&P 500 current-constituent targets were both negative: average individual RV
lost 4.92% QLIKE and cross-sectional return variance lost 13.46% QLIKE. IWM and
IWR top-holdings diagnostics were also negative.

| Target | OOS N | First OOS | Last OOS | QLIKE Improvement % | QLIKE DM t |
|---|---:|---|---|---:|---:|
| SP500 current constituents avg individual RV 22d | 1100 | 2022-01-03 | 2026-05-21 | -4.92 | -2.12 |
| SP500 current constituents cross-sectional return var 22d | 1100 | 2022-01-03 | 2026-05-21 | -13.46 | -2.00 |
| IWM yfinance top holdings avg individual RV 22d | 1100 | 2022-01-03 | 2026-05-21 | -12.89 | -1.88 |
| IWR yfinance top holdings avg individual RV 22d | 1100 | 2022-01-03 | 2026-05-21 | -7.99 | -2.57 |

Interpretation: the public strategy-ETF dispersion proxy does not support the
claim that hedge-fund/alternative-strategy dispersion leads next-month stock
cross-sectional risk. The result should be logged as a null or mixed-negative
screening result, not promoted into an article without a better hedge-fund
return dispersion measure or a stronger historical membership dataset.

## Data Coverage

- Strategy ETFs downloaded: CTA, DBMF, RPAR, HFXI, MRGR, MNA, QAI.
- Strategy ETF price window: 2009-03-25 to 2026-06-23; signal requires at least
  five ETFs available on a date.
- S&P 500 constituents requested/downloaded: 503 / 494.
- IWM/IWR diagnostics use 10 yfinance top holdings each, not full fund holdings.

## Limitations

- The S&P 500 universe is current constituents from Wikipedia, so the stock
  target has survivorship bias.
- IWM/IWR full holdings CSV downloads were not reliably available in this
  session; top-holdings diagnostics are not a full small/mid-cap universe test.
- Strategy ETF proxies are not hedge-fund indices and include ETF-specific
  replication, liquidity, and fee effects.
- Strategy ETF availability changes through time; CTA begins later than the
  older QAI/MNA/MRGR/HFXI history.
