---
title: "K1426: Partial Cointegration Hedging IS PoC — 三對 ETF 全 NULL，ρ 為負的警示"
audience: research
tags: ["對沖", "partial cointegration", "Kalman filter", "ETF", "實證研究", "避險效益"]
experiment_refs: ["k1426"]
description: "Clegg-Krauss (2018) partial cointegration hedging 在 SPY/IVV、USO/BNO、GLD/IAU 三對 ETF 的 IS-only PoC 全數 NULL。ρ 負值代表 AR(1) 振盪而非均值回歸；USO/BNO 表面上 HE_PCH > HE_OLS 是 β 尺度 artifact，不是真贏。"
---

## 摘要

本實驗（K1426）以 Clegg & Krauss（2018, *Quantitative Finance*）提出的 partial cointegration hedging（PCH）為方法，對三對 ETF（SPY/IVV、USO/BNO、GLD/IAU）進行 2015–2024 日線 IS-only PoC。Kalman filter + scipy MLE（20-multistart，seed=42）估出 state-space 參數後，與 OLS static hedge 和 EG-VECM 比較避險效益（HE）。

結果全部落在 honesty gate 內，overall verdict: NULL（3/3 pairs）。SPY/IVV 與 USO/BNO 的 AR(1) 均值回歸係數 ρ 皆為負值（分別 -0.198、-0.401），代表 AR(1) 在振盪而不是均值回歸。GLD/IAU 的 half-life 僅 0.24 天，mean-reverting 成分與 i.i.d. 雜訊無從區分。USO/BNO 看似 HE_PCH = 0.887 大幅勝過 HE_OLS = 0.590，但此差異是 β 尺度的 artifact，不是 partial cointegration 帶來的實質改善。

OOS rolling-window + 100-multistart + bootstrap CI 已進 compute queue。

---

## 研究背景

Clegg & Krauss（2018）的 partial cointegration 把兩資產的 log price spread 分解為兩個獨立成分：AR(1) 均值回歸成分 M_t，加上純隨機漫步成分 R_t。經典 cointegration 假設整個 spread 都是均值回歸的，PCH 放寬這個假設，承認 spread 可以同時帶有均值回歸與永久偏離的成分。

這個分解對避險的意涵：OLS 對 spread 整體最小化變異，而 PCH 的 Kalman filter 狀態估計理論上能「只用 M_t 部分」來做動態 hedge ratio，對 R_t（永久偏離）部分的暴露不試圖 hedge 掉，因為試圖 hedge 隨機漫步反而增加 tracking error。Poulos, Curphey & Williams（2024, *RQFA*）把這個框架延伸至跨截面資產定價，並指出許多 pair 在實際資料中 R²_MR（mean-reverting variance share）接近 0，模型退化成純 random walk。

本實驗的問題：對流動性高、追蹤關係明確的 ETF pairs，PCH 的 M_t + R_t 分解是否能找到有意義的均值回歸結構？

---

## 方法與數據

| 項目 | 設定 |
|------|------|
| 資料來源 | yfinance daily adjusted close |
| 期間 | 2015-01-01 — 2024-12-31 |
| 樣本 | 2,515 個交易日（三對相同）|
| 標的 | SPY/IVV（S&P 500 重複 ETF）、USO/BNO（WTI/Brent 原油 ETF）、GLD/IAU（黃金重複 ETF）|
| PCH 估計 | Kalman filter + scipy L-BFGS-B MLE；rho 用 tanh() reparameterization；sigma 用 log() reparameterization |
| Multistart | 20 次（seed=42）；full 100-start 留 compute_queue |
| Baselines | OLS static hedge；EG-VECM（Stage-1 OLS + Stage-2 speed-of-adjustment） |
| 統計口徑 | IS-only；三 estimator 對稱 IS 口徑，無 lookahead 不對等 |

**Honesty gate**（任一觸發即報 NULL）：
1. ρ ≥ 0.999 → PCH 退化為純 random walk
2. R²_MR < 0.05 → M 成分佔比過低
3. ρ ≤ 0 → AR(1) 振盪而非均值回歸
4. half-life < 1 day → 均值回歸速度與 i.i.d. 雜訊無法分辨

---

## 核心發現

### 三對 ETF 結果彙總

| Pair | β_OLS | β_PCH | ρ | R²_MR | half-life | HE_OLS | HE_PCH | Verdict |
|------|-------|-------|---|-------|-----------|--------|--------|---------|
| SPY/IVV | 0.998 | 0.996 | -0.198 | 0.813 | — | 0.998 | 0.998 | NULL_RHO_NEGATIVE |
| USO/BNO | 0.424 | 1.008 | -0.401 | 0.070 | — | 0.590 | 0.887 | NULL_RHO_NEGATIVE |
| GLD/IAU | 0.982 | 0.998 | 0.053 | 0.990 | 0.24d | 0.994 | 0.994 | NULL_HALFLIFE_TRIVIAL |

### Pair 1 — SPY/IVV：重複 ETF 收斂正確，ρ 為負

![SPY/IVV 三 estimator Spread 比較](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/fig_pair_1_SPY_IVV_spread.png)

SPY 與 IVV 追蹤相同的 S&P 500 指數，是 sanity check 對。OLS β = 0.998，HE = 0.998，與經濟直覺吻合。PCH MLE 收斂（20/20 starts 全部收斂），估出 β_PCH = 0.996、R²_MR = 0.813，即 Kalman filter 判定 81% 的 spread 變異屬於均值回歸成分 M_t。

但 ρ = -0.198。Clegg-Krauss 模型要求 ρ ∈ (0, 1) 才算均值回歸；ρ 為負代表 AR(1) 每一期在正負方向振盪（overshooting），不是收斂。PCH 加上 Kalman 動態 beta 之後，HE = 0.998，與 OLS 幾乎相同。這兩個 ETF 的 spread 本來就幾乎為零，OLS 已達幾乎完美的避險，PCH 沒有加分空間。

### Pair 2 — USO/BNO：HE 看似改善，實為 β 尺度 artifact

![USO/BNO Kalman 狀態分解](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/fig_pair_2_USO_BNO_decomp.png)

這對是三對中最有鑑別力的案例。USO 追蹤 WTI 原油期貨，BNO 追蹤 Brent 原油期貨，兩者有長期 WTI-Brent 價差，理論上是 PCH 最有意義的應用場景。

乍看 HE 數字：HE_OLS = 0.590，HE_PCH = 0.887。差距 0.297，看起來 PCH 大幅勝出。

但這個比較犯了一個根本性的錯誤：**兩個 spread 不在同一尺度上**。

- OLS 選 β_OLS = 0.424，以最小化 spread 變異為目標，這是標準 minimum-variance hedge ratio
- PCH 選 β_PCH = 1.008，把 USO 與 BNO 強制視為幾乎 1:1 的同商品關係

β 從 0.424 跳到 1.008，代表 PCH 用的 spread（log_USO − 1.008 × log_BNO）與 OLS 用的 spread（log_USO − 0.424 × log_BNO）是完全不同的序列。在不同的「hedge reference point」下比較 HE 數值，在數學上沒有意義。

真正的判定依據是 ρ = -0.401。AR(1) 振盪、不是均值回歸，PCH 的核心前提不成立。上圖（Kalman 狀態分解）可看到估出的 M_t 序列在正負之間快速切換，沒有持續均值回歸的特徵。

### Pair 3 — GLD/IAU：R²_MR 很高，但半衰期只有 0.24 天

GLD 與 IAU 同樣追蹤黃金，是第二組 sanity check。PCH 估出 R²_MR = 0.990，表面上 99% 的 spread 變異都屬於均值回歸成分。數字看起來很好，但 ρ = 0.053，對應的理論半衰期只有 0.24 天。

半衰期不到一個交易日，代表 M_t 成分幾乎瞬間回到均值，與 i.i.d. 白噪音在統計上難以區分。Kalman filter 在此把幾乎可忽略的自相關捕捉為 M_t 成分，結果 PCH 的「均值回歸」速度比一個交易日還快，不具備任何避險操作的實用性。HE_PCH = 0.994 vs HE_OLS = 0.994，兩者相等。

---

## Interpretation

NULL 結果不代表 PCH 方法錯誤。Poulos et al.（2024）本身就發現，在實際資料中「many pairs degenerate to R²_MR ≈ 0」。他們的文獻是對 cross-sectional asset pricing 的應用，並非宣稱對所有 pair 都能找到均值回歸結構。

這次實驗的三對選法有明顯限制：

**重複 ETF（SPY/IVV、GLD/IAU）**：追蹤同一底層標的的 ETF，spread 本來就接近零，任何 state-space 估計都在一個幾乎沒有訊號的序列上找結構。即使 MLE 收斂，估出的 ρ 與 R²_MR 更多是 numerical artifact，而非經濟意義上的均值回歸。

**USO/BNO 的 2015–2024 窗口**：這段期間含 2020 年 4 月 WTI 期貨負油價事件，以及 2022 年俄烏衝突導致的 Brent-WTI 價差劇烈擴大。隨機漫步成分在這段資料中可能確實佔主導，PCH 估不出持續性均值回歸是合理的實證結果。

下一步 OOS rolling-window 才能真正測試 PCH 能否在 expanding window 估計下找到任何 pair 在 OOS 期間有 HE_PCH > HE_OLS（bootstrap 95% CI 排除 0）。

---

## 實務意義

對量化避險研究而言，K1426 的貢獻主要是方法論層面：

1. **ρ 正值是 PCH 有效性的必要條件**，不是充分條件。R²_MR 高不代表 PCH 有用，ρ 為負就直接否定。
2. **HE 跨模型比較必須確認 spread 在同一尺度**。不同 β 選擇下的 spread 是不同序列，HE 無法直接比較。
3. **重複 ETF 適合作 sanity check，不適合作 PCH 的鑑別 pair**。真正有意義的測試需要有經濟基本面支撐的 spread（如跨市場同商品 ETF、供應鏈上下游關係的股票 pair 等）。

OOS follow-up（compute queue 任務 `compute-k1426-oos-partial-cointegration-hedging-1780934756`，等 :15/:30 worker 執行）若仍 NULL，後續方向包括換 pair 組合（GLD/SLV、XLE/USO、跨幣種 commodity ETF），或轉向 multivariate PCH 框架。

---

## 限制

1. **IS-only**：in-sample HE 是 upper bound，OOS 結果可能更低。
2. **20-multistart（Pair 2/3）**：full 100-start 已進 compute queue；理論上多 start 可能找到不同 loglik basin，但 ρ 為負的結論預期不變。
3. **未做 Codex code review**：worktree agent 環境限制，主線程 verify 後再寫 knowledge.json（K1259 process gate）。
4. **2020 油價異常事件**：USO/BNO 的結果包含 WTI 負油價時期，若剔除這段，PCH 的 ρ 可能轉正。但刪除極端事件本身有 data snooping 風險，不在本 PoC 範圍內。

---

## 結論

K1426 IS PoC 結果：PCH 在 SPY/IVV、USO/BNO、GLD/IAU 三對 ETF 的 2015–2024 日線資料上全數 NULL。AR(1) 均值回歸係數 ρ 在兩對為負（振盪），第三對的半衰期不到一天（近似 i.i.d.）。USO/BNO 表面上的 HE 改善是 β 尺度 artifact，在 ρ 為負的前提下不具任何 partial cointegration 的詮釋。

OOS rolling-window + bootstrap CI 正在 compute queue 執行，結果出來後若仍 NULL 會產出 follow-up 分析。若 OOS 在特定 pair 或特定子期間找到 HE_PCH > HE_OLS（bootstrap CI 排除 0），才值得進一步探索動態 beta 應用的實務方向。

---

*資料來源：yfinance daily adjusted close，2015-01-01 — 2024-12-31；實驗 K1426（腳本：`experiments/k1426/k1426.py`，結果：`experiments/k1426/k1426_results.json`）。文獻：Clegg & Krauss (2018) QF 18(1), 121–138；Poulos, Curphey & Williams (2024) RQFA 62(3), 1031–1061；Lien (2004) QREF 44(5), 654–658。*

*[提出: Claude, 執行: Claude]*
