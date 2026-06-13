# K1487: TWSE 當沖佔比與次日台股波動

## Research Question

台股市場層級的當沖強度，是否能預測下一個交易日的 realized volatility？

更精確地說，本實驗拆成兩個方向：

- **當沖放大波動**：TWSE 當沖成交值占比是否 Granger-lead 次日 `log(r_t^2)`？
- **波動吸引當沖**：市場波動是否 Granger-lead 後續當沖成交值占比？

## Motivation and Literature

這個題目來自任務池 `research_herding`，理由是 TWSE 有罕見的免費市場層級日頻當沖統計，適合檢驗 retail/herding 是否有台股在地 volatility signal。

文獻與背景：

- TWSE 官方當沖統計頁標示資料自 2014-01-06 起可查，且日表包含當沖成交量、買進/賣出成交值及占市場比重。
- Barber, Lee, Liu and Odean 的台灣 day-trading 研究顯示，台灣當沖在其樣本中占總成交值超過 20%，且短線交易高度散戶化。
- Hsieh (2013, *International Review of Financial Analysis*) 用台股高頻資料發現個人與機構都有 herding，但個人 herding 較偏行為與情緒驅動，且後續報酬表現較差。
- Jones, Kaul and Lipson (1994, *Review of Financial Studies*) 是 volume / transactions / volatility 關係的基礎文獻；本實驗的增量是把一般成交量換成台灣特有的當沖占比。

Reference links:

- TWSE day-trading statistics: <https://www.twse.com.tw/en/trading/day-trading.html>
- TWSE monthly day-trading API used here: <https://www.twse.com.tw/exchangeReport/TWTB4U2>
- Barber et al., Taiwan day-trading paper: <https://faculty.haas.berkeley.edu/odean/papers/Day%20Traders/Day%20Trade%20040330.pdf>
- Hsieh (2013) Taiwan herding abstract: <https://ideas.repec.org/a/eee/finana/v29y2013icp175-188.html>
- Jones, Kaul and Lipson (1994): <https://ideas.repec.org/a/oup/rfinst/v7y1994i4p631-51.html>

## Data

Day-trading data:

- Source: TWSE official `exchangeReport/TWTB4U2` monthly API.
- Cache: `experiments/k1487_herding/data/twse_day_trading_market_monthly.csv`.
- Raw available cache span: 2014-01-06 to 2026-03-31.
- Rows in cache: 2,970 trading days.

Price data:

- `TWII`: `storage/macro/yf_TWII.csv`.
- `0050.TW`: `storage/macro/yf_0050.TW.csv`.
- Both are local yfinance snapshots. The common price endpoint currently ends on 2026-03-17.

Model panel:

- Effective sample after 252-day z-score warm-up: 2014-07-15 to 2026-03-17.
- `TWII`: n = 2,823.
- `0050.TW`: n = 2,823.
- OOS window: 2022-09-13 to 2026-03-17, n = 847.

## Timing and Lookahead Guard

Target row is date `t`.

Predictors are all known by `t-1`:

- `log_rv_lag1`, `log_rv_lag5`, `log_rv_lag22`.
- `day_trading_value_pct_lag1`.
- `day_trading_value_pct_z_lag1`.
- `day_trading_volume_pct_z_lag1`.

The script uses explicit `.shift(1)` for all forecasting features. Same-day correlations are reported only as descriptive diagnostics and are not used as forecast evidence.

## Method

Descriptive layer:

- Same-day Spearman correlation between TWSE day-trading ratios and realized variance.

Forecast layer:

- Baseline: rolling HAR-style log-RV model.
- Extensions:
  - `HAR + day_trading_value_pct_lag1`.
  - `HAR + day_trading_value_pct_z_lag1`.
  - `HAR + day_trading_volume_pct_z_lag1`.
- Rolling window: 1,000 observations.
- Refit: every 21 observations.
- Evaluation: OOS QLIKE, DM test vs HAR, Harvey threshold `|t| > 3.0`, moving-block bootstrap CI for mean loss difference.

Granger layer:

- Standard F-test Granger on current standardized `dt_z` and `log_rv`.
- Lags tested: 1, 5, 22.
- Multiple testing: Bonferroni alpha = 0.05 / 6 = 0.00833 across two directions and three lags.

## Results

### Descriptive Statistics

TWII panel:

- Mean day-trading value share: 27.45%.
- Median day-trading value share: 31.30%.
- 95th percentile day-trading value share: 43.04%.
- Mean day-trading volume share: 14.94%.
- Annualized volatility from mean daily RV: 17.22%.
- Same-day Spearman value-share vs RV: 0.0664, p = 0.00042.
- Same-day Spearman volume-share vs RV: 0.0983, p = 1.66e-7.

Same-day association exists but is small; it is not forecast evidence.

### OOS Forecasting

TWII:

| Model | QLIKE | Relative improvement vs HAR | DM t | p-value | Harvey pass |
|---|---:|---:|---:|---:|---|
| HAR | 4.3312 | 0.00% | NA | NA | NA |
| HAR + value share | 4.3206 | +0.245% | -0.456 | 0.649 | No |
| HAR + value-share z | 4.4669 | -3.133% | 2.987 | 0.00290 | No |
| HAR + volume-share z | 4.3666 | -0.818% | 1.570 | 0.117 | No |

0050.TW robustness:

| Model | Relative improvement vs HAR | DM t | p-value | Harvey pass |
|---|---:|---:|---:|---|
| HAR + value share | -13.93% | 1.891 | 0.0589 | No |
| HAR + value-share z | -16.73% | 2.319 | 0.0206 | No |
| HAR + volume-share z | +0.052% | -0.006 | 0.995 | No |

The only positive TWII OOS lift is economically tiny and statistically unsupported. The 0050 robustness check is mostly worse than HAR.

### Granger Direction

TWII:

| Direction | Lag 1 p | Lag 5 p | Lag 22 p | Bonferroni result |
|---|---:|---:|---:|---|
| Day-trading z -> log RV | 0.428 | 0.890 | 0.514 | 0/3 pass |
| log RV -> day-trading z | 5.38e-26 | 8.96e-12 | 4.21e-9 | 3/3 pass |

0050.TW:

| Direction | Lag 1 p | Lag 5 p | Lag 22 p | Bonferroni result |
|---|---:|---:|---:|---|
| Day-trading z -> log RV | 0.761 | 0.919 | 0.270 | 0/3 pass |
| log RV -> day-trading z | 1.16e-16 | 1.41e-6 | 1.15e-5 | 3/3 pass |

The direction is strongly asymmetric: realized volatility leads future day-trading intensity; day-trading intensity does not lead future realized volatility.

## Verdict

**NULL for forecast use.**

TWSE 當沖成交值占比是有意義的市場狀態與散戶注意力 proxy，但本實驗不支持把它上架為 next-day RV 預測因子：

- OOS QLIKE 沒有通過 Harvey `|t| > 3.0`。
- Moving-block bootstrap CI does not support a robust loss reduction for the only mildly positive TWII model.
- Bonferroni-adjusted Granger shows the opposite direction: volatility attracts day trading, not day trading forecasting volatility.

Operational implication: do not add TWSE day-trading ratio to Indicator Arena as a volatility-forecast signal without a different mechanism or intraday/order-imbalance version.

## Limitations

- Day-trading ratio is market-level; it does not identify investor type directly.
- TWII / 0050 price files are local yfinance snapshots ending 2026-03-17; TWSE day-trading cache extends to 2026-03-31 but the merged panel stops at the price endpoint.
- Granger tests are linear F-tests, not structural causal identification.
- Daily close-to-close `r_t^2` is a noisy realized-volatility proxy; intraday RV could be a cleaner follow-up if a canonical Taiwan intraday panel is added.

## Files

- `k1487_herding.py` — end-to-end reproducible script.
- `k1487_herding_results.json` — full results artifact.
- `data/twse_day_trading_market_monthly.csv` — TWSE official API cache.
- `figures/k1487_day_trading_ratio_timeseries.png` — day-trading ratio vs 22-day annualized RV.
- `figures/k1487_oos_qlike_improvement.png` — OOS QLIKE improvement vs HAR.
