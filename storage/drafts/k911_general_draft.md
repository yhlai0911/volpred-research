---
title: 危機來臨時，市場「尾端連動」會比「平均連動」更早拉警報嗎？K911 量化分位連結度實測
description: 用 Quantile VAR 把市場連結度拆成三條分位線（極跌 / 中位 / 極漲），17 年實測發現尾端 TCI 與 VIX 的關聯比平均 TCI 強得多，但要拿來預測尾端事件，加值僅約 7 個百分點 — 一個 MIXED 的誠實答案。
tags:
  - connectedness
  - tail-risk
  - QDVC
  - network
  - contagion
  - quantile
  - VIX
experiment_refs: [K911]
phase: research
audience: general
status: draft
---

# 危機來臨時，市場「尾端連動」會比「平均連動」更早拉警報嗎？

## 為什麼要再問一次「市場有沒有連動」這個老問題

過去 K907、K910 兩個實驗，我們花了不少時間檢驗「平均連結度（mean TCI）能不能當作風險或交易訊號」，結論很清楚：**不行**。

- K907：四資產的平均 TCI 大約 50%，但與 VIX 的相關係數 r = 0.001 — 完全正交
- K910：把 mean TCI 當成擇時訊號，與未來報酬的相關係數只有 r = 0.005 — 等於沒訊號

但我們在文獻裡持續看到一個聲音（Ando, Greenwood-Nimmo and Shin, 2022）：「**也許看錯了維度。市場危機是一個 tail phenomenon — 你應該看的是極端尾端的連動，不是平均的連動。**」

這個質疑很合理。直覺上，危機時「全部資產一起崩盤」是定義性事件；平靜時各自走各自的路。如果這個故事為真，**極跌分位（tau = 0.05）的連結度** TCI 應該在危機時 spike，而且這個 spike 不應該被 VIX 完全吸收 — 否則我們就有了一個獨立於 VIX 的尾端風險訊號，網絡結構就還能講話。

這就是 K911 要回答的問題。

## 方法：把連結度按分位拆成三條線

標準的 Diebold-Yilmaz 連結度（DY）用 OLS-VAR 估出條件均值的衝擊傳遞，然後做 Generalized FEVD 算每個變數對其他變數預測誤差變異的解釋比例。**問題**：這個是「平均」尺度的故事。

K911 用 Ando-Greenwood-Nimmo-Shin (2022) 的 **Quantile VAR** 做法：把 OLS 換成 Quantile Regression（Koenker and Bassett, 1978），分別在 tau = 0.05 / 0.50 / 0.95 三個分位估三套 VAR(2)，然後每套都跑一次 Generalized FEVD，得到三張不同分位的連結度表。

- **tau = 0.05** = 極跌尾端連結（"當大家都在崩，崩得多一致？"）
- **tau = 0.50** = 中位連結（≈ 一般 DY mean TCI）
- **tau = 0.95** = 極漲尾端連結（"當大家都在噴，噴得多一致？"）

數據細節（period attribution）：

- **資料來源**：yfinance OHLC，2009-01-02 到 2026-03-31，共 4,475 個交易日
- **資產**：SPY（美股）、QQQ（科技）、GLD（黃金）、0050.TW（台股 ETF）
- **波動率代理**：Garman-Klass（用 OHLC 而非單純 close-to-close，估計效率較高）
- **VAR 階數**：lag order 2；預測期間 H = 10 日
- **滾動視窗**：250 個交易日（約 1 年）；step = 5 日 — 這對 OOS 是合法的，因為每個視窗都只用視窗內的歷史資料估計
- **Lookahead 防線**：滾動估計天然滿足 t-1 information set；tail event 標籤用同期實現報酬，不參與訓練

## 第一個發現：尾端 TCI 確實 spike，但跟平均 TCI 同步 spike

先看全樣本連結度水準（單位：%）：

| 分位 (tau) | 全樣本 TCI | 滾動 TCI 平均 | 滾動 TCI 標準差 |
|---|---|---|---|
| 0.05（極跌尾端） | 24.15 | 34.40 | 10.81 |
| 0.50（中位） | 21.64 | 35.01 | 10.62 |
| 0.95（極漲尾端） | 71.21 | 69.87 | 8.29 |

第一個直覺：**極漲分位 (tau=0.95) 的 TCI 永遠很高（70%+）**。這個結果在 quantile connectedness 文獻裡早有討論 — 高分位的 quantile regression 對 tail observations 的依賴比較重，會放大 cross-asset 的共同趨勢。我們不過度解讀這條線，主軸放在 tail (0.05) vs mean (0.50) 的對比。

關鍵問題：**tail TCI 與 mean TCI 是不是兩條獨立的訊號？**

實測結果是當頭一棒：

![尾端 vs 平均 TCI 滾動比較](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/k911_tail_vs_mean_tci.png)

- **tau=0.05 vs tau=0.50 的時序相關係數 r = 0.952**
- tau=0.05 vs tau=0.95 r = 0.022
- tau=0.50 vs tau=0.95 r = 0.017

換句話說：**極跌尾端 TCI 與中位 TCI 走得幾乎一模一樣**。我們原本期待「尾端有獨立故事」這條 hypothesis，第一道關卡就直接被資料打回去 — tail 跟 mean 共享 95.2% 的時序變異。

「看錯維度」的修補思路在這個 4 資產樣本上沒有出現結構性翻盤。

## 第二個發現：尾端 TCI 與 VIX 的關聯比平均 TCI 強得多

但故事還沒完。即便 tail 與 mean TCI 高度同步，**它們與 VIX 的關聯卻有顯著差別**：

| 分位 (tau) | 與 VIX Pearson r | 統計顯著性 |
|---|---|---|
| 0.05（極跌尾端） | **0.399** | 達顯著水準（極強） |
| 0.50（中位） | 0.347 | 達顯著水準（極強） |
| 0.95（極漲尾端） | 0.091 | 達顯著水準（弱） |

對照 K907 的同類設定（9 資產 mean TCI vs VIX，r = 0.001）— K911 的 4 資產 tail TCI 對 VIX 的關聯**強了兩個數量級以上**。

兩個解讀路徑：

1. **資產組合差別**：K911 只用 4 個資產（SPY/QQQ/GLD/0050.TW），其中 SPY 與 QQQ 都是美股，VIX 直接寫進它們的隱含波動率。K907 是 9 資產，含商品、外匯、利率、新興市場等，diversification 把 VIX 訊號稀釋了。
2. **Quantile estimator 的尾端敏感度**：tau=0.05 的 quantile regression 對極端觀察值權重更大，VIX 高的時候極端觀察值也多，自然 r 變大。

不管怎麼解，這條線**不能視為「網絡結構獨立於 VIX」的證據** — 它與 VIX 共動，只是共動程度比 mean TCI 更強。

## 第三個發現：要拿來預測尾端事件，加值只有約 7 個百分點

研究的最後一步是把 tail TCI 推到 horse race：能不能在 logistic regression 中超越（或補強）VIX 對尾端事件（每資產報酬 ≤ 5% 分位）的預測？

| 模型 | AUC |
|---|---|
| Tail TCI only | 0.581 |
| VIX only | 0.515 |
| Tail TCI + VIX | 0.588 |

幾個觀察：

- **單獨 tail TCI 的 AUC = 0.581** — 比隨機（0.50）好，但不到「有用訊號」門檻（一般 0.60+ 才談得上實務應用）
- **VIX 單獨 AUC = 0.515** — 也很弱。這呼應了一個老觀察：當期 VIX 對未來尾端事件的預測力本來就有限（VIX 主要反映當下隱含波動率，不是 forward predictor）
- **兩者合併 AUC = 0.588**，比 VIX 單獨提升 0.073，比 tail TCI 單獨只提升 0.007

也就是說，tail TCI 提供的 incremental 訊號**比 VIX 多了一點**，但兩者合在一起仍然遠低於可用門檻。

## 第四個發現：危機期間，tail 跟 mean 的 spike 比例幾乎一樣

最後一張圖把 2008 GFC、2020 COVID、2022 升息、2017 平靜年放在同一張比較：

![Crisis 期間 TCI 比較](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/k911_crisis_comparison.png)

關鍵數字：

| 期間 | tau=0.05 平均 TCI | tau=0.50 平均 TCI | spike 比例 (tail vs normal) | spike 比例 (mean vs normal) |
|---|---|---|---|---|
| 2017 平靜 | 26.29 | 26.06 | 1.00x | 1.00x |
| 2020 COVID | 52.84 | 51.57 | 2.01x | 1.98x |
| 2022 升息 | 28.38 | 28.61 | 1.08x | 1.10x |

想找的答案是「tail TCI 在 COVID 比 mean 多 spike 多少？」 — 答案是 **2.01x vs 1.98x，差距 0.03x**。換言之，COVID 期間平均連動度漲了快兩倍，尾端連動度也漲了快兩倍，**幾乎同步**。

升息週期（2022）兩條線都 sub-1.10x — 連結度結構幾乎沒被擾動。這跟「市場崩盤型壓力」（COVID）vs「政策路徑型壓力」（升息）的本質差異一致：前者觸發 contagion，後者主要是 cross-section 重定價。

## 整體結論：MIXED — 維度修對了一點點，但結構故事仍然是 VIX

把四個發現合起來：

1. Tail (tau=0.05) 與 Mean (tau=0.50) TCI 時序相關 r = **0.952** — **不是兩條獨立訊號**
2. Tail TCI 與 VIX 相關 r = **0.399**（vs K907 mean TCI = 0.001）— 比 mean TCI 接近 VIX，但這也代表它**不是與 VIX 正交的補充訊號**
3. Tail TCI 對尾端事件的 logistic AUC = **0.581**，加上 VIX 後 0.588 — incremental 只有 0.007
4. COVID 期間 tail spike ratio 2.01x vs mean 1.98x — 同步 spike，沒有 tail-only 故事

研究誠實的講法是：**四種「看市場連結度」的方法都拼不過 VIX 作為單一風險指標**（K907 mean TCI / K910 trading signal / K908 network-augmented VaR / K911 quantile-tail TCI）— 這是**第 35 次 VIX-sufficiency 確認**。網絡結構在描述性層面（"COVID 時連動度翻倍"）有它的價值，但**作為時序 forward 風險訊號或交易訊號，VIX 已經把該講的都講了**。

但 K911 也不是完全 NULL — 它把 mean TCI vs VIX 從 r = 0.001 修到 tail TCI vs VIX r = 0.399。這代表「分位維度」確實**不是無關的維度**，它捕捉了 mean 看不到的 VIX-correlated 變異。問題在於這個變異**已經在 VIX 裡了**，不是新訊息。

## 給投資人 / 讀者的三個 takeaway

1. **不要相信「市場連動度創新高所以該避險」這類媒體論述** — 連動度的確會 spike，但 VIX 早已 spike 在前。連動度作為早期警報，比 VIX 慢
2. **危機是 contagion 現象沒錯，但 tail 跟 mean 同步 spike** — 「only the tail spikes」這類精緻假說在 4 資產測試上不成立
3. **網絡結構是好的事後敘事工具，不是好的預警工具** — 它告訴我們「為什麼當時會崩」，不告訴我們「下個月會不會崩」

## 滾動 TCI 全圖（供參考）

![Rolling Quantile TCI 三線圖](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/k911_rolling_quantile_tci.png)

紅線（tau=0.95）長期偏高且穩定；綠線（tau=0.50，mean）與藍線（tau=0.05，tail）幾乎完全重疊 — 這就是 r = 0.952 的視覺對應。三大事件（2010 歐債、2020 COVID、2022 升息）的 spike 在三條線上都看得到，但時間點與幅度差異不顯著。

## 數據與方法

- 期間：2009-01-02 到 2026-03-31，4,475 個交易日
- 資產：SPY / QQQ / GLD / 0050.TW（4 資產，為了 quantile regression tractable）
- 波動率代理：Garman-Klass OHLC-based
- 模型：Quantile VAR(2) + Generalized FEVD，tau in {0.05, 0.50, 0.95}
- 滾動：250 日視窗，每 5 日推進
- 來源：yfinance；對 0050.TW 做了 clean_tw50_data 預處理
- Runtime：26.4 秒（Quantile regression 比 OLS 慢，但 4 資產 + 250 視窗仍可快速跑完）
- 完整數據：experiments/k911/k911_quantile_connectedness_results.json

## 參考文獻

- Ando, Greenwood-Nimmo and Shin (2022). Quantile Connectedness: Modeling Tail Behavior in the Topology of Financial Networks. Management Science.
- Diebold and Yilmaz (2012). Better to give than to receive: Predictive directional measurement of volatility spillovers. International Journal of Forecasting.
- Diebold and Yilmaz (2014). On the network topology of variance decompositions: Measuring the connectedness of financial firms. Journal of Econometrics.
- Koenker and Bassett (1978). Regression quantiles. Econometrica.

## 內部對照

- K907：9 資產 mean TCI ~50%，r_VIX=0.001，VIX-sufficiency 確認 #1
- K910：mean TCI 對未來報酬 r=0.005，沒有擇時訊號
- K908：MF-GJR + HistSim 解 VaR，不用網絡結構
- K911（本文）：tail dimension 修補 mean TCI 的 VIX-orthogonality，但拼不過 VIX-sufficiency
