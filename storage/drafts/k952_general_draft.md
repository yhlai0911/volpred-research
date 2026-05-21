---
title: "門檻 ARMA 真的能打贏 GARCH 嗎？一場關於波動率預測的誠實檢驗"
audience: general
status: draft
tags: [波動率預測, 模型比較, SPY, 方法論, 失敗實驗]
experiment_refs: [K952]
---

# 門檻 ARMA 真的能打贏 GARCH 嗎？一場關於波動率預測的誠實檢驗

## 一句話結論

我們花了相當功夫，在 SPY 上實作了 Chen, Liu, Gerlach (2011) 提出的「門檻 ARMA（TARMA）」波動率模型，與經典的 GARCH 家族在十年資料上正面交鋒。最後得到的結論很樸實：**TARMA 沒有顯著贏過 GARCH**，連最寬鬆的比較標準也過不了關。這是一篇關於「研究失敗」的文章——但失敗本身有它的價值。

## 為什麼要研究這件事？

波動率（volatility）是金融市場最重要、卻也最難預測的變數之一。它直接影響選擇權定價、風險值（VaR）計算、避險比率，以及投資組合的槓桿配置。學界主流的工具是 1980 年代由 Engle 和 Bollerslev 發展起來的 GARCH 家族，但 GARCH 也有自己的限制——它假設波動率的演化是「平滑遞移」的，遇到劇烈的 regime shift 時反應可能不夠快。

於是學者們陸續嘗試各種替代品。其中一條路徑是：**直接對「絕對報酬」|r_t| 建立 ARMA 模型**，並允許參數在不同市場狀態下切換。這就是 TARMA（Threshold ARMA）。Chen, Liu, Gerlach 在 2011 年的論文中用 Bayesian Subset Selection 的方法，宣稱 TARMA 能捕捉 GARCH 遺漏的 MA 成分與非線性 regime 效應。

聽起來很有道理。所以我們決定動手驗證——在 SPY 這檔全世界流動性最好的 ETF 上，把 TARMA 與 GARCH 家族放在同一個競技場裡比一比。

## 實驗設計

| 設計要素 | 設定 |
|---|---|
| 標的 | SPY（S&P 500 ETF） |
| 資料來源 | yfinance（價格）、^VIX（恐慌指數） |
| 全樣本期間 | 2004-01-05 ~ 2026-04-02 |
| 樣本外（OOS）期間 | 2016-01-04 ~ 2026-04-02 |
| OOS 觀察數 | 2,577 個交易日 |
| 估計視窗 | rolling 2,000 天，每 21 天重新校準一次 |
| 預測目標 | |r_t|（當日絕對報酬，常用作波動率代理變數） |

樣本外橫跨 2016 到 2026，包含 2018 年的 Volmageddon、2020 年的 COVID 崩盤、2022 年的升息週期、2024-2025 年的 AI 行情，市場狀態的多樣性足以分辨真本事與運氣。

我們同時跑了 6 個模型：

1. **AR(5)**——基礎對照組，純自迴歸
2. **ARMA(2,1)**——加入移動平均成分
3. **TARMA(|r|)**——以前一日 |r_{t-1}| 為門檻變數，閾值取滾動中位數
4. **TARMA(VIX)**——以前一日 VIX 為門檻變數，閾值固定 20
5. **GJR(1,1,1)**——非對稱 GARCH，捕捉壞消息的放大效果
6. **MF-GJR(VIX)**——兩成分模型，σ² = τ(VIX) × g_t，把 VIX 當作長期波動率成分

所有預測都嚴格使用「t-1 之前的資訊預測 t」，沒有任何向前看（lookahead）的污染。隨機種子固定（seed=42）以利重現。

## 主結果：六個模型的成績單

下表是樣本外 2,577 天的核心評估指標。**MSE / MAE 越低越好**；**Spearman ρ 越高代表 ranking 能力越好**；**QLIKE 是 Patton (2011) 推薦的波動率專用損失函數，越低越好**。

| 模型 | MSE | MAE | Spearman ρ | QLIKE(r²) |
|---|---|---|---|---|
| AR(5) | 5.699e-5 | 0.004993 | 0.339 | 1.783 |
| ARMA(2,1) | 5.572e-5 | 0.004939 | 0.354 | 1.766 |
| TARMA(\|r\|) | 5.544e-5 | 0.004931 | 0.358 | 1.756 |
| TARMA(VIX) | 5.814e-5 | 0.004932 | 0.384 | 1.715 |
| **GJR(1,1,1)** | **5.224e-5** | **0.004851** | 0.415 | 1.665 |
| **MF-GJR(VIX)** | 7.490e-5 | 0.005067 | **0.455** | **1.590** |

![K952 模型比較圖](k952_comparison.png)

幾個關鍵觀察：

**第一，TARMA 確實比 AR/ARMA 略好。** TARMA(|r|) 的 MSE 比 AR(5) 改善了約 2.7%，比 ARMA(2,1) 略好一點點。這顯示「regime 切換」這個直覺方向沒有錯——讓參數在高低波動環境下不一樣，確實能榨出一點點額外的訊息。

**第二，GJR(1,1,1) 在點預測上全面領先。** 不論是 MSE 還是 MAE，GJR 都是最低。它比最好的 TARMA(|r|) 在 MSE 上又便宜了 5.8%。這個結果有點殘酷：GJR 早在 1993 年就提出，是個結構簡單到幾乎可以手算的模型，卻把 2011 年發表的 TARMA 在自家擅長的「直接建模 |r_t|」這條路上輾過去。

**第三，MF-GJR(VIX) 的 ranking 能力獨步全場。** 雖然它的 MSE 不漂亮（甚至比 AR(5) 還差），但 Spearman ρ = 0.455 與 QLIKE = 1.590 都是最佳。這代表：**它可能高估或低估了波動率的絕對水準，但它把「哪些日子比較波動」的相對順序排得最對。** 這在風險管理應用上其實非常有用——很多時候我們需要的是「今天比昨天危險嗎」而不是「今天波動率精確等於多少」。

## 統計強度檢驗：差異有沒有真的成立？

光看數字差距還不夠。我們用 Diebold-Mariano 框架做了兩模型比較檢定，並採用 Harvey 修正後的嚴格門檻（|t| > 3.0）作為「達顯著水準」的判準。

**關鍵發現：在 Harvey 嚴格統計檢驗門檻下，沒有任何一對模型的差距達到顯著水準。**

具體來說：

- TARMA(|r|) vs GJR(1,1,1)：DM 統計強度未達門檻，方向上 GJR 較佳
- TARMA(VIX) vs GJR(1,1,1)：未達門檻，方向上 GJR 較佳
- ARMA(2,1) vs GJR(1,1,1)：未達門檻，方向上 GJR 較佳
- TARMA(|r|) vs AR(5)：未達門檻，方向上 TARMA 較佳

換句話說，**雖然點估計上 GJR 看起來最好，但這個「最好」並沒有強到我們可以拍胸脯保證它在下一個十年還是最好**。模型之間的差距，落在統計雜訊的合理範圍內。

這是一個很重要的誠實聲明。在波動率預測這個領域，許多論文宣稱自己的新方法擊敗 GARCH，但若認真用 Harvey 門檻檢驗，往往不過關。我們的這個 null result 是這個學術現象的又一個例證。

## Regime 分析：TARMA 的長處與短處

雖然整體表現沒贏過 GJR，TARMA(VIX) 在不同 regime 下的表現仍透露一些訊息：

| Regime | MSE |
|---|---|
| VIX ≤ 20（低波動環境） | 2.329e-5 |
| VIX > 20（高波動環境） | 1.338e-4 |

低波動環境下，TARMA(VIX) 的誤差比整體平均小一個數量級。但在高波動環境下，誤差大幅放大——而高波動正是我們最需要準確預測的時候。

這個 pattern 暗示了一件事：**TARMA 的門檻切換機制在「平靜的市場」效果不錯，但在「真正動盪」的時候，反而是 GJR 那種具有 variance recursion 結構的模型更穩健。** GARCH 的優勢在於它有一個內建的「記憶」，能讓昨天的衝擊持續影響今天的預測；TARMA 的兩段式 ARMA 切換相對來說是更「短記憶」的。

## 為什麼這個失敗有價值？

讀者可能會問：既然結論是 TARMA 沒贏，那為什麼還要花一整個實驗去做、還要寫一篇文章告訴大家？

答案有三個。

**第一，研究誠實原則。** 在這個平台上，我們承諾每一個 K 編號的實驗結果都會誠實公佈，不論結果好壞。學術界長期存在「發表偏誤」（publication bias）——成功的方法被發表、失敗的方法被埋葬，導致後人誤以為某個方向「應該可行」，於是重複踩同樣的雷。把 null result 公開，本身就是對研究社群的貢獻。

**第二，方法論層面的釐清。** 這個實驗回答了一個具體的問題：**「直接對 |r_t| 建模的 ARMA 路徑，是否優於間接的 GARCH → |r| 轉換路徑？」** 答案是否定的。GARCH 雖然建模 σ² 而不是 |r|，但透過 σ × √(2/π) 換算回 |r| 後，仍然在點預測上更精確。這暗示了 variance recursion 結構的訊息密度高於 |r| 的 ARMA 演化。

**第三，給 MF-GJR(VIX) 一個亮點。** 這個實驗的副產品是發現 MF-GJR(VIX) 在 ranking 能力上的領先優勢。對於需要「相對風險排序」的應用（例如：哪些日子應該降低槓桿、哪些日子適合進場），MF-GJR(VIX) 可能是一個比點預測導向的 GJR 更好的選擇。這條線將在後續實驗中持續追蹤。

## 對讀者的實務啟發

如果你是個人投資者或風險管理者，這篇文章帶給你三個 takeaway：

1. **不要被新方法的論文嚇住。** 經典模型（GJR-GARCH）經得起時間考驗；新方法即使在頂級期刊發表，也未必在你關心的市場、你關心的時間段、你關心的指標上贏。
2. **要分清「點預測」與「ranking 預測」的需求差異。** 前者問「波動率是多少」，後者問「哪一天比較危險」。不同的需求，最佳模型可能不同。
3. **嚴格統計檢驗是必要的紀律。** 兩個模型 MSE 差個 5%，看起來像贏了；但若用 Harvey 門檻檢驗，可能根本連顯著都不到。沒有顯著性的「贏」，未必能複製到下一個十年。

## 後續方向

這次實驗指出幾條值得追的線索：

- **MF-GJR 的 ranking 優勢能否轉化為策略 alpha？** 如果它能正確排序「哪天危險」，那麼在 VT（volatility targeting）或槓桿動態調整上應該有實際效益。
- **TARMA 是否在其他資產上表現不同？** SPY 的市場效率極高，可能不利於 TARMA 這類捕捉 regime 切換的模型；新興市場、加密貨幣或商品類資產或許是更合適的舞台。
- **能否將 TARMA 的 regime 切換邏輯與 GARCH 的 variance recursion 混合？** 例如「regime-dependent GJR」。這是個自然的下一步研究方向。

## 資料來源

- **價格資料**：yfinance（SPY、^VIX），抓取期間 2004-01-05 ~ 2026-04-02
- **樣本外評估期間**：2016-01-04 ~ 2026-04-02，共 2,577 個交易日
- **完整實驗檔案**：`experiments/k952/`（含 README、Python 腳本、結果 JSON、比較圖）
- **實驗編號**：K952
- **隨機種子**：seed=42（重抽樣與模型估計皆已固定）

## 參考文獻

- Chen, C. W. S., Liu, F. C., & Gerlach, R. (2011). Bayesian Subset Selection for Threshold Autoregressive Moving-Average Models. *Computational Statistics*, 26(1), 1-30.
- Patton, A. J. (2011). Volatility forecast comparison using imperfect volatility proxies. *Journal of Econometrics*, 160(1), 246-256.
- Glosten, L. R., Jagannathan, R., & Runkle, D. E. (1993). On the Relation between the Expected Value and the Volatility of the Nominal Excess Return on Stocks. *Journal of Finance*, 48(5), 1779-1801.
- Diebold, F. X., & Mariano, R. S. (1995). Comparing Predictive Accuracy. *Journal of Business & Economic Statistics*, 13(3), 253-263.
- Harvey, D., Leybourne, S., & Newbold, P. (1997). Testing the equality of prediction mean squared errors. *International Journal of Forecasting*, 13(2), 281-291.
