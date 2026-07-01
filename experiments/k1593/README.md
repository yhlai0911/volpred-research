# K1593 - CNN-Transformer Hybrid Volatility Forecast Adjudication

Status: completed smoke/adjudication run

Task: `research_cnn_transformer_hybrid`

Verdict: `NULL_VS_HARX`

## Motivation

The backlog item named a CNN-Transformer hybrid as a candidate next volatility
forecasting direction. Prior project evidence already shows a repeated
machine-learning ceiling in daily volatility forecasting, especially when
published neural models are compared against stronger and information-matched
HAR/GARCH baselines. K1593 tests the specific architecture claim in a small,
fixed, reproducible setting.

The question is not whether a CNN-Transformer can fit volatility persistence.
The question is whether it adds an out-of-sample architecture edge after a
linear HAR-X/Ridge model receives the same lagged RV and VIX information.

## Literature Checked

1. Taneva-Angelova and Granchev (2025), "Deep Learning and Transformer
   Architectures for Volatility Forecasting: Evidence from U.S. Equity
   Indices", JRFM 18(12):685.
   <https://www.mdpi.com/1911-8074/18/12/685>
2. Tu (2025), "Bridging Short- and Long-Term Dependencies: A CNN-Transformer
   Hybrid for Financial Time Series Forecasting", arXiv:2504.19309.
   <https://ideas.repec.org/p/arx/papers/2504.19309.html>
3. "Advances in forecasting realized volatility: a review of methodologies",
   Financial Innovation, 2025.
   <https://link.springer.com/article/10.1186/s40854-025-00809-5>

The search did not verify a stable "European Journal of Finance 2025" paper
matching the backlog label. This experiment therefore treats the backlog label
as a research direction, not as a verified bibliographic fact.

## Data

Frozen local source:

`paper/leverage-direction/data/spy_qqq_gld_tlt_eem_iwm_slv_btc_usd_vix_2010-2026.csv`

Assets:

`SPY`, `QQQ`, `EEM`, `GLD`, `TLT`, `IWM`, `SLV`

Target:

Next-day Parkinson realized variance in percent-squared units.

Split:

- Train: target date through 2020-12-31
- Validation: 2021-01-01 through 2022-12-31
- OOS: 2023-01-01 through 2026-06-30

The source CSV contains BTC weekend rows. The script first builds each ETF's
own valid trading calendar, then computes 5-day and 22-day rolling RV on that
asset-specific calendar.

## Models

All forecasts are one-step ahead. Each row uses feature date `t` to forecast
target date `t+1`.

- `RollingMean22`: lagged 22-trading-day mean Parkinson RV.
- `HAR-X`: linear log-RV regression using the same lagged features as the NN.
- `Ridge-HAR-X`: ridge log-RV regression; alpha selected on 2021-2022 validation.
- `CNNTransformer`: Conv1D local feature extractor plus one Transformer encoder
  layer, trained on 22-day sequences of the same lagged features.

Feature set:

`log_rv1`, `log_rv5`, `log_rv22`, `log_vix_var`, `abs_ret`, `neg_ret`

## Inference

Primary loss is Patton QLIKE:

`actual / predicted - log(actual / predicted) - 1`

Tests:

- Asset-level DM tests, h=1.
- Holm correction across assets for `CNNTransformer` vs `HAR-X`.
- Date-clustered panel DM: cross-asset mean loss by common target date before
  inference.
- Hansen-Lunde-Nason MCS at alpha 0.10 with 1000 bootstrap draws.

## Main Results

Asset-level results:

| Asset | Best mean QLIKE model | CNN vs HAR-X DM t | Holm p | Strict CNN win? |
|---|---:|---:|---:|---:|
| SPY | HAR-X | +1.16 | 0.929 | no |
| QQQ | RollingMean22 | +0.50 | 1.000 | no |
| EEM | HAR-X | +1.25 | 0.929 | no |
| GLD | RollingMean22 | +1.42 | 0.929 | no |
| TLT | CNNTransformer | -5.45 | 0.000000485 | yes |
| IWM | RollingMean22 | -0.44 | 1.000 | no |
| SLV | RollingMean22 | +1.32 | 0.929 | no |

Panel results, all seven assets on common target dates:

- Common dates: 641
- Best mean-loss model: `RollingMean22`
- Mean QLIKE: RollingMean22 0.434, HAR-X 0.472, Ridge-HAR-X 0.473,
  CNNTransformer 0.511
- CNNTransformer vs HAR-X DM t = +1.34, p = 0.180
- MCS survivors: all four models

Conclusion:

`CNNTransformer` is not a robust winner. It has one clear TLT win, but it does
not survive as a cross-asset or panel-level superiority claim. The evidence
supports another daily-volatility ML ceiling result: architecture complexity
does not beat a same-information HAR-style baseline in this fixed OOS test.

## Lookahead Guard

The result JSON records for every asset:

- `max_training_feature_date`
- `first_oos_feature_date`
- `first_oos_target_date`
- `oos_feature_before_target_all_rows`

All assets satisfy `feature_date < target_date` for every OOS row.

Example:

`first_oos_feature_date = 2022-12-30`, `first_oos_target_date = 2023-01-04`.

## Artifacts

- `k1593.py`: reproducible experiment script.
- `k1593_results.json`: summary, inference, and lookahead guard.
- `k1593_oos_predictions.csv`: actual RV, forecasts, pointwise losses.
- `k1593_oos_losses.csv`: compact loss matrix.
- `figures/fig1_oos_qlike_by_asset.png`
- `figures/fig2_cnn_vs_harx_dm.png`
- `figures/fig3_panel_cumulative_loss_diff.png`

## Reproduce

```bash
uv run python experiments/k1593/k1593.py
```

Runtime on this machine was about 31 seconds.

## Limitations

- This is not a full SOTA replication of any single published architecture.
- One fixed architecture and one fixed seed are used.
- Horizon is h=1 only.
- Target is Parkinson RV only; no Yang-Zhang, close-to-close, or intraday RV
  robustness.
- No transaction-cost or portfolio translation layer is tested.
- The TLT positive cell deserves follow-up before any article claim, because it
  is one asset out of seven and the panel test is null.
