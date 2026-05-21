---
title: "GARCH 參數固定 vs 滾動估計，哪個贏？K635：固定贏在 QLIKE 也贏在 Sharpe"
audience: general
phase: K635_fixed_vs_rolling
tags: garch,vt,fixed-params,rolling-refit,parameter-stability,prediction-application
experiment_refs:
  - K635
---

# GARCH 參數固定 vs 滾動估計，哪個贏？K635：固定贏在 QLIKE 也贏在 Sharpe

## 一個寫量化研究的人遲早會遇到的選擇

只要你做過 GARCH 波動率預測，幾乎一定會碰到這個技術問題：**GARCH 的參數要每次重新估嗎？**

學界與實務界的標準做法是**滾動重估**（rolling refit）：每隔一段固定長度（每天、每月、每季）把過去 N 年的資料丟進去，重新估一次 $\omega$、$\alpha$、$\beta$、$\gamma$。直覺上很合理 — 市場結構會變，參數不該停在 5 年前。

但這個直覺有一個假設：**參數真的會變，而且變得夠多，值得每月花估計成本去追**。如果參數本身就很穩定，每月重估反而引入估計雜訊（estimation noise），讓預測更差，還順便多出換倉成本。

K634 已經告訴我們：對 SPY 而言，GARCH 參數的 persistence 變動係數（CV）只有 0.011 — 幾乎不動。那把這個發現往下推一層：**如果預測層（QLIKE）固定贏，那策略層（VT 的 Sharpe）會跟著贏嗎？**

這是 K635 想回答的問題。答案直白：**就 GARCH 參數的選擇而言，固定贏，QLIKE 贏，Sharpe 也贏。**

但這個結論有重要的前提條件 — 不是所有「固定」都會贏，需要仔細說明。

## K635 的設計

K635 在 SPY 上比較三種波動率估計方法 + 兩個外部基準：

| 編號 | 策略 | 估計方式 |
|---|---|---|
| 1 | **Rolling VT**（基準） | GJR-GARCH，每 21 日用過去 W=2000 資料重估參數 |
| 2 | **Fixed VT**（K634 啟發） | GJR-GARCH，僅在 OOS 開始**前一次**估參數，OOS 期間參數不動 |
| 3 | **EWMA VT** | 不用 GARCH，純 $\lambda=0.94$ 指數加權移動變異 |
| 4 | 12/VIX VT | 不用任何模型，純 VIX overlay |
| 5 | Buy & Hold SPY | 最低基準 |

實驗條件：

- 資料：SPY（yfinance），分析期間 2006-01-01 起，OOS 2023-01-01 至 2024-12-31，共 502 個交易日
- 目標年化波動：10%；持倉上限 150%、下限 0%（不放空）
- 交易成本：2 bp round-trip
- Fixed 參數估計：用 OOS 開始之前所有可用樣本（>4,000 obs）一次性 MLE
- 統計檢定：QLIKE 的 Diebold-Mariano 兩模型比較

固定參數的數值（一次估完之後 OOS 期間不動）：

| 參數 | SPY 估計值 | 詮釋 |
|---|---|---|
| $\omega$ | 3.00 × 10⁻⁶ | 變異常數項 |
| $\alpha$ | 0.0148 | 對稱衝擊係數 |
| $\gamma$ | **0.219** | leverage 不對稱（負衝擊放大波動） |
| $\beta$ | 0.855 | persistence |
| $\alpha+\gamma/2+\beta$ | **0.980** | 總 persistence（接近 1，極度持續） |

$\gamma=0.219$ 是 SPY 典型的 leverage effect — 負報酬會比同等正報酬多觸發 21.9% 的條件變異。這個數字在過去 18 年的 SPY 樣本上極穩定（K634：100% 滾動窗口都是正值），這是「固定參數能贏」的結構性理由。

## 結果一：QLIKE — 固定顯著贏，DM p < 0.0001

預測準度層次先看 QLIKE：

![K635 QLIKE 比較：Fixed vs Rolling vs EWMA](/experiments/k635/k635_qlike_comparison.png)

| 方法 | OOS QLIKE（小=好） |
|---|---|
| Rolling refit（每 21 日） | 1.4924 |
| **Fixed pre-OOS** | **1.4644** |
| EWMA (λ=0.94) | 1.5227 |

**Fixed 比 Rolling 低 0.028**（1.9% 改善），看起來小，但 DM 檢定下：

- DM 統計量 = 4.078
- p 值 = 4.5 × 10⁻⁵

兩模型比較**極為顯著** — 在 502 個 OOS 觀察上，rolling 預測的 squared loss 系統性高於 fixed。EWMA 則明顯落後兩者。

這證實了 K634 在 SPY 上的核心發現：**頻繁重估 GARCH 帶來的估計雜訊，超過它能捕捉的真實參數變動**。

## 結果二：Sharpe — 固定也贏，但與滾動差距溫和

接下來是策略層次：

![K635 各策略 Net Sharpe 比較（SPY OOS 2023-2024）](/experiments/k635/k635_sharpe_comparison.png)

| 策略 | 年化報酬 | 年化波動 | 淨 Sharpe（扣 2bp） | 換倉次數 |
|---|---|---|---|---|
| Rolling VT | 15.69% | 10.01% | 1.5345 | 247 |
| **Fixed VT** | **16.08%** | 9.96% | **1.5901** | **65** |
| EWMA VT | 16.50% | 10.22% | 1.6013 | 40 |
| 12/VIX VT | 23.77% | 8.98% | 2.6285 | 117 |
| Buy & Hold SPY | 23.66% | 12.80% | 1.8485 | — |

**Fixed VT 淨 Sharpe = 1.5901 vs Rolling VT 1.5345，差距 +0.056**。同時：

- 換倉次數從 247 降到 65（**減少 74%** — 與 K634 在 SPY 預測層的觀察一致）
- 平均日權重變化從 0.064 降到 0.048（**降 25%**）
- 年化報酬高 0.39 個百分點，年化波動還略低 0.05 個百分點

Sharpe 差距 +0.056 在直覺上不大，DM 經濟損失差異統計（p≈0.183）也未達兩模型比較顯著。**所以 Sharpe 維度上，「固定贏」是一致方向但不是強統計**。

但這正是這篇研究真正的價值所在 — 你不會因為改用固定參數就賺爆，但你也**不會輸**，反而換倉成本減少 74%、權重平穩度提升 25%。對實務操作而言，這是純粹的 win-win。

至於 12/VIX 為什麼遠勝兩者（Sharpe 2.63） — 它跟「固定 vs 滾動 GARCH」是不同的話題，K634 / K476 / K656 等實驗已經處理過，不在 K635 比較範圍。本文只專注在「**GARCH 參數的選擇**」這個層次。

## Prediction-application aligned：一個重要也容易誤讀的訊號

K635 的真正貢獻不是「固定贏 0.056 Sharpe」，而是 **prediction 與 application 在 SPY 上方向一致**：

- QLIKE 贏家 = Fixed
- Sharpe 贏家 = Fixed
- 結論 = `prediction_application_aligned`

這在我們研究記錄中是少見的「對齊」案例。在 K459 / K474 / K476 / K603 等實驗中，QLIKE 改善常**沒有**翻譯成策略層次的 Sharpe 改善（甚至有反向案例）— 我們稱之為「prediction ≠ application」原則。

K635 的對齊意味著：**對 GARCH 參數選擇這個維度而言，QLIKE 是策略表現的合理代理變數**。研究者可以在預測層次先用 QLIKE 篩選候選方法，相對放心地推到策略層測試。

但要強調 — 這個 alignment **特定於「GARCH 參數固定 vs 滾動」**這個比較。它**不能推論**：

- 「QLIKE 贏的方法都會 Sharpe 贏」（K603 反面案例）
- 「固定參數在所有資產類別都贏」（K634 中 GLD 的 leverage 不穩，固定可能不適用）
- 「固定優於所有 EWMA / VIX overlay 方法」（K635 中 12/VIX 顯然更強）

## 與既有結論的鏈結

K635 是 SPY 上「固定參數穩健性」研究鏈的策略層收尾：

| K | 層次 | 發現 |
|---|---|---|
| K571 | 設計 | 固定窗口 W=2000 最穩 |
| K550 | 細節 | 月度 vs 季度 refit 無顯著差異 |
| K594 | 動態 | 動態切換 W 的 NULL：固定贏 |
| K603 | 跨期 | 跨五個 OOS 期間，固定參數 robust |
| **K634** | 預測 | Fixed QLIKE 顯著低於 Rolling（DM p<0.001） |
| **K635** | 策略 | Fixed Sharpe 略高 + 換倉減 74%（本文） |

整體故事：對 SPY 這類 leverage effect 強且穩定的標的，**「該用對窗口」比「該頻繁更新」更重要**。

## 對讀者的實務啟示

1. **如果你跑 SPY 的 VT 策略**：別預設「每月重估」是最佳；先比較固定參數版本，至少 break-even，多半略勝且交易成本明顯降低。

2. **如果你做 GARCH 預測研究**：在 SPY 樣本上 fixed-pre-OOS baseline 是合理的「不過擬合」對照，rolling-refit 不應自動被當作 ground truth。

3. **跨資產別硬套**：K634 已警告 GLD 的 leverage gamma 不穩（148 個窗口中 52% 為負）— 對黃金、商品、新興市場 ETF，「固定」是否仍贏需要重新驗證，**不可外推**。

4. **未來方向**：把 K635 的 design 推到 0050.TW、TAIFEX、外匯等市場 — 我們仍缺非美股市場的 fixed-vs-rolling 證據。

## 參考文獻

- Andersen, T. G., & Bollerslev, T. (1998). "Answering the skeptics: Yes, standard volatility models do provide accurate forecasts." *International Economic Review*, 39(4), 885-905.
- Hillebrand, E. (2005). "Neglecting parameter changes in GARCH models." *Journal of Econometrics*, 129, 121-138.
- Hansen, P. R., & Lunde, A. (2005). "A forecast comparison of volatility models: does anything beat a GARCH(1,1)?" *Journal of Applied Econometrics*, 20, 873-889.
- Fleming, J., Kirby, C., & Ostdiek, B. (2001). "The economic value of volatility timing." *Journal of Finance*, 56(1), 329-352.

---

*實驗腳本：experiments/k635/k635_fixed_vs_rolling_vt.py*
*結果數據：experiments/k635/k635_results.json*
*資料來源：yfinance (SPY)，OOS 期間 2023-01-01 至 2024-12-31，n=502*
*[提出: 用戶, 執行: Claude]*
