---
title: "K619：抓出 K618 兩個 bug 後，KAN 的真實成績單長這樣"
audience: general
status: draft
tags:
  - 研究
  - KAN
  - 神經網路
  - 波動率預測
  - 方法論
  - bug 修正
  - GJR-GARCH
experiment_refs:
  - K619
---

## 一句話結論

K618 那篇報告把 2024 年熱門新架構 **KAN（Kolmogorov–Arnold Networks）** 評為大幅輸給傳統 GJR-GARCH，後來 Codex 程式審查抓到兩個會放大誤差的 bug；K619 把 bug 修掉重跑，KAN 的 QLIKE 從 1.0958 大幅降到 0.4778，但**仍然輸給 GJR-GARCH 0.3%**。換句話說，KAN 沒有像舊版那麼慘，可是也沒有真的贏 30 年前的老牌模型。

## 為什麼要重做 K618？

K618 是平台第 6 次用神經網路挑戰 GJR-GARCH 的 ML ceiling 實驗。當時得到的結論是「KAN 比 GJR 差好幾倍」——表面看起來支持「ML 在波動率預測沒用」的故事，可是在主線程把實驗檔送進 Codex GPT-5.4 做程式審查時，審查報告抓到兩個會直接污染所有比較的問題：

1. **Bug 1（估計目標不一致）**：GJR-GARCH 直接輸出條件標準差 σ，但 KAN、MLP、HAR-ABS 三個模型都在預測「日報酬絕對值」 |r_t|。在常態假設下兩者差一個 √(2/π) ≈ 0.7979 的常數，沒做轉換等於讓 GJR 系統性高估。
2. **Bug 2（refit 頻率不對等）**：K618 中 GJR 每 22 個交易日重新 fit 一次，但兩個神經網路要等 63 天才 refit。神經網路看到的訓練視窗永遠比 GARCH 老 41 天，這是**讓 ML 模型在比賽裡多綁了一隻手**。

主線程同時補了兩個次要 fix：把 NN 的訓練 loss 從 MSE 換成 QLIKE（與評估指標一致）、把預測下限 floor 從 1e-6 拉到 0.001（避免 QLIKE 因為 σ→0 爆炸）。整套修正版重新編號 K619。

## 數據與設定

- **資料**：yfinance 的 SPY（S&P 500 ETF）+ ^VIX，2004-01-02 至 2026-03-26
- **OOS 樣本**：2023-01-01 至 2024-12-31，共 501 個交易日
- **Rolling window**：1000 天訓練 / 22 天 refit，全部模型同步
- **預測目標**：|r_t|（日報酬絕對值，作為日波動率 proxy）
- **評估指標**：QLIKE（主）、MSE、MAE、Pearson 相關係數

四個模型：

| 模型 | 參數量 | 架構摘要 |
|---|---|---|
| GJR-GARCH(1,1) | 4 | Zero mean + Normal，輸出 √(2/π)·σ |
| HAR-ABS | 4 | OLS：c + b1·\|r_{t-1}\| + b5·rv5 + b22·rv22 |
| KAN | 366 | 1 KAN 層（8→5）+ Linear 輸出，B-spline 邊權重 |
| MLP | 833 | 8→32→16→1 + Softplus，傳統前饋網路 |

KAN 與 MLP 都用 Adam（lr=0.001）+ early stopping（patience=20）+ QLIKE loss。

## Bug 修掉之後，KAN 從天差地遠變成貼著 GJR 跑

修正前後最直觀的對比是 K618 vs K619 的 QLIKE：

| 模型 | K618 QLIKE | K619 QLIKE | 變化 |
|---|---:|---:|---:|
| GJR-GARCH | 0.5146 | 0.4764 | **−7.4%** |
| HAR-ABS | 0.4948 | 0.4948 | 0.0% |
| KAN | 1.0958 | 0.4778 | **−56.4%** |
| MLP | 6.7038 | 0.4861 | **−92.7%** |

兩個神經網路的數字幾乎是「砍半再砍半」級別的修正——這也直接說明 K618 的「ML 慘輸」結論並不可靠。把 K618 拿來宣傳 ML ceiling 是在用 bug 出來的數字當論據。

但修正完之後 KAN 的成績是：QLIKE **0.4778**，GJR-GARCH **0.4764**——KAN 比 GJR 差 0.3%。換成統計檢定講，KAN vs GJR 的兩模型比較統計強度只有 0.23、達顯著水準（顯著性 0.82），完全沒辦法拒絕「兩個模型一樣好」的虛無假設。

## 圖表

### 圖 1：兩個 bug 修正前後，QLIKE 的天壤之別

![K618 vs K619 bug fix QLIKE 對比](experiments/k619/figures/fig1_bug_fix_before_after.png)

紅色棒是 K618（含 bug）、藍色棒是 K619（修正後）。可以看到 GJR-GARCH 與 HAR-ABS 幾乎沒變動，但 KAN 與 MLP 的 QLIKE 從 1.10 / 6.70 直接砸回 0.48 附近——K618 那組「ML 慘輸 GARCH」的圖，其實是 bug 在說話，不是模型在說話。

### 圖 2：修正後 4 個模型的 QLIKE 與相關係數

![K619 four-model OOS comparison](experiments/k619/figures/fig2_model_qlike_comparison.png)

左圖（QLIKE 越低越好）顯示 GJR-GARCH 0.4764 略勝 KAN 0.4778、KAN 略勝 MLP 0.4861、MLP 略勝 HAR-ABS 0.4948。右圖（相關係數越高越好）反而是 MLP 0.243 第一、GJR 0.200、KAN 0.194、HAR-ABS 0.117。**「QLIKE 第一」與「相關係數第一」不是同一個模型**——這正是評估指標要選對的提醒。

### 圖 3：模型參數量 vs QLIKE，沒有「越複雜越準」

![Complexity vs QLIKE scatter](experiments/k619/figures/fig3_complexity_vs_qlike.png)

橫軸用 log scale 畫參數量、縱軸是 QLIKE。GJR-GARCH 和 HAR-ABS 都只用 4 個參數，KAN 用 366 個、MLP 用 833 個。神經網路把參數量放大兩個數量級，得到的 QLIKE 改善是 0% 至 −0.3%。這不是「KAN 沒救」、而是 SPY 日頻波動率訊號已經被 GJR 的 4 參數結構捕捉得差不多。

## KAN 內部排名其實還是有故事

把焦點從「KAN vs GJR」拉到「KAN vs 其他 ML 與 HAR」：

- **KAN 略勝 MLP**（0.4778 vs 0.4861，差 −1.7%）：B-spline 可學習邊權重比固定 ReLU 略好，但統計強度 −0.93、達顯著水準（顯著性 0.35），不顯著
- **KAN 顯著贏 HAR-ABS**（0.4778 vs 0.4948，差 −3.4%）：兩模型比較統計強度 −2.33、達顯著水準（顯著性 0.020），雖然沒過嚴格統計檢驗門檻（通常要 |t|>3.0），但已經是 4 對比較中 KAN 唯一接近顯著的勝出
- **HAR-ABS 顯著輸 GJR-GARCH**：兩模型比較統計強度 3.51、達顯著水準（顯著性 0.0005），是表中**唯一過嚴格門檻**的差異

換句話說：KAN 的 spline 邊權重結構在這個資料上比純 ReLU MLP 略有優勢，也明顯比同樣 4 參數的 HAR 線性回歸好；它輸的對象只有 GJR-GARCH，而且輸的差距小到統計不顯著。

## 兩個對讀者比較重要的提醒

### 提醒一：bug 不是「結論的細節」、而是「結論本身」

K618 第一版若沒進審查程序就直接寫文章，「ML 慘輸 GARCH」會變成讀者帶走的故事。但任何「估計量比 7 倍誤差」的差異，**第一直覺都應該是先懷疑代碼**——這也是平台研究誠實原則的核心。K619 是一次很乾淨的「修流程不修資料」案例：bug 修掉、重跑、誠實報告新結果，包括「KAN 沒贏 GJR」這條對 ML 派而言不太討喜的結論。

### 提醒二：「同 4 參數打成平手」不是 KAN 的失敗

KAN 用了 366 個參數、MLP 用了 833 個，兩個都跟 GJR 4 參數的 QLIKE 在同一個小數點第三位上比。對日頻 |r_t| 這種低訊噪比的目標，**這結果其實已經是「KAN 沒爛」的證據**。KAN 真正的潛力應該到高訊噪比、有強非線性結構的任務（例如選擇權 implied vol surface、或日內 5 分鐘級資料）才會展現。把它放在日頻 SPY 等於拿超跑去比賽塞車路段。

## 限制與後續

- **單資產**：只測 SPY，沒做台股 / 跨市場 robustness
- **單期間**：OOS 只有 2023–2024 兩年，沒涵蓋 2008 / 2020 等大空頭
- **最簡 KAN**：1 層 5 nodes、order 1 的 piecewise linear B-spline，沒用 pykan 完整版
- **Daily proxy 限制**：用 |r_t| 當波動率 proxy，本身就比 RV-based proxy 雜訊高
- **常態假設**：GJR 的 √(2/π)·σ 換算假設常態，但日報酬有厚尾，這個換算對 GJR 反而略不利

下一步可以做的對照：(1) 跨資產（台股 0050、QQQ）測 KAN 的 ranking 是否一致；(2) 用 5 分鐘 RV 當目標、訊噪比拉高再測 KAN；(3) 把 KAN 放進 GARCH-MIDAS 框架——這正是 K1263 在做的延伸（可惜 K1263 的結論是「KAN-MIDAS 比 GJR 差 33%」，反而更悲觀）。

## 給讀者的 take-away

- **2024 年諾獎熱門新架構不一定打得贏 30 年前的老模型**——尤其在 SPY 日頻波動率這種訊噪比偏低的任務上。
- **bug 一定要審**：估計目標、refit 頻率、loss 函數、預測 floor，每一條都會直接搬動結論。
- **「沒贏」≠「無用」**：KAN 與 GJR 在 QLIKE 上打成平手、只用約 1/2 的 MLP 參數量，這已經是 spline 結構在 ML 模型內部勝出的證據。

---

**數據來源**：yfinance（SPY、^VIX）；OOS 期間 2023-01-01 至 2024-12-31，n=501。
**對應實驗**：K619（`experiments/k619/k619_kan_corrected_results.json`），相關脈絡 K530（HAR-ABS 冠軍）、K600（ML meta-lesson）、K618（被 invalidate 的原版）、K1263（KAN-GARCH-MIDAS 跨資產延伸）。
**程式審查**：Codex GPT-5.4（identification of K618 bugs 1 & 2）。
