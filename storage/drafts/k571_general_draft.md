---
title: VIX 均值回歸速度能用來擇時嗎？K571 給出 MARGINAL 答案
audience: general
status: draft
tags:
  - VIX
  - 均值回歸
  - 半衰期
  - 擇時策略
  - 嚴格統計
  - 一般讀者
experiment_refs:
  - K571
---

# VIX 均值回歸速度能用來擇時嗎？K571 給出 MARGINAL 答案

> 「VIX 是一條會回到平均的數列」是恐慌指數最廣為人知的性質——學術上稱為均值回歸（mean-reversion）。每次 VIX 衝破 25、30 甚至 80（COVID）之後，遲早會回到平靜的 15–20 區間。**真正的問題是：回得多快？而這個「速度」資訊，能不能拿來幫投資人決定何時把保護倉重新放回市場？** K571 實驗用 2004–2026 共 22 年的 SPY 與 ^VIX 日資料，把 97 次 VIX 突破 25 的尖峰事件都標出來，量化每次的回歸半衰期，並且把它做成可實戰的再進場訊號。本文照實揭露結果：訊號的方向是對的、樣本外多次贏過 baseline，**但統計上沒能跨過嚴格的 Harvey 門檻**——這是一個「方向有 hint、檢定不過」的 MARGINAL 結論。

[提出: 賴奕豪, 執行: Claude]

## 一、VIX 均值回歸：學術共識，但「速度」差異巨大

VIX 會均值回歸是 Whaley (2009, *Journal of Portfolio Management*) 與 Bollen & Whaley (2004) 等多篇文獻早已建立的事實。但「**速度**」不是常數：2020 年 3 月 COVID 把 VIX 推到 82，花了將近三個月才回到 20；2024 年 8 月 carry-trade 解倉那波 VIX 65，兩週就退潮；2007–08 GFC 的若干尖峰花了超過半年。

K571 把規則寫死：**每次 VIX 從 25 以下穿越到 25 以上算一個事件，記錄到 VIX 重新跌破 20 所需的天數（半衰期）**。22 年共 101 次事件，97 次能完整觀察。下面是分佈摘要：

![半衰期分佈與迴歸係數](/experiments/k571/k571_half_life_overview.png)

* 中位數半衰期 **20 天**、平均 **33.3 天**、標準差 **49 天**——這是一條**極度右偏**的分佈：多數事件兩到三週就過去，但少數壓力事件會把尾巴拉到 100+ 天。
* 用 peak VIX、回升速度（velocity）、SPY 同期 drawdown 三個變數迴歸半衰期：**R² = 0.835**（高解釋力），peak VIX 與 velocity 的係數都達到嚴格顯著（顯著性 0.000），SPY drawdown 也通過 5% 門檻。
* 換言之，**「這次回歸會多快」是事前可估計的**——不是亂猜。

## 二、把它做成擇時訊號：5 種變體一字排開

K571 把這個資訊接上一個簡單的權重策略：訊號用 12/VIX 規則作 baseline（VIX 越高就降低 SPY 權重），然後設計四個改良版：

| 策略 | 邏輯 |
|---|---|
| baseline 12/VIX | 經典再進場規則 |
| fast_reentry 14/VIX | 對「快速回歸」事件早一點重押 |
| slow_reentry 10/VIX | 對「慢速回歸」事件慢一點重押 |
| adaptive_peak | 視當次 peak VIX 動態調整 |
| regression_adaptive | 用迴歸預測值動態調整 |

樣本內（2004–2026 全段）的 Sharpe 比較：

![Sharpe 與 Harvey 嚴格門檻](/experiments/k571/k571_sharpe_vs_harvey.png)

* **方向是對的**：fast_reentry、adaptive_peak、regression_adaptive 三個策略 Sharpe 都贏 baseline（0.302 / 0.310 / 0.299 vs. 0.286）。
* **直覺反向的 slow_reentry 慢進場是輸**（Sharpe 0.248），這也對應「速度資訊有用」的假說。
* 但右圖告訴你嚴酷的故事：DM 比較檢定的統計強度（兩模型比較顯著值）落在 1.4–2.4 區間。**5% 的標準閾值是 ±1.96**，部分變體勉強跨過；**但 K571 採用的是 Harvey (2017, *Review of Financial Studies*) 嚴格門檻 |t| > 2.78**——沒有任何一個變體跨得過。

## 三、跨樣本外驗證：方向贏多次，仍不過嚴格門檻

光看樣本內結果不夠。K571 切了三段不重疊的 train/test：

![三段樣本外一致性](/experiments/k571/k571_cross_oos_consistency.png)

* OOS-1（2012–2015）、OOS-2（2018–2021）、OOS-3（2023–2026）三段中，**fast_reentry 與 regression_adaptive 都是 3 戰 3 勝 baseline**；adaptive_peak 是 2/3。
* 一致性方向強烈，但每段個別 DM 統計量仍多落在 1.3–2.4，沒有任一段達到 Harvey 嚴格門檻。
* 結論欄位：`harvey_pass: []`（空陣列）。verdict 是 K571 自己給的標籤——**MARGINAL: Some OOS improvement but no Harvey significance**。

## 四、為什麼用 Harvey 嚴格門檻，而不是寬鬆的 5%？

讀者可能會想：「DM 兩個變體 p < 0.05 不就夠了？」這正是 Campbell Harvey 在 *…and the Cross-Section of Expected Returns*（2017 RFS Presidential Address）批評整個資產定價文獻的核心：**過去 50 年文獻測試了 300+ 個 anomaly factor，若每個都用 5% 門檻，多重檢定下 false discovery 比率早已失控**。

Harvey 提議把臨界值拉到 **|t| > 3.0**（甚至 3.5），對應的有效顯著性遠低於 1%。這不是「任意嚴格」——而是承認「研究者面對 100 個假說時，5% 門檻會讓你 commit 到 5 個純運氣」。本研究遵守此標準是為了**避免把 over-fitted noise 包裝成可上架策略**。

## 五、那這個發現有沒有用？

**有，但不是上架策略**。K571 的 take-away 分兩層：

1. **機制層面**：VIX 半衰期可預測（R² = 0.835）+ 跨 OOS 方向一致勝出，**支持「速度資訊本身有訊號」這個假說**——它不是 noise。文獻上接得起來：Whaley (2009) 早就指出 VIX 的尖峰持續性與市場狀態相關。
2. **執行層面**：Sharpe 改善約 +0.01–0.02、年化超額報酬約 0.2%——**邊際幅度太小，不足以承擔 multiple-testing risk**。任何一個小手續費假設、一段不利市況，這個邊際就會蒸發。

下一步（已寫入 research backlog）：把 VIX 半衰期訊號**結合其他不相關訊號**做組合（K524 政策規則 / K503 12/VIX 結構訊號），看能不能在組合層次把 t-stat 推過嚴格門檻。**單一訊號 MARGINAL，不代表它沒貢獻**——只是它不能單獨上場。

## 結論：研究誠實的價值

K571 給的是一個 honest negative-leaning 結果：**方向贏、機制清楚、但通不過嚴格統計**。在我們的研究治理裡，這類 MARGINAL 結果不會被「好像有 alpha」的話術包裝後上架——但也不會被丟進垃圾桶。它會以這篇文章的形式公開、用真實的 t-stat 與 OOS 數據曝光，等待後續實驗把它接上更強的訊號群組。

把研究做誠實，比把每篇文章寫成「我們又找到一個賺錢策略」重要得多。

---

**資料來源**：yfinance（SPY、^VIX，2004-01-05 至 2026-03-26，5,592 筆日資料），全部統計量與 backtest 來自 `experiments/k571/k571_vix_mean_reversion_speed_results.json`。
