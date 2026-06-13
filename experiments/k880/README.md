# K880

- Experiment ID: `K880`
- Type: empirical
- Status: completed with post-publication code review follow-up
- Script: [`experiments/k880/k880_prg_spy_validation.py`](/Users/yhlai0911/Desktop/volpred-research/experiments/k880/k880_prg_spy_validation.py)
- Results: [`experiments/k880/k880_results.json`](/Users/yhlai0911/Desktop/volpred-research/experiments/k880/k880_results.json)

## 問題描述

驗證 PRG（periodic GARCH）從 TAIFEX 移到美股 SPY 日資料後，是否仍能在共同目標
`sigma2_fullday = r2_overnight + r2_intra` 上優於傳統波動率模型，並分辨：

- PRG 的優勢是否來自 session cross-recursion
- at-open 使用已實現 overnight 資訊後，和 close-only baseline 是否仍算公平比較
- 在多重比較、HLN MCS、VaR backtest 下結論是否穩健

## 資料來源與樣本

- 標的：SPY
- 資料來源：`yfinance` 日 OHLC
- 全樣本期間：2000-01-04 至 2026-04-02（以 `k880_results.json` 為準）
- In-sample：2000-01-03 至 2018-12-31
- Out-of-sample：2019-01-02 至 2026-04-02
- OOS 樣本數：1823 個交易日

日內拆解定義：

- `r_overnight = log(open_t / close_{t-1})`
- `r_intra = log(close_t / open_t)`
- `sigma2_fullday = r2_overnight + r2_intra`

## 動機

- K874 系列在 TAIFEX 找到 PRG 對 GJR 的顯著優勢，但該優勢可能是台灣市場結構特有。
- SPY 可作為跨市場 sanity check：如果優勢可移植，PRG 才有較強的通用性主張。
- 2026-06-13 的 Codex 24h review 指出原始版本存在 timing fairness、DM 實作與 MCS 方法論缺口，因此本實驗 README 與程式一併補強。

## 模型與方法

比較模型：

1. `GJR`：close-to-close GJR-GARCH(1,1)
2. `HAR`：對 `sigma2_fullday` 做 HAR proxy
3. `PRG_Basic`：6 參數 periodic GARCH
4. `PRG_Extended`：8 參數 periodic GARCH，at-open 版本，使用已實現 `overnight_t`
5. `PRG_Extended_tminus1`：嚴格 `t-1` day-ahead 公平版本，不使用當日 overnight realization
6. `Separate`：overnight / intraday 各自獨立 GARCH，無 cross-recursion

評估層：

1. Loss：QLIKE、MSE、MAE、HMSE、Mincer-Zarnowitz R²
2. MCS：`src/volpred/stats/mcs.py` 的 HLN stationary bootstrap MCS
3. Spearman：stationary bootstrap CI + 252 日 rolling stability
4. VaR：1% / 5% Kupiec、Christoffersen、Basel traffic light
5. DM：pairwise QLIKE DM，回報 raw / Bonferroni / Benjamini-Hochberg p-values

研究誠實與防錯：

- PRG at-open 版本明確標示使用 `overnight_t`，不再混稱 strict day-ahead
- 補一個 `PRG_Extended_tminus1` 與 close-only baseline 做公平 horserace
- bootstrap / refit 隨機流程固定 seed

## 主要結果

2026-06-13 follow-up 重跑後，主結果變為：

- `PRG_Basic` 是最佳 QLIKE 模型：0.7546
- `PRG_Extended` 仍優於 `GJR`：DM t=5.06，Bonferroni p=`6.78e-06`，BH p=`6.16e-07`
- 新增的 `PRG_Extended_tminus1` 對 `GJR` 不再顯著：DM t=-1.48，Bonferroni p=`1.00`
- HLN MCS 只保留 `PRG_Basic` 與 `PRG_Extended`
- `PRG_Extended` 對 `Separate` 仍顯示 cross-recursion value：DM t=-5.69
- SPY overnight variance share 約 34.5%

這代表原始文章必須區分兩件事：

- at-open PRG 在 SPY 上仍有優勢
- 一旦改成嚴格 `t-1` 公平 horserace，優勢明顯縮水，不能再把 at-open 結果寫成 strict day-ahead 勝利

## 限制

- 資料是日 OHLC proxy，不是高頻 realized volatility 或可交易的即時 order book
- at-open 與 strict `t-1` 是兩種不同資訊集，解讀時不可混用
- SPY 單一市場的 cross-market 驗證仍不足以推出「PRG 普適優於所有 baseline」
- 若要重現最新結果，需重新執行腳本產生新 `k880_results.json`

## 重現方式

```bash
uv run python experiments/k880/k880_prg_spy_validation.py
```

輸出：

- `experiments/k880/k880_results.json`
- `experiments/k880/k880_charts/qlike_comparison.png`
- `experiments/k880/k880_charts/rolling_qlike_ratio.png`
- `experiments/k880/k880_charts/prg_scatter.png`

## 相關審查

- [`experiments/k880/reviews/codex_24h_review_mile_862223de.md`](/Users/yhlai0911/Desktop/volpred-research/experiments/k880/reviews/codex_24h_review_mile_862223de.md)
