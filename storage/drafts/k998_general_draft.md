---
title: "看起來很準，卻完全沒用：一個 GARCH 指標的預測失敗紀錄"
audience: research
status: draft
phase: garch
tags:
  - VRP
  - GARCH
  - 波動率
  - NULL結果
  - 研究誠實
  - 過度擬合
  - 變異風險溢酬
experiment_refs:
  - K998
---

# 看起來很準，卻完全沒用：一個 GARCH 指標的預測失敗紀錄

**數據**：SPY 2005-01-05 至 2026-04-07，共 5,346 個交易日  
**OOS 樣本**：2019-01-01 起，共 1,825 天  
**實驗編號**：K998

---

## 故事從一個好消息開始

在上一個實驗 K988b 裡，我們發現 MF-GJR-X 類模型的 g proxy 和 VRP 有很高的同期 rank correlation。這很容易讓人產生一個想法：如果 g 能提前看出 VRP 的方向，或許可以設計一個 variance swap 交易訊號。

K998 專門測這件事。它不問「g 是否和當下狀態一起動」，而是問更嚴格的問題：g 能不能預測未來 VRP，並在樣本外變成有用的交易訊號？

---

## 三層檢驗

第一層是 Granger causality test。短期 horizon 看起來很漂亮：

| 預測期間 | F 統計量 | p 值 | 顯著？ |
|---------|---------:|------:|-------|
| 1 天後（h=1） | 66.17 | < 0.001 | 是 |
| 5 天後（h=5） | 32.03 | < 0.001 | 是 |
| 10 天後（h=10） | 17.95 | < 0.001 | 是 |
| 22 天後（h=22） | 2.12 | 0.146 | 否 |

![K998 圖一：Granger F 統計量顯著，但 Newey-West t 統計量未達 Harvey 門檻](experiments/k998/k998_fig1_granger_vs_harvey.png)

如果只看這張表，你會覺得這個指標很有用。但這只是樣本內線性關係，不等於可靠預測。

第二層是預測迴歸。我們控制 VRP 自身 lag 後，看 g 的係數是否還有增量，並用 Newey-West 標準誤與 Harvey et al.（2016）建議的 `|t| > 3.0` 門檻。

| 預測期間 | NW t 統計量（g 係數） | 通過 Harvey 門檻？ |
|---------|----------------------:|-------------------|
| h=1 | -2.15 | 否 |
| h=5 | -1.91 | 否 |
| h=10 | -1.61 | 否 |
| h=22 | -1.40 | 否 |

所有 horizon 都沒有過 `|t| > 3.0`。g 在 Granger 表裡看起來強，但控制 VRP 自身 lag 後，沒有達到金融預測因子該有的保守門檻。

第三層是樣本外 R²。2026-06-16 的 code review 修正了 h-step expanding OOS R² 的 target-alignment：每次預測 `t+h` 時，訓練資料只包含 target date 已經實現的 pair，避免 h>1 時偷看到 `t+1` 到 `t+h-1` 的 outcome。

| 預測期間 | OOS R²（純 g 模型） | OOS R²（AR1 + g） |
|---------|--------------------:|------------------:|
| h=1 | +0.011 | -0.053 |
| h=5 | -0.033 | -1.241 |
| h=10 | -0.068 | -3.859 |
| h=22 | -0.011 | -0.018 |

有效評估樣本為 1,530-1,572 天。h=1 的純 g 模型有微小正值，但簡化 CW-style 一側檢定不顯著（p=0.452）。h=5 以上全部為負，AR1+g 在 h=5 和 h=10 甚至大幅輸給歷史均值。

---

## 策略測試

最後看交易。K998 的 variance swap 訊號實作如下：

- 用前一天的 g 值作為訊號（`signal.shift(1)`）
- g 高於 expanding median -> 賣波動率，收 VRP
- g 低於 expanding median -> 買波動率

策略在 OOS 期間（2019-2026，n=1,573 天）的成績：

| 策略 | 年化 Sharpe |
|------|------------:|
| g 訊號策略 | -1.06 |
| Naive 永遠賣波動率 | +0.85 |

![K998 圖二：lookahead-clean OOS R² 與策略 Sharpe](experiments/k998/k998_fig2_oos_r2_sharpe.png)

這是最直接的判決。用 g 做訊號，結果比什麼都不看、永遠賣波動率還差很多。統計上看起來有關係的東西，搬到交易上反而變成負貢獻。

---

## 為什麼 Granger 顯著，預測卻失效？

同期狀態 proxy 不等於前瞻預測能力。MF-GJR-X 的 g component 反映的是模型裡的 variance decomposition，它可以和市場壓力同時變化，但這不代表它知道明天或下週的 VRP 會往哪裡走。

VRP 本身也很吵。K998 的 OOS 期間裡，VRP 日頻一階自相關只有 0.20；年化均值約 79 bps，但年化標準差高達 1,362 bps。訊噪比太低時，樣本內 Granger 顯著很容易在樣本外消失。

這也是 NULL result 值得公開的原因。K998 記錄的是一個明確失敗：g 成分沒有通過 Harvey 門檻，lookahead-clean OOS R² 幾乎全負，交易 Sharpe 也輸給 naive baseline。它告訴我們不要把 MF-GJR-X 的 g 成分拿去當 VRP timing signal。

---

## 限制

- VRP proxy 是日頻近似：`(VIX_{t-1}/100)^2/252 - r_t^2`，不是 option-level model-free VRP。
- OOS 含 COVID 極端期，會放大 VRP 雜訊。
- 只測 SPY，未跨資產驗證。
- results JSON 的 `CW_*` 欄位是簡化 DM-style/CW-style 一側檢定，不是完整 Clark-West nested-model adjustment。

下一步若要繼續，應該改測截面 VRP 差異，而不是單一資產的日頻時間序列 timing。

---

*本文所有統計數字均來自 K998 實驗（`experiments/k998/k998.py`，結果：`experiments/k998/k998_results.json`）。資料來源：yfinance SPY 與 ^VIX；資料期間 2005-01-05 至 2026-04-07，OOS 自 2019-01-01。*
