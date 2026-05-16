# K547b: Daily VT shift(1) Re-run — VIX Timing Correction

- **Experiment ID**: `K547b`
- **Status**: running
- **Created At**: 2026-05-17
- **Depends On**: K547

## 問題描述

K547 Codex review (FAIL→CONDITIONAL) 指出：`run_strategy` 函式用當日 VIX 計算當日權重（`weight[t] = 12 / VIX[t]`），但更保守（也更嚴格的研究慣例）是用昨日 VIX 決定今日權重（`weight[t] = 12 / VIX[t-1]`）。

## 動機

- 研究誠實原則：若 shift(1) 導致 Daily VT Sharpe 大幅下降，原文 1.666 數字需要修訂。
- K547 文章（mile_53983530）在「Lookahead lag 二次驗證（待後續校驗）」小節已預告此驗證。
- Codex FAIL 原因之一即此 timing 問題（verdict: FAIL → CONDITIONAL，K547b pending）。

## 方法

- 資料：SPY + ^VIX，2005-01-04 至 2026-03-26（yfinance，與 K547 相同期間）
- 修正：`vix_lagged = vix_aligned.shift(1)`，再代入所有 `run_strategy` 策略計算
- 比較：full sample metrics + 5 子期間 OOS + block bootstrap（block=20, B=10,000）
- 種子：`numpy.random.seed(42)`

## Lookahead 政策

- `weight[t] = 12 / VIX[t-1]`（前一日 VIX 決定今日倉位）= 正確 shift(1)
- `port_ret[t] = weight[t] * spy_ret[t]`（今日報酬）
- 第一個交易日 weight = NaN → 強制設 0（跳過）

## 成功標準

1. 程式碼通過 Codex review（CONDITIONAL PASS 以上）
2. 結果 JSON 含所有策略 Sharpe + CAGR + MDD（shift(1) 版本）
3. 與 K547 原版比較表格
4. 若 Daily VT Sharpe 變化 >5%（相對），需更新文章 mile_53983530

## 結論

（待補充）
