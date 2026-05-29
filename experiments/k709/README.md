# k709

- Experiment ID: `k709`
- Status: completed_rebuild
- Created At: `2026-04-16T09:40:33.621493+00:00`
- Rebuilt At: `2026-05-29`

## 問題描述

重建 production article `mile_ada624d5` 對應的 K709 artifact。原始狀態只有：

- `k709_results.json` 三個數字
- `README.md` 全 placeholder
- `data/`、`references/` 空目錄
- 無 `k709.py`

因此無法驗證文章中的：

- 降息時 `GLD +30.8%` vs `SPY +13.4%`
- regime 佔比 `21% / 62% / 19%`
- `Sharpe 0.850 vs 0.869`
- 「使用 6 個月前已確認的利率環境」這個 anti-lookahead claim

## 動機

這次重建的目標不是替舊文硬湊數字，而是把 K709 變成可重現、可審查、可驗證的實驗：

1. 明確分開「事後描述性分群」與「可交易 lagged strategy」
2. 補齊原始資料快照與腳本
3. 對小幅 Sharpe 差異補上正式不確定性檢定
4. 說清楚原文哪些 claims 可以重建、哪些不能精準對回

## 方法

### 資料

- Source: yfinance `SPY`, `GLD`, `^TNX`, `^IRX`
- Price field for return computation: `Adj Close`
- Sample download window: `2005-12-01` to `2026-05-29`
- 實際有效報酬樣本：見 `k709_results.json`

資料快照輸出到 `data/`：

- `SPY_yfinance_snapshot.csv`
- `GLD_yfinance_snapshot.csv`
- `TNX_yfinance_snapshot.csv`
- `IRX_yfinance_snapshot.csv`
- `adj_close_panel.csv`

### Regime 定義

- `lookback = 126` 交易日，約 6 個月
- `delta_tnx_126 = TNX_t - TNX_{t-126}`
- `delta > +0.50` → `rising`
- `delta < -0.50` → `falling`
- 其餘 → `stable`

這個 `+/-50bp` 門檻是 best-faith reconstruction，因為它能重現原文最醒目的描述性數字：

- falling regime: `GLD ≈ 30.8%`, `SPY ≈ 13.4%`
- occupancy 約 `21/61/19`

### 兩套分析必須分開

1. **Descriptive same-day regime stats**
   - 用當天已知的 trailing-126d rate regime 直接切片
   - 這是事後描述，不是可交易策略

2. **Tradable lagged strategy**
   - 先把 regime label 再 `shift(126)`，只用 6 個月前已確認的 regime
   - 每月月底凍結 signal
   - 下個月整月使用固定配置
   - 配置規則：
     - `rising`: `60% SPY / 40% GLD`
     - `stable`: `50% SPY / 50% GLD`
     - `falling`: `40% SPY / 60% GLD`
   - Benchmark: 每月再平衡 `50/50 SPY/GLD`

### 檢定

- `DM-HLN`：日報酬差異（以 `loss = -return` 表達）
- `Jobson-Korkie-Memmel`：Sharpe difference
- `Moving block bootstrap`
  - block size = `21` 交易日
  - reps = `2000`
  - seed = `42`

## 結果摘要

### A. 描述性分群（same-day）

在 `+/-50bp` 規則下，falling regime 的描述性數字確實接近原文：

- `GLD annualized ≈ 30.8%`
- `SPY annualized ≈ 13.4%`
- occupancy 約 `20.8% / 60.5% / 18.7%`

也就是說，原文 headline 的大數字可以由**事後分群**重建。

### B. 可交易 lagged strategy

可交易版本的結果則明顯小很多，而且沒有重現舊文的 `+0.019`：

- conditional Sharpe（rf=0）約 `0.851`
- benchmark Sharpe（rf=0）約 `0.853`
- `ΔSharpe ≈ -0.002`
- threshold sensitivity（`0.48~0.50`）也只在 `+0.003` 到 `-0.003` 間波動

這說明精確的 `0.850 vs 0.869` 並沒有在同一組 surviving spec 下被完整重現。

### C. Claim reconciliation

重建後最重要的發現不是「原文全錯」，而是：

- `30.8% / 13.4%` 來自 **same-day descriptive slicing**
- 公平的月頻 lagged tradable backtest 並沒有推出 `+0.019`
- 沒有單一 surviving artifact 能同時精準推出原文所有數字

最合理解釋是：原文把**描述性分群結果**與**可交易回測結果**放在同一篇敘事中，但當時沒有留下足夠 provenance 讓兩者可被嚴格對回。

## 結論

1. K709 現在已符合「三件套」最低要求：`README + k709.py + results.json`
2. 原文 headline 的 falling-regime return gap 可重建
3. 原文小幅 Sharpe 優勢未被重建，不能 1:1 驗證
4. K709 的正確口徑應是：
   - **描述性上**：rate regime slice 看起來有大差距
   - **可交易上**：lagged implementation 的增益很小，且統計上不強
5. 這個重建支持把 K709 視為 **null / weak-effect result**，不支持強宣稱

## 產物

- Script: `k709.py`
- Results: `k709_results.json`
- Figures:
  - `k709_regime_occupancy.png`
  - `k709_regime_returns.png`
  - `k709_sharpe_compare.png`
- Notes: `references/method_notes.md`
