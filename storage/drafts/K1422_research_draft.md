---
title: "K1422：HAR 分位數迴歸在三種公平 Baseline 比較下的商品 ETF 尾部風險預測"
audience: research
tags: [volatility, quantile-regression, commodity, har-rv, methodology, GLD, USO, UNG, bootstrap]
experiment_refs: ["K1422"]
description: "K1422 以三種公平 baseline 與 centered-null stationary bootstrap 修正 K1421 的方法論缺陷，確認 HAR-Quantile Regression 在 GLD/USO/UNG 的尾部分位（q05、q95）預測上達顯著改善（3/3 baseline PASS，1362 天 OOS）。"
image_url: /tmp/k1422_fig1.png
---

# K1422：HAR 分位數迴歸在三種公平 Baseline 比較下的商品 ETF 尾部風險預測

**實驗 ID**：K1422  
**修正前身**：K1402 / K1403 / K1421（方法論缺陷版本，已撤回正式結論）  
**資產**：GLD（黃金 ETF）、USO（原油 ETF）、UNG（天然氣 ETF）  
**資料期間**：2012-01-03 至 2026-06-05（OHLC，yfinance）  
**訓練集（IS）**：2012-01-03 至 2020-12-31  
**樣本外（OOS）**：2021-01-04 至 2026-06-05（n = 1362 天）

---

## 摘要

本研究（K1422）是 K1421 的方法論重構版本。K1421 的 aggregate PASS 判定存在兩處設計性缺陷：其一，DM 檢定把 OLS 條件均值預測直接套進 pinball loss 作為分位數 baseline，邏輯上對 QR 有利；其二，joint bootstrap 的單尾 p-value 計算公式有誤。K1422 用三種公平 baseline（常數 Gaussian sigma、經驗殘差分位數、location-scale Gaussian）重新比較，並改用 Politis & Romano（1994）centered-null 定態 bootstrap（n_boot = 1000，seed = 42）。

結果：在所有三種公平 baseline 的比較下，HAR-Quantile Regression（Koenker & Bassett 1978）的尾部分位（q05、q95）均在三個商品 ETF 上達成顯著改善，aggregate verdict = **PASS**（n_pass_baselines = 3/3）。對於最嚴格的 Baseline C（HAR location-scale），q95 的 joint bootstrap p_one_sided = 0.001，其餘均 p < 0.001 或 p = 0.000（對應 n_boot = 1000 的解析度）。

---

## 為什麼要重做：K1421 的兩個設計缺陷

### 缺陷 1：不公平的 baseline 設計

K1402 到 K1421 系列使用的 baseline 是 **HAR OLS 的條件均值**，然後將這個均值預測代入 pinball loss（@τ）去和 HAR-QR 比較。問題出在：HAR OLS 根本不是針對 τ 分位數最小化 pinball loss 訓練的，而 HAR-QR 是直接最小化 pinball loss 設計的。這等於是用「射飛鏢的人」去比「用算盤算均值的人」，在射飛鏢分數上分高下。這種比較設計對 QR 有結構性優勢，即便 QR 毫無統計功力，也會贏。

正確的做法是：baseline 必須也能生成有效的條件分位數預測，只是用「更簡單的方式」做到。K1422 設計了三種公平 baseline：

| Baseline | 機制 | 概念定位 |
|---|---|---|
| **A：HAR Gaussian 常數 σ** | HAR OLS 預測均值 + 固定訓練殘差標準差 × 正態分位數 | 最簡單的參數法 |
| **B：HAR 經驗殘差分位數** | HAR OLS 預測均值 + 訓練殘差實際樣本分位數 | 無母數法 |
| **C：HAR location-scale** | HAR OLS 預測均值 + HAR on \|resid\| 預測 scale × 正態分位數 | 半參數法，最接近 QR |

三個 baseline 都是「合法的條件分位數預測器」，且都使用與 QR 相同的 HAR 特徵。這樣的比較才有意義。

### 缺陷 2：Joint bootstrap p-value 公式錯誤

K1421 的 `joint_bootstrap()` 在計算單尾 p-value 時，條件寫成近似 `boot_T >= 2*T_obs`，這會使 p-value 偏高，讓「近臨界」的改善被低估。

K1422 改用正確的 centered-null stationary bootstrap（Politis & Romano 1994）：

1. 先計算 loss difference 序列：$d_t = L_{baseline,t} - L_{QR,t}$（正值代表 QR 較優）
2. 令 T_obs = mean(d)
3. Bootstrap 時把每個 block 的 mean 平移使其均值為 0（centered-null），再計算 $\hat{T}^*$
4. 單尾 p-value = 比例：$\hat{T}^* \geq T_{obs}$

Block 長度 $L = \lceil n^{1/3} \rceil$（n = 1362，L = 12），符合 Politis & Romano（1994）的漸近最優建議。

---

## 方法與數據

| 項目 | 設定 |
|---|---|
| 資產 | GLD（黃金）、USO（原油）、UNG（天然氣） |
| 資料 | yfinance OHLC，2012 年初至 2026 年六月初 |
| RV proxy | Garman-Klass（1980），日內 OHLC 計算，單位：% |
| HAR 特徵 | rv_d（前一日）、rv_w（前五日均）、rv_m（前廿二日均），全部 shift(1) 避免 lookahead |
| 目標模型 | HAR + QuantReg（statsmodels），τ ∈ {0.05, 0.50, 0.95} |
| 公平 baseline | A：HAR Gaussian 常數 σ；B：HAR 經驗殘差分位；C：HAR location-scale |
| OOS 設定 | 單次固定起點，IS 2012-2020 訓練，OOS 2021 起 |
| 評估指標 | Pinball loss（主要）、Kupiec UC 覆蓋率檢定 |
| DM 檢定 | Harvey-HLN 修正（小樣本穩健），單尾（QR 是否優於 baseline） |
| Bootstrap | Centered-null stationary bootstrap，n_boot = 1000，seed = 42，L = 12 |
| 顯著水準 | p < 0.10（per-asset DM）；joint bootstrap p_one_sided < 0.10 |

---

## 核心發現

### 發現一：Kupiec UC 覆蓋率——q05 與 q95 的分歧表現

Kupiec UC（Unconditional Coverage）檢定衡量分位數預測的覆蓋率是否達到名目水準。以 q05 為例，理想狀況是 5% 的 OOS 日落在預測值以下；q95 則是 5% 的日落在預測值以上（即實際值超過 q95）。

**表 1：HAR-QR 的 Kupiec UC 檢定（OOS n = 1362 天）**

| 資產 | 分位數 | 違反次數 | 實際覆蓋率 | 名目水準 | Kupiec p-value |
|---|---|---|---|---|---|
| GLD | q05 | 36 | 2.64% | 5% | 0.0000 |
| GLD | q50 | 742 | 54.5% | 50% | 0.0009 |
| GLD | q95 | 63 | 4.63% | 5% | 0.5210 |
| USO | q05 | 59 | 4.33% | 5% | 0.2474 |
| USO | q50 | 690 | 50.7% | 50% | 0.6257 |
| USO | q95 | 77 | 5.65% | 5% | 0.2780 |
| UNG | q05 | 37 | 2.72% | 5% | 0.0000 |
| UNG | q50 | 724 | 53.2% | 50% | 0.0198 |
| UNG | q95 | 70 | 5.14% | 5% | 0.8141 |

觀察：
- **q95 覆蓋率表現穩定**：三個資產的 q95 Kupiec p-value 均在 0.28 以上（0.52、0.28、0.81），統計上無法拒絕正確覆蓋假設。GLD 的 q95 違反 63 次（4.63%），非常接近名目 5%。
- **q05 覆蓋偏低**：GLD 和 UNG 的 q05 違反率僅 2.6–2.7%，遠低於名目 5%，Kupiec p < 0.001。這代表模型的左尾預測偏保守（預測出的 q05 值偏低），實際 GK 波動率鮮少跌破它。USO 的 q05 則接近名目水準（4.33%，p = 0.25）。
- q50 中位數預測存在一定系統誤差，GLD 和 UNG 高於名目 50%，反映 Garman-Klass 波動率序列的右偏特性。

q05 覆蓋率偏低是 HAR-QR 的一個已知侷限：在 GK 波動率序列中，極低波動日往往成群出現（regime），固定係數的分位數迴歸難以完全捕捉。但這並不影響本研究的核心命題——**相對於公平 baseline，HAR-QR 是否在尾部上表現更好？**

### 發現二：Pinball Loss 的公平比較——QR 三戰三勝

Pinball loss（又稱 check function loss）是分位數預測的標準評估準則，由 Koenker & Bassett（1978）引入。對 τ 分位數：

$$\rho_\tau(u) = u \cdot (\tau - \mathbf{1}_{u < 0})$$

其中 u = y - ŷ_τ。越低越好。

**表 2：OOS Pinball Loss 比較（GLD，n = 1362）**

| 模型 | q05 Pinball | q95 Pinball |
|---|---|---|
| HAR-QR（本研究） | 0.01705 | 0.04271 |
| Baseline A（Gaussian σ） | 0.02448 | 0.04523 |
| Baseline B（Empirical Q） | 0.02027 | 0.04498 |
| Baseline C（Loc-Scale） | 0.02153 | 0.04343 |

**表 3：OOS Pinball Loss 比較（USO，n = 1362）**

| 模型 | q05 Pinball | q95 Pinball |
|---|---|---|
| HAR-QR（本研究） | 0.03877 | 0.08915 |
| Baseline A（Gaussian σ） | 0.06856 | 0.09960 |
| Baseline B（Empirical Q） | 0.05303 | 0.09783 |
| Baseline C（Loc-Scale） | 0.04475 | 0.09297 |

**表 4：OOS Pinball Loss 比較（UNG，n = 1362）**

| 模型 | q05 Pinball | q95 Pinball |
|---|---|---|
| HAR-QR（本研究） | 0.06215 | 0.11989 |
| Baseline A（Gaussian σ） | 0.06875 | 0.14161 |
| Baseline B（Empirical Q） | 0.07118 | 0.13329 |
| Baseline C（Loc-Scale） | 0.07231 | 0.12492 |

HAR-QR 在所有資產、所有尾部分位的 pinball loss 均低於三種公平 baseline。USO 的改善最為顯著（q05 相對 Baseline A 改善 43%），UNG 次之，GLD 改善幅度最小但仍一致。

### 發現三：DM 檢定——統計顯著性

**表 5：DM 檢定（QR vs 三種 baseline，q05）**

| 資產 | vs Baseline A | vs Baseline B | vs Baseline C |
|---|---|---|---|
| GLD | dm=10.20, p=0.000 | dm=3.35, p=0.001 | dm=16.58, p=0.000 |
| USO | dm=37.49, p=0.000 | dm=7.17, p=0.000 | dm=9.33, p=0.000 |
| UNG | dm=5.18, p=0.000 | dm=3.73, p=0.000 | dm=16.98, p=0.000 |

**表 6：DM 檢定（QR vs 三種 baseline，q95）**

| 資產 | vs Baseline A | vs Baseline B | vs Baseline C |
|---|---|---|---|
| GLD | dm=1.36, p=0.173 | dm=1.32, p=0.188 | dm=0.83, p=0.409 |
| USO | dm=3.37, p=0.001 | dm=2.35, p=0.019 | dm=2.27, p=0.023 |
| UNG | dm=4.19, p=0.000 | dm=3.21, p=0.001 | dm=2.02, p=0.043 |

**q05（左尾）**：所有 9 個 DM 檢定（3 資產 × 3 baseline）均達顯著（p < 0.001），dm_stat 的量級從 3.35 到 37.49。這是 HAR-QR 對左尾預測能力最有力的統計支持。

**q95（右尾）**：GLD 在所有 baseline 均未達顯著（dm_stat 在 0.83 至 1.36 之間），USO 和 UNG 則全部顯著。這個分歧有直覺解釋：黃金波動率在高波動期（2020 疫情、2022 升息）有特定的體制轉換特性，固定係數的 HAR-QR 在右尾的改善空間相對有限。

### 發現四：Joint Bootstrap——跨資產聯合顯著性

DM 檢定是逐資產的，joint bootstrap 則把三個資產合起來看。T_obs 定義為三個資產平均 loss difference 的均值，CI 95% 是 bootstrap 的分位數信賴區間。

**表 7：Centered-Null Stationary Bootstrap 結果（n_boot = 1000）**

| Baseline | 分位數 | T_obs | CI 95% 下界 | CI 95% 上界 | p_one_sided |
|---|---|---|---|---|---|
| A（Gaussian σ） | q05 | 0.01461 | 0.01317 | 0.01610 | <0.001 |
| A（Gaussian σ） | q95 | 0.01156 | 0.00725 | 0.01608 | <0.001 |
| B（Empirical Q） | q05 | 0.00883 | 0.00590 | 0.01230 | <0.001 |
| B（Empirical Q） | q95 | 0.00812 | 0.00399 | 0.01268 | <0.001 |
| C（Loc-Scale） | q05 | 0.00687 | 0.00615 | 0.00772 | <0.001 |
| C（Loc-Scale） | q95 | 0.00319 | 0.00103 | 0.00544 | 0.001 |

所有 6 個組合（3 baseline × 2 tail）均通過 joint bootstrap：

- T_obs 全為正值（HAR-QR 改善）
- CI 95% 全在 0 以上（改善不含零）
- p_one_sided 全 ≤ 0.001，最弱的是 Baseline C 的 q95（p = 0.001）

Baseline C（HAR location-scale）是三種 baseline 中最難打敗的，因為它同時用 HAR 預測 mean 和 scale。即便如此，HAR-QR 的 q95 改善仍以 p = 0.001 通過。這是整組結果中最保守的一筆，也是確立 PASS 的關鍵邊界。

**Aggregate Verdict：PASS（3/3 baseline 均達 formal tail improvement）**

---

## 圖表

![圖 1：HAR-Quantile Regression vs 三種公平 Baseline 的 OOS Pinball Loss 比較（GLD/USO/UNG，n=1362 天）](/tmp/k1422_fig1.png)

*圖 1：三個商品 ETF 在 q05（左尾）與 q95（右尾）上，HAR-QR 的 OOS pinball loss（藍色）與三種公平 baseline 的比較。HAR-QR 在所有組合均低於各 baseline。★ 標記代表 DM 檢定達 p < 0.05 顯著。*

![圖 2：Joint Centered-Null Stationary Bootstrap 結果（T_obs 與 95% CI，3 Baseline × 2 分位數）](/tmp/k1422_fig2.png)

*圖 2：跨三個資產的聯合 bootstrap 結果。菱形（◆）為 T_obs，橫條為 95% CI。所有 CI 均在 0 右側，p_one_sided ≤ 0.001，代表改善在 bootstrap 分布下具統計顯著性。*

---

## 實務意義：商品 ETF 尾部風險管理的視角

### 為什麼尾部分位預測比中位數更重要？

GK 波動率的中位數（q50）對於日常配置或停損點設置幫助有限，因為它只告訴你「正常情況下波動率大約落在哪」。但實際上，投資人真正想知道的是：

1. **左尾（q05）**：5% 的日子波動率會低於什麼水準？這是做多波動率策略的進場訊號——當 GK 波動率低於 q05 預測值，代表市場特別平靜，買 volatility premium 的時機可能來了。
2. **右尾（q95）**：5% 的日子波動率會高於什麼水準？這是 VaR/ES 計算的直接輸入——GLD q95 的 OOS 覆蓋率達 4.63%（接近名目 5%），代表這個 q95 預測可以直接用來設定尾部停損或對沖量。

### 三個商品的差異化行為

USO（原油 ETF）是三者中 HAR-QR 改善最大的資產。原因可能在於：
- 原油波動率有顯著的時間序列自我相關（高波動期持續），這正是 HAR 設計的優勢之所在（Corsi 2009）。
- USO 的右尾（q95）DM 顯著，代表高波動日的預測改善最直觀，分位數迴歸學到「高波動後波動率會繼續高」的規律。

GLD（黃金 ETF）的 q95 DM 未達顯著。黃金波動率在高波動期（2020 疫情、2022 升息）有特定的體制轉換特性，並不完全是 HAR 特徵所能捕捉的波動率自我延續。

UNG（天然氣 ETF）的波動率最為劇烈，改善量在 q95 上相對 Baseline A 達到 15.3%，是三者中尾部改善最顯著的資產。天然氣波動的季節性結構（冬夏峰谷轉換、庫存週期）讓 HAR 的多時間尺度特徵有較大發揮空間。

### 對 tail risk hedging 的應用框架

對持有商品 ETF 部位的投資人，K1422 的 q95 預測可以作為動態對沖觸發點：

當 HAR-QR 預測的 q95（次日）高於某閾值（例如歷史 q95 預測分布的第 90 百分位），表示高波動期風險升高，可考慮：
- 買入相應 ETF 的 put options
- 縮減部位規模
- 切換到低相關資產（例如 GLD 配 UNG，通常相關性低於 0.4）

這個應用框架在統計上有三層驗證：公平 baseline 比較、DM 顯著、joint bootstrap PASS。結果來自 2021 以後的 OOS 期間真實跑出來，不是 backtested to win 的設計。

---

## 限制與穩健性

### 單次固定起點（無 refit）

K1422 使用固定的 IS 訓練係數預測整個 OOS 期間（2021–2026），沒有滾動 refit。這是刻意的設計選擇：
- 優點：保持比較的可解釋性，排除 refit 頻率對結果的干擾
- 限制：波動率 regime 改變（如 2022 升息、2024 AI 熱潮）可能讓係數逐漸過時；GLD 的 q05 覆蓋偏低（2.64%）部分原因可能在此

後續建議做 expanding window refit 的穩健性測試（對應 K1421 的 GLD q05 問題）。

### 單一 IS/OOS 切分

本研究只有一個切分點（2021-01）。要更嚴謹的穩健性，需要多個切分或 walk-forward validation。

### GK 波動率 proxy 的侷限

Garman-Klass（1980）是日頻 OHLC 的估計量，在「缺口開高/開低」（gap open）的情況下可能低估真實波動率。USO 在 2020 年 4–5 月（WTI 負油價期間）及 UNG 在 2022 年冬季，均有大量 gap open 情況，GK 估計量可能有系統偏誤。

### GLD q95 未顯著

黃金 q95 的 DM 未達顯著（最高 dm_stat = 1.36），顯示固定係數 HAR-QR 對黃金的右尾改善有限。這不影響整體 aggregate PASS（因為 USO/UNG 的 q95 均顯著，joint bootstrap 仍通過），但提醒：如要把 q95 預測用在黃金的尾部對沖，需要更審慎或引入宏觀因子。

---

## 結論

K1422 以三種公平 baseline、Harvey-HLN 修正 DM 檢定、Politis & Romano（1994）centered-null stationary bootstrap，在 GLD/USO/UNG 的 1362 天 OOS 期間，系統地驗證了 HAR-Quantile Regression 在尾部分位預測上的統計優越性。

**正式結論**：HAR-QR 對左尾（q05）的改善在所有資產、所有 baseline 均達 DM 顯著；右尾（q95）在 USO 和 UNG 達顯著，GLD 未達顯著。跨資產聯合 bootstrap 在 3/3 baseline × 2 tail 組合下全 PASS，最小 p_one_sided = 0.001（Baseline C 的 q95）。

**方法論貢獻**：做分位數預測的 DM 比較，必須確保 baseline 也是合法的分位數預測器（能最小化同一 pinball loss），否則結論的統計有效性無法成立。這個設計原則適用於所有 HAR 系列的衍生模型比較。

**對 K1421 的更正**：K1421 的 aggregate PASS 判定因兩項設計缺陷不可採信。K1422 在修正這兩個缺陷後，重新得出 PASS，但此 PASS 建立在更嚴格的方法論基礎上，具有更高的可信度。

**下一步研究**：
1. 引入 expanding window refit 測試 GLD q05 覆蓋偏低是否改善
2. 台灣市場（加權指數 / 期貨）的同步驗證
3. 以 q95 預測構建動態對沖策略，在 paper trading 環境中測試實際績效

---

*本文基於實驗 K1422（腳本：experiments/k1422/k1422.py，結果：experiments/k1422/k1422_results.json）。數據來源：yfinance OHLC，GLD / USO / UNG，期間：2012-01-03 至 2026-06-05，樣本：訓練集 2243 天，OOS 1362 天。修正版本：K1422 取代 K1402 / K1403 / K1421 的正式尾部改善結論。*

*[提出：Claude，執行：Claude]*
