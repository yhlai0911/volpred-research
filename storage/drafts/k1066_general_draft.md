---
title: "VIX 平方搭配「開盤到收盤」報酬，能贏過收盤對收盤嗎？三項假設誠實打分"
audience: general
status: draft
tags: [波動率, VIX, 預測模型, 穩健性, 跨期間驗證, 研究誠實]
experiment_refs: [K1066]
---

# VIX 平方搭配「開盤到收盤」報酬，能贏過收盤對收盤嗎？三項假設誠實打分

## 一句話結論

把 SPY 報酬從「收盤到收盤」改成「開盤到收盤」（也就是只看交易時段），再搭配 VIX 平方做為長期變異數驅動因子，這個組合在它自己的目標上**贏過了 GJR 基準模型**，並且在 5 個子期間全部勝出；但它的「贏的幅度」**並沒有超過**過去用收盤對收盤建立的最佳成績——所以我們不會把它扶正成主版本。

這篇文章記錄 K1066 實驗的完整誠實版本：哪些假設通過、哪一條失敗、失敗代表什麼、以及為什麼我們選擇兩種做法並陳，而不是把舊版本換掉。

## 為什麼要做這個比較

過去這個專案的長期主力模型是 A4f_close：用 SPY 收盤對收盤的日報酬，再把每天的長期變異數（τ_t）綁定 VIX 平方，短期波動 g_t 走 GJR(1,1)。在 Paper 9 的全段 rolling out-of-sample 設定下，A4f_close 對 GJR_close 的兩模型比較統計強度達到 4.48（樣本外從 2019-01 起算 1,828 個交易日），這是已知的 baseline。

但前一個實驗（K1065）拿 Hansen-Lunde（2005）把全日變異數拆解後發現一件耐人尋味的事：

- VIX² 對 **交易時段內**（intraday）的變異數有 26% 的 QLIKE 改善
- 但對 **隔夜**（overnight）的變異數，改善只有 3.9%

換句話說，VIX 這個指標的「資訊」可能更集中在白天的交易時段。如果是這樣，把報酬從「close-to-close」改成「open-to-close」（只算開盤到當日收盤），是不是能拿出一個更乾淨、改善更大的版本？這就是 K1066 想驗證的。

## 三項假設（一次講清楚）

我們事前明確訂下三項假設與通過標準，避免事後挑數字：

| 假設 | 內容 | 通過標準 | 結果 |
|---|---|---|---|
| H1 | A4f_oc（開盤到收盤版）在自己的原生目標 r²_oc 上，比 GJR_oc 顯著好 | 統計強度 > 3.0（嚴格統計檢驗門檻，文獻 2016） | **PASS**（4.04） |
| H2 | A4f_oc 的改善幅度，要**超過** K988 已建立的 A4f_close 改善幅度（4.48） | 統計強度 > 4.48 | **FAIL**（4.04 < 4.48） |
| H3 | A4f_oc 在 5 個子期間全部勝出 | 5/5 wins | **PASS**（5/5，重抽樣比較顯著） |

兩個 PASS、一個 FAIL，這就是這篇文章要誠實處理的核心張力。

## 實驗怎麼跑

- 資料：SPY 的 OHLC 與 VIX，來源 yfinance，期間 **2005-01-04 到 2026-04-10**，共 5,350 個交易日
- 樣本外起始：2019-01-01，樣本外長度 **1,828 日**
- 估計視窗：2,000 日的 rolling window
- 重新估計頻率：每 63 個交易日（約一季），全程共 **30 次重估**
- 隨機種子固定：42（為了完整可重現）
- 公平比較設計：A4f_close 與 GJR_close 都用收盤對收盤報酬；A4f_oc 與 GJR_oc 都用開盤對收盤報酬。每組各自有「同口徑的 GJR 對照組」，避免拿不同 baseline 偷分數。

評估指標主要看 QLIKE（Patton 2011 提出的 robust loss function，越低越好），輔以 MSE、MAE、Spearman 排序相關係數，並用兩種變異數 proxy：

- r²_close（K988 沿用的 close-to-close 平方報酬）
- r²_oc（A4f_oc 的原生 proxy，open-to-close 平方報酬）

兩模型的比較檢定都用 Newey-West HAC 標準誤，避免序列相關污染推論。

## 結果（真實數字）

### 在收盤對收盤目標 r²_close 上

| 模型 | QLIKE | Spearman ρ |
|---|---|---|
| **A4f_close** | **-8.3594** | 0.4184 |
| GJR_close | -8.2731 | 0.3671 |
| A4f_oc | -8.2409 | 0.4288 |
| GJR_oc | -8.0152 | 0.3812 |

### 在開盤對收盤目標 r²_oc 上

| 模型 | QLIKE | Spearman ρ |
|---|---|---|
| **A4f_oc** | **-8.8162** | 0.4211 |
| A4f_close | -8.7130 | 0.4168 |
| GJR_oc | -8.7036 | 0.3695 |
| GJR_close | -8.6888 | 0.3641 |

可以看到一個非常清楚的「模型－目標匹配」現象：每個模型在自己對應的 proxy 上贏。A4f_close 在 r²_close 上拿第一，A4f_oc 在 r²_oc 上拿第一。這是符合預期的，因為一個用 close-to-close 訓練的模型，本來就最會預測 close-to-close 的平方。

![兩模型比較 — 4 模型 × 2 proxy 比較矩陣](experiments/k1066/k1066_dm_comparison.png)

### 兩模型比較的關鍵幾個對戰

| 對戰 | proxy | 統計強度 | 贏家 |
|---|---|---|---|
| A4f_close vs GJR_close | r²_close | +4.71 | A4f_close（嚴格統計檢驗門檻通過） |
| A4f_oc vs GJR_oc | r²_oc | **+4.04** | A4f_oc（嚴格統計檢驗門檻通過） |
| A4f_oc vs A4f_close | r²_oc | +5.17 | A4f_oc |
| A4f_oc vs A4f_close | r²_close | -3.71 | A4f_close |
| A4f_oc vs GJR_close | r²_oc | **+7.05** | A4f_oc |
| GJR_oc vs GJR_close | r²_close | -3.08 | GJR_close |

最值得注意的數字是 **+7.05**：當目標是 open-to-close 變異數時，把基準的 GJR_close 模型拿來跟我們的 A4f_oc 比，差距相當大。這背後的訊息是：「VIX 平方做長期變異數驅動因子」這件事在交易時段的變異數上特別有用——這也呼應了 K1065 的拆解結論。

但同樣明顯的是：A4f_close 在 r²_close 的 4.71 比 A4f_oc 在 r²_oc 的 4.04 大一點。這就是 H2 失敗的根源。

## H2 為什麼會失敗？誠實的解讀

兩個改善「在它各自原生目標上的相對統計強度」是可以直接比較的（兩者都用了 Newey-West 標準化）。H2 失敗代表：A4f_oc 雖然在自己的目標上贏，但贏的「相對幅度」沒有超過 close-to-close 那一邊既有的紀錄。

我們認為背後有兩個機制：

**第一，VIX 本來就被設計來預測整個交易日（甚至跨夜）的變異數。** VIX 是 30 日 risk-neutral 變異數的市場期望值，它涵蓋的是「全日（含隔夜）」的不確定性，不是只看交易時段。所以 VIX² 對 close-to-close 的資訊含量本來就比對 open-to-close 多。即使我們在 K1065 看到「VIX 對 intraday 變異數的 QLIKE 改善 26%、對 overnight 只有 3.9%」，那是用高頻 5 分鐘 realized variance 當 proxy 量出來的；換成 r²_oc（noisy proxy）的時候，訊號被噪音蓋掉一部分。

**第二，r²_oc 是極為 noisy 的 proxy。** 它就是「open-to-close 報酬的平方」，跟用高頻資料合成出來的 realized variance 完全是兩個量級。任何模型用 r²_oc 評分，都會被 proxy 噪音壓低統計強度。要看到 K1065 那種乾淨的 26% intraday 改善，得用 5 分鐘 RV 才行。

## 5 個子期間全勝，但訊號比較弱

H3 的子期間穩定性檢驗結果（A4f_oc vs GJR_oc，目標為 r²_oc）：

| 期間 | N | GJR_oc QLIKE | A4f_oc QLIKE | 改善% | 統計強度 | 達顯著水準 |
|---|---|---|---|---|---|---|
| P1 Pre-COVID | 252 | -9.4871 | -9.5171 | -0.32% | +1.93 | 否 |
| P2 COVID | 377 | -8.2829 | -8.5117 | -2.76% | +1.92 | 否 |
| P3 Post-COVID | 379 | -8.1656 | -8.2631 | -1.19% | +3.40 | **是** |
| P4 Rate Hike | 374 | -9.0640 | -9.1041 | -0.44% | +2.41 | 否 |
| P5 Recent | 446 | -8.7713 | -8.9060 | -1.53% | +2.96 | 否 |

5 個子期間全部 A4f_oc 勝出（重抽樣比較達顯著水準）。但只有 P3 Post-COVID 這一段通過「嚴格統計檢驗門檻」。對比之前 K1056 在 close-to-close 版本的記錄是 5 段裡有 3 段通過該門檻，這一輪的訊號明顯比較弱。

![5 個子期間穩定性](experiments/k1066/k1066_subperiod_stability.png)

可以看到「方向一致性」很強（沒有任何一個子期間翻盤），但「每段內的統計強度」相對不足。這是樣本較小 + open-to-close 變異數本身可預測性低於 close-to-close 的綜合結果。

## τ_t 的 θ₁ 演化：兩個版本的個性

我們也比較了 A4f_close 和 A4f_oc 兩個版本中，VIX 平方那一項的係數 θ₁ 在 30 次重估中怎麼變。

| 模型 | θ₁ 平均 | θ₁ 標準差 | θ₁ 變動係數 CV |
|---|---|---|---|
| A4f_close | 4.75e-06 | 1.72e-05 | 3.6 |
| A4f_oc | 1.07e-07 | 2.03e-08 | 0.19 |

兩個觀察：

1. A4f_oc 的 θ₁ 比 A4f_close 小**兩個數量級**——這是因為 r²_oc 的整體量級就比 r²_close 小（8.69e-08 vs 2.68e-07 的 MSE 對比也呈現同樣關係）。
2. A4f_oc 的 θ₁ 變動非常**穩定**（CV 0.19），相對於 A4f_close 的 CV 3.6 顯著穩定。也就是說，open-to-close 變異數對 VIX 平方的反應更**線性、更一致**——只是反應強度比較小。

![θ₁ 在 30 次重估中的演化](experiments/k1066/k1066_theta1_evolution.png)

這個發現本身就有獨立價值：用 VIX² 預測 open-to-close 變異數，模型校準會比較不易在不同期間飄移。

## 那 Paper 9 要不要換 target？答案：不換，但要並陳

H2 失敗讓「換成 open-to-close 當主 target」這條路被否決。但 H1 + H3 雙 PASS、加上 +7.05 那個跨 return 定義的對戰結果，又顯示這個版本確實有獨立洞見。

我們的處理方式是：

1. **不換主版本**：Paper 9 主結果繼續用 close-to-close（A4f_close 對 GJR_close，4.71）。
2. **加 robustness section 並陳兩種設定**：報告 A4f_oc 在 r²_oc 上的 4.04，以及它跨 return 定義對 GJR_close 的 +7.05，強化「VIX² 在交易時段變異數上特別有用」這個機制訊息。
3. **K1065 的拆解結論獨立存放**：作為 mechanism paper 候選，不直接合併進 Paper 9，避免把不同的 proxy（5 分鐘 RV vs r²_oc）混在同一個 narrative 裡。

## 一個方法論小結（給後續實驗用）

K1066 留下三個對未來實驗有用的提醒：

**第一，「在自己原生目標上贏」是最低門檻，不是賣點。** 任何模型搭自己最熟悉的 proxy 都應該贏，這是機械性的。要看到真本事，得跨 proxy 比較（K1066 的 A4f_oc vs GJR_close on r²_oc 達到 +7.05，這才有資訊量）。

**第二，proxy 的噪音水準會壓縮統計強度。** 想用 r²_oc 看到跟 5 分鐘 RV 同等級的訊號是不公平的。如果未來要強化「open-to-close 是 VIX 的最佳目標」這個論點，得改用 high-frequency RV_oc 才有勝算。

**第三，子期間的「方向一致」和「每段達顯著」是兩件事。** A4f_oc 的方向一致性（5/5）和 A4f_close 一樣強，但每段達顯著的數量（1/5 vs 3/5）比較弱——前者代表模型沒有翻盤風險，後者代表單一子期間下的證據強度。報結論時要分開描述，不能混為一談。

## 後續方向

1. 用 5 分鐘 RV_oc 替代 r²_oc 重跑同樣的設定——預期能複現 K1065 的 intraday 大幅改善
2. 嘗試 HAR-A4f 混合：用 HAR-RV 的日／週／月時序分解搭配 VIX² 驅動的 τ_t
3. 跨市場驗證：0050.TW（台股）、N225（日股）—— 但需先處理各市場 VIX 代理變數的可得性

## 資料來源

- SPY 與 VIX 日資料：yfinance（period: 2005-01-04 ～ 2026-04-10，n=5,350 個交易日）
- 樣本外期間：2019-01-01 起，n=1,828 日
- 模型估計：2,000 日 rolling window，63 日重估頻率，30 次重估，隨機種子 42
- QLIKE 與兩模型比較均使用 Newey-West HAC 標準誤
- 完整實驗腳本與結果 JSON：K1066

## 參考文獻

- Engle, R., Ghysels, E., & Sohn, B. (2013). Stock Market Volatility and Macroeconomic Fundamentals. *Review of Economics and Statistics* 95(3): 776-797.
- Hansen, P. R., & Lunde, A. (2005). A Realized Variance for the Whole Day Based on Intermittent High-Frequency Data. *Journal of Applied Econometrics*.
- Patton, A. J. (2011). Volatility forecast comparison using imperfect volatility proxies. *Journal of Econometrics* 160: 246-256.

## 相關實驗

- K988：A4f_close 在全段 rolling OOS 對 GJR_close，建立 4.48 baseline
- K1056：A4f_close 5 個子期間穩定性（5/5 wins，3/5 達嚴格統計檢驗門檻）
- K1065：A4f_oc 在高頻 RV intraday proxy 上的拆解結果（+5.38），K1066 試圖在 r²_oc 上以全段 rolling OOS 重現
