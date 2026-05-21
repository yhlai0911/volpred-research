---
title: 56 天 5 分鐘 SPY 高頻數據能告訴我們什麼？HAR-RV pilot 的 PRELIMINARY 觀察（初步）
audience: general
status: draft
description: 我們累積了 56 天 SPY 5 分鐘高頻資料，跑了 HAR-RV 模型作為 pilot。樣本不足以下任何正式結論，但能讓我們認識「高頻 RV 是什麼、HAR-RV 為何是標準工具、56 天為何只是 PRELIMINARY」三件事。本文誠實標示樣本上限，並解釋 K849 已知的 mechanical caveat。
tags:
  - 一般讀者
  - 高頻數據
  - HAR-RV
  - SPY
  - 樣本不足
  - PRELIMINARY
experiment_refs:
  - K953
---

# 56 天 5 分鐘 SPY 高頻數據能告訴我們什麼？HAR-RV pilot 的 PRELIMINARY 觀察（初步）

> **PRELIMINARY 警語（全文適用）**：本文所述 K953 實驗只用了 56 個交易日（2026-01-14 到 2026-04-06）的 SPY 5 分鐘資料。此樣本遠低於正式 OOS 評估的 252 天門檻。文中所有數字、模型比較、排名都應視為「資料管線檢查點」與「初步訊號」，**不是經過驗證的研究結論**。我們刻意把這些初步觀察寫出來，是為了示範一個誠實研究流程在「資料還沒夠」時該怎麼說話。

[提出: 賴奕豪, 執行: Claude]

## 一句話摘要

我們開始累積 SPY 的 5 分鐘高頻資料，目前累積到 56 個交易日，平均每天 74.8 個 5 分鐘觀測值。這份 pilot 的目的**不是**比較哪個波動率模型最好，而是：(1) 確認資料管線運作正常、(2) 對未來真正能跑正式評估時的設計做暖身、(3) 教育讀者「樣本不足」與「mechanical caveat」這兩件研究誠實上的常見陷阱。

![K953 RV time series, ACF, RV vs r², 模型對照（PRELIMINARY）](experiments/k953/k953_rv_analysis.png)

## 為什麼要看 5 分鐘資料？高頻 RV 是什麼？

傳統 GARCH/GJR 家族的模型只看每日收盤價的報酬率，能取到的「波動率代理」就是當日報酬的平方 r²。問題是 r² 是個**極度噪音**的代理 — 它每天都在跳動，但其中大部分跳動是抽樣雜訊，不是真實波動水準。

高頻資料給我們另一個選項：**Realized Variance（RV）**。做法非常簡單：

> 把當日所有 5 分鐘報酬的平方加總，得到當日的 realized variance。

直觀上這就是「用一整天的盤中變動量，去估這天的真實 σ²」。理論上 Andersen et al.（2003）證明：在沒有微結構雜訊的理想情況下，RV 是日內 quadratic variation 的 consistent estimator。實作上對 5 分鐘 SPY 來講，這個近似已經夠好。

K953 的 56 天樣本中，我們算到：

- 平均每日 RV：5.57e-05（年化波動率約 11.30%）
- 標準差（每日 RV）：3.11e-05（年化波動率 std 3.59%）
- 中位數每日 RV：5.48e-05
- skewness：0.34、kurtosis：-0.56

換句話說，這 56 天 SPY 的「每日 RV 分佈」是一個輕微右偏、扁平、年化波動率落在 11% 附近的分佈。這跟長期 SPY 的歷史 vol 樣態一致 — 但**這只是 56 天**，不要往「未來 SPY 波動會這樣」那個方向推論（**PRELIMINARY**）。

### RV vs r² 是同一件事嗎？

不是。在我們這 56 天樣本中：

- RV 與 r² 的 Pearson 相關係數：0.280
- RV 與 r² 的 Spearman 排序相關：0.229
- 平均 r² 減 RV：3.4e-05（這個正值反映了**隔夜成分** — RV 只算盤中 5 分鐘變動，r² 的「close-to-close」報酬包含隔夜跳動）

這意味著：用 r² 評估的「最佳波動率模型」與用 RV 評估的「最佳波動率模型」很可能是**不同的模型**。這個 measurement 問題在 K849 / K906 / K744 等舊文章中已經反覆強調，這裡我們再用 K953 的數字確認一次。

## HAR-RV 模型：用「昨日 + 上週 + 上月」預測明日 RV

Corsi（2009）提出的 HAR-RV 模型形式很簡單：

$$ RV_t = \beta_0 + \beta_d \cdot RV_{t-1} + \beta_w \cdot \overline{RV}_{t-5:t-1} + \beta_m \cdot \overline{RV}_{t-22:t-1} + \varepsilon_t $$

三個 window 對應三種「異質市場參與者」：

- 日交易者只看昨日 RV → β_d
- 週度交易者看過去 5 天 RV 平均 → β_w
- 月度部位看過去 22 天 RV 平均 → β_m

這個結構為什麼是 vol forecasting 的標準工具？三個原因：

1. **設計上沒有 lookahead 風險**：所有 window 都是 t-1 / t-5..t-1 / t-22..t-1，全部是 backward-looking。不像某些花俏 ML 模型一不小心就把「未來資訊」漏進訓練集，HAR-RV 的線性結構讓它幾乎不可能踩到這個雷。
2. **抓 long-memory 但不用 fractional integration**：RV 有顯著的長記憶，HAR 用「nested 不同尺度的移動平均」近似，省去長記憶模型的估計困難。
3. **可解釋性高**：每個 β 對應一種市場參與者的時間視角。

### 但 56 天能估 HAR-RV 嗎？答案是「不能」（PRELIMINARY）

HAR-RV 的「月窗」需要至少 22 天的 lag，所以 56 天扣掉前 22 天，**只剩 34 個可用觀測值**。我們在這 34 個 obs 上跑 OLS，結果如下：

| 係數 | 估計值 | 顯著性 |
|---|---|---|
| 常數項 | 4.60e-05 | 顯著性 0.225 |
| β_d（日窗） | 0.053 | 顯著性 0.794 |
| β_w（週窗） | -0.325 | 顯著性 0.469 |
| β_m（月窗） | 0.619 | 顯著性 0.376 |

整體 R² = 0.033，調整後 R² = -0.064 — **配適度極差**。沒有任何一個係數達到傳統意義上的顯著水準。

這個結果並**不**告訴我們「HAR-RV 在 SPY 上沒用」 — 這個結論需要 252+ 天的樣本才能下。它告訴我們的只是：**56 天加上 22 天 lag 損耗剩 34 個 obs，去估一個 4 個參數的模型，本來就不會有像樣的結果**。這是「樣本不足」的純粹算術，不是模型診斷（**PRELIMINARY**）。

## 跨模型比較：HAR-RV vs GJR vs EWMA vs MF-GJR(VIX)

我們在 K953 的 33 個共同可比較交易日上算了四個模型的 QLIKE。以下兩張表都標 **PRELIMINARY** — 樣本太小，**排名不可信**。

![K953 PRELIMINARY 四模型 QLIKE 對比（兩種 target）](experiments/k953/k953_qlike_preliminary.png)

### 在 RV target 上（HAR 的 native target）

| 模型 | QLIKE on RV | 註解 |
|---|---|---|
| **HAR-RV** | **0.109** | 直接預測 RV，by design 應贏 |
| EWMA | 0.126 | 預測 σ²，不是 RV |
| GJR | 0.194 | 預測 close-to-close σ² |
| MF-GJR(VIX) | 0.501 | 預測 σ²；多尺度 |

### 在 r² target 上（Patton 2011 proxy-robust 公平比較）

| 模型 | QLIKE on r² | 註解 |
|---|---|---|
| **GJR** | **1.139** | 預測 close-to-close σ² 的 native target |
| EWMA | 1.260 | 同 family |
| MF-GJR(VIX) | 1.275 | 多尺度 |
| HAR-RV | 1.296 | 預測 RV，不是 σ²；用在 r² 上吃虧 |

兩張表呈現一個重要事實：**換 target 就換贏家**。

### K849 mechanical caveat：這不是「HAR 比 GJR 好」

舊實驗 K849 在台指期上發現 HAR-RV 在 RV target 顯著贏 GJR（兩模型比較顯著、t≈-11.14），這個結果**字面上正確**，但**不能解讀為「HAR 在波動率預測上是更好的模型」**。原因很簡單：

- HAR-RV 的訓練目標就是 RV
- GJR 的訓練目標是 close-to-close σ²
- 用 HAR 的目標去比兩個模型 → HAR 贏是 mechanical（設計上必然）
- 公平比較需要 Patton（2011）的 proxy-robust loss + 把 r² 當作 σ² 的 noisy proxy → 這時 GJR family 才有公平的機會

K953 的 56 天 PRELIMINARY 數字也呈現相同 pattern：HAR 在 RV target 上 0.109 < GJR 0.194（HAR 贏），但在 r² target 上 GJR 1.139 < HAR 1.296（GJR 贏）。這跟 K849 的 mechanical caveat 一致。

讀者帶走的訊息應該是：

> **不要看到「HAR-RV 顯著贏 GJR」就認為 HAR 是更好的波動率模型。先問：用什麼 target 評估？兩個模型的 native target 是不是同一個？**

## 自相關結構：高頻 RV 的記憶長度

K953 的 RV ACF 結構：

| Lag | ACF |
|---|---|
| 1 | 0.290 |
| 2 | 0.146 |
| 3 | -0.073 |
| 5 | 0.096 |
| 10 | 0.183 |

可以看到 RV 有中度的 lag-1 持續性（0.29），lag-3 出現微負相關，lag-10 還有 0.18 的 echo — 這跟文獻上 RV 的 long-memory 結構一致。但**請再次注意**：這只是 56 天 ACF，標準誤夠大時 lag-3 的負相關和 lag-10 的 0.18 可能都只是雜訊（**PRELIMINARY**）。

## 為什麼我們特地寫一篇 PRELIMINARY 文章？

研究誠實上有個常見陷阱：**短樣本拿到「看起來像訊號」的數字後，作者往往會抓著這些數字寫成正式結論**。讀者也容易把短樣本的 ranking 當成「這就是答案」。

K953 是個案例研究：

1. 我們的資料管線運作正常 — 56 天 × 平均 74.8 個 5-min obs/day，沒有缺漏。
2. RV 描述統計與長期 SPY vol 一致（年化 11.30%），這是一個 sanity check 通過的訊號。
3. HAR-RV 配適 R² = 0.033 不是「HAR 沒用」 — 是「34 個 obs 估 4 個參數本來就不會有像樣結果」。
4. 模型 ranking 在 RV target 與 r² target 上不同 — 這個 pattern 跟 K849 / K906 一致，但 56 天的具體數字不應拿來推論。
5. 我們會繼續累積資料；當資料達 120+ 天 HAR 才開始有意義；達 252+ 天才能跑正式評估。

## 給讀者的三個 take-away

1. **高頻資料是好事，但時間還沒夠**：5 分鐘 RV 比 r² 雜訊小，是更好的波動率代理，但要做正式模型評估你還是需要 252 天以上的樣本。我們還在累積中。
2. **比較模型前先確認 target 一致**：HAR-RV 的 native target 是 RV，GJR 的 native target 是 close-to-close σ²。在 RV 上比 → HAR 贏（mechanical）；在 r² 上比 → GJR 贏（GJR 的 native target）。**換 target 就換贏家**。
3. **樣本不足時的誠實做法**：標 PRELIMINARY、把樣本上限寫清楚（56 天 < 252 天門檻）、不下強結論、繼續累積資料、把 mechanical caveat 寫在最顯眼的地方。本文示範的是這個流程。

## 數據與方法對照

- 資料：yfinance 5 分鐘 SPY，2026-01-14 至 2026-04-06，56 個交易日，平均 74.8 obs/day
- HAR-RV：Corsi（2009）標準形式 RV_t = β₀ + β_d·RV_{t-1} + β_w·RV_{t-5:t-1} + β_m·RV_{t-22:t-1}
- 對照模型：GJR(1,1,1)（3+ 年日報酬訓練）、EWMA（λ=0.94）、MF-GJR(VIX)
- 評估：QLIKE（lower better）+ MSE，分別在 RV target 與 r² target 計算
- Lookahead 防護：所有 lag 都是 t-1 起，無未來資訊洩漏
- 樣本警語：56 天 < 252 天正式 OOS 門檻，所有結果為 PRELIMINARY

## 參考文獻

- Corsi, F. (2009). A Simple Approximate Long-Memory Model of Realized Volatility. *Journal of Financial Econometrics*, 7(2), 174-196.
- Patton, A. J. (2011). Volatility forecast comparison using imperfect volatility proxies. *Journal of Econometrics*, 160(1), 246-256.
- Hansen, P. R., & Lunde, A. (2005). A forecast comparison of volatility models: does anything beat a GARCH(1,1)? *Journal of Applied Econometrics*, 20(7), 873-889.
- Andersen, T. G., Bollerslev, T., Diebold, F. X., & Labys, P. (2003). Modeling and forecasting realized volatility. *Econometrica*, 71(2), 579-625.

## 相關實驗

- K849：HAR-RV vs GJR 在台指期 5-min 的 mechanical advantage 完整論述
- K906：SPY HAR-RV vs GJR 初步 horse race（隔夜遺漏導致四個量級 QLIKE 差距）
- K744 / K745：日頻 vs 5 分鐘的高頻揭露 GARCH 天花板
- K1057：跳躍分解是噪音 — Jump 不改善 HAR-RV
- K530：HAR 多尺度 vs GARCH 家族 — proxy 變化讓排名翻 3 倍

---

**再次提醒：本文所有數字皆為 PRELIMINARY（56 天 < 252 天門檻）。請以「資料管線檢查點 + 教育性案例研究」的角度閱讀，不要當作驗證後的研究結論。**
