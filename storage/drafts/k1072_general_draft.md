---
title: "5 分鐘 SPY 真的乾淨嗎？Realized Kernel vs RV 初步觀察"
audience: general
status: draft
tags:
  - 波動率
  - 高頻數據
  - 微觀結構
  - 估計量
  - SPY
  - 穩健性
  - 方法論
experiment_refs:
  - K1072
---

# 5 分鐘 SPY 真的乾淨嗎？Realized Kernel vs RV 初步觀察

## 為什麼要在意「5 分鐘 RV」這件事

實證波動率研究的標準作法，是把日內每 5 分鐘的報酬平方加總，得到「Realized Variance（RV）」當作當天「真實波動率」的代理。我們先前的多個實驗（K1054、K1063、K1065、K1066）都是這麼做的：把 5 分鐘 RV 當成 ground truth，再去比 HAR、GJR-GARCH、A4f-VIX² 哪個預測得最準。

但這套作法背後藏著一個假設：**5 分鐘的取樣間隔已經夠稀疏，市場微觀結構雜訊（microstructure noise，包括 bid-ask bounce、非同步交易、tick rounding 等）小到可以忽略不計**。如果這假設不成立，那我們先前算出來的 RV 其實是「真 σ² + 噪音」，過去用它當基準的所有結論都可能被噪音污染。

學界對此早有解方。Barndorff-Nielsen, Hansen, Lunde & Shephard（2008，*Econometrica*）提出 Realized Kernel（RK），用 Parzen 核函數對自共變項做加權平均，理論上是 σ² 的一致估計量；Zhang, Mykland & Aït-Sahalia（2005，*JASA*）則提出 Subsampled RV，把多個錯位的 5 分鐘格子平均掉短期相關。本實驗 K1072 的核心問題很單純：**SPY 在 5 分鐘頻率下，到底有沒有顯著的微觀結構雜訊？如果有，先前用 RV 當基準的結論會不會被翻盤？**

## 資料來源

- **資產**：SPY（S&P 500 ETF），yfinance 5 分鐘 bars
- **樣本期間**：2026-01-14 至 2026-04-10
- **天數**：60 個交易日下載，58 天可用（每日門檻 ≥70 bars）
- **OOS 預測天數**：28 天（HAR expanding window，initial=30 天）
- **實驗編號**：K1072（status=PRELIMINARY，因樣本仍遠少於建議的 252 天）

## 三個 estimator 怎麼比

我們同時計算三個版本的日內波動估計：

| Estimator | 公式角色 | 直觀解讀 |
|-----------|---------|---------|
| RV | Σ r²（5 分鐘） | 標準作法，可能被噪音膨脹 |
| RK（Parzen kernel） | γ₀ + 加權自共變項 | 噪音穩健，BNHLS 2008 |
| RV_sub | 5 個 offset grid 平均 | ZMA 2005 中介估計 |

最佳 bandwidth H*由 BNHLS 2008 公式估出，結果落在 14 到 32 之間（平均 17.2）。58 天樣本的描述統計如下：

| 估計量 | 平均 | 標準差 | 中位數 |
|--------|------|--------|--------|
| RV | 5.63e-5 | 3.00e-5 | 5.48e-5 |
| RK | 5.70e-5 | 4.52e-5 | 4.42e-5 |
| RV_sub | 5.25e-5 | 3.66e-5 | 4.20e-5 |

三者相關性都偏高：corr(RV, RK)=0.756、corr(RV, RV_sub)=0.872、corr(RK, RV_sub)=0.934。值得注意的是 **RK 的標準差 (4.52e-5) 反而比 RV (3.00e-5) 大**，這是 small-sample（n_bars≈78）下 RK 估計量本身變異較大的後果——RK 不一定是「更乾淨」的版本，只是對特定噪音模式比較穩健。

![三個 estimator 的時序、散佈圖與分布比較](/api/research/figure/k1072/k1072_estimator_comparison.png)

## 雜訊到底有沒有？初步證據說「不顯著」

如果 5 分鐘有 bid-ask bounce 等噪音，理論上會看到兩個現象：(a) RV 系統性高於 RK（噪音膨脹 RV）；(b) 5 分鐘報酬的一階自相關（γ₁/γ₀）應為負。我們檢查：

| 指標 | 數值 | 解讀 |
|------|------|------|
| (RV−RK)/RV 平均 | +2.99% | RV 平均高出 ~3% |
| (RV−RK)/RV 中位數 | +8.43% | 中位數 ~8.4%，分布右偏 |
| 大於 RK 的天數比例 | 63.8% | 多數日 RV 確實 > RK |
| 配對均值比較 | 統計強度極弱（達顯著水準遠未達 0.10，實際 0.87） | **均值差不顯著** |
| Wilcoxon 非參數比較 | W=745，達顯著水準遠未達 0.10（實際 0.39） | 非參數也不顯著 |
| γ₁/γ₀ 平均 | +0.0006 | 近零，不像典型 bid-ask bounce 的負值 |
| γ₁ 為負的天數比例 | 43.1% | 不到一半 |

兩個關鍵訊號告訴我們：**SPY 在 2026 年初的 58 天樣本裡，看不到顯著的微觀結構雜訊**。雖然 RV 有六成多的日子大於 RK（中位差 8.4% 看起來不小），但配對檢定與非參數檢定都遠未達顯著水準。更重要的是 γ₁/γ₀ 平均近零、且**只有 43% 的日子是負值**——這完全不符合 bid-ask bounce 那種「報酬必為負相關」的指紋。

噪音對訊號比 q 的估計平均 0.31、中位 0.19，但這個估計量依賴 ω² = max(−γ₁/n, 0) 的粗估，因為超過一半的日子 γ₁ 是正的，這個估計量會被 floor 到 0——也就是說 q 的真實值很可能比 0.19 還小，這個量化「雜訊強度」的數字本身不可信賴。

![微觀結構雜訊診斷：γ₁/γ₀、ω̂² 與 H* 時序](/api/research/figure/k1072/k1072_noise_diagnostics.png)

這個結果其實與 Liu, Patton & Sheppard（2015，*Journal of Econometrics*）對流動性最高的指數的觀察一致——5 分鐘對於主要 ETF 已經夠稀疏。SPY 的 daily volume 動輒上億股、bid-ask spread 經常只有 1 分錢，bid-ask bounce 在 5 分鐘聚合下基本被抹平。

## HAR 預測：用 RK 當 target 時 HAR-RK 邊緣勝出

我們同時跑了三個 HAR 模型（Corsi 2009 規格），分別用 RV、RK、RV_sub 當訓練目標，再以 Patton（2011）proxy-robust 的 QLIKE 評分。28 天 OOS 結果：

| QLIKE Target | HAR-RV | HAR-RK | HAR-sub |
|---|---|---|---|
| RV | −8.592 | −8.590 | −8.590 |
| **RK** | −8.660 | **−8.674** | −8.661 |
| RV_sub | −8.703 | −8.726 | −8.713 |

當 target 是 RK 時，HAR-RK 看起來最好（−8.674），略優於 HAR-RV（−8.660）。兩模型比較的統計強度約為 2.0（達顯著水準 0.056），**但未通過 HLZ (2016) 嚴格統計門檻**。28 天 OOS 樣本太短，這個邊緣優勢不能下定論。換言之：如果未來真有微觀結構雜訊，理論上 HAR-RK 在更長樣本下會穩定勝出；但目前我們手上的 28 天 OOS 不足以證實這件事。

![三個 HAR 模型在三種 target 下的 QLIKE 比較](/api/research/figure/k1072/k1072_har_comparison.png)

## 真正讓人鬆一口氣的：K1054 的 A4f 結論完全穩健

這是 K1072 對 Paper 9 影響最大的一段。先前 K1054 用 5 分鐘 RV 當基準，發現 **HAR-RV 顯著贏 A4f-VIX²**（兩模型比較統計強度 t=−3.50，達顯著水準 0.0016，HLZ 嚴格門檻 PASS）。當時最大的疑慮是：「會不會 A4f 輸是因為 RV 被噪音污染、A4f 的 VIX² 結構反而更接近真 σ²？換成 RK 結果會不會翻盤？」

K1072 把同樣三個模型（HAR-RV、GJR-GARCH、A4f-VIX²）在四個 proxy 下重新評估：

| Proxy | HAR-RV | GJR-GARCH | A4f-VIX² | 排序 |
|-------|--------|-----------|----------|------|
| RV_5min | −8.592 | −8.481 | −8.406 | HAR > GJR > A4f |
| **RK** | **−8.660** | **−8.543** | **−8.450** | **HAR > GJR > A4f** |
| RV_sub | −8.703 | −8.559 | −8.466 | HAR > GJR > A4f |
| r²_daily | −7.631 | −7.977 | −8.040 | A4f > GJR > HAR |

**結論很乾脆**：把 noise-robust 的 RK 拿來當 target，HAR > GJR > A4f 的排序紋風不動。HAR-RV vs A4f 的兩模型比較統計強度只是從 t=−3.50 略縮到 −2.86（達顯著水準 0.008），方向完全一致，只是因為樣本短而沒過 HLZ 嚴格門檻。在 RV_sub 下統計強度 t=−3.31，仍達顯著水準（0.003），HLZ 門檻 PASS。

唯一翻盤的是用「日報酬平方 r²」當 target——這時排序變成 A4f > GJR > HAR。但這個翻盤是 **K1054 已經知道的 model-target mismatch（機制性現象）**：HAR 預測的是 intraday RV，本來就不該用全日 r² 來評，這是評分規則錯誤造成的 artifact，不是真實的預測能力翻轉。

![A4f proxy 敏感性：QLIKE heatmap 與兩模型比較統計強度](/api/research/figure/k1072/k1072_a4f_proxy_sensitivity.png)

這意味著 K1054 的核心結論——**HAR-RV 在日內 RV 預測上顯著贏 A4f-VIX²**——通過了「換 noise-robust proxy 也成立」的穩健性檢驗。Paper 9 可以放心用 RV 當主文 target，並把 RK robustness table 放進附錄。

## 局限與下一步：別把初步結論當定論

K1072 標記 PRELIMINARY 不是客套，是真的有重大限制：

1. **58 天樣本過短**：兩模型比較 / 配對檢定的統計強度都不夠；q 估計超過一半被 floor 到 0，真實噪音強度其實沒有可靠估出。
2. **噪音變異數估計粗糙**：BNHLS 2008 Table 1 提供更精確的多 lag autocovariance 估計程序，本實驗只用 ω² = max(−γ₁/n, 0) 簡化版。
3. **Two-Scales RV (TSRV) 未實作**：subsampled RV 是 ZMA 2005 的簡化版，bias-corrected 版本還沒跑。
4. **HAR-RK 預測 RK target 的迴圈論**：隱含假設 RK 是「真 vol」，但 RK 在 n=78 bars 下本身 noisy，這個假設可能過於理想化。
5. **缺 signature plot**：用 RV 對 sampling frequency 作圖（1-min, 2-min, 5-min, 10-min, 15-min）是診斷雜訊的標準工具，本實驗未涵蓋。

## Lookahead audit

K1072 的 HAR 預測使用 expanding window OLS，每天的預測只用到 t 之前的歷史資料；當天的 RV/RK/RV_sub 是用當天 5 分鐘 bars 計算（這是「當日波動率的事後測量」，不是隔日預測 target，符合 realized variance 的標準定義）。Random seed 42 固定。**無 lookahead leakage**。

## 一句話收尾

5 分鐘 SPY 在 2026 年這 58 天裡看起來夠乾淨（沒有顯著微觀結構雜訊），先前用 5 分鐘 RV 為基準的 K1054 結論（HAR > A4f）通過了 noise-robust proxy 穩健性檢驗——但 28 天 OOS 太短，這只是初步觀察，等樣本累積到 252+ 天再下定論。研究誠實的鐵律是：邊緣顯著（達顯著水準 0.056）不是證實，而是「值得繼續看」的訊號。

## 參考文獻

- Barndorff-Nielsen, P. R. Hansen, A. Lunde & N. Shephard (2008). "Designing Realized Kernels to Measure the Ex Post Variation of Equity Prices in the Presence of Noise." *Econometrica* 76(6).
- Zhang, L., P. A. Mykland & Y. Aït-Sahalia (2005). "A Tale of Two Time Scales: Determining Integrated Volatility With Noisy High-Frequency Data." *JASA* 100.
- Corsi, F. (2009). "A Simple Approximate Long-Memory Model of Realized Volatility." *Journal of Financial Econometrics* 7.
- Patton, A. J. (2011). "Volatility Forecast Comparison Using Imperfect Volatility Proxies." *Journal of Econometrics* 160.
- Liu, L. Y., A. J. Patton & K. Sheppard (2015). "Does Anything Beat 5-Minute RV? A Comparison of Realized Measures Across Multiple Asset Classes." *Journal of Econometrics* 187.
- HLZ (2016). 嚴格統計門檻文獻基礎（｜統計強度｜>3.0）。

---

**實驗檔案**：`experiments/k1072/`（README.md、k1072.py、k1072_results.json、4 張 PNG）
**狀態**：PRELIMINARY — 58 天樣本 / 28 天 OOS，所有結論待 252+ 天樣本累積後重跑驗證。
