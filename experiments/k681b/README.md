# K681b: Lookahead Fix — US/EFA VIX Percentile Strategy

- Experiment ID: `k681b`
- Status: pending
- Parent: K681
- Created: 2026-05-18
- Trigger: K681 code review found 1-day lookahead in US/EFA weights

## 問題描述

K681 中 US/EFA 策略使用當日 VIX 作為信號（`w_pct_us = 1 - pct[i]`，`pct[i]` 含 `vix[i]`），但回測乘以同日報酬 `return[i]`。交易必須在 VIX 收盤前完成，無法知道當日收盤 VIX。文章宣稱「前一日 VIX」但代碼未 shift。

## 修正

- `w_pct_us_fixed = (1 - pct).shift(1)` — 改用昨日百分位
- `w_12vix_us_fixed = min(12/VIX, 1).shift(1)` — 改用昨日 VIX

## 範圍

只跑 US (50/50 SPY/GLD) 和 EFA。台灣已正確使用 `vix_lag1`，不需要修正。

## 成功標準

| 情境 | 行動 |
|------|------|
| EFA Fixed Sharpe ≥ 1.2 | 原宣稱成立，文章加 errata 說明時間對齊細節 |
| EFA Fixed Sharpe 0.8–1.2 | 文章數字需向下修正 |
| EFA Fixed Sharpe < 0.8 | 文章需 major correction；EFA 部分宣稱撤回 |

## 結果（2026-05-18，compute_queue 完成）

**狀態：EFA Fixed Sharpe < 0.8 → MAJOR CORRECTION REQUIRED**

| 市場 | 指標 | 原始（含前瞻偏差）| 修正後（.shift(1)）| Sharpe 降幅 |
|------|------|------|------|------|
| US (50/50 SPY/GLD) | Pct Sharpe | 1.712 | **0.341** | -1.371 |
| US | 12/VIX Sharpe | 1.117 | **0.483** | -0.634 |
| US | DM Harvey Pass | ✓ (t=3.109) | ✗ (t=-1.070) | — |
| EFA | Pct Sharpe | 1.871 | **-0.054** | -1.925 |
| EFA | 12/VIX Sharpe | 0.851 | **0.019** | -0.832 |
| EFA | DM Harvey Pass | ✓ (t=5.368) | ✗ (t=-0.062) | — |

## 結論

- US Pct 修正後 Sharpe 0.341 < 0.8 → 顯著性宣稱撤回
- EFA Pct 修正後 Sharpe -0.054 < 0.8 → 「最能讓人放心的結果」宣稱撤回
- 兩市場 DM 檢定均未通過 Harvey 門檻
- 台灣結果不受影響（本即使用 `vix_lag1`）
- **文章 mile_073884fd 已加更正通知，美國/EFA 「達顯著水準」欄位已更新**

## 行動記錄

| 時間 | 行動 |
|------|------|
| 2026-05-18 02:18 UTC | K681 code review 發現 US/EFA lookahead |
| 2026-05-18 02:20 UTC | K681b 排入 compute_queue |
| 2026-05-18 02:30 UTC | compute_worker 完成計算 |
| 2026-05-18 10:07 UTC | 主線程讀取結果，更正文章 feed.json，寫 knowledge.json |
