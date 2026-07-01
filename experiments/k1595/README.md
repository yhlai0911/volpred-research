# K1595 — Multi-Transformer-lite Volatility Forecast Adjudication

## Verdict

`NULL_OR_NEGATIVE`

The MultiTransformerLite model does not pass the local VolPred gate. It is never the best mean-QLIKE model across the six OOS ETF cells, has zero strict Holm-adjusted wins against the annual GJR-GARCH baseline, and records 15 strict Holm-adjusted losses across the per-asset pairwise DM family.

This is a bounded local adjudication, not a full replication of the Mishra-Renganathan-Gupta (2024) or Ramos-Perez-Alonso-Gonzalez-Nunez-Velazquez (2021) architectures.

## Motivation

The backlog item asked whether a Multi-Transformer volatility forecasting design can add value beyond classical volatility baselines. The relevant literature reports strong performance for hybrid Transformer / Multi-Transformer volatility models, including risk-measure applications. The local question is narrower and stricter:

Can a small pooled Transformer ensemble, trained only on information available before OOS, beat simple HAR/Ridge/EWMA/GJR baselines under Patton QLIKE on next-day close-to-close squared returns?

## Literature Checked

- Mishra, Renganathan, and Gupta (2024), "Volatility forecasting and assessing risk of financial markets using multi-transformer neural network based architecture," *Engineering Applications of Artificial Intelligence*, 133, 108223. DOI: https://doi.org/10.1016/j.engappai.2024.108223
- Ramos-Perez, Alonso-Gonzalez, and Nunez-Velazquez (2021), "Multi-Transformer: A New Neural Network-Based Architecture for Forecasting S&P Volatility," *Mathematics*, 9(15), 1794. https://www.mdpi.com/2227-7390/9/15/1794
- Nie et al. (2023), "A Time Series is Worth 64 Words: Long-term Forecasting with Transformers" / PatchTST. https://arxiv.org/abs/2211.14730
- Patton (2011), "Volatility forecast comparison using imperfect volatility proxies." https://public.econ.duke.edu/~ap172/Patton_vol_proxies_JoE_2011.pdf

## Data

- Frozen local cache: `experiments/k1552/data/prices.parquet`
- Assets: `SPY`, `QQQ`, `IWM`, `XLF`, `XLE`, `XLU`
- Train: 2005-01-01 to 2011-12-31
- Validation: 2012-01-01 to 2015-12-31
- OOS: 2016-01-01 to 2026-06-26
- OOS rows: 15,678 asset-days, 2,613 per asset
- Target: next-day close-to-close squared log return

## Models

- `EWMA94`: RiskMetrics-style recursive EWMA, lambda 0.94
- `HAR_LogOLS`: log-variance OLS with lagged 1d / 5d / 22d terms
- `RidgeFactors`: lagged HAR, range, VIX, and SPY variance features
- `GJR_GARCH_Annual`: annual refit GJR-GARCH(1,1), recursive one-step forecasts
- `TransformerLite`: one small pooled Transformer encoder
- `MultiTransformerLite`: average of three independently seeded `TransformerLite` models

All tabular model features use explicit `*_l1` columns. Transformer target date `t` uses only the prior 22 trading rows `[t-22, t-1]`. Feature standardization is fit on 2005-2011 training rows only.

## Primary Results

Mean QLIKE, lower is better:

| Asset | Best model | GJR | EWMA | HAR | Ridge | Transformer | MultiTransformer |
|---|---:|---:|---:|---:|---:|---:|---:|
| IWM | GJR | 1.390 | 1.423 | 3.052 | 2.963 | 3.481 | 3.309 |
| QQQ | GJR | 1.542 | 1.615 | 3.824 | 4.376 | 4.055 | 3.917 |
| SPY | GJR | 1.578 | 1.673 | 4.028 | 3.763 | 4.481 | 3.472 |
| XLE | GJR | 1.506 | 1.527 | 3.241 | 3.152 | 2.926 | 3.340 |
| XLF | GJR | 1.540 | 1.611 | 3.789 | 3.150 | 4.056 | 3.920 |
| XLU | GJR | 1.480 | 1.494 | 3.331 | 3.351 | 3.348 | 3.350 |

Per-asset DM tests for `MultiTransformerLite - GJR_GARCH_Annual` are all positive and strict, so they favor GJR:

| Asset | DM t-stat | Direction |
|---|---:|---|
| IWM | 13.24 | GJR wins |
| QQQ | 14.86 | GJR wins |
| SPY | 12.12 | GJR wins |
| XLE | 10.31 | GJR wins |
| XLF | 12.26 | GJR wins |
| XLU | 13.72 | GJR wins |

The only strict Holm-adjusted wins for `MultiTransformerLite` are against weaker comparisons in SPY: versus `HAR_LogOLS` and versus `TransformerLite`. These are not enough for a positive finding because GJR and EWMA dominate the economically relevant ranking.

## Interpretation

This result supports the existing VolPred ML-ceiling pattern: at daily ETF frequency, a small attention ensemble does not displace recursive volatility dynamics. The Transformer features do contain some ranking information, visible in Spearman correlations and the SPY weak-comparison wins, but the variance level calibration is poor relative to GJR/EWMA under QLIKE.

Safe claim:

> In a six-ETF 2016-2026 OOS daily-volatility test, a lite Multi-Transformer ensemble did not beat annual GJR-GARCH or EWMA under Patton QLIKE.

Unsafe claim:

> Multi-Transformer volatility forecasting is disproven.

That would overstate the evidence because this experiment is not a full hybrid MTL-GARCH replication and does not evaluate VaR/ES.

## Artifacts

- `k1595.py`
- `k1595_results.json`
- `k1595_oos_forecasts.csv`
- `figures/fig1_relative_qlike_vs_har.png`
- `figures/fig2_cumulative_loss_diff_vs_gjr.png`
- `figures/fig3_regime_qlike.png`
- `codex_review.md`

