---
title: 不假設分配的風險值估計：Conformal VaR 在 SPY 13 年外樣本表現
audience: general
status: draft
tags:
  - 風險管理
  - VaR
  - SPY
  - GARCH
  - 美股
  - 方法論
experiment_refs:
  - K1026
---

# 不假設分配的風險值估計：Conformal VaR 在 SPY 13 年外樣本表現

## 一、為什麼風險值估計總是「差一截」

在金融機構的日常風險管理中，風險值（Value-at-Risk, VaR）幾乎是不可或缺的工具。它的目的很單純：**告訴你在 99% 的日子裡，明天最多可能虧多少錢**。但實作上卻處處是陷阱。

最常見的做法是先用 GARCH 一族模型估計波動率 σ，再假設報酬率服從某個分配（例如常態分配或 Student-t），把分位數乘上 σ 當作 VaR。這套流程的問題在於：**「報酬率分配」這個假設本身可能就是錯的**。如果真實分配比假設更厚尾，VaR 會低估風險；如果分配是動態變化的（牛市與熊市的尾部行為截然不同），固定一個分配會在某些期間嚴重失準。

實務上常見的後果是：低波動期間 VaR 違反率（實際虧損超過 VaR 的天數比例）遠低於目標，看起來很「安全」，但一進入高波動期間違反率就暴衝，甚至觸發 Basel 監管的 RED zone。風險管理者只能在參數上手動調整，補洞補得焦頭爛額。

**有沒有辦法讓資料自己說話，不用先假設分配？** 這就是本實驗 K1026 想回答的問題。

## 二、Conformal Prediction：讓資料自己定義尾部

Conformal prediction 是統計學界這幾年很熱門的工具，核心思想簡單到令人懷疑：**既然你不知道真實分配，那就用過去一段時間的「標準化殘差」的經驗分位數來當 VaR 的乘數**。

具體操作：
1. 用 GARCH 模型估計每天的波動率 σ_t
2. 計算標準化殘差 e_t = r_t / σ_t（每天的報酬率除以當天的波動率）
3. 取過去 252 天（約一年交易日）e_t 的 α-分位數，作為今天的 VaR 乘數
4. 今天的 VaR_t = σ_t × Quantile_α(過去 252 天的 e)

這個方法有一個非常吸引人的性質：**你不需要假設 e_t 服從常態分配、Student-t、還是 skew-t**。你只需要假設 e_t 在過去 252 天和今天大致同分配（exchangeability），這個假設遠比「報酬率服從 Student-t(df=8)」溫和得多。

但歷史上 conformal VaR 並非沒有踩過坑。本團隊早期的 K800 實驗也做過類似嘗試，但被獨立程式碼審查者推翻為 artifact——校準窗口太短、檢定不嚴格。K1026 重新審視這條路：**用 252 天足夠長的校準窗口、套用嚴格統計檢驗門檻、與 GARCH 參數法做公平比較**，看看 conformal 是真的有效，還是只是好看的故事。

## 三、實驗設計：5 個方法、3 個風險水準、13 年外樣本

### 比較對象

| 編號 | 方法 | 波動率模型 | 分配假設 |
|------|------|-----------|---------|
| M1 | GJR + Normal | GJR-GARCH | 常態 |
| M2 | GJR + t(8) | GJR-GARCH | Student-t(df=8) |
| M3 | A4f + t(8) | A4f（VIX 驅動） | Student-t(df=8) |
| M4 | Conformal-GJR | GJR-GARCH | **無假設** |
| M5 | Conformal-A4f | A4f（VIX 驅動） | **無假設** |

A4f 是本研究系統中經 K1021 驗證的 VIX 驅動波動率模型，它把 VIX 資訊納入 σ 估計，比純 GJR 反應更快。

### 資料

- **標的**：SPY（S&P 500 ETF）
- **樣本期**：2005-01-03 至 2026-04-09，共 5,601 個交易日
- **外樣本**：2013-01-02 起算約 13 年（3,287-3,337 個 OOS 觀察值）
- **校準窗口**：252 天（約一年交易日）
- **重估頻率**：每 63 天重新訓練一次
- **隨機種子**：42（所有隨機程序固定）

### 評估指標（每個 VaR 水準 6 個）

- **Kupiec UC test**：違反率是否等於目標
- **Christoffersen CC test**：違反是否獨立（不集中在某些日子）
- **Dynamic Quantile（DQ）test**：違反是否能被歷史變數預測
- **Basel traffic light**：監管機構的紅綠燈分類
- **Acerbi-Szekely Z1/Z2**：ES（條件尾部期望損失）的兩個檢定
- **Sharpness**：平均 |VaR|（在 coverage 正確的前提下，越小越節省資本）

每個方法在 1%、2.5%、5% 三個水準各跑 6 個檢定（1% 和 5% 沒做 ES 檢定，計 4 個），總計 12 個檢定點，全 PASS 才算完美。

## 四、結果：Conformal 拿下兩個 6/6 完美 scorecard

![VaR Scorecard](experiments/k1026/k1026_var_scorecard.png)

### 總體 Pass Rate

| 方法 | 通過 / 總檢定 | 通過率 |
|------|-------------|--------|
| M1: GJR + Normal | 7 / 12 | 58% |
| M2: GJR + t(8) | 7 / 12 | 58% |
| M3: A4f + t(8) | 10 / 12 | 83% |
| **M4: Conformal-GJR** | **11 / 12** | **92%** |
| **M5: Conformal-A4f** | **11 / 12** | **92%** |

兩個 conformal 方法把通過率推到 92%，比最強的參數法（A4f + t(8) 83%）再多一階。

### 2.5% VaR 細部表現（最具資訊量的水準）

| 方法 | Scorecard | 違反率（目標 2.5%） | 平均 \|VaR\| |
|------|-----------|-------------------|-------------|
| M1: GJR + Normal | 4/6 | 3.51% | 0.0178 |
| M2: GJR + t(8) | 4/6 | 3.39% | 0.0181 |
| M3: A4f + t(8) | 5/6 | 3.06% | 0.0181 |
| **M4: Conformal-GJR** | **6/6** | **2.56%** | 0.0200 |
| **M5: Conformal-A4f** | **6/6** | **2.71%** | 0.0195 |

注意 M1 和 M2 的違反率分別是 3.51% 和 3.39%，這意味著**用 GJR + 常態或 Student-t(8) 算出來的 2.5% VaR，實際上有 35% 以上的時間被超過**——這是 Basel monitoring 的 GREEN zone 邊緣，再差一點就要進 YELLOW。M4/M5 的違反率落在 2.56% / 2.71%，幾乎貼合目標 2.5%。

更關鍵的是，**這不是因為 VaR 變得「過度寬鬆」造成的好看數字**——M4 的平均 |VaR| 是 0.0200，比 M1 的 0.0178 寬約 12%。它**真的多吃了一些尾部風險**，但換到了正確的 coverage。

## 五、最重要的發現：高低波動期間的差距大幅縮小

風險管理最大的痛點，是模型在不同市場狀態下的表現極不平均。低波動期間 VaR 過保守（違反率遠低於目標，浪費資本），高波動期間又不夠（違反率暴衝，吃監管罰單）。

我們把外樣本依當天的 VIX 中位數分成「高 VIX」與「低 VIX」兩個 regime，看 2.5% VaR 在兩個 regime 各自的違反率：

![VaR Sharpness Comparison](experiments/k1026/k1026_var_sharpness.png)

| 方法 | 高 VIX 違反率 | 低 VIX 違反率 | 差距 |
|------|--------------|--------------|------|
| M1: GJR + Normal | 6.04% | 0.96% | 5.08pp |
| M2: GJR + t(8) | 5.87% | 0.90% | 4.97pp |
| M3: A4f + t(8) | 4.61% | 1.50% | 3.11pp |
| M4: Conformal-GJR | 4.01% | 1.10% | 2.91pp |
| **M5: Conformal-A4f** | **4.01%** | **1.40%** | **2.61pp** |

GJR + 常態的差距高達 5.08 個百分點：高波動期間實際違反率達 6.04%，是目標 2.5% 的兩倍多；而低波動期間只有 0.96%，浪費了大量資本緩衝。

A4f 因為把 VIX 資訊內嵌在波動率估計裡，差距縮到 3.11 個百分點。Conformal-A4f 進一步把差距壓到 2.61 個百分點，**幾乎是 GJR + 常態的一半**。這對風險管理者的意義是：**用 conformal 算 VaR，在牛熊轉換的關鍵時刻不太需要重新校正**——它本身就具有一定程度的市場狀態適應能力。

## 六、Coverage 與 Sharpness 之間有清楚的 tradeoff

天下沒有白吃的午餐。Conformal 取得更準確的 coverage，付出的代價是 VaR 平均比參數法寬：

- Conformal-GJR 比 GJR + t(8) 寬 10.5%
- Conformal-A4f 比 A4f + t(8) 寬 7.4%

對銀行的資本計提來說，這意味著要多預留約 7-10% 的緩衝。但若考慮 Basel monitoring 的 RED zone 風險（一旦進入會被加成資本要求），更準確的 coverage 在長期反而能避免更大的成本。

## 七、底層模型仍然重要：A4f 全面優於 GJR

實驗的另一個明確發現是：**conformal 不是萬能藥，底層 σ 估計品質還是基礎**。

| 比較 | A4f-based | GJR-based |
|------|-----------|-----------|
| 參數法 pass rate | M3: 83% | M2: 58% |
| Conformal pass rate | M5: 92% | M4: 92% |
| Conformal sharpness | M5: 0.0195 | M4: 0.0200 |
| QLIKE（越低越好） | -8.644 | -8.537 |

雖然 M4 和 M5 的 pass rate 都是 92%，但 M5 在 sharpness 上仍勝 M4 約 2.7%。換句話說：**A4f 把 VIX 資訊融入 σ 估計，幫 conformal 提供了更好的「乘數基底」**。

結論很直接：**好的 σ 模型 + conformal 校準 = 最佳 VaR**，而非「conformal 就好，σ 隨便用」。

## 八、局限性與下一步

1. **單一資產**：本實驗僅在 SPY 上驗證。不同資產的尾部行為差異很大，台股、QQQ、加密貨幣的 conformal 表現需另做驗證。
2. **校準窗口固定 252 天**：未測試不同窗口長度的敏感度。窗口太短會被近期事件主導，太長則對市場 regime 變化反應慢。
3. **1% VaR 仍困難**：所有方法在 1% 水準的 DQ 檢定都未達顯著水準，暗示殘差仍有時序依賴沒被完全捕捉。可能解法是 adaptive conformal——對近期殘差賦予更高權重。
4. **Sharpness 代價**：對極端注重資本效率的金融機構，多 7-10% 的緩衝不是免費。是否值得需依機構成本結構評估。

## 九、給讀者的實務啟發

1. **若你正在用 GJR + 常態分配算 VaR，請檢查違反率**。本實驗顯示 SPY 上的 13 年違反率達 3.5%，遠超 2.5% 目標。
2. **若你已經升級到 Student-t**，A4f + t(8) 在 SPY 上拿到 83% pass rate，是不錯的中間方案。
3. **若你想要更穩健的 coverage**，conformal 是值得認真考慮的選項——尤其是在 VIX 高低 regime 切換頻繁的市場。
4. **不要因為某個方法「比較簡單」就用它**。M1（GJR + 常態）是最直觀的方法，但在嚴格檢定下表現最弱。簡單與正確是兩件事。

VaR 不是金融工程的歷史古董，而是每天有真金白銀風險暴露的工具。讓資料自己說話，比強行套一個分配假設，往往更接近事實。

## 十、資料來源

- **標的價格**：SPY 收盤價，2005-01-03 至 2026-04-09，來自 yfinance（共 5,601 個交易日）
- **波動率指數**：VIX，來自 yfinance ^VIX
- **波動率模型**：GJR-GARCH 與 A4f（VIX-driven），自寫 MLE 估計
- **實驗代號**：K1026
- **外樣本**：2013-01-02 起，共 3,287-3,337 個觀察值（依 conformal 校準窗口扣減略有差異）
- **隨機種子**：42（所有隨機程序均固定）
- **完整結果**：`experiments/k1026/k1026_results.json`

## 參考文獻

- Kupiec, P. (1995). Techniques for Verifying the Accuracy of Risk Measurement Models. Journal of Derivatives.
- Christoffersen, P. F. (1998). Evaluating Interval Forecasts. International Economic Review.
- Engle, R. F., & Manganelli, S. (2004). CAViaR: Conditional Autoregressive Value at Risk by Regression Quantiles. JBES.
- Acerbi, C., & Szekely, B. (2014). Backtesting Expected Shortfall. Risk Magazine.
- Patton, A. J. (2011). Volatility Forecast Comparison Using Imperfect Volatility Proxies. Journal of Econometrics.
- Vovk, V., Gammerman, A., & Shafer, G. (2005). Algorithmic Learning in a Random World. Springer.（Conformal prediction 的奠基文獻）
