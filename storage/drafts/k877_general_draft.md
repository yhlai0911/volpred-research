---
title: "金銀比能預測美股波動嗎？一個 NULL 結果"
audience: general
status: draft
tags: [金銀比, 波動率, VIX, 預測, SPY, 商品, 樣本外]
experiment_refs: [K877]
---

# 金銀比能預測美股波動嗎？一個 NULL 結果

## 一句話結論

把金銀比（Gold-Silver Ratio，GS ratio）加進以 VIX 為基準的美股波動率預測模型，**樣本內看起來相當顯著**（partial correlation t = 14.0），但**移到樣本外、用 Diavebold-Mariano（DM）檢定、套用 Harvey 多重檢定門檻 |t| > 3.0 之後，沒有任何金銀比衍生變數能在統計上明確優於只用 VIX 的基準**。換句話說，**VIX 已經把金銀比想傳達的資訊吸收得差不多了**。這是一篇誠實寫出來的 NULL RESULT。

---

## 為什麼會想到金銀比？

金銀比是金價除以銀價的比值，在大宗商品研究中常被當成「避險情緒指標」：黃金被視為傳統避險工具，白銀則同時帶有工業金屬與貨幣金屬的雙重身份。當市場恐慌、避險情緒升溫，黃金通常表現比白銀強，金銀比往往拉高；當景氣樂觀、製造業需求活絡，白銀容易反超，金銀比下降。

於是一個自然的推論浮現：

> 既然金銀比反映風險情緒，那它有沒有可能對未來幾週的「股市波動率」也具有領先性？

學界已有不少文獻探討黃金、白銀作為避險工具的角色，例如 Baur 與 Lucey（2010）發表在 *Finance Research Letters* 的 "Is gold a hedge or a safe haven?" 是經典起點。後續延伸研究也指出，貴金屬市場的波動與股市風險指標之間存在共動性。但「金銀比能否在 VIX 之外，**額外**幫助預測美股波動」這件事，並沒有被很完整地回答。

K877 這個實驗，就是針對這個具體問題做出測試。

---

## 資料來源

- **實驗編號**：K877
- **資料供應**：yfinance（GLD、SLV、SPY、^VIX）
- **樣本期間**：2007-04-30 到 2026-03-03，共 4,741 個交易日
- **分割**：樣本內（IS）2,939 日；樣本外（OOS）1,801 日，OOS 窗口為 2019-01-02 到 2026-03-03（涵蓋 2020 COVID 崩盤與 2022 升息熊市）
- **預測標的**：SPY 未來 22 個交易日（約一個月）的年化已實現變異
- **解釋變數家族**：VIX 基準；GS ratio（金銀比水準）；GS change（金銀比的變動量）；GS zscore（金銀比的滾動標準化）

所有預測變數都嚴格做了 `shift(1)`，意思是用 t-1 觀察到的金銀比與 VIX 來預測 t 起算的 22 日波動 — **沒有 lookahead**。估計用展開窗口（expanding window）OLS、每季重新擬合一次。樣本外評估指標包含 Patton（2011）的 QLIKE 損失、Diebold-Mariano 檢定，以及 Harvey 等（2016）建議的多重檢定門檻 |t| > 3.0。

---

## 樣本內：金銀比看起來有訊號

先看樣本內描述統計。金銀比與未來 22 日已實現波動的同期相關係數約 0.085 — 數字不大，但**控制 VIX 之後的 partial correlation** 卻意外活潑：

| 變數（in-sample, 控制 VIX） | partial r | t-stat |
|---|---|---|
| GS ratio | 0.112 | 6.12 |
| GS change | 0.235 | 13.07 |
| GS zscore | 0.250 | 13.99 |

t-stat 衝到 13–14 看起來相當醒目。如果只看這張表，很容易得出「金銀比的標準化版本對股市波動有獨立解釋力」的結論。**但這是樣本內 OLS 的相關性，不是預測力。**

關鍵的差別在這裡：上表裡的 GS 變數和 RV 是**同一段時間**的觀察。樣本內 partial correlation 告訴我們「在這個樣本期間，控制 VIX 之後 GS 變動跟 RV 仍然共動」，這只是 in-sample correlation。要回答「能不能拿來做預測」，必須走樣本外 + 訊號 lag + 公平比較 + 統計檢定。

---

## 樣本外：訊號完全消失

把模型 freeze 在 2019-01-02 之前的訓練集、滾動 refit、用 t-1 的金銀比預測 t 起跑的未來 22 日波動，1,801 個 OOS 點下來，結果如下：

| 模型 | OOS R² | Spearman ρ | DM t（vs VIX） | Harvey \|t\|>3.0 顯著？ |
|---|---|---|---|---|
| VIX only（基準） | 0.135 | 0.585 | — | — |
| VIX + GS ratio | 0.102 | 0.585 | 2.64 | **否** |
| VIX + GS change | 0.134 | 0.543 | -2.33 | **否** |
| VIX + GS zscore | 0.163 | 0.593 | -2.67 | **否** |
| GS ratio only | -0.042 | 0.254 | 2.65 | **否** |
| GS change only | 0.027 | 0.117 | -1.49 | **否** |
| GS zscore only | 0.080 | 0.303 | -1.23 | **否** |

幾個觀察：

1. **VIX only 的 OOS R² 是 0.135、Spearman 0.585** — 這是一個相當扎實的單變數基準。
2. **加 GS 不一定變好**：VIX + GS ratio 的 R² 反而退到 0.102，VIX + GS zscore 升到 0.163；但加進 DM 檢定後，「升 / 降」沒有任何一個越過 Harvey |t| > 3.0 門檻。
3. **單獨用 GS**：GS ratio only 的 OOS R² 甚至是 **-0.042**（負值代表比歷史均值還差）。
4. **DM t 最大絕對值是 2.67**（VIX + GS zscore vs VIX only），離 Harvey 門檻 3.0 還有距離。

**結論：VIX 已經 sufficient。金銀比即使在樣本內看起來有獨立訊號，到樣本外被 VIX 完全吸收**。

---

## 為什麼樣本內顯著、樣本外消失？

這是波動率預測研究中很常見的故事，但每次重現都值得停下來想一下機制：

**第一**，樣本內 partial correlation 是同一段時間的共變動，本質上是 **in-sample fit**。控制 VIX 後 GS 仍解釋部分 RV 變異，可能是因為金銀比反映的避險情緒和 VIX 的恐慌指數在不同事件時間點各自抓到一些訊號，pooled 起來看 partial r 就放大。

**第二**，樣本外預測要面對 **structural break** 與 **regime shift**。2019-2026 OOS 期間經歷 COVID 崩盤、2021 meme 股泡沫、2022 升息熊市、2023 銀行業危機。金銀比在這些事件中的「警示能力」並不穩定 — 例如 2020 年 3 月避險情緒爆表時 VIX 飆到 80+，金銀比也走到極端，但兩者幾乎同步移動而非 GS 領先 VIX。

**第三**，**VIX 是隱含波動，本身就是市場對未來 30 日波動的定價共識**，已經把眾多 risk factor（情緒、流動性、貨幣政策、地緣政治）打包進去。要讓金銀比在 VIX 之外擠出 incremental information，需要它捕捉到 VIX 沒看到的訊號。從 K877 OOS 結果看，這個 incremental piece 並不存在 — 至少在 SPY 22 日 RV 預測這個任務上不存在。

---

## 研究誠實：null result 也是結果

值得明白寫下來：**這個實驗不是失敗、而是清楚回答了一個問題**。學術圈長期以來有 publication bias — 有顯著結果的研究比較容易發表、null result 容易被丟進抽屜。但對波動率預測這類 ops 導向的研究，null result 的價值同樣高：它告訴我們**不要把 GS ratio 加進現行 VIX-based 風險警示框架**，因為它不會帶來統計上可信的提升、反而讓模型更複雜、增加 overfit 風險。

過去有許多文獻提及貴金屬與股市風險的共動，但**「共動」不等於「在控制 VIX 後仍有預測力」**。K877 的 OOS DM 結果，把這個區別在實證上清楚畫了一條線。

對讀者的具體 takeaway：

- 看到「金銀比飆高 = 股市要崩」這類 social media 風格的論述時，**多一份懷疑**。它可能反映的是同期共動（VIX 也已經在飆），而不是 VIX 沒看到的領先訊號。
- 在自家的風險預測模型裡，**先把 VIX 跑好**比堆疊更多 commodity-based 變數有效得多。VIX 只是 1 個變數、卻能拿到 OOS R² ≈ 0.14、Spearman ≈ 0.59 — 這是非常扎實的單一指標 baseline。
- 如果未來有人提出「金銀比 + 某種非線性轉換 + 某個 regime filter」可以打敗 VIX，請要求看樣本外 DM 檢定 + Harvey 門檻；in-sample t-stat 13 不算數。

---

## 防錯紀錄（Lookahead audit）

這篇文章背後的實驗在設計時做過下列檢查，方便未來複查與追溯：

- **Signal lag**：所有解釋變數（VIX、GS ratio、GS change、GS zscore）統一 `shift(1)`，預測 t 期 RV 用的是 t-1 已可觀察的數值，沒有同期混入。
- **In-sample 與 OOS 分離**：partial correlation 表報告的是 IS（用 2007-2018 樣本估計），預測力評估只看 OOS（2019-2026），兩者不混口徑。
- **DM 檢定使用 forward 22 日 RV** 與 forecast 的 squared loss / QLIKE loss，配合 Harvey 多重檢定門檻 |t| > 3.0。
- **每季 refit + 展開窗口**：避免 freeze 過久造成 stale model 的人工放大優勢。

---

## 結論

K877 用 4,741 日 SPY / GLD / SLV / VIX 資料、嚴格 lag、樣本外 DM 檢定，回答了「金銀比能否在 VIX 之外幫助預測美股 22 日波動」這個問題。**答案是：不能。** VIX 已經 sufficient；金銀比的水準、變動、標準化版本都沒有越過 Harvey 多重檢定門檻 |t| > 3.0。

這不是說金銀比沒用 — 它在大宗商品策略、貴金屬對沖、避險情緒監測等場景仍可能有獨立價值。但在 SPY 短期波動預測這個特定任務上，它沒有提供 VIX 沒看到的東西。

把這個 null result 寫出來，希望讓往後研究金銀比 / 商品 / 股市風險關聯的同行少走一段路：**請直接把樣本外 DM + Harvey 門檻設成第一個 gate，再決定要不要繼續往下挖**。

---

## 資料來源

- **實驗**：K877 — Gold-Silver Ratio as Equity Volatility Predictor
- **樣本期間**：2007-04-30 到 2026-03-03（n=4,741；OOS n=1,801，2019-01-02 起）
- **資產代碼**：GLD（黃金 ETF）、SLV（白銀 ETF）、SPY（標普 500 ETF）、^VIX
- **主要文獻**：
  - Baur, D. G., & Lucey, B. M. (2010). Is gold a hedge or a safe haven? *Finance Research Letters*.
  - Patton, A. J. (2011). Volatility forecast comparison using imperfect volatility proxies. *Journal of Econometrics*, 160.
  - Harvey, C. R., Liu, Y., & Zhu, H. (2016). … and the cross-section of expected returns. *Review of Financial Studies*.
- **方法**：expanding window OLS + 每季 refit；OOS 評估用 QLIKE + DM + Spearman；多重檢定門檻採 Harvey |t| > 3.0

## 圖表

![OOS R² 比較：VIX 已 sufficient，GS 變數加入不顯著改善](experiments/k877/k877_oos_r2_comparison.png)

![IS 統計強度 6-14 但 OOS 全低於嚴格門檻 3.0](experiments/k877/k877_is_vs_oos_strength.png)
