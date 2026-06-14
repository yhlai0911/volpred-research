# experiment_price_duration_interday_intraday_vol_2026_06_14

## 研究問題

價格存續期（price duration）是否能在本地可得的 5 分鐘資料上，拆出 interday vs intraday volatility 的不同動態？更具體地說：在一個 plain adaptive-threshold duration count 模型之外，加入 train-sample 估計的日內 duration seasonality，是否能降低 holdout intraday RV 的 RMSE？

## 動機與差異化

- 任務池：`research_price_duration_interday_vs_intraday_vol`
- `research_program.md` 將此題列為 price-duration interday/intraday decoupling backlog。
- 既有 `experiments/k196/` 已做 5-min RV / BPV / overnight pilot，但沒有用 price-threshold duration event count。
- 本實驗不聲稱復現完整 tick-level price-duration estimator，而是用本地 5 分鐘 bar 做可驗證 proxy pilot。

## 文獻前置

1. Li, Nolte, Nolte and Yu (2025), "Decoupling Interday and Intraday Volatility Dynamics With Price Durations", *Journal of Time Series Analysis*. DOI: <https://doi.org/10.1111/jtsa.12849>
2. Engle and Russell (1998), "Autoregressive Conditional Duration: A New Model for Irregularly Spaced Transaction Data", *Econometrica*. <https://www.jstor.org/stable/2999632>
3. Andersen and Bollerslev (1998), "Deutsche Mark-Dollar Volatility: Intraday Activity Patterns, Macroeconomic Announcements, and Longer Run Dependencies", *Journal of Finance*. <https://econ.duke.edu/~boller/Published_Papers/jf_98.pdf>

## 資料

- 資料源：本地 `data/intraday/` 5 分鐘 CSV
- 標的：
  - SPY：2026-01-14 至 2026-06-12，99 個完整交易日
  - 0050.TW：2026-01-20 至 2026-06-11，81 個完整交易日
- 切分：chronological 70/30 train/test
  - SPY train/test = 69 / 30 天
  - 0050.TW train/test = 56 / 25 天
- Seed：42

## 方法

1. 對每個市場，只用 train split 估計 adaptive price threshold：
   - `threshold = median(train daily intraday sigma) / sqrt(bars_per_day)`
2. 在每個交易日內，從開盤價格開始，累積 log price move；每跨越一次 threshold 記一個 duration event。
3. 用 train split 估計每個 5 分鐘 bin 的 duration event seasonality profile。
4. 對 test split 比較三種 intraday RV estimator：
   - `plain_duration`: `log(intraday_rv) ~ log(threshold^2 * event_count)`
   - `seasonality_augmented_duration`: plain feature + season-weighted event count + event seasonal alignment
   - `parkinson_range`: range-based benchmark
5. 用 paired day bootstrap（1000 次，固定 seed）檢定 seasonal model 的 RMSE 是否低於 plain model。

## 防錯規則

- 不使用 same-day signal 交易；本實驗是 realized volatility estimation，不是回測。
- Threshold 與 seasonality profile 只用 train split 估計；test split 不參與調參。
- 不使用 yfinance 下載，避免 `auto_adjust` 預設漂移。
- 結論只限本地 2026 年短樣本與 5 分鐘 proxy，不外推成 tick-level price-duration 文獻結論。

## 主要結果

| 市場 | plain RMSE | seasonal RMSE | RMSE 改善 | bootstrap 95% CI for delta | p(seasonal better) |
|---|---:|---:|---:|---:|---:|
| SPY | 1.8516e-05 | 1.8372e-05 | 0.776% | [-9.08e-07, 4.80e-07] | 0.360 |
| 0050.TW | 5.5136e-05 | 5.5111e-05 | 0.045% | [-2.03e-05, 2.10e-05] | 0.495 |

Duration event count 與 intraday RV 的相關性很高，但這部分主要是 estimator 的機械性同日關係，不應解讀成預測力：

| 市場 | test corr(event_count, intraday_rv) | test corr(event_count, overnight_var) | test overnight share |
|---|---:|---:|---:|
| SPY | 0.974 | 0.292 | 0.287 |
| 0050.TW | 0.955 | 0.532 | 0.499 |

## 結論

- **核心檢定未通過**：加入 duration seasonality 後，SPY 與 0050.TW 的 RMSE 都只有極小改善，且 bootstrap CI 都跨 0。
- **可報告的弱結果**：duration intensity 對 intraday RV 有很強同日 estimator 關係，且通常比 overnight variance 更貼近 intraday RV。
- **不可過度宣稱**：本實驗不支持「duration seasonality 顯著改善 RV 估計」；只支持「這個方向值得用更長 tick data 做正式 price-duration estimator」。

## 產物

- `experiment_price_duration_interday_intraday_vol_2026_06_14.py`
- `experiment_price_duration_interday_intraday_vol_2026_06_14_results.json`
- `fig_duration_seasonality.png`
- `fig_rmse_comparison.png`

## 重現

```bash
uv run python experiments/experiment_price_duration_interday_intraday_vol_2026_06_14/experiment_price_duration_interday_intraday_vol_2026_06_14.py
```
