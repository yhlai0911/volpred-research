---
paths:
  - "storage/**"
  - "scripts/supabase_sync.py"
  - "scripts/daily_update.py"
  - "scripts/recalc_metrics.py"
  - "src/volpred/memory/**"
---

# 資料流核心規則

`storage/` 是本地唯一源頭。任何修改資料流的動作都要守住下列規則。

## 源頭與同步

- `storage/` → 本地唯一源頭（JSON）
- `scripts/supabase_sync.py` → Supabase 同步（由 `daily_update.py` 呼叫）
  - **文章同步**：只讀取 `storage/reports/feed.json`（唯一源頭，`storage/feed.json` 已廢除）
  - **Paper trades 同步**：自動剝離市場數據，只存策略 weights + returns
  - **Draft 同步**：用 `published_at OR created_at` 過濾
- `scripts/daily_update.py` → 每日 00:03 UTC（台灣 08:03）美股收盤後計算策略權重 + 同步 Supabase + 重算績效指標
  - 每日只產出一篇「每日策略建議」（含市場快照 + 持倉表 + VIX 分析），不再分兩篇
- **Mirror 資料流**：`MemorySystem._sync_to_remote()` → 雙寫 Supabase + Mirror API

## Paper Trading 資料結構（關鍵規則）

- `paper_trading.json` 是**唯一源頭**，不可手動修改歷史數據
- `daily_update.py` 正確使用 **next-day return**（K692 驗證），forward tracking 自動修正；不要為了修歷史數字去改它
- `recalc_metrics.py` 每次執行自動 sync 到 Supabase `strategy_metrics_cache`
- **市場數據統一存在 `_market_daily`**（key = 日期），不在每個 entry 重複

## 新策略評估

- 必須用 `scripts/evaluate_new_strategy.py` 在 `COMMON_START=2023-01-04` ~ 今天**同期間比較**
- 不同期間的結果不可直接比（違反上架 5 項檢驗的第一項）

## Anti-patterns（禁止）

- ✗ 手動改 `paper_trading.json` 歷史 entry 的 `portfolio_return`（K693 教訓：曾嘗試改 9935 筆導致 metrics 不同步、Supabase 不一致，已 revert）
- ✗ 寫入已廢除的 `storage/feed.json`（只能寫 `storage/reports/feed.json`）
- ✗ 用新策略跟舊策略的「不同期間績效」比較（必須對齊 COMMON_START）
- ✗ 在 Supabase 用 PATCH 手動補資料 — 永遠修 sync 流程，不修資料（參見 CLAUDE.md「思維模式：永遠修流程，不修資料」）
