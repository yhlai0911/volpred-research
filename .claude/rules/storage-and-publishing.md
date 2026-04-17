<!-- AUTO-GENERATED FROM agent-specs/. Edit canonical sources instead. -->

---
paths:
  - "storage/**/*"
  - "scripts/daily_update.py"
  - "scripts/supabase_sync.py"
  - "scripts/recalc_metrics.py"
  - "docs/architecture.md"
---

# Storage / Publishing Rules

- `storage/` 是本地唯一資料源；不要手改歷史 JSON 來補洞。
- 發文一律走 `feed-publisher`；thinking 不是 content。
- 非時效性文章預設 `draft` 進池；事件驅動文章要立即 `published`。
- 每篇文章都要有真實圖表、數據來源與對應實驗。
- `paper_trading.json` 不手改歷史值；回補與績效重算走既有流程。
- Supabase / Mirror sync 是流程責任，不要手動 PATCH 當作正式修復。
