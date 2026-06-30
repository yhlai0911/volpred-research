---
name: reference_strategy_card_metrics_window
description: 線上策略卡 metrics（Sharpe/MDD/cumret）是 2023-01-04 起 paper-trading 窗口值；保守型 VT 低 MDD 是設計使然非 bug
metadata: 
  node_type: memory
  type: reference
  originSessionId: df279cec-2a1a-4970-b0ae-111055444eb8
---

線上 `/api/strategy-overview` 策略卡的 Sharpe / MDD / cumulative_return **三者同窗口**，皆來自 `COMMON_START = 2023-01-04` 起的 `portfolio_return` 序列（TS `data-server.ts:calcMetrics` 與 Python `scripts/recalc_metrics.py:calc_metrics` 同一套邏輯；`sigma_ann`/`vix_level` 例外，來自 `strategy_signals` 即時市場 snapshot）。

**不要把保守型 VT 的低 MDD 當 bug**（2026-06-02 查證，subagent a70d79285 唯讀調查）：保守型 VT（Piecewise）線上 MDD −2.48% / Sharpe 3.08 / 年化波動 5.24% 經獨立 byte-exact 重算驗證**正確**。低 MDD 是設計使然 —— 此策略 **VIX>20 直接全現金**（`daily_update.py:707-735`），836 天有 164 天空倉，超低曝險。「VT 該 −15~−30%」的直覺只適用滿倉高曝險 VT。canonical 全期回測（含 2008 GFC）在 `experiments/k574/`（同變體 MDD −4.91% / Sharpe 1.875）—— 線上短窗口 −2.48% < 全期 −4.91% 方向一致。

**Why**：2026-06-02 我曾誤把 −2.48% 當「偏小、疑似窗口 bug」並派 subagent 調查，結果是正確。記此避免未來重複誤判 + 重複調查。
**How to apply**：看到線上策略卡 MDD/cumret「看起來太好」時，先記得那是 2023-01 起 benign paper-trading 窗口、且保守型策略本就低回撤；要全天候對照看 K574 canonical。真要查 cache 是否 stale 才比對 Supabase `strategy_metrics_cache` vs `storage/strategy_metrics.json`。關聯 [[feedback_research_rigor]]。
