# Oil / OVX / VIX Spillover Follow-Up

Task: `trending_repost_2026_06_12_地緣波動`

Purpose: update the May 2026 Iran-war oil-volatility theme with 2026-06-11 market data, focusing on whether oil volatility is still spilling into U.S. equity volatility.

## Data

- Source: Yahoo Finance via `yfinance`.
- Tickers: `^OVX`, `^VIX`, `CL=F`, `BZ=F`, `USO`, `XLE`, `SPY`, `^TNX`, `DX-Y.NYB`.
- Window: 2007-01-01 to 2026-06-12, where end date is exclusive.
- Latest U.S. close used: 2026-06-11.

Public references used for definitions/context:

- FRED OVXCLS: https://fred.stlouisfed.org/series/OVXCLS
- Cboe OVX dashboard: https://www.cboe.com/us/indices/dashboard/ovx/
- CME WTI conflict context: https://www.cmegroup.com/videos/2026/06/10/wti-crude-oil-futures-climbed-past-91-amid-middle-east-conflict.html

## Reproduce

```bash
uv run python experiments/trending_2026_06_12_oil_vix_spillover/trending_2026_06_12_oil_vix_spillover.py
```

Expected outputs:

- `close_prices.csv`
- `summary_table.csv`
- `trending_2026_06_12_oil_vix_spillover_results.json`
- `fig_1_oil_vix_2026_path.png`
- `fig_2_spillover_correlations.png`

## Research Notes

This is a descriptive spillover diagnostic, not a causal model. Same-day and next-day correlations are used as a lightweight check against overclaiming. Weak lead-lag correlations should be reported as weak evidence, not reframed as a predictive signal.
