---
title: "K1306：SEC 10-K 管理階層語氣能預測個股月度 RV 嗎？Loughran-McDonald pilot — NULL"
audience: research
status: draft
experiment_refs:
  - K1306
tags:
  - research
  - audience-research
  - Loughran-McDonald
  - SEC-EDGAR
  - NLP
  - realized-volatility
  - VIX
  - pilot-study
---

# K1306：SEC 10-K 管理階層語氣能預測個股月度 RV 嗎？Loughran-McDonald pilot — NULL

[提出: Claude（autonomous backlog gap-scan），執行: Claude]

## 摘要

本文報告 K1306 pilot 實驗：以 AAPL、GOOGL、MSFT、NVDA 四家公司 2020–2024 年 10-K 年報為樣本（N=16 filing-level obs），用 Loughran-McDonald（2011）金融情緒詞典萃取負面語氣年變化量（`tone_delta_neg`），檢驗其在 VIX 控制後是否對次年 12 個月個股月度已實現波動率（RV）具增量預測力。結論為 **NULL**：四家公司均因樣本過小（N≤4 per firm）無法跑出有效 per-firm HC1 t 統計量；pooled bootstrap（500 次）的 β_tone 均值=0.211，95% CI 為 [−3.79, +2.63]，大幅跨零；`frac_positive`=0.856 顯示方向偏正，但無統計顯著性可言。此結果符合 VIX 充分性假說的延伸——個股層級年報語氣在 pilot 規模下未提供超過市場隱含波動率的增量資訊。

---

## 研究背景

### 為什麼要測 SEC 10-K 情緒

`research_program.md` 長期把 SEC 財報文字列為「BLOCKED — 待數據取得」。這個分類是一個誤判：SEC EDGAR 完全公開免費，rate limit 是每秒 10 req，不是付費門檻。真正的阻力是 HTML 解析與文字切段，但對 pilot 規模完全可克服。

更重要的動機來自文獻缺口：

- **Tetlock（2007, JF）** 以 WSJ 媒體悲觀指數預測市場 RV，支持文字情緒的可預測性。
- **Loughran & McDonald（2011, JF）** 證明金融語境中的負面詞彙判斷與通用詞典不同，並釋出公領域詞典。
- 本研究前已有多個 K 驗證 VIX 充分性（K473 Google Trends NULL、K1116 EPU NULL），但均為**總體層級**。

**K1306 的差異化**：管理階層在 10-K 中對自家公司風險的描述，是否比市場聚合指標（VIX）帶有更精準的個股前瞻資訊？這是上述 NULL 系列未觸及的 firm-specific 角度。

### 研究假說

**H_K1306**：對至少 3 家受試公司，以下回歸中 β_tone 的 |t| > 2，且 OOS QLIKE 改善 > 5%：

$$RV_{t,i} = \alpha + \beta_{VIX} \cdot VIX\_lag + \beta_{tone} \cdot \Delta neg\_tone\_lag + \varepsilon$$

PASS 條件：≥3 家公司同時達標，即可升級為「feasible direction」並啟動 K1307 全 S&P 500 panel。
NULL 條件：≤2 家（或全部因 N 不足跳過），記錄 VIX 充分性延伸至 firm-level text。

---

## 方法與數據

| 項目 | 設定 |
|------|------|
| 樣本公司 | AAPL、GOOGL、MSFT、NVDA（原計畫 30 × 10，pilot 縮為 4 × 5） |
| 資料期間 | 10-K filing years 2020–2024 |
| N（filing-level obs） | 16（每家最多 5 筆；GOOGL 2020–2022 因 Alphabet CIK reorg 缺失） |
| 文字特徵 | Loughran-McDonald 2011 master dictionary — MD&A + risk_factors 段落負面詞比例（`frac_negative`） |
| 核心信號 | `tone_delta_neg`：當年 vs 前一年 `frac_negative` 變化量（需前一年 filing 才可計算，故 pilot 首年 NaN） |
| 預測目標 | 10-K 提交日後第 1–12 個完整月度 RV（月末收益率平方和，以日頻 yfinance 計算） |
| Baseline | VIX-only OLS：$RV \sim VIX\_lag$ |
| Challenger | $RV \sim VIX\_lag + tone\_delta\_neg\_lag$ |
| 統計檢定 | Per-firm HC1 heteroscedasticity-robust t-stat；pooled bootstrap CI（N_boot=500，seed=42）；Stouffer's Z（樣本太小，未能計算） |
| Lookahead | 提交日 + 1 個交易日 embargo；VIX lag 使用 embargo 日前 21 交易日均值（.shift(1) 類比） |
| Random seed | 42 |
| Codex review | 三輪達 PASS（gpt-5.4，session 019e2ac0，2026-05-15） |

### 關鍵設計決策

**forward window** 的月份邊界修正（K1306v2 Bug 1）：原版用 `> embargo` 為下界，可能納入 embargo 當月的殘尾交易日（部分月份）。修正後改為先計算 `embargo_month_end = embargo + MonthEnd(0)`，再取 `> embargo_month_end` 且 `≤ embargo_month_end + MonthEnd(12)` 的月末日期，確保完整月度不受 embargo 切割污染。

**小樣本 HC1 保護**（K1306v2 Bug 2）：三參數模型（const + VIX + tone）需要 df_resid ≥ 2，即 N ≥ 5。原版 guard 為 N < 3，允許 N=3、N=4 進入 HC1 計算，統計量無效。修正後提高為 N < 5 skip。這個修正直接導致 AAPL（N=4）和 MSFT（N=4）被跳過，是 pilot 最終無法產出 per-firm 結果的直接原因。

---

## 核心發現

### Per-firm OLS：全部跳過

| Ticker | N obs | 結果 |
|--------|-------|------|
| AAPL | 4 | 跳過（N<5，df 不足 HC1） |
| GOOGL | 1 | 跳過（N<5；2020–2022 filing 缺失） |
| MSFT | 4 | 跳過（N<5；2023/2024 risk_factors 萃取失敗） |
| NVDA | 3 | 跳過（N<5，包含 NaN tone_delta） |

**0/4 firms** 能進入有效 per-firm HC1 OLS。PASS 條件（≥3 firms \|t\| > 2）不可能達到。

### Pooled Bootstrap（N=16 filing obs，500 次重複抽樣）

| 統計量 | 數值 |
|--------|------|
| β_tone（bootstrap mean） | +0.211 |
| 95% CI 下界 | −3.786 |
| 95% CI 上界 | +2.632 |
| frac_positive（β > 0 的比例） | 0.856 |
| 方向性 | 正向偏多，但 CI 大幅跨零 |

β_tone 的 bootstrap CI 跨越 0 且範圍極寬（±約 3.2），即使方向 86% 指向正值（語氣轉悲觀 → RV 上升，符合直覺），也無法排除 β_tone = 0 的虛無假說。

### Stouffer's Z（跨公司組合 p 值）

樣本量不足（0 家公司完成有效 per-firm 回歸），無法計算。

### Panel 統計描述

| 變數 | N | 均值 | 標準差 | 範圍 |
|------|---|------|--------|------|
| VIX_mean_lag | 16 | 20.96 | 6.01 | [13.4, 30.3] |
| tone_delta_neg | 12 | −0.00091 | 0.00524 | [−0.0163, +0.0046] |
| rv_fwd_12m | 16 | 0.01068 | 0.00834 | [0.0033, 0.0308] |

`tone_delta_neg` 的標準差（≈0.005）相對於預測目標（RV 均值≈0.0107）和 VIX（均值≈21）都極小，這在技術上不排除效果存在，但訊噪比很低。

---

## 實務意義

以目前 pilot 結果，**不宜** 在個股波動率預測模型中納入年報情緒作為常規特徵。這個建議的根據：

1. **VIX 已吸收大部分系統性波動**：對科技大型股而言，beta 高度暴露於市場因子，個別公司的語氣變化很難在 VIX 控制後留下殘差。
2. **年度頻率問題**：10-K 每年更新一次，預測 12 個月 RV 本質上是低頻問題，信號更新速度遠低於高頻波動率預測的需求。
3. **文字信息到市場反應的路徑問題**：市場可能在 10-K 提交前即從財報電話會議（Earnings Call）消化類似信息，年報語氣的增量性已被提前 price-in。

若信號方向（frac_positive=0.856）能在更大樣本下持續，潛在的有效路徑包括：8-K 事件披露（更高頻）、MD&A 特定段落細顆粒分析（替代整體 risk_factors）、或結合盈餘意外（SUE）的交互效應。

---

## 限制與穩健性

**樣本層面**：
- N=16 filing obs 是任何嚴格推斷的底線。即便 bootstrap 跑 500 次，底層資料只有 16 個點；bootstrap CI 的寬度反映的是這 16 個點的高方差，不是模型估計不確定性的收斂值。
- 原計畫 30 家 × 10 年 = 300 觀測值未能實現：EDGAR API 在 pilot window 下 META filings 因 CIK 切換缺失，GOOGL 2020–2022 因 Alphabet CIK reorganization 缺失。

**文字萃取層面**：
- MSFT 2023/2024 risk_factors 段落萃取回傳 < 50 字（heuristic miss），實際納入的是 MD&A 而非 risk_factors。這個段落切換是否影響語氣計算未獨立驗證。
- 本實驗使用 heuristic keyword matching 切段；更可靠的方式是使用 SEC XBRL structured filing tags，能直接取得標準化段落。

**統計層面**：
- 12 個月 forward RV window 的相鄰 filing 窗口重疊（例如 2021 annual 和 2022 annual 的預測窗口共享大部分月份），殘差存在自相關，未做 Driscoll-Kraay 或 Newey-West 時間序列校正。
- Per-firm N≤4 的情況，即使未來小幅放寬守衛，t 統計量仍接近 z 分佈假設的極限，推斷效力有限。

**Lookahead 驗證**：
- 信號 lag 設計（embargo = filing_date + 1 BD；VIX lag 使用 embargo 前 21 交易日）已通過 Codex 三輪審查確認無 lookahead。
- VIX 的 `.shift(1)` 等效語意在 pooled OLS 中透過 `vix_mean_window < embargo_date` 達成，與 per-firm 一致。

---

## 未來研究方向

**K1307（如果資源允許）**：擴大到全 S&P 500 公司 × 10 年（目標 ≈ 4,000 obs），加入個股固定效應（FE）和 Driscoll-Kraay standard errors，能提供更可靠的推斷。這是本方向的下一個自然步驟。

**替代信號設計**：
- 改用 8-K 事件披露（有突發事件觸發，頻率更高，市場反應窗口更窄）
- 改用盈餘電話會議（Earnings Call）逐字稿（更接近實際決策者語氣）
- 細化 MD&A 段落（前景展望 vs 風險因子分開計算語氣）

**機器學習增強**：LM 詞典基於詞頻計數，無法捕捉語境（例如「我們的風險管理非常穩健」vs「我們面臨重大風險」中，同樣的 negative 詞後接不同修飾詞）。近年 FinBERT 等模型能做 contextual sentiment，對語氣細顆粒分類更準確，但需要更多計算資源和更多 labeled data 作對比驗證。

---

## 結論

K1306 pilot 在 N=16 的規模下未能提供 SEC 10-K 管理階層語氣預測個股月度 RV 的統計證據（pooled bootstrap 95% CI [−3.79, +2.63]，pass_firms=0/4）。

這個結論有兩層意涵：第一，**不等於「文字情緒對波動率無用」**，它只說明在此 pilot 規模和設計下無法排除零效應。第二，它指向方向問題：VIX 充分性假說在個股層面可能同樣成立，年報語氣的增量信息可能在提交日前已被高頻渠道（電話會議、媒體報導）消化。

在未能用更大樣本排除這些替代假說之前，本研究建議：沿用 VIX 作為個股短期波動率的基準特徵；若需要公司特定信號，優先考慮更高頻的文字資料（8-K、Earnings Call transcript），而非低頻的 annual filing。

*本文基於實驗 K1306v2（腳本：experiments/k1306/k1306.py，結果：experiments/k1306/k1306_results.json）。數據來源：SEC EDGAR public API + Loughran-McDonald 2011 master dictionary（public domain，Notre Dame SRAF）+ yfinance 日頻股價，期間：2020–2024，N=16 filing-level observations。*
