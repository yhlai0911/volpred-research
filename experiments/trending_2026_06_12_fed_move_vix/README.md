# Fed / MOVE / VIX Trending Evidence Package

Task: `trending_repost_2026_06_12_fed降息`

Purpose: support a reader-facing article on the divergence between U.S. rates volatility (`^MOVE`) and equity volatility (`^VIX`) after June 2026 Fed cut expectations were repriced.

## Data

- Source: Yahoo Finance via `yfinance`.
- Tickers: `^VIX`, `^MOVE`, `SPY`, `TLT`, `^TNX`, `^IRX`, `ZQ=F`, `ZN=F`.
- Window: 2003-01-01 to 2026-06-12, where end date is exclusive.
- Latest U.S. close used: 2026-06-11.

Public methodology references used for definitions:

- CME FedWatch: https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html
- Cboe VIX methodology: https://cdn.cboe.com/resources/indices/Volatility_Index_Methodology_Cboe_Volatility_Index.pdf
- ICE MOVE description: https://developer.ice.com/fixed-income-data-services/catalog/ice-data-indices-move-index

## Reproduce

```bash
uv run python experiments/trending_2026_06_12_fed_move_vix/trending_2026_06_12_fed_move_vix.py
```

Expected outputs:

- `close_prices.csv`
- `summary_table.csv`
- `trending_2026_06_12_fed_move_vix_results.json`
- `fig_1_move_vix_normalized_1y.png`
- `fig_2_move_vix_ratio_history.png`

## Research Notes

This package is descriptive, not a trading backtest. It does not claim causal direction between MOVE and VIX. The article should frame the result as cross-asset risk pricing divergence and explicitly note that futures-implied rate levels are approximations from generic Yahoo Finance contracts, not CME FedWatch target-rate probabilities.
