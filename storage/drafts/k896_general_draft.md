---
title: 「最壞那幾天到底有多壞？」台股 0050 用 ES 補足 VaR 看不到的尾端
audience: general
status: draft
tags:
  - 台股
  - 風險管理
  - 0050
  - 尾端風險
  - 波動率策略
experiment_refs:
  - K896
---

# 「最壞那幾天到底有多壞？」台股 0050 用 ES 補足 VaR 看不到的尾端

## 一句話結論

K896 用 GJR-GARCH 加上 4 種尾端分配假設，對台股 0050（0050.TW）做了完整的 VaR 與 ES（Expected Shortfall，預期尾端損失）測試。**結果在 1% 信心水準下，只有「GJR+歷史模擬」與「GJR+Student-t」兩種設定能同時通過 VaR 三項檢定與 ES 檢定**；而「8.63/VIX 的波動率目標化策略（VT）」在 1% 與 5% 兩個水準的 VaR 檢定都沒過 — 也就是說，VT 策略的「自帶風險度量」會嚴重低估真實尾端發生的頻率，**這是一個必須正視的風險揭露問題**，不是樂觀的結果。

---

## 為什麼一定要看 ES，不能只看 VaR

VaR（Value-at-Risk，風險值）告訴你：「明天我有 1%（或 5%）的機率虧超過 X%」。
但它**沒有告訴你那超過 X% 的日子，平均到底虧多少**。

舉個例子：兩個策略明天 1% VaR 都是 -3%，但策略 A 突破後平均虧 -3.5%，策略 B 突破後平均虧 -8%，A 跟 B 對你的意義天差地別。**這就是 ES 補足 VaR 看不到的部分** — ES 是「條件期望損失」，意思是「在最壞那 1% 的日子裡，平均會虧多少」。

2008 金融海嘯以後，巴塞爾協定（Basel III、FRTB）就把市場風險的監管度量從 VaR 換成 ES，原因正是 VaR 在尾端不夠誠實。對學術研究來說，Acerbi & Szekely (2014) 與 Fissler & Ziegel (2016) 也提供了 ES 的正式檢定工具。

K896 這個實驗的目的，就是把這套 ES 的嚴格檢驗框架，套用到台股 0050。

---

## 實驗設計：5 個模型、2 個信心水準、1756 個交易日

實驗對象：**0050.TW**（元大台灣 50 ETF）。
樣本外（OOS）期間：**2019-01-01 ~ 2026-04-02**，共 **1756** 個交易日。
模型每 **63** 個交易日重新估一次（roll-forward）。
資料來源：yfinance。

樣本外日報酬的描述統計：

| 統計量 | 數值 |
|---|---|
| 平均（年化前） | 0.10% |
| 標準差 | 1.32% |
| 偏度 | -0.169 |
| 峰度 | 7.27 |
| 最小單日報酬 | -10.00% |
| 最大單日報酬 | +9.99% |

峰度 7.27 遠高於常態分配的 3，意味著**極端事件比常態假設預期得多** — 這正是後面為什麼「常態假設下的 VaR 會失準」的原因。

實驗比的 5 個模型分別是：

1. **GJR+常態（Normal）** — 最基礎，假設殘差服從常態
2. **GJR+Student-t** — 殘差用 t 分配，捕捉厚尾
3. **GJR+歷史模擬（HistSim）** — 直接用實證殘差分配，無參數假設
4. **GJR+Cornish-Fisher（CF）** — 用偏度與峰度修正常態分位數
5. **8.63/VIX VT 策略組合** — 一個用 VIX 倒數調整曝險的波動率目標化策略，組合報酬本身的歷史模擬 ES

---

## 1% 信心水準：只有 2 個模型通關

下表是 1% VaR/ES 各模型的成績單（**全部數值來自 K896 結果檔**）：

| 模型 | 違反率 | 預期 | Kupiec | Christoffersen | Basel 紅綠燈 | ES 檢定 | VaR 三項 | 整體 |
|---|---|---|---|---|---|---|---|---|
| GJR+Normal | 1.71% | 1.00% | 不通過 | 通過 | 黃 | 通過 | FAIL | FAIL |
| GJR+Student-t | 1.03% | 1.00% | 通過 | 通過 | 綠 | 通過 | PASS | **PASS** |
| GJR+HistSim | 1.03% | 1.00% | 通過 | 通過 | 綠 | 通過 | PASS | **PASS** |
| GJR+Cornish-Fisher | 0.51% | 1.00% | 不通過（過保守） | 通過 | 綠 | 通過 | FAIL | FAIL |
| 8.63/VIX VT 策略 | 1.73% | 1.00% | 不通過 | 不通過 | 綠 | 通過 | FAIL | FAIL |

**讀懂這張表：**

- **GJR+Normal**：違反率 1.71% 顯著高於 1% — 常態假設低估尾端，**73% 的超出率**。
- **GJR+Cornish-Fisher**：違反率 0.51%，反而**過度保守**（過保守的代價是平日資本佔用過多）。
- **GJR+Student-t 與 GJR+HistSim**：兩者違反率都是 1.03%，幾乎正中靶心，且 Christoffersen 獨立性、Basel 紅燈、ES 檢定全綠 — **這是台股 1% 尾端的兩個合格度量**。
- **VT 策略**：違反率 1.73%，且 Christoffersen 也不通過（意味違反不只多，還會群聚發生 — 風險集中爆發）。

ES 的角度看，1% 水準下 GJR+HistSim 的「壞日子平均損失」是 **-4.02%**，GJR+Student-t 是 **-4.00%** — 兩者非常接近，且 ES/VaR 比值約 1.32，與台股實證觀察一致。

---

## 5% 信心水準：4 個 GJR 模型都過，VT 策略還是失敗

| 模型 | 違反率 | 預期 | Kupiec | Christoffersen | ES 檢定 | 整體 |
|---|---|---|---|---|---|---|
| GJR+Normal | 4.95% | 5.00% | 通過 | 通過 | 通過 | **PASS** |
| GJR+Student-t | 5.58% | 5.00% | 通過 | 通過 | 通過 | **PASS** |
| GJR+HistSim | 5.30% | 5.00% | 通過 | 通過 | 通過 | **PASS** |
| GJR+Cornish-Fisher | 5.13% | 5.00% | 通過 | 通過 | 通過 | **PASS** |
| 8.63/VIX VT 策略 | 6.45% | 5.00% | 不通過 | 通過 | 通過 | FAIL |

**有趣的對比**：在 5% 信心水準下，連最基本的「GJR+Normal」也能過 — 這提醒我們，**「常態夠不夠用」要看你關心的是哪一個尾端**。對 5% 這種較淺的尾端，常態幾乎沒事；但對 1% 這種真正會傷到投資組合的尾端，常態就明顯失靈。

而 **VT 策略在兩個信心水準都 FAIL**，是一致的訊號 — 不是哪一段抓到怪日子，而是**整體 VaR 模型本身對於 VT 策略的尾端就是低估的**。

---

## VT 策略為什麼會 FAIL？

8.63/VIX 是一個經典的「波動率目標化」策略：當 VIX 高（市場恐慌）就降曝險，VIX 低就維持滿倉（曝險上限為 1.0）。直觀上它應該降低尾端風險，**但 K896 的結果顯示這個策略自帶的歷史模擬 ES 度量會低估自己的尾端風險**。

可能的原因：

1. **「擴張式歷史模擬」對結構轉變不敏感** — VT 策略只用過去歷史報酬估 VaR/ES，遇到新的高波動環境時反應慢。
2. **VT 本身降低了平均波動，但極端日的「滑落」仍然會發生** — 這在用 VIX 訊號降曝險的隔天，若市場 gap up/down，VT 並沒有真的避開。
3. **VT 違反 Christoffersen 獨立性檢定**（1% 水準）— 違反會群聚，這意味著 VT 在某些壞時段會連續吃到 tail event，而模型沒抓到這個動態。

**這是一個誠實的負面結論**：VT 是好策略沒錯（前面 K 系列實驗驗證過它在風險調整後報酬上的優勢），**但用它自己的歷史模擬 ES 來向投資人揭露尾端風險，是不夠的**。實務應對方式：對 VT 策略另外用 GJR+HistSim 或 GJR+Student-t 套件做 ES 揭露。

---

## 給投資人的 3 個 takeaway

1. **「我家 ETF 1% VaR 是 X%」這句話沒講完** — 你還要問：「那 ES 是多少？」 K896 顯示 0050 在 1% 信心下，ES 約是 VaR 的 **1.32 倍**（GJR+Student-t）— 也就是壞日子的平均損失比 VaR 大概多 1/3。

2. **常態假設在淺尾端可以接受，但深尾端會騙人** — 5% VaR 用常態就夠，但 1% VaR 用常態的違反率會多 73%。台股市場有顯著厚尾（峰度 7.27），不能套美股的常態經驗。

3. **VT 策略風險揭露要「外接」嚴謹度量** — 不要只用組合本身的歷史 ES，因為它可能低估自己的尾端。同時搭配 GJR+HistSim 的 ES 比較穩。

---

## 圖表（待補）

[TODO 主線程：plot 1% 與 5% VaR/ES 各模型違反率柱狀圖（含預期線）]
[TODO 主線程：plot 0050 樣本外日報酬時序 + GJR+Student-t 1% VaR 線（標出違反日）]
[TODO 主線程：plot ES/VaR 比率對比 5 模型]

---

## 方法論細節（給研究讀者）

- **GJR-GARCH(1,1)** with leverage term，每 63 日 refit 一次（rolling）
- **OOS 條件變異**用遞迴：h[t] = ω + α·r²[t-1] + γ·r²[t-1]·I[r[t-1]<0] + β·h[t-1]
- **Student-t scale 修正**：σ_t = sqrt(h_t · (df-2)/df)，每次 refit 重算 df
- **VaR 訊號 lag**：所有模型 VaR/ES 預測都用 t-1 的條件變異 + t 的實現報酬比較（無 lookahead）
- **VT 訊號 lag**：VIX 用 t-1 的值，乘上 t 的 0050 報酬（標準 cross-market lag）
- **ES 檢定**：Acerbi-Szekely Z2（bootstrap，1000 次）
- **VaR 三項檢定**：Kupiec POF + Christoffersen 獨立性 + Basel 紅綠燈（250 日視窗）

---

## 資料來源

- 0050.TW 日線：yfinance（2019-01-01 ~ 2026-04-02，1756 個交易日）
- VIX 日線：yfinance `^VIX`
- 實驗檔案：K896（`experiments/k896/k896_taiwan_es_supplement_results.json`）
- 樣本：n=1756，refit 次數 28 次

---

## 文獻基礎

- Acerbi, C. & Szekely, B. (2014). "Backtesting Expected Shortfall." *Risk Magazine*.
- Fissler, T. & Ziegel, J. F. (2016). "Higher order elicitability and Osband's principle." *Annals of Statistics* 44(4): 1680-1707.
- Patton, A. J., Ziegel, J. F. & Chen, R. (2019). "Dynamic semiparametric models for expected shortfall (and Value-at-Risk)." *Journal of Econometrics*.
- McNeil, A. J. & Frey, R. (2000). "Estimation of tail-related risk measures for heteroscedastic financial time series." *Journal of Empirical Finance*.
- Kupiec, P. (1995); Christoffersen, P. (1998); Basel Committee (1996, 2019).

---

## 相關實驗

- **K829**：早期台股 1% VaR 研究 — 結論「所有方法都 FAIL」
- **K836**：找到 GJR+CF 是 0050 1% VaR 唯一三項通過的模型
- **K896（本篇）**：補上 ES 維度後，發現 1% 水準下真正同時通過 VaR + ES 的，是 GJR+HistSim 與 GJR+Student-t（CF 反而過保守 FAIL Kupiec）— 修正了 K836 的部分結論

研究是一個逐步累積的過程；K896 不是要推翻 K836，而是要說：**只看 VaR 給的答案，跟同時看 VaR + ES 給的答案，可能不一樣。誠實揭露兩者，是研究與實務都該守的底線。**
