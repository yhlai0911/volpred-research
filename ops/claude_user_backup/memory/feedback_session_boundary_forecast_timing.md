---
name: feedback_session_boundary_forecast_timing
description: Session-boundary forecast timing — 用戶在 open 用已 realized overnight 資訊下單 (開盤價) 是 legitimate timing，不是 lookahead。這是 Paper 6 K880 audit 的 methodology 判定原則。
type: feedback
originSessionId: 13f14b3a-4b87-487c-988c-baf42c9ee835
---
當某個 volatility/return forecast model 在 day-t intraday session 的預測使用 day-t overnight session 已 realized 的 r²（code 上寫起來像 `r2_overnight[t]` 看似 same-day），**不是 lookahead**，若滿足以下條件：

1. Overnight session 在 intraday session 之前完成（temporal ordering 清楚）
2. Forecast 在 day-t open 時發出，而不是 day-(t-1) close 時發出
3. Paper body 明示 two-phase forecast timing：overnight forecast at (t-1) close, intraday forecast at t open conditional on realized overnight

**Why:** 用戶 2026-04-17 在 Paper 6 K880 lookahead audit decision point 明確 declared：「本來在知道 overnight 之後 在開盤用開盤價買進 是合理的」。這是實務 trading 事實——trader 看完 overnight news 在 open 下單用開盤價執行，是 routinely implementable 的 timing convention，不構成 look-ahead。K880 DM t=6.00 的 SPY 主結果在這個 defensible methodology 下成立並保留。

**How to apply:**
- 下次遇到 session-level / session-boundary forecasting model audit，若 code 使用 "same-day" realized session return 作為下一 session forecast input — 先確認 temporal session ordering + forecast issue timing 是否明確
- 若 methodology 未寫清，指出需要補 Eq. 明示 information set $\mathcal{F}_{d-1}^{\,c}$ vs $\mathcal{F}_{d}^{\,o}$ 差異（參考 Paper 6 main.tex Eqs. 5-6 pattern）
- Benchmark models (GJR, HAR) 若 target $\sigma^2_{\text{full},d}$ 且在 $\mathcal{F}_{d-1}^{\,c}$ 發出，要明標「更 restrictive information set」作為 fair comparison framing
- Trading strategy table notes 要補 "rebalancing executed at day-d open" timing 說明
- 適用範圍：PRG, DCS-EGARCH (Linton 2020), Overnight GARCH-Itô (Kim 2023), score-driven overnight models (Opschoor 2021) 等 session-level models
- 不適用：close-to-close 單一 forecast issue point 的模型（e.g., 標準 GARCH on daily returns）——那裡 same-day realized 才真的是 lookahead

**Reference**: Paper 6 (prg-periodic-garch) main.tex line 111-140 implements this pattern; commit 7d35418b.
