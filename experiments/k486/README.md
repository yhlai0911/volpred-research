# K486：GJR-GARCH-X(VIX) 跨 OOS 與 VaR Trinity

## Data & Methodology

- 類型：empirical forecast comparison
- 資料：yfinance `SPY`、`^VIX`；模型評估期固定為 2015–2024 的五個兩年 OOS
- Estimation window：每期 rolling 2,000 日，21 日重估一次
- Target / loss：SPY close-to-close `r²`，QLIKE
- 模型：GJR-GARCH 與 GJR-GARCH-X(VIX)
- VaR：Student-t；1% / 5% 各跑 Kupiec、Christoffersen、DQ Trinity

## 2026-07-11 canonical HAC 重跑

原 local DM 在 `h=1` 時 `range(1, h)` 為空，實際沒有 HAC。現在委派
`volpred.stats.model_evaluation.dm_test`，輸出 loss differential ACF(1–5)，並以
Harvey `|t|>3` 作 headline gate。

| OOS | 舊 t | canonical HAC t | ACF(1) | Harvey |
|---|---:|---:|---:|---|
| 2015–2016 | 2.925 | 2.781 | +0.071 | FAIL |
| 2017–2018 | 2.717 | 2.532 | +0.025 | FAIL |
| 2019–2020 | 1.629 | 1.409 | +0.057 | FAIL |
| 2021–2022 | 1.379 | 1.580 | -0.047 | FAIL |
| 2023–2024 | 2.017 | 2.463 | -0.092 | FAIL |

QLIKE 點估仍是 GJR-X 5/5 較低、平均改善 17.43%；nominal `p<0.10` 仍為 3/5。
但五期沒有任何一期通過 Harvey，故不能再把 QLIKE 優勢寫成多重檢定後的正式顯著結果。
VaR Trinity 完全不走 DM helper，1% 兩模型 5/5 PASS、5% GJR 2/5 與 GJR-X 3/5 均不變。

兩次 live-yfinance 重跑的 DM t 最大漂移 0.0002，所有方向與 gate 一致。執行前
Codex review PASS；結果 JSON 改為同目錄原子寫入。
