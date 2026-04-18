---
paths:
  - "scripts/daily_update.py"
  - "scripts/add_strategy.py"
  - "scripts/evaluate_new_strategy.py"
  - "storage/paper_trading.json"
  - "storage/strategy_metrics.json"
  - "storage/strategy_signals.json"
---

# 策略生命週期 SOP（DB 驅動，無需重新部署）

策略 metadata 的唯一來源：`daily_update.py` 頂部的 `STRATEGY_REGISTRY`。Registry 驅動 Feed 文章（只列 active）、Supabase 同步、Paper trading。

## 新增策略（3 步驟）

1. 在 `daily_update.py` 加入 `STRATEGY_REGISTRY`（含 id / name / active / metadata）
2. 加計算邏輯到對應的 strat_list 或策略函式
3. 用 `uv run python scripts/add_strategy.py` 寫入 DB（`strategy_signals` + `strategy_metrics_cache`）

## 下架策略

- 改 `STRATEGY_REGISTRY[<id>]['is_active'] = False`
- 效果：
  - 面板上自動隱藏（前端依 `is_active` 過濾）
  - Feed 文章不再列出
  - **Paper trading 繼續記錄**（歷史續跑，不中斷 tracking）
- 不可直接從 `STRATEGY_REGISTRY` 刪除 — 會讓歷史資料 orphan

## 上架 gate（引用）

值得上架的 gate 在 `.claude/skills/autonomous-research/references/strategy-launch-gate.md`：同期間比較、Cross-OOS、Codex 審查、Sensitivity、MDD 五項全過才 handoff。**`strategy-lifecycle.md` 處理「怎麼做」，不處理「能不能做」。**

## 平台上架操作入口

真正的 `upsert` / activation / 平台同步走 `admin-ops` skill：

- `uv run volpred ops strategy-upsert`
- `uv run volpred ops strategy-set-active`
- `uv run volpred ops recalc-metrics`

## Anti-patterns

- ✗ 直接 PATCH Supabase 的 `strategies` 表加新策略（繞過 registry，會讓 daily_update 抓不到）
- ✗ 從 registry 移除下架策略（失去歷史追蹤）
- ✗ 新策略跳過 `evaluate_new_strategy.py`（導致不同期間比較）
- ✗ 手改 `strategy_metrics.json` 湊數字（違反「永遠修流程，不修資料」）
