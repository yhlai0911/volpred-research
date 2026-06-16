# K824 — Quantile Forecasting: 分位數方法對 VaR 合規性的影響

- Experiment ID: `k824`
- Status: completed (CONDITIONAL_PASS, Codex-reviewed 2026-06-17)
- Created At: 2026-04-16T09:41:14.235898+00:00
- Article: `mile_328ced24` 「風險模型不是愈高級愈安全：最土的方法反而最少踩線」

## 問題描述

在 GJR-GARCH(1,1) 點預測之上，四種尾端分位數方法（Normal / Student-t / Quantile Regression / Historical Simulation）對 SPY 1% VaR 合規性的影響為何？

## 動機

過往 GARCH 文獻多以 Student-t 為標準分配假設；但 Basel III 真正在乎的是 VaR violation 計次，而非 pinball loss 等 continuous 指標。本實驗測試「同一波動率引擎、不同尾端轉換」對監管合規的實證差異。

## 方法

- 資產：SPY
- 樣本：訓練 2006-01-01 → 2022-12-31，OOS 2023-01-01 → 2024-12-31（n=502）
- 點預測：GJR-GARCH(1,1)，refit_every=63 交易日
- 尾端：M1 Normal / M2 Student-t (df MLE) / M3 Quantile Regression / M4 Historical Simulation
- 評估：Kupiec、Christoffersen、avg Pinball Loss、Diebold-Mariano (Harvey-corrected)

## 結果摘要

| 方法 | 1% VaR 違反次數 | 違反率 | Kupiec p | Trinity PASS |
|---|---:|---:|---:|:---:|
| Normal | 10 | 1.99% | 0.049 | FAIL |
| Student-t | 8 | 1.59% | 0.219 | FAIL |
| QuantReg | 4 | 0.80% | 0.635 | **PASS** |
| HistSim | 4 | 0.80% | 0.635 | **PASS** |

avg Pinball Loss 四方法差距僅 0.00000359；DM 兩兩比較全 not significant (Harvey-corrected)。

## 結論

- HistSim 與 QuantReg 在 1% VaR 點估計**並列贏家**（皆 4/502 violations），但 DM test 顯示兩者統計上無法區分。
- Normal 系統性低估尾部風險（Kupiec p<0.05 拒絕）。
- Student-t 改善方向正確但仍 Trinity FAIL。
- 「平均 pinball loss 幾乎相同、尾端違反次數天差地遠」是核心 takeaway。

## Codex Review (2026-06-17, CONDITIONAL_PASS)

- Look-ahead：PASS（OOS loop `r_train = r_values[:train_end]`；HistSim 經驗分位數只用 t-1 以前殘差）
- 數字一致性：PASS
- Seed：CONDITIONAL（GJR multistart 有 seed；yfinance 資料無 snapshot）
- Caveats：
  1. HistSim 每日 update vs 其他方法 63-day refit 不完全公平 — 已於文章揭露
  2. Student-t df 估計使用未標準化 `t.logpdf`，forecast 時又縮放成 unit variance — 口徑潛在不一致，可能低估 Student-t 表現
  3. Basel traffic light 是 alpha*1.5 / alpha*2.0 自訂 heuristic，不是官方 250-day 計次門檻

## Followup

- 後續可做：所有方法統一 daily / weekly refit，跨市場（0050.TW、EM）驗證 HistSim 的尾部 dominance
- Student-t df MLE 改用 standardized t density 重估，看 Student-t 表現是否拉近
