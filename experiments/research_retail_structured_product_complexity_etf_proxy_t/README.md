# research_retail_structured_product_complexity_etf_proxy_t

## Motivation

This experiment tests whether exchange-traded complex payoff products can serve as a free proxy for retail structured-product complexity demand. The ideal variable would be product-level structured-note sales / AUM / payoff terms. Those data are not public in this repository, so this experiment deliberately uses a narrower ETF proxy.

## Data & Methodology

- Data source: yfinance OHLCV daily data.
- Requested start: `2021-01-01`.
- Effective sample: `2021-01-04` to `2026-06-22` across 1373 union trading days.
- Complex-product proxy: rolling 63d z-score of log dollar volume for option-income ETFs, defined-outcome/buffer ETFs, and single-stock leveraged/inverse ETFs.
- Targets: next 5 trading-day realized variance, next 5d negative log return, and next 5d VIX/VVIX log changes.
- Lookahead guard: every predictive regression uses `signal_lag = signals.shift(1)`, so the signal is known no later than t-1 and the target starts at t.
- Inference: OLS with HAC(4) standard errors, Benjamini-Hochberg q-values, Bonferroni p-values, and Harvey-style `|t| >= 3` screening.
- Methodology type: empirical proxy diagnostic, not causal identification.

## Main Result

Verdict: **POSITIVE_PROXY_NEEDS_CAUSAL_FOLLOWUP**.

- Total regressions: 33.
- Harvey `|t| >= 3` passes: 3.
- BH 5% passes: 4.
- Bonferroni 5% passes: 3.

## Top HAC Cells

| signal | target | n | coef | HAC t | p | BH q |
|---|---:|---:|---:|---:|---:|---:|
| single_stock_leveraged | COIN_rv5 | 943 | 0.00521394 | 3.77 | 0.0002 | 0.0053 |
| single_stock_leveraged | NVDA_rv5 | 943 | 0.00180736 | 3.60 | 0.0003 | 0.0053 |
| single_stock_TSLA | TSLA_rv5 | 943 | 0.00164869 | 3.19 | 0.0014 | 0.0154 |
| single_stock_leveraged | GOOGL_rv5 | 943 | 0.000628535 | 2.83 | 0.0047 | 0.0385 |
| single_stock_COIN | COIN_rv5 | 924 | 0.00210168 | 2.63 | 0.0084 | 0.0556 |
| single_stock_AAPL | AAPL_rv5 | 925 | 0.00034678 | 2.55 | 0.0106 | 0.0585 |
| single_stock_leveraged | AMD_rv5 | 943 | 0.00130858 | 2.13 | 0.0331 | 0.1561 |
| single_stock_MSFT | MSFT_left_loss5 | 905 | 0.00421799 | 2.02 | 0.0433 | 0.1787 |

## Bootstrap Check

```json
{
  "signal": "single_stock_leveraged",
  "target": "COIN_rv5",
  "hac_coef": 0.005213938811578111,
  "hac_t": 3.774704053082024,
  "available": true,
  "seed": 42,
  "reps": 1000,
  "block": 20,
  "coef_mean": 0.005339028417898119,
  "ci_025": 0.0026831579330015075,
  "ci_975": 0.008205558060621822,
  "n_success": 1000
}
```

## Figures

- `demand_timeseries`: `figures/complex_demand_proxy_timeseries.png`
- `top_hac_tstats`: `figures/top_hac_tstats.png`

## References

- Celerier, C. and Vallee, B. (2026), Competition, complexity, and security design: evidence from retail investment products, Review of Finance. — https://academic.oup.com/rof/advance-article/doi/10.1093/rof/rfag001/8516563
- Huang, Z. (2025), The Rise of Single-Stock ETFs and More Volatile Stock Prices, SSRN. — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5691524
- Lenkey, S. L. (2024), The market impact of leveraged ETFs: A Survey of the literature, Quantitative Finance and Economics. — https://www.aimspress.com/article/doi/10.3934/QFE.2024031?viewType=HTML
- Garcia-Feijoo, L. and Silverstein, B. (2023), The Dynamics of Defined Outcome Exchange Traded Funds, SSRN. — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4371346
- SEC Investor Advisory Committee (2023), Draft Recommendation on Single-Stock ETFs and Leveraged ETFs. — https://www.sec.gov/files/20230616-recommendation-single-stock-etfs-and-leveraged-etfs.pdf

## Limitations

- ETF volume is only a proxy for retail complex-payoff demand; it is not OTC structured-note issuance or investor-level exposure.
- Some product families have short histories and product launches during the sample; early periods are sparse by construction.
- Daily close-to-close data cannot test late-day rebalancing pressure directly.
- The tests are predictive associations, not causal identification.
