---
title: "分數階差分救得了波動率預測嗎？跨五資產的誠實答案"
audience: general
status: draft
tags: [波動率, 分數階差分, GARCH, 長記憶, 機器學習特徵, 比較研究]
experiment_refs: [K194]
---

# 分數階差分救得了波動率預測嗎？跨五資產的誠實答案

## 為什麼會想到「分數階差分」？

任何做時間序列研究的人都知道一件事：**讓資料變平穩（stationary）**幾乎是所有計量模型的入場券。經典做法是「取差分」——`x_t − x_{t−1}`——這在統計上很乾淨，卻有個代價：差分一次就會把序列裡的「記憶」幾乎洗光。研究者得到平穩，但失去了長期相依結構（long memory），而長期相依正是波動率最有名的 stylized fact 之一。

Marcos López de Prado 在 2018 年的《Advances in Financial Machine Learning》中提出一個聰明的折衷：**分數階差分（Fractional Differentiation, FFD）**。它把差分階數 `d` 從整數 1 推廣到 0 到 1 之間的小數，例如 `d=0.1` 或 `d=0.3`。直覺上：

- `d=0`：完全不差分，保留所有記憶但可能不平穩。
- `d=1`：完全差分，平穩但記憶被砍光。
- `d=0.1`：差分一點點，希望同時保留長記憶與獲得平穩性。

這個構想在金融機器學習圈廣為流傳，許多教科書、課程和 Kaggle competition 都把它列為「特徵工程必修」。聽起來很美，但**實證上能不能在波動率預測上打贏成熟的 GJR-GARCH？** 這就是 K194 想回答的問題。

---

## 資料來源

- **實驗代號**：K194（Fractional Differentiation for Volatility Features）
- **資產**：SPY、QQQ、GLD、TLT、BTC-USD（五個跨類別代表）
- **樣本期**：SPY/QQQ/GLD/TLT 為 2007-01-03 至 2025-03-21（4,584 個交易日）；BTC-USD 為 2015-01-01 至 2025-03-22（3,734 個交易日）
- **OOS 期間**：2023-01-01 至 2024-12-31（涵蓋 2023 銀行業危機、2024 利率高點）
- **波動率代理**：每日報酬平方 `r_t²`（squared daily returns）
- **資料來源**：Yahoo Finance（透過 `yfinance` 套件）
- **訓練窗**：OLS rolling window 500 天；GARCH rolling refit 2000 天

---

## 我們做了什麼

整個實驗有三個層次：

**第一層：差分階數選擇**。對每個資產跑 ADF（Augmented Dickey-Fuller）檢定，掃 `d ∈ {0.1, 0.2, ..., 0.9}`，找到讓序列達顯著水準的最小 `d`（記為 `d*`）。直覺：用最少的差分換到平穩。SPY/QQQ/GLD/TLT 的 `d* = 0.1`，BTC-USD 的 `d* = 0.2`。原始 `log RV` 序列其實**本身就達顯著水準**（SPY ADF 統計量 −8.94），但分數階差分讓平穩性更強（SPY 在 `d=0.1` 時 ADF 達 −18.13）。

**第二層：模型對決**。比較七個模型在 OOS 期間的 QLIKE 損失（QLIKE 是波動率預測的標準損失函數，越負代表預測越準）：

- **EWMA(0.94)**：RiskMetrics 經典 baseline。
- **GJR-GARCH(1,1)**：捕捉非對稱波動率（壞消息影響大於好消息）。
- **Raw_logRV_OLS**：直接用 log RV 做 OLS 預測。
- **FFD(d=0.1)_OLS / FFD(d=0.3)_OLS / FFD(d=0.5)_OLS**：用分數階差分後的 log RV 做 OLS。
- **FFD(VIX, d=0.1)_OLS**：把 VIX 也做分數階差分加進回歸（僅 SPY/QQQ）。

**第三層：兩模型比較顯著**。對每個資產跑比較檢定（FFD vs 各 baseline），看 FFD 的優勢是否真的達顯著水準。

---

## 實證結果：FFD 有打贏 GJR-GARCH 嗎？

直接看數字。下表是各資產的最佳模型與 QLIKE：

| 資產 | 最佳 `d*` | 最佳模型 | 最佳 QLIKE | GJR-GARCH QLIKE | EWMA QLIKE |
|------|-----------|----------|------------|-----------------|------------|
| SPY | 0.1 | FFD(VIX, d=0.1)_OLS | −8.6355 | −8.6156 | −8.5778 |
| QQQ | 0.1 | FFD(VIX, d=0.1)_OLS | −7.9677 | −7.9368 | −7.9115 |
| GLD | 0.1 | FFD(d=0.1)_OLS | −8.4489 | −8.4484 | −8.4323 |
| TLT | 0.1 | EWMA(0.94) | −8.2005 | −8.1958 | −8.2005 |
| BTC | 0.2 | GJR-GARCH | −6.2883 | −6.2883 | −6.2815 |

最直接的結論：**只用 log RV 自身做 FFD（不加 VIX）的版本，5/5 資產都沒有顯著贏 GJR-GARCH**。
唯一兩個 FFD-based 模型贏 GJR 的案例（SPY、QQQ），靠的是把 VIX 加進回歸；換言之，**贏的是「VIX 資訊」而不是「分數階差分本身」**。

更嚴格地看兩模型比較顯著：以 SPY 為例，FFD(d=0.1)_OLS vs GJR-GARCH 的統計強度只有 0.84，遠未達顯著水準（顯著性 0.40）。QQQ、GLD、TLT 的比較檢定全都未達顯著水準，BTC-USD 甚至 FFD 還小輸 GJR。**把五個資產合起來看：FFD 對 GJR 的勝率 = 0/5。**

唯一「真的有顯著差距」的兩兩比較，是 FFD(d=0.1)_OLS 大勝**未經差分的 Raw_logRV_OLS**（SPY 的比較統計強度 −4.14、QQQ 的 −3.94，皆達高度顯著水準）。這證明分數階差分**確實改善了線性 OLS 的預測能力**——只是改善幅度不足以超越 GARCH 家族用遞迴結構自然捕捉到的波動率群聚。

---

## 為什麼會這樣？三個原因

**(1) GARCH 家族的遞迴結構已經內建了「記憶」**。GJR-GARCH 的條件變異數方程式 `σ²_t = ω + α·r²_{t−1} + γ·I·r²_{t−1} + β·σ²_{t−1}` 中那個 `β·σ²_{t−1}` 把過去全部資訊以指數衰減的方式保留下來。雖然數學上 GARCH 不是嚴格的長記憶，但在實際預測上，它已經把「持續性」做得很好。FFD 想補的那塊記憶，GARCH 已經補了。

**(2) 日頻 RV 代理本身雜訊太強**。我們用 `r²_t` 當每日真實波動率代理，這是業界標準做法，但它的訊噪比很差。看 K194 的 lag autocorrelation：原始 log RV 在 lag 1 的相關係數約 0.13–0.18；FFD(d=0.1) 後 lag 1 變成 −0.04 到 −0.11，**短期記憶被破壞，長期記憶又被雜訊蓋過**。線性 OLS 在這種訊號下挖不出 GARCH 已經挖到的東西。若改用 5 分鐘日內收盤估的 realized variance（K966 走的方向），訊噪比會好很多——但那是另一個故事。

**(3) FFD 的權重結構在實證樣本下「截斷代價」很高**。固定窗 FFD 用一個閾值（這裡是 1e-5）把過久的權重砍掉。`d=0.1` 留下 4,076 個 lag、`d=0.3` 留下 2,275 個、`d=0.5` 留下 927 個。但因為每個 lag 的權重都很小（`d=0.1` 的權重總和才 0.41），**等於在做一個高度平滑的 moving average**——這跟線性 OLS 用 lagged log RV 抓相依結構，效果其實大同小異。

---

## 相關研究脈絡

- **K966 HAR-PD**：Corsi (2009) 的 HAR-RV 用 1 日 / 5 日 / 22 日的多時間尺度線性組合近似長記憶，是另一條「不靠 FFD 也能抓 long memory」的路。
- **K1024 GARCH refit**：探討 GARCH 滾動再估計的頻率與成本，確認 GJR 的時變結構是它打贏靜態模型的關鍵。
- **K1066 A4f**：嘗試用 multiplicative GARCH 修正非對稱結構。

把這些放在一起：**波動率的長記憶結構，多時間尺度線性回歸（HAR）+ GARCH 遞迴 + 適當再估計，已經把訊號擠得很乾**。FFD 的概念優美，但實證 ROI 在日頻、squared-return 代理下很低。

---

## Lookahead 風險與本研究的處理

分數階差分本身只用過去資訊（`x_t` 的 FFD 值依賴 `x_{t}, x_{t−1}, ..., x_{t−L}`），沒有 forward leak。但**`d` 的選擇方式**是 lookahead 的高風險點：如果用「在全樣本 ADF 上掃出最小 `d`」，再拿這個 `d` 回頭做 OOS 預測，等於用未來資訊調超參數。

本實驗的 `d*` 是用**所有歷史 OOS 開始前的資料**做 ADF 選的（2007–2022 的訓練段），OLS 預測再走 rolling window，不回頭重選 `d`。文獻上更嚴格的做法是 walk-forward 每天重選 `d`，K194 的設定算是中間光譜——足以排除最粗糙的全樣本作弊，但若未來改進可以再緊縮。所有隨機程序（OLS 訓練樣本切分等）固定 seed。

---

## 誠實結論：null result 也是結果

K194 的結論很簡單：**在每日頻率、用 squared returns 當 RV 代理、線性 OLS 預測的設定下，分數階差分（無論 `d=0.1, 0.3, 0.5`）都沒有比 GJR-GARCH 顯著更好**。FFD 的概念吸引力（保留長記憶 + 達平穩）在實證上被兩件事抵銷：(a) GARCH 已經內建了足夠的記憶結構；(b) 日頻 RV 雜訊太強，讓 FFD 保留的記憶結構在線性 OLS 框架下無法被有效挖出。

這不代表 FFD 一無是處——它在 SPY/QQQ 上把 VIX 做完分數階差分後加進回歸，確實榨出了一點 baseline 之外的 incremental 資訊。但**單純把 RV 替換成 FFD(RV) 不會改善預測**。

研究誠實的價值就在這裡：**負結果（null result）和正結果一樣重要**。它幫助下一輪研究者把資源放在更可能有 ROI 的方向（高頻 RV、jump component、cross-asset spillover），而不是把時間花在「直觀上應該有用」但實際上並沒有的方法。

---

## 圖表


![K194 跨 5 資產：最佳模型與 QLIKE](experiments/k194/k194_best_models.png)

![SPY 跨模型 OOS QLIKE：GJR vs FFD 邊際差異](experiments/k194/k194_spy_models.png)

![FFD 權重衰減：不同 d 值的前 5 個 lag](experiments/k194/k194_ffd_weights.png)
