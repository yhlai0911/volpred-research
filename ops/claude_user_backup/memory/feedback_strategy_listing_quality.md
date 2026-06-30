---
name: Strategy listing must have uniform format, period, and display
description: 上架策略的績效、圖表、時段、顯示格式必須與現有策略完全一致
type: feedback
---

上架新策略時，績效和圖表呈現必須與現有策略完全統一。

**Why:** 用戶指出新策略上架後：(1) Fear DCA 顯示 SPY 15000%（weight 格式錯誤）(2) 新策略只有 32 天數據（回填不足）(3) best_day 顯示 undefined（metrics 欄位缺失）(4) 圖表和績效期間不統一。多次犯同樣的錯——流程不完整。

**How to apply:**
- **回填期間統一**：所有策略必須從相同起始日期回填（目前是 2023-01-01），新策略不能只有幾天
- **日頻結算**：即使月頻 rebalancing，每日都要計算 portfolio_return（組合每天都有價值變動）
- **Weight 格式**：portfolio weight 用小數（0.50 = 50%），前端會 ×100 顯示。不要用 150 代表 150%
- **Metrics 欄位完整**：必須包含 sharpe, cumulative_return, annualized_return, max_drawdown, calmar, sortino, best_day, worst_day
- **Sparkline 統一**：90 個數據點的 cumulative return 序列
- **日期欄位**：用 trade_date + data_date（不是 date），與既有策略一致
- **上架後必須驗證**：用 `list_new_strategy.py --verify-only` 確認所有欄位完整
- **不要只改 local JSON**——必須確認 Supabase 所有相關表（strategy_signals, strategy_metrics_cache, paper_trades）都正確更新
