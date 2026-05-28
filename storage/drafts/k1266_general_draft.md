---
title: "多資產 rough volatility 聽起來很新，為什麼放到日線還是輸給老派 DCC-GARCH？"
audience: general
status: draft
tags:
  - rough-volatility
  - DCC-GARCH
  - SPY
  - QQQ
  - IWM
  - 波動率預測
experiment_refs:
  - K1266
---

# 多資產 rough volatility 聽起來很新，為什麼放到日線還是輸給老派 DCC-GARCH？

很多新模型的賣點都很強。名字新、數學漂亮、論文也新，看起來像是該把老模型換掉了。

K1266 測的就是這種題目。對手一邊是近年很紅的 multivariate rough volatility，一邊是 2002 年就提出的 DCC-GARCH。資料用的是三檔最常見的美股 ETF：SPY、QQQ、IWM，外樣本期間從 2019-01-02 到 2026-04-29，一共 1,841 個交易日。

結果很直接：**新模型沒有小輸，它是整排輸。**

## 先看最重要的一張圖

![K1266 三模型三資產 QLIKE 比較](experiments/k1266/k1266_qlike_comparison.png)

這張圖的意思不複雜。三個模型都在做同一件事：預測明天的波動。QLIKE 越低越好。

K1266 的結果是：

| 模型 | 多變量 QLIKE 平均 |
|---|---:|
| DCC-GARCH | **-26.04** |
| Multivariate Rough Vol | -23.54 |
| Univariate Rough Vol | -22.31 |

如果把 DCC-GARCH 當基準，multivariate rough vol 並沒有帶來改善，反而**差了 9.58%**。這不是某幾天失手而已，SPY、QQQ、IWM 三檔分開看也都是 DCC-GARCH 較好。

## 問題不只在平均值，連三個子期間都沒贏

![K1266 DM 比較熱圖](experiments/k1266/k1266_dm_heatmap.png)

研究另外把樣本拆成 2020、2022、以及其餘期間。原因很簡單：有些模型會在危機年特別亮眼，平常時間卻不行。如果 rough vol 只是在 COVID 或熊市比較強，拆開後應該看得出來。

但 K1266 沒有看到這件事。`subperiod_wins_mv_vs_dcc` 的結果是 `0/3`。也就是說，rough vol 在三個子期間一場都沒拿下。

這讓結論變得很清楚：它不是「有潛力但不穩」，而是**在這組日資料上，系統性地比 DCC-GARCH 差**。

## 為什麼會這樣

這份實驗給了兩個很實際的理由。

第一，rough vol 在文獻裡常常是配高頻 realized volatility 用的。可 K1266 用的是日線 close-to-close 報酬，估出來的 Hurst 幾乎貼近 0：SPY `0.0153`、QQQ `0.0153`、IWM `0.10`。換句話說，模型最想抓的那種「粗糙結構」，在這個頻率上幾乎看不清楚。

第二，簡化版 rough Bergomi 預測對新 shock 的反應偏慢。GARCH 看到昨天波動突然放大，會很快把條件變異數往上調；rough vol 這個版本靠的是較平滑的 log-RV 混合，碰到 regime 轉換時比較容易慢半拍。

所以這次輸掉的，不只是「新模型不夠花俏」，而是**模型想吃的訊號，本來就不在這個資料層上**。

## 這對投資人真正有什麼意義

很多人看到新方法會直覺覺得：多資產、rough、聯立結構，資訊比單資產更多，效果應該更強。

K1266 的答案剛好相反。至少在日線美股 ETF 這個任務上，額外複雜度沒有換來更準的預測，反而只增加估計噪音。老派的 DCC-GARCH 雖然名字不新，卻把這題做得更穩。

這種結果也很符合這個 repo 最近幾輪的共同訊號：當預測頻率停在日線時，很多看起來更前沿的波動率模型，最後都撞上同一道牆。真正能留下來的，通常還是那些反應快、估計穩、參數解釋清楚的方法。

## 最後一句

K1266 不是在說 rough volatility 沒價值。它比較像是在提醒一件事：**模型和資料頻率要配得起來。**

如果你拿高頻世界的武器來打日線戰場，輸給 20 多年前的老模型，真的不奇怪。

## 資料來源

本文基於實驗 `K1266`（腳本：`experiments/k1266/k1266.py`，結果：`experiments/k1266/k1266_results.json`）。數據來源：`yfinance`，資產為 SPY、QQQ、IWM；期間 `2010-01-05` 至 `2026-04-29`，外樣本 `2019-01-02` 至 `2026-04-29`，樣本 `1,841` 個交易日。
