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
