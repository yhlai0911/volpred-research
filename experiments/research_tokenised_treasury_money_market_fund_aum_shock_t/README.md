# Tokenised Treasury / MMF AUM Shock and T-bill ETF Liquidity-Vol

## Question

Does growth in tokenised Treasury / money-market-fund-like RWA assets spill over into short-end Treasury ETF liquidity-volatility?

Backlog item:

> Tokenised Treasury / money-market fund AUM shock 是否外溢到 T-bill ETF liquidity-vol.

## Data

- Tokenised Treasury / MMF-like AUM proxy: DefiLlama protocol TVL for `blackrock-buidl`, `circle-usyc`, `ondo-yield-assets`, `invesco-ustb`, `spiko`, `anemoy-capital`, `openeden-tbill`, `matrixdock-stbt`, `vaneck-treasury-fund`, and `arca-labs-arcoin`.
- Short-end Treasury ETF targets: yfinance daily OHLCV for `BIL`, `SHV`, `SGOV`, `USFR`, and `TFLO`.
- Controls: yfinance `SPY`, `TLT`, `^VIX`, `BTC-USD`, `ETH-USD`; FRED `SOFR`, `IORB`, and `WRMFNS` retail money-market fund assets.
- Final sample: 2023-04-11 to 2026-07-01, 809 ETF trading days after tokenised TVL first exceeds USD 100 million.
- Latest aggregate tokenised TVL in the sample: USD 11.7246 billion, 9 active components.

## Method

The primary signal is the 21-trading-day log growth z-score of aggregate tokenised Treasury / MMF-like TVL.

Lookahead controls:

1. Tokenised TVL growth signals use `.shift(1)`.
2. FRED retail MMF AUM control uses `.shift(5)` after daily forward filling.
3. Targets are future windows `t+1..t+h`, with `h=5` and `h=22`.
4. Expanding OOS forecasts embargo training rows by the target horizon, so a train row whose forward label would not be observable at the forecast origin is excluded.

Targets:

- `future_log_rv_5d`, `future_log_rv_22d`: log future equal-weighted short-end ETF close-to-close realized variance.
- `future_log_range_5d`, `future_log_range_22d`: log future high-low range variance proxy.
- `future_log_amihud_5d`, `future_log_amihud_22d`: log future Amihud-style absolute-return-per-dollar-volume proxy.

Gate:

- Positive primary-signal coefficient.
- HAC `|t| >= 3`.
- Holm-adjusted p-value below 0.05 across the six primary cells.
- Positive expanding-OOS MSE improvement with DM-style HAC t-statistic at least 3.

## Files

- `research_tokenised_treasury_money_market_fund_aum_shock_t.py`: reproducible script.
- `research_tokenised_treasury_money_market_fund_aum_shock_t_results.json`: machine-readable results.
- `data/analysis_panel.csv`: final date-level analysis panel.
- `data/summary_table.csv`: six primary test cells.
- `data/defillama_protocol_*.csv`: raw cached protocol TVL pulls.
- `data/fred_*.csv`: raw cached FRED pulls.
- `data/yfinance_ohlcv_panel.csv`: raw cached yfinance OHLCV panel.
- `figures/tokenised_tvl_signal.png`: aggregate TVL and lagged signal.
- `figures/primary_test_diagnostics.png`: HAC t-stats and OOS MSE diagnostics.
- `codex_review.md`: source-level reproducibility review.

## References

- Luo, Tinn, Duran, Wu, and Liu, "Transaction Profiling and Address Role Inference in Tokenized U.S. Treasuries", 2025: https://arxiv.org/abs/2507.14808
- Mafrur, "Tokenize Everything, But Can You Sell It? RWA Liquidity Challenges and the Road Ahead", 2025: https://arxiv.org/abs/2508.11651
- Ankenbrand, Bieri, Ferrazzini, and Hoehener, "Classifying Tokenised Money: Dimensions and Design Features", 2025: https://arxiv.org/abs/2512.11010
- Mafrur, "Tokenized but Illiquid? Evidence from Real-World Asset Markets", 2026: https://arxiv.org/abs/2606.01131
- DefiLlama protocol API: https://api.llama.fi/protocols
- FRED: https://fred.stlouisfed.org/

## Current Result

Run:

```bash
uv run python experiments/research_tokenised_treasury_money_market_fund_aum_shock_t/research_tokenised_treasury_money_market_fund_aum_shock_t.py
```

Verdict: `WEAK_RAW_ONLY_NO_ROBUST_OOS_PASS`.

Primary diagnostics:

- 5-day close-to-close RV: coefficient `-0.0106`, HAC t `-0.58`, Holm p `0.829`, OOS MSE improvement `-5.61%`.
- 22-day close-to-close RV: coefficient `-0.0251`, HAC t `-0.91`, Holm p `0.829`, OOS MSE improvement `-11.67%`.
- 5-day range-vol: coefficient `+0.0399`, HAC t `2.05`, raw p `0.040`, Holm p `0.201`, OOS MSE improvement `+1.12%`, DM t `0.56`.
- 22-day range-vol: coefficient `+0.0386`, HAC t `1.70`, raw p `0.089`, Holm p `0.354`, OOS MSE improvement `+1.37%`, DM t `0.25`.
- 5-day Amihud proxy: coefficient `-0.0184`, HAC t `-2.43`, Holm p `0.090`, OOS MSE improvement `-6.83%`.
- 22-day Amihud proxy: coefficient `-0.0094`, HAC t `-1.09`, Holm p `0.829`, OOS MSE improvement `-22.59%`.

Interpretation: public tokenised Treasury / MMF-like TVL growth has a weak raw positive association with short-end ETF high-low range-vol, but it fails the multiple-testing and OOS gates. Close-to-close RV and Amihud-style liquidity-vol do not support the spillover hypothesis. Treat this as a bounded null/weak diagnostic, not evidence against tokenised collateral channels at transaction level.

Limitations:

- DefiLlama protocol TVL is a public proxy, not a complete RWA.xyz or issuer-by-issuer collateral ledger.
- Daily ETF OHLCV cannot observe bid-ask spreads, primary-market creations/redemptions, or bill-market order flow.
- The tokenised Treasury history is short and dominated by 2024-2026 adoption growth.
- The design tests public proxy usefulness only; it is not a causal test of tokenised-fund flows.
