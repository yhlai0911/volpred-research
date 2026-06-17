---
title: 日頻 ETF 找不到 Russell / S&P 指數調整日波動衝擊：K1341 NULL result、4 個 bug 修正、與多重比較的代價
audience: research
category: research
phase: results
status: draft
tags: [K1341, event-study, index-reconstitution, null-result, methodology, multiple-testing, bonferroni]
experiment_id: K1341
experiment_refs: [K1341]
description: K1341 以 2014-2026 年 IWM/IWB/SPY/QQQ 日頻 OHLC 檢驗 Russell 年度重構（n=12）與 S&P 季度再平衡（n=49）是否產生日頻波動衝擊。Wilcoxon + block bootstrap 結果均不顯著，Bonferroni 校正後 IWB/QQQ 的邊際 p 值（0.018-0.030）也轉為不顯著。Codex v2 修正 4 個方法論 bug 後結果維持 NULL。本文討論樣本規模、closing-auction 機制、多重比較代價，以及事件研究設計的教訓。
proposer: VolPred 研究團隊
---

## TL;DR

K1341 檢驗 Russell 年度重構日（每年 6 月最後週五，n=12）與 S&P 500 季度再平衡日（3/6/9/12 月第三週五，n=49）是否在 IWM、IWB、SPY、QQQ 的日頻資料上留下可量測的波動衝擊，以及衝擊後是否在 t+1 出現均值回歸。資料期間 2014-01 至 2026-06，三種波動度量（close-to-close 平方、Parkinson H-L、close-to-open 平方），Wilcoxon signed-rank 加 block bootstrap 做推論。

結果：**假說不獲支持**。15 個 ticker × measure × event-set 組合全無統計顯著性，Bonferroni 校正後邊際顯著的 IWB/QQQ 也變成 non-significant。IWM 的 t+1 z-score 達 +2.20，顯示的是持續（persistence），不是均值回歸。S&P 季度再平衡對 SPY/QQQ 毫無訊號。Codex CLI 抓出 4 個方法論 bug 並在 v2 修正；修正後數字略有變動但整體結論不變。

---

## 動機與假說

Russell 年度重構是被動型基金最密集的集體行動節點之一。BMLL Technologies 2025 年 closing-auction 報告記錄，Russell 重構週五的收盤競價份額從一般日的約 9% 跳升至約 20%。這筆 closing-auction 訂單流的方向性極強，機械式的成分更換要求被動基金幾乎同步下單。

Madhavan & Ming（2003）在分鐘頻率資料上找到 reconstitution 衝擊的明確訊號。Chen、Noronha & Singal（2004）在 S&P 500 成分調整的文獻中也觀察到不對稱的價格反應。這些先行文獻提供了期望：若 closing-auction 流量足夠大，日內 H/L 範圍（Parkinson estimator 的基礎）應當拉大，而 close-to-close 報酬平方（r²\_cc）也該偏高。

K1341 的核心假說因此有兩層：

1. **Dislocation**：事件日的日頻波動度量顯著高於同月基準（Wilcoxon + block bootstrap 單尾 p < 0.05）
2. **Mean reversion**：若 dislocation 存在，t+1 的同一度量應回歸基準（z-score 接近 0 或負值）

若兩層都成立，這個「dislocate-then-revert」模式就是一個在已知日曆日上可預測的結構性異常，直接關係到 VolPred 平台的 calendar-event 波動率建模方向。

---

## 資料與方法

**資產 universe**：

- IWM（iShares Russell 2000 ETF）：年度 Russell 重構曝險最直接
- IWB（iShares Russell 1000 ETF）：同一年度重構週五，不同市值層
- SPY（SPDR S&P 500 ETF）：S&P 500 季度再平衡
- QQQ（Invesco Nasdaq-100 ETF）：對照組，有季度再平衡但 passive 足跡相對小

資料來源：yfinance 日頻 OHLCV，2014-01-01 至 2026-06-14。

**事件集**：

- Russell 重構日：每年 6 月最後週五，2014-2025，共 12 個事件
- S&P 季度再平衡日：每季第三週五（3/6/9/12 月），2014Q1-2026Q1，共 49 個事件

**三種波動度量**：

- `r²_cc = (ln(C_t / C_{t-1}))²`：close-to-close 報酬平方，最通用的日頻波動代理
- `Parkinson = 0.361 × (ln(H_t / L_t))²`：日內高低範圍估計器，直接捕捉 intraday dislocation
- `r²_co = (ln(C_t / O_t))²`：close-to-open 平方（隔夜跳空），輔助分析

**Baseline 定義**：以事件日所在 calendar month 的所有交易日為分母，扣除事件窗 `[t_e-5, t_e+5]` 後取均值。排除窗採用 **位置式交易日** index（不是日曆天 buffer），見下方方法論審查說明。

**統計推論**：

- Wilcoxon signed-rank test（單尾，H₁：event > baseline），計算各事件的成對差異
- Block bootstrap（block size=5，B=1000，seed=42），p-value = (count+1)/(B+1) 以避免零值
- t+1 均值回歸 check：以各事件的 per-event baseline std 計算 z-score

---

## 完整結果

**表一：Russell 重構日（n=12，2014-2025）**

| Ticker | Measure | event_mean | baseline_mean | ratio | Wilcoxon p (>) | Bootstrap p (>) | t+1 z |
|--------|---------|-----------|--------------|-------|---------------|----------------|-------|
| IWM | r²_cc | 2.85e-4 | 1.75e-4 | 1.63x | 0.810 | 0.185 | +2.20 |
| IWM | Parkinson | 8.71e-5 | 1.00e-4 | 0.87x | 0.788 | 0.538 | +1.28 |
| IWM | r²_co | 1.04e-4 | 9.83e-5 | 1.05x | 0.741 | 0.385 | +2.10 |
| IWB | r²_cc | 2.57e-4 | 9.09e-5 | 2.83x | 0.396 | **0.018** | +1.44 |
| IWB | Parkinson | 5.69e-5 | 4.50e-5 | 1.26x | 0.259 | **0.030** | +0.64 |
| IWB | r²_co | 8.30e-5 | 4.55e-5 | 1.83x | 0.575 | 0.184 | +0.69 |
| QQQ | r²_cc | 3.19e-4 | 1.30e-4 | 2.44x | 0.425 | **0.030** | +1.27 |
| QQQ | Parkinson | 8.52e-5 | 7.77e-5 | 1.10x | 0.545 | 0.227 | +0.75 |
| QQQ | r²_co | 1.07e-4 | 7.80e-5 | 1.37x | 0.689 | 0.254 | +1.27 |

粗體代表 raw bootstrap p < 0.05，但見「多重比較」段討論。

**表二：S&P 500 季度再平衡日（n=49，2014Q1-2026Q1）**

| Ticker | Measure | event_mean | baseline_mean | ratio | Wilcoxon p (>) | Bootstrap p (>) | t+1 z |
|--------|---------|-----------|--------------|-------|---------------|----------------|-------|
| SPY | r²_cc | 1.57e-4 | 1.42e-4 | 1.10x | 0.384 | 0.222 | +0.24 |
| SPY | Parkinson | 9.24e-5 | 7.15e-5 | 1.29x | 0.910 | 0.195 | +0.64 |
| SPY | r²_co | 1.25e-4 | 6.77e-5 | 1.84x | 0.857 | 0.241 | -0.10 |
| QQQ | r²_cc | 1.37e-4 | 2.02e-4 | 0.68x | 0.992 | 0.885 | -0.24 |
| QQQ | Parkinson | 1.35e-4 | 1.14e-4 | 1.19x | 0.866 | 0.217 | -0.27 |
| QQQ | r²_co | 1.86e-4 | 1.12e-4 | 1.66x | 0.805 | 0.162 | -0.30 |

S&P 季度再平衡組：ratio 有時偏高（SPY r²_co 1.84x），但 Wilcoxon p 最高達 0.910，bootstrap p 最低 0.162，全無統計顯著性。t+1 z-score 絕對值均小於 1，不支援也不反對均值回歸（訊號太弱無從推論）。

---

## 事件窗剖面圖

以下兩圖為 Parkinson 估計器在 [-5, +5] 交易日窗口內的逐日均值（event_day=0）與同月基準帶（mean ± 1 std）。

![Russell 重構日 Parkinson 事件窗剖面](experiments/K1341/figures/event_window_parkinson_russell.png)

![S&P 季度再平衡日 Parkinson 事件窗剖面](experiments/K1341/figures/event_window_parkinson_sp.png)

兩張圖的共同特徵：事件日附近的 Parkinson 均值在基準帶的範圍內浮動，沒有視覺上明顯的尖峰。Russell 組在 t=0 前後有些微抬升，但個別年份差異懸殊，跨事件標準差很大，進一步壓低了 Wilcoxon test power。

![Russell 重構日 close-to-close r² 事件窗剖面](experiments/K1341/figures/event_window_r2cc_russell.png)

r²\_cc 剖面（第三圖）顯示 IWB 與 QQQ 在 t=0 有較明顯的抬升，但跨年份波動同樣大。這與 bootstrap p ≈ 0.018-0.030 的邊際訊號一致——偶有幾個年份確實較高，但整體分佈並不穩定。

---

## 方法論審查：Codex v1 FAIL 到 v2 PASS 的 4 個修正

K1341.py 初版（v1）由 Codex CLI（gpt-5.4）審查後判 FAIL，原因是 4 個設計缺陷；v2 全數修正後重新判 PASS。以下記錄每個問題的性質與影響。

**Bug 1：baseline 排除窗用日曆天 buffer 而非位置式交易日**

v1 在計算同月基準時，以 `event_date ± 10 calendar days` 排除事件窗。問題是：若某個年份 6 月最後週五剛好在假期附近，日曆天 buffer 可能排除到前後的交易日，但另一些年份同等長度的交易日窗口卻大不相同。v2 改為從 dataframe index 取出位置 `[pos-5, pos+5]` 對應的實際交易日，排除這 11 個位置。

影響：baseline 估計值在個別年份略有改變，但因為是 within-month 操作，對大多數事件的影響有限。關鍵在於這個修正讓不同年份的排除行為真正一致。

**Bug 2：align\_event\_to\_index 無最大跳躍限制**

若事件日（例如某年 6 月最後週五）剛好是假日，v1 的 align 函數會 silent forward-snap 到下一個交易日，沒有任何 guard。最壞情況下，一個週五公假可能讓 t=0 跳到下週二，不知不覺製造 3 個交易日的 lookahead。v2 加上 `max_gap_days=3`，超過 3 個日曆天的跳躍直接丟棄，不進入統計。

影響：這個修正對 Russell 組（12 個事件）的影響最直接，特別是 2020 年 6 月 26 日確認為有效交易日（無假日衝突）。整個修正偏保守，寧可少幾個事件也不接受 lookahead 汙染。

**Bug 3：Bootstrap p-value 可能回傳 0**

v1 計算 bootstrap p-value 的方式是直接 `count / B`，若所有 bootstrap 樣本的差異統計量都小於觀察值，p 會嚴格等於 0。這在小樣本（n=12）加上小 B（=1000）的情境下會出現。p=0 是人造精確性，不是真實結果。v2 改用 `(count + 1) / (B + 1)` 的 continuity correction，最小 p-value 為 1/1001 ≈ 0.001，保留適當的不確定性。

影響：IWB r²\_cc 的 bootstrap p 在修正前後從邊際值微調，但方向不變。

**Bug 4：t+1 z-score 用跨事件的 baseline std，而非 per-event**

v1 計算 t+1 z-score 時，分母用的是「所有事件對應的 baseline mean 的 cross-event 標準差」。這個量捕捉的是 across-event variability，不是某個特定事件後的「相對於那個月度基準」的偏離程度。要判斷 t+1 是否回歸，應該問：「t+1 的波動相對於這個事件所在月份的 baseline，偏離了幾個 std？」v2 改為 per-event baseline std。

影響：IWM 的 t+1 z-score 在修正後仍為 +2.20，IWM r²\_co 為 +2.10，兩者均偏高——意思是 IWM 在 Russell 重構日後的 t+1，波動度仍相對基準偏高，是持續（persistence），不是均值回歸。

這 4 個 bug 在設計上都不算低級錯誤——calendar buffer 看起來合理、forward-snap 是常見 convenience、bootstrap p=0 容易被忽略、z-score 分母的選擇需要思考推論目的。Codex 審查程序在這個案例直接改變了可解釋性。

---

## 多重比較的代價：Bonferroni 後沒有顯著條目

本研究有 15 個統計測試：4 個 ticker × 3 個 vol measure，但因 IWM/IWB/QQQ 只看 Russell 組、SPY/QQQ 看 S&P 組，實際有效組合為 3（Russell 組）× 3（measure）= 9 + 2（S&P 組）× 3（measure）= 6，合計 15。

在 α = 0.05 的 nominal 水準下，Bonferroni 校正後 αᵢₙ𝒹ᵢᵥᵢ𝒹ᵤₐₗ = 0.05 / 15 ≈ 0.0033。

三個邊際 p 值的校正結果：

| 條目 | Raw bootstrap p | Bonferroni 校正後判定 |
|------|----------------|----------------------|
| IWB Russell r²_cc | 0.018 | 0.018 > 0.0033 → NS |
| IWB Russell Parkinson | 0.030 | 0.030 > 0.0033 → NS |
| QQQ Russell r²_cc | 0.030 | 0.030 > 0.0033 → NS |

校正後 15 個測試全部 non-significant。Bonferroni 是保守的族誤差率控制，在 n=12 加上明確 data-driven 假說的情境下略嫌保守。但即便換用 Benjamini-Hochberg FDR 方法（FDR 控制在 5%），三個 raw p 值的順位也不足以通過 BH 步進程序。

從 Type II error 的角度看：Russell 組 n=12，假設真實 effect size（Cohen's d）為 0.5，block bootstrap 在 B=1000 下的 power 對 n=12 相當有限。這是「可能有效應但 underpowered」還是「真的沒效應」，資料本身無法完全區分。

---

## 為何是 NULL？四個機制

**1. 日頻粒度太粗**

Madhavan & Ming（2003）的訊號出現在分鐘頻率資料。日頻 OHLC 的高低範圍（Parkinson estimator）是 intraday range 的某種投影，但它把整個交易時段壓縮成兩個數字。若 closing-auction 的衝擊發生在最後 30 分鐘，收盤前的 H/L 已經確定，日頻 Parkinson 只能捕捉全天的 range，稀釋了晚段的訊號。更直接的設法應是分鐘頻率收盤競價開始後的 realized variance。

**2. ETF 本身的 internal offset**

IWM 和 IWB 作為 ETF，其 create/redeem 機制讓大型 authorized participants 可以用 in-kind 方式處理流量，不必在 secondary market 留下痕跡。被動型基金之間有大量的 cross-netting——同樣一批股票，一個買進一個賣出，實際的 price impact 被大幅壓縮。這個機制在 ETF 文獻裡有充分討論，但 K1341 的研究設計無法分離「ETF 層面的 in-kind netting」與「underlying 的真實 dislocation」。

**3. Closing-auction 機制本身的穩定性**

BMLL（2025）記錄的 20% closing-auction 份額，意味著大量訂單在 4:00pm 一個時點釋放，但同時也意味著大量對手方訂單也在同一時點出現。closing-auction 的設計目標本就是要最小化 price impact——電子競價讓訂單集中撮合，反而比 intraday 連續競價更有效率。從 daily OHLC 的角度，4:00pm 的收盤價就是 closing-auction 的成交均價，不一定會讓 H/L 拉大。

**4. 樣本規模與統計功效的根本限制**

n=12（Russell）在事件研究的標準下是偏小的樣本。若真實 effect 存在，但每年有 2-3 個「乾淨」年份、2-3 個「沒效應」年份（例如市場大跌或疫情異常年份的稀釋），跨 12 個事件的 Wilcoxon 排名很容易被幾個離群值打亂。從表一的各事件數字可以看到，ratio 在 IWB r²_cc 達 2.83x，但 Wilcoxon p 是 0.396——代表至少有相當一部分事件的 event-day 比自己的 baseline 還低，拉低了 signed-rank 統計量。個別年份的異質性是解讀「ratio 高但 p 高」的關鍵。

---

## Implications

**對波動率預測的啟示**

K1341 的 NULL finding 給 calendar-event vol forecasting 提供了一個有用的負面結果：**日頻 ETF 層面的 index rebalance 效應，不是一個可靠的預測訊號**。如果量化策略要在已知的 event calendar 上做波動率交易，所需的訊號很可能需要來自分鐘頻率的 closing-auction 資料，而不是日頻 OHLC。

**對事件研究設計的啟示**

Codex v1 抓出的 4 個 bug 都屬於設計假設的靜默偏移：calendar-day buffer 看似合理、forward-snap 看似合理、p=0 看似精確。這類 bug 的共同特點是：在大樣本下影響很小，但在 n=12 的小樣本裡可能改變 p-value 的大小方向。事件研究在小 n 情境下對 implementation detail 反而更敏感。

**對 multiple-testing disclosure 的啟示**

研究者報告 raw p < 0.05 而不提及 test family size，是量化金融文獻的常見問題。K1341 的 15 個測試在 Bonferroni 後全部歸零，提醒任何「某個子集顯著」的 event study 結果，都需要明確說明測試了幾個子集、是否校正族誤差率。

---

## Caveat 與後續方向

**樣本限制**：Russell 組 n=12 的功效問題根本性地限制了本研究的推論能力。要在日頻層面獲得充足 power，需要擴展到個別股票（Russell 成分股）或更長的歷史（2000 年以前的 Russell，但資料品質差異大）。

**頻率限制**：分鐘頻率或 tick 資料（Bloomberg、BMLL、CRSP TAQ）才能直接看到 closing-auction 前後的 volatility profile。K1341 的日頻結論是「日頻看不到」，不是「效應不存在」。

**mid/small cap 差異**：IWM 和 IWB 都是大 ETF，被動基金持有高度集中。若改看 Russell 2000 中較小的 ETF 或個別小市值股票，in-kind netting 效率降低，dislocation 可能更明顯。

**事件定義的精細化**：本研究用「Russell 重構週五」作為單一 event，但實際上 Russell 的 preliminary / final 名單各有公告日，市場可能在名單公告後就開始前置定位，週五收盤才是結算日而非衝擊日。細化事件時序（名單公告 T-10 至 T-0）是更貼近機制的研究設計。

---

**實驗資訊**：K1341，run\_date 2026-06-15，seed=42，yfinance source，Codex CLI v2 PASS（final reviewer: Codex CLI primary path）

<!-- anti-ai-style: pass -->
