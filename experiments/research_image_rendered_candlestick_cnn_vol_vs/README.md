# Image-rendered candlestick CNN vs numeric volatility baselines

## Verdict

`NULL_VS_NUMERIC_BASELINES`

Rasterized 20-day OHLCV candlestick images did not deliver a robust out-of-sample edge for next-week realized variance forecasting. The panel best model by mean QLIKE was `GARCH11`, not the image CNN, and the CNN was significantly worse than `HAR_Ridge` on the panel loss test.

Primary gate result:

- Strict asset-level CNN wins versus `HAR_Ridge`: 0 / 7
- Panel best mean QLIKE model: `GARCH11`
- Panel DM test on daily panel losses, CNN minus HAR: t = 2.4845, p = 0.0132
- Support rule was intentionally strict: require at least 4 strict asset wins, panel best model equal to `CNNImage`, and panel DM t < -3.

## Research Question

Can a CNN trained on rasterized OHLCV candlestick images predict next-week realized variance better than traditional numeric OHLC/HAR/GARCH baselines?

This experiment is orthogonal to the numeric candlestick estimator backlog item: it tests a pixel-level visual representation rather than an analytic candlestick volatility formula.

## Prior Context

Project memory search before the run found related but distinct results:

- K1558: numeric OHLC candlestick estimators lost to GARCH in the existing project setting.
- K1593 / K1535: broader ML/CNN/Transformer volatility pilots found limited or no robust edge over HAR-style numeric baselines.
- No exact project experiment had tested rasterized candlestick chart images as the primary input.

Literature checked before implementation:

- Bollerslev, Li, Li, and Li (2026), Journal of Financial Econometrics, "Optimal Candlestick-Based Spot Volatility Estimation..."
- Duong et al. (2025), arXiv:2501.12239, candlestick chart image CNN market-strength prediction.
- Sezer and Ozbayoglu (2020), Financial Innovation, candlestick/time-series image encoding with CNNs.
- Dixon and Zeng (2026), Journal of Financial Markets, stock chart image-driven factors.

## Data

Frozen local source:

`paper/leverage-direction/data/spy_qqq_gld_tlt_eem_iwm_slv_btc_usd_vix_2010-2026.csv`

Assets:

`SPY`, `QQQ`, `IWM`, `EEM`, `GLD`, `TLT`, `SLV`

Sample construction:

- Feature window: 20 trading days of adjusted OHLCV through feature date t.
- Target: close-to-close realized variance over t+1 through t+5, annualized.
- Sample stride: 2 trading days.
- Train: feature dates through 2018-12-31, 7,861 samples.
- Validation: feature dates 2019-01-01 through 2020-12-31, 1,764 samples.
- OOS: target dates 2021-01-01 through 2026-06-30, 4,792 samples.

## Models

- `CNNImage`: 48x48 RGB rendered candlestick-plus-volume image classifier. Forecast is class-probability expected variance using train-set class medians.
- `NumericLogit`: multinomial logistic regression on numeric OHLC/HAR/range features, using the same RV buckets.
- `HAR_Ridge`: ridge regression on numeric OHLC/HAR/range features predicting log next-week variance.
- `RollingMean20`: lagged 20-day close-to-close realized variance.
- `GARCH11`: fixed-parameter GARCH(1,1) estimated pre-OOS and recursively filtered through OOS.

Guardrails:

- No network dependency; all data came from the frozen local CSV.
- The feature date uses information only through t.
- Target uses future returns t+1 through t+5.
- Random seeds are fixed.
- The CNN support rule requires broad asset-level and panel-level evidence, not a single visual-model win.

## Results

Panel metrics, lower QLIKE is better:

| Model | Mean QLIKE | Bucket accuracy | Balanced bucket accuracy | Spearman(log forecast, log actual) |
|---|---:|---:|---:|---:|
| CNNImage | 0.8521 | 0.3485 | 0.3333 | 0.0552 |
| NumericLogit | 0.4833 | 0.5632 | 0.4845 | 0.6292 |
| HAR_Ridge | 0.4360 | 0.5751 | 0.5518 | 0.6295 |
| RollingMean20 | 0.3983 | 0.5628 | 0.5127 | 0.5845 |
| GARCH11 | 0.3513 | 0.5641 | 0.4952 | 0.6055 |

Asset-level summary:

| Asset | Best QLIKE model | CNN QLIKE | HAR QLIKE | NumericLogit QLIKE | GARCH QLIKE | DM t, CNN-HAR | Holm p | Strict CNN win |
|---|---|---:|---:|---:|---:|---:|---:|---|
| EEM | GARCH11 | 0.5178 | 0.5155 | 0.3999 | 0.3669 | 0.0349 | 1.0000 | false |
| GLD | GARCH11 | 0.5522 | 0.4938 | 0.4105 | 0.3717 | 0.7419 | 1.0000 | false |
| IWM | NumericLogit | 0.5758 | 0.3597 | 0.3322 | 0.3494 | 2.6558 | 0.0567 | false |
| QQQ | GARCH11 | 0.7337 | 0.3788 | 0.3988 | 0.3508 | 2.6161 | 0.0567 | false |
| SLV | GARCH11 | 2.7137 | 0.5805 | 1.2333 | 0.3546 | 1.9322 | 0.2151 | false |
| SPY | NumericLogit | 0.5848 | 0.4089 | 0.3776 | 0.4075 | 2.6184 | 0.0567 | false |
| TLT | NumericLogit | 0.3513 | 0.3199 | 0.2569 | 0.2579 | 0.7774 | 1.0000 | false |

Interpretation:

The rendered image representation discarded too much precise numerical scale information for this volatility task. The CNN's balanced bucket accuracy was exactly random at one-third on the panel, while numeric features preserved strong rank information. This does not rule out all image-based finance tasks, but it does reject this simple daily OHLCV candlestick-image approach as a robust RV forecasting improvement over numeric baselines.

## Outputs

- Script: `research_image_rendered_candlestick_cnn_vol_vs.py`
- Results JSON: `research_image_rendered_candlestick_cnn_vol_vs_results.json`
- OOS predictions: `data/oos_predictions.csv`
- Summary table: `data/summary_table.csv`
- Figures:
  - `figures/dm_cnn_vs_har_by_asset.png`
  - `figures/panel_cumulative_loss_diff.png`
  - `figures/example_candlestick_images.png`

Reproduce:

```bash
uv run python experiments/research_image_rendered_candlestick_cnn_vol_vs/research_image_rendered_candlestick_cnn_vol_vs.py
```

## Limitations

- This is a daily OHLCV image pilot, not a high-frequency realized-volatility model.
- The CNN uses bucket classification and maps class probabilities to expected variance, so QLIKE forecasts are deliberately coarse.
- The 48x48 rendering may erase numerical scale information that numeric OHLC features retain.
- No trading strategy, transaction-cost, or portfolio claim is made.
