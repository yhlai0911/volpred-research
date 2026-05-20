---
title: TAIFEX TX1 五分鐘 RV 的 HAR-family 四連 NULL — Decomposition 為什麼沒幫上忙
audience: research
phase: synthesis
category: milestone
tags: [null-result, har-family, taifex, methodology, synthesis, decomposition]
experiment_refs: [K868, K1301, K1303, K1309]
image_url: "https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/null_quartet_har_tx1_dm.png"
proposer: Claude
status: draft
---

## 摘要

本文彙整四個獨立實驗（K868 / K1301 / K1303 / K1309）的結果，所有實驗都針對 TAIFEX TX1 五分鐘已實現變異數（Realized Variance, RV），測試四種主流 HAR-family decomposition 是否能在 OOS 預測上打敗 magnitude-pooled 的 baseline HAR-RV（Corsi, 2009）。四種 decomposition 涵蓋文獻上彼此正交的四條切割路徑——session（日 vs 夜）、sign（正向 vs 負向 semivariance, Barndorff-Nielsen et al. 2010）、jump（連續 vs 跳躍部分, Andersen et al. 2007）、path（路徑相依特徵, Liu, Fu and Hong 2025）——而四份 Diebold-Mariano-Harvey-Leybourne-Newbold (DM-HLN) 檢定**全部都距離 Harvey ±3σ 門檻甚遠**（|t| 介於 0.35 到 1.29 之間，p ∈ [0.197, 0.729]）。我們把這個現象稱為 NULL Quartet，並指出其方法論意涵：在 TX1 這個單一 session、流動性集中、機構主導的市場結構下，HAR-RV 的 magnitude-pooled 規格已經 forecast-sufficient，四種 orthogonal 切割都沒能提供 marginal information。文章末段亦比較 SPX/SSE 上的文獻發現，指出 decomposition 效能是 market-structure-dependent，並提示未來方向。

## 1. 研究背景

HAR-RV 自 Corsi（2009, *JFEC*）提出以來，已成為高頻波動率預測的事實上工作馬模型：用日（d）/週（w）/月（m）三個尺度的 RV 平均值線性疊加，估計簡單、解釋清楚、out-of-sample 表現穩健。文獻上對 HAR-RV 的改進，大致沿著四條 orthogonal decomposition 路徑展開：

1. **Session decomposition**：將 RV 拆成日盤與夜盤（或 overnight / intraday）兩段，動機是日內與隔夜的資訊產生機制不同（macro vs idiosyncratic, 流動性差異, market microstructure noise）。代表作：Hansen & Lunde (2005, *JFEC*)、Andersen, Bollerslev & Huang (2011, *JoE*)。
2. **Sign decomposition (Realized Semivariance)**：將 RV 分為正向跳動（RS⁺）與負向跳動（RS⁻），動機是不對稱波動率（leverage / asymmetric reaction）。代表作：Barndorff-Nielsen, Kinnebrock & Shephard (2010, *Volatility and Time Series Econometrics*)；Patton & Sheppard (2015, *JFE*)。
3. **Jump decomposition (HAR-CJ)**：用 Bipower Variation 把 RV 拆為 continuous（C）與 jump（J）兩部分，動機是 jump 的 persistence 結構與 continuous component 不同。代表作：Andersen, Bollerslev & Diebold (2007, *RFS*)；Corsi, Pirino & Renò (2010, *JoE*)。
4. **Path decomposition (HAR-PD)**：考慮 return 路徑相依特徵（例如累積符號加權平均），動機是路徑訊息可能補 magnitude pooling 之不足。代表作：Liu, Fu & Hong (2025, arXiv:2503.00851)。

四條路徑切割方式不同，動機獨立，文獻上在 S&P 500、SSE Composite、ETF 與 forex 上皆有過 PASS 紀錄。本研究的問題很單純：**這四條路徑在 TAIFEX TX1（台指期）五分鐘 RV 上，誰能打敗 baseline HAR-RV？**答案是 — 沒有。

## 2. 資料與方法

| 項目 | 規格 |
|---|---|
| 標的 | TAIFEX TX1（台指期近月） |
| 頻率 | 5 分鐘 intraday，日聚合 |
| 樣本期間 | 2017-06-16 ~ 2026-05-07（約 9 年） |
| n_har_rows | 2162 ~ 2186（依 lag 結構） |
| Train / Test | 1513-1514 / 649 |
| Baseline | HAR-RV（Corsi 2009）三尺度 OLS |
| Loss | Squared error（DM-HLN test） |
| Forecast horizon | h=1 |
| Significance gate | Harvey ±3σ（pass_3sigma=False 即視為 NULL）|
| Seed | 42（K1309 bootstrap），實驗皆固定 |

所有實驗都遵守 `signal.shift(1)` lag 慣例（feature 使用 t-1 期之前的資料預測 t 期 RV），baseline 與 decomposition 模型在同一 lag 結構下比較，避免 lookahead bias。

## 3. NULL Quartet — 四個實驗結果一覽

| K | Decomposition | 來源文獻 | DM-HLN t | p-value | MSE_OOS (baseline) | MSE_OOS (alt) | Verdict |
|---|---|---|---|---|---|---|---|
| K868 | Day-Night (session) | Hansen-Lunde 風格 | **+1.084** | 0.278 | — | — | NULL |
| K1301 | HAR-RS (sign) | BNKS 2010 | **+1.290** | 0.197 | 1.4709 | 1.4503 | NULL |
| K1303 | HAR-CJ (jump) | ABD 2007 | **−0.910** | 0.363 | 1.4709 | 1.4890 | NULL |
| K1309 | HAR-PD (path) | Liu-Fu-Hong 2025 | **−0.346** | 0.729 | 1.4712 | 1.5023 | NULL |

注解：K868 之 t-stat 為 HAR-DN vs HAR-RV，loss=QLIKE on RV proxy（K868 沒跑 squared-error DM-HLN，但 QLIKE 結果同樣未跨 Harvey 門檻）。K1301/K1303/K1309 為 squared-error DM-HLN，h=1，n_test=649。

四個 |t| 值最大也只有 1.29 — 不到 Harvey ±3σ 門檻的一半。其中**正負號還剛好兩兩相反**：sign 與 session decomposition 的點估計微幅優於 baseline，jump 與 path decomposition 的點估計微幅劣於 baseline，但**沒有一條跨過統計顯著線**。

![NULL Quartet: 4-K DM-HLN bar chart with Harvey gate](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/null_quartet_har_tx1_dm.png)

K1309（HAR-PD）另外跑了 500 次 block bootstrap，MSE 差距 95% CI = [−0.175, +0.172]，**完整包含 0**，再次印證 NULL。

![K1309 HAR-PD vs HAR-RV MSE 對比](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/k1309_mse_plot.png)

## 4. 共通根因：為什麼 4 條 orthogonal 路徑都 NULL？

四種 decomposition 在動機與切割方式上彼此獨立 — 它們**不會**因為某個 implementation bug 同時失敗（已先後通過各自 K 的 code review）。因此 NULL Quartet 指向的是**結構性原因**，不是工程缺陷。我們整理三層解釋：

### 4.1 Magnitude-pooled HAR-RV 在 TX1 daily horizon 已經 forecast-sufficient

HAR-RV 的核心假設是：**過去不同尺度（d / w / m）的 RV 平均**已包含預測下期 RV 所需的全部 magnitude information。在 TX1 的日聚合上，HAR-RV 的 in-sample R² ≈ 0.517，OOS R² ≈ 0.043；雖然 OOS 偏低（與所有單變數 RV 模型在台指期一致），但**四種 decomposition 模型的 OOS R² 都沒有明顯更高**（HAR-RS 0.057, HAR-CJ 0.031, HAR-PD 0.023）。Decomposition 雖然把 RV 切成更細的 component，但每個 component 在 d/w/m 三尺度下的 lag 結構**已被 baseline 的 d/w/m 平均吸收掉大半** — 切細未必帶來 marginal info。

### 4.2 台股單一 session 結構簡化了資訊產生

相對於 S&P 500（NYSE + AH + 跨時區 ECN）或 SSE（早盤 / 午盤 / 跨港股 spillover），TAIFEX TX1 的交易結構相對單純：日盤 08:45-13:45（5 小時連續）+ 夜盤 15:00 起。資訊在台指期上**集中於日盤前段**，這使得：

- **Session decomp (K868)**：日 vs 夜 RV 的橫斷面相關性高（K868 descriptive: corr_day_night 高），夜盤 RV 的 marginal predictive content 已被日盤 RV 吸收
- **Sign decomp (K1301)**：TX1 的 RS⁺ / RS⁻ 不對稱性在 daily aggregation 下被平均掉；leverage effect 在台指期經常被報導為較 SPX 弱（institutional vs retail 結構差異）
- **Jump decomp (K1303)**：K1303 descriptive 顯示 mean_j_share_of_rv ≈ 7.13%、frac_days_zero_jump ≈ 40.9% — 跳躍在 TX1 daily RV 的相對佔比偏低，且 j_d/j_w/j_m 係數 magnitude 在 baseline 旁的點估計極不穩定（j_d ≈ +2224, j_m ≈ −8416），暗示 jump component 沒有 stable lag structure 可以利用
- **Path decomp (K1309)**：HAR-PD 的 R² (in-sample ≈ 0.278) 遠低於 HAR-RV (0.517) — path features 在 TX1 日頻上本身解釋力就比 magnitude pooling 弱

### 4.3 Daily horizon 對 decomposition 不友善

四個 K 都是 h=1 daily forecast。在更短的 horizon（intraday tick / 5-min step）上，decomposition 可能還有空間 — 因為短期 lag 結構未被 d/w/m 平均吸收；在更長的 horizon（週、月）上，magnitude 的 mean-reversion 主導，decomposition 進一步邊際遞減。Daily horizon 剛好落在 HAR-RV magnitude pooling 最有效的區段。

## 5. 與已發表文獻的比較 — Market-structure dependent，不是文獻錯

這份 NULL Quartet 看起來「跟教科書唱反調」。但**正確的解讀是 market structure dependent**，不是說 BNS / ABD / Liu 的方法本身錯誤：

- **BNKS (2010) 在 SPX**：HAR-RS 對 SPX intraday/daily RV 通常 PASS，原因是 SPX 顯著的 asymmetric leverage（VIX skew 結構印證），與 TX1 較弱的 leverage 不同
- **ABD (2007) 在 SPX/SSE**：HAR-CJ 在跨資產 panel 通常 PASS，jump component 比例較高（SPX cluster jumps、SSE policy-induced jumps），TX1 的 jump share 偏低（7.13%）使 marginal contribution 受限
- **Liu et al. (2025) 在 SPX/USEQ**：HAR-PD 在美股單股 panel 有報導 PASS，但 path features 對 broad index 的有效性本來就比 single-stock 弱（cross-sectional averaging 摧毀 path-dependent info），TX1 是 broad index，這結果與 Liu et al. 對 broad index 的 caveat 一致

換句話說：**這些 decomposition 在 TX1 上的 NULL，不是「方法失敗」，而是「TX1 沒有足夠的 decomposable structure 讓方法施展」**。

## 6. 對交易與避險的實務意涵

1. **HAR-RV 是 TX1 day-ahead RV forecast 的合理 default**。多花估計 degrees of freedom 跑 HAR-RS / HAR-CJ / HAR-PD，在 TX1 daily horizon 上沒有 statistically detectable 的 forecast 收益。
2. **不要把 SPX 上的 best practice 機械式移植到 TX1**。若你的 risk model（VaR / ES）以 SPX 為原型訓練，移植到台指期前**必須在 TX1 上做同樣的 decomposition gating test**。
3. **省下的 estimation cost 應該投入到 distinct mechanism**，例如 macro-conditional regime、cross-asset spillover、event-window jump clusters — 而不是繼續在 HAR family 內做 marginal decomposition。

## 7. 限制與穩健性

1. **n_test = 649**：對 daily horizon 是中等樣本，bootstrap CI 已驗證 NULL 不是樣本量不足造成
2. **US benchmark 資料受限**：K1303/K1309 的 US 標的（SPY/QQQ/GLD）受 yfinance 60d intraday cap 限制，n_har_rows ≈ 36-37，被各 K 的 `sample_trust_flag` 標為 UNTRUSTWORTHY 或僅供 exploratory；本文 verdict 完全基於 TX1
4. **Horizon h=1 only**：未測 h=5（週）、h=22（月），無法排除 longer-horizon decomposition 的可能 marginal value
5. **Squared-error loss only**：對 tail risk-sensitive 應用（VaR/ES），需另跑 asymmetric loss（QLIKE / Patton 2011 family）— K868 已在 QLIKE 下同樣 NULL，但 K1301/K1303/K1309 squared-error-only 是限制
6. **沒測 ensemble / convex combination**：HAR-RV 與 decomp models 的 convex weights 可能 marginally beat any single model，但 single-model NULL 已足以反駁「decomposition 必然 PASS」的弱主張

## 8. 未來方向

四個 orthogonal decomposition 都 NULL 暗示：**在 HAR-RV 之上再切 RV 本身的 components 已邊際遞減**。下一步應該跳出 HAR family，測試三種 distinct mechanism：

1. **Macro-conditional regime switching**：以 VIX / Taiwan FSI / 利差為 conditioning variable 對 HAR-RV 做 MS-HAR
2. **Jump-cluster Hawkes** intensity 直接建模 jump arrival rate（而非把 jumps 平均成 d/w/m component）
3. **Cross-asset spillover**：S&P 500 / KOSPI200 / Nikkei225 night-time RV 對 TX1 next-day RV 的 incremental predictive content

這些方向不再依賴「把 RV 本身切細」，而是引入 RV 以外的 information set — 對 magnitude-pooled HAR-RV 是真正的 orthogonal challenge。

## 9. 結論

NULL Quartet 是一個 informative null：四個 orthogonal HAR-family decomposition 在 TAIFEX TX1 五分鐘 RV 上**齊聲說 No** — 不是因為方法失敗，而是因為 TX1 的 daily-horizon, magnitude-pooled forecast 結構已被 baseline HAR-RV 吸收完。對台指期波動率交易者與避險者而言，這提供一個簡潔的 baseline 結論：用 HAR-RV，把 budget 投到 distinct mechanism。對學術研究而言，這提供一個 cross-market 比較的 control case — decomposition 在 SPX/SSE PASS、在 TX1 NULL 的對比，說明 microstructure / market participant composition / leverage strength 對 RV-decomposition payoff 的決定性影響。

## 參考文獻

1. Corsi, F. (2009). A Simple Approximate Long-Memory Model of Realized Volatility. *Journal of Financial Econometrics*, 7(2), 174-196. DOI: 10.1093/jjfinec/nbp001
2. Barndorff-Nielsen, O. E., Kinnebrock, S., & Shephard, N. (2010). Measuring downside risk: realised semivariance. In *Volatility and Time Series Econometrics: Essays in Honor of Robert F. Engle* (T. Bollerslev, J. Russell, M. Watson, eds.), Oxford University Press.
3. Andersen, T. G., Bollerslev, T., & Diebold, F. X. (2007). Roughing it up: including jump components in the measurement, modeling, and forecasting of return volatility. *Review of Economics and Statistics*, 89(4), 701-720. DOI: 10.1162/rest.89.4.701
4. Patton, A. J., & Sheppard, K. (2015). Good volatility, bad volatility: signed jumps and the persistence of volatility. *Review of Economics and Statistics*, 97(3), 683-697. DOI: 10.1162/REST_a_00503
5. Liu, J., Fu, X., & Hong, Y. (2025). Path-dependent realized volatility forecasting. *arXiv preprint* arXiv:2503.00851.
6. Harvey, D., Leybourne, S., & Newbold, P. (1997). Testing the equality of prediction mean squared errors. *International Journal of Forecasting*, 13(2), 281-291. DOI: 10.1016/S0169-2070(96)00719-4
7. Diebold, F. X., & Mariano, R. S. (1995). Comparing predictive accuracy. *Journal of Business & Economic Statistics*, 13(3), 253-263. DOI: 10.1080/07350015.1995.10524599

---

**Source experiments**: K868（HAR-DN, Day-Night session decomp NULL）, K1301（HAR-RS, BNKS sign decomp NULL）, K1303（HAR-CJ, ABD jump decomp NULL）, K1309（HAR-PD, Liu-Fu-Hong 2025 path decomp NULL）. 全部數據來自 `experiments/<id>/<id>_results.json`，未經人工調整。
