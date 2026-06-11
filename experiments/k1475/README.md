# K1475: 11-訊號 Momentum Composite vs 純價格動能（Honest Proxy）

## 研究問題

多加 11 個價格/風險/流動性訊號做 equal-weight composite，能不能比單一 `12_1`
價格動能更能改善尾部風險？

這個 task 的原始方向來自 2025 前後的 multidimensional momentum 題目，但 repo
內沒有對應論文級美股截面 panel，且 sandbox 不能即時連 Yahoo。依研究誠實原則，
本實驗採 **honest proxy**：

- 用 repo 已落地的本地 ETF 快照 `experiments/k1090b/data/`
- 做同一 universe、同一月頻 rebal、同一交易成本下的 apples-to-apples 比較

## 文獻動機

本實驗的動機不是重新證明 momentum 存在，而是檢驗「多訊號組合是否能減少 crash / MDD」：

1. Moskowitz, Ooi, Pedersen (2012), *Time Series Momentum*  
2. Barroso, Santa-Clara (2015), *Momentum Has Its Moments*  
3. Levy, Lopes (2021), *Trend-Following Strategies via Dynamic Momentum Learning*  
4. Lu et al. (2025), *TrendFolios*  

對本題真正 relevant 的共同點是：大家都在問 momentum 的**訊號組合**或**風險控管**
能否改善單一 lookback 規則的脆弱性。

## 資料

- **來源**：`experiments/k1090b/data/*.csv` 本地快照
- **期間**：2018-01-02 至 2024-12-30
- **實際分析期間**：2019-01-31 至 2024-12-30
  原因：需要 252 日 warmup 來計算 `12_1` 與 52 週高點等訊號
- **樣本數**：1,489 個交易日 / 72 個月
- **Seed**：42

### Ranked Universe（11 檔）

- SPY
- QQQ
- IWM
- EEM
- EWJ
- FXI
- VGK
- GLD
- TLT
- USO
- SLV

### Defensive fallback

- `IEF`

## 方法

### 基準策略：Pure Price Momentum

- 月底 `t` 計算 `12_1` 動能：`t-252` 到 `t-21`
- 只在 `12_1 > 0` 的資產中排序
- 持有前 3 名，等權
- 若不足 3 檔，剩餘權重停在 `IEF`

### 挑戰策略：11-Signal Composite

月底 `t` 對每個資產計算 11 個訊號，先做**橫截面 percentile rank**，再等權平均：

1. 1 個月報酬
2. 3 個月報酬
3. 6 個月報酬
4. `12_1` 價格動能
5. 1 個月日 Sharpe proxy
6. 3 個月日 Sharpe proxy
7. 6 個月日 Sharpe proxy
8. 距離 52 週高點
9. 過去 63 日上漲日占比
10. 短長期美元成交額趨勢 `log(21d / 126d)`
11. 負的 63 日 downside volatility

其餘持有規則與基準相同：

- 仍要求 `12_1 > 0` 才有資格入選
- 前 3 名等權
- 不足部位補 `IEF`

### Timing discipline

- 所有訊號只使用月底 `t` 當下或更早資料
- 倉位從 **下一個交易日** 開始持有，到下次月底 rebal
- 沒有 same-day signal × same-day return

### 交易成本

- 每次權重變動收 `10 bps`

### 評估

- 年化報酬、年化波動、Sharpe、Sortino、Calmar
- Max Drawdown
- `Harvey t`（daily mean/std 口徑）
- 月報酬 Newey-West mean t
- 3 個月 block bootstrap（5,000 次）比較：
  - challenger Sharpe 勝率
  - challenger CAGR 勝率
  - challenger MDD 較佳勝率

## 主要結果

### 全樣本（2019-01-31 至 2024-12-30）

| Strategy | Ann Ret | Ann Vol | Sharpe | MDD | Turnover |
|---|---:|---:|---:|---:|---:|
| Pure `12_1` momentum | 9.24% | 17.15% | 0.538 | -20.31% | 5.70x |
| 11-signal composite | 7.01% | 17.54% | 0.400 | -32.42% | 9.20x |

### Bootstrap

- `P(Composite Sharpe > Baseline Sharpe) = 0.262`
- `P(Composite CAGR > Baseline CAGR) = 0.326`
- `P(Composite MDD better) = 0.177`
- 平均 MDD 差（composite - baseline） = **-6.28 個百分點**

這不是邊際輸，而是**大方向就不成立**。

## Crisis / Subperiod 解讀

### COVID crash（2020-02-19 至 2020-03-23）

- Baseline：-14.41%，MDD -19.14%
- Composite：-11.66%，MDD -16.53%

這裡 composite 的確比較穩。

### 2022 rate shock（2022-01-03 至 2022-10-14）

- Baseline：-7.59%，MDD -18.12%
- Composite：-24.65%，MDD -32.42%

但 2022 這段把前面的 tail 改善幾乎全部吐回去，而且更差。

### 子期間

- **2019**：baseline 明顯較強（Sharpe 1.25 vs 0.68）
- **2020-2021**：composite 較強（Sharpe 1.34 vs 0.77）
- **2022-2024**：composite 轉負 Sharpe（-0.25），baseline 仍為正（0.25）

## 結論

在這個本地 honest-proxy 設定下：

1. **11 訊號等權 composite 沒有改善尾部**
2. 它不只 MDD 更深，Sharpe 也更差
3. 它唯一可說的優點是 2020 crash 略穩，但這個優勢在 2022-2024 完全失效
4. 多訊號組合在這裡更像是**增加換手與噪音**，不是穩定的 tail fix

最誠實的讀法是：

> 「多加很多合理訊號」不等於「能穩定修掉 momentum 的尾部問題」。

## 與 queue 題目的關係

原題是：

> 多訊號 momentum composite 改善尾部：11 訊號等權 vs 純價格動能

本實驗給出的 verdict 是：

- **在本地可重現 proxy 上，不支持。**

不是說這個研究方向永遠錯，而是：

- 目前這個 repo 內可驗證資料條件下
- 這個簡單 equal-weight composite
- 沒有交出更好的 tail profile

## 限制

1. 這不是論文原始 stock-level panel，而是 ETF honest proxy
2. 樣本只有 2018-2024，涵蓋 72 個月，不算長
3. 11 個訊號都來自價格/成交額；沒有基本面、分析師修正、macro release 等 richer signal
4. Equal-weight aggregation 很樸素，沒有學習權重

## 檔案

- `k1475.py`
- `k1475_results.json`
- `k1475_equity_drawdown.png`
- `k1475_metrics.png`
