---
name: project_strategy_lifecycle_standing_directive
description: boss 2026-06-21 standing directive：交易策略持續增加，表現好上架觀察、不好下架，走既有 gate；3 檔高 Sharpe inactive 的 lookahead audit 已完成（6/21 全 reject：c2c artifact，維持 inactive）
process_owner: .claude/skills/admin-ops/references/strategy-lifecycle.md
metadata: 
  node_type: memory
  type: project
  originSessionId: 9b03f82f-4b5a-4fd1-8247-88240cdbc856
---

boss 2026-06-21（email-11862）standing directive：**交易策略要持續增加** — 表現好的就上架觀察（上架），不好的就下架；上架標準與流程**與既有一致**（不另立標準）。同信也重申「你是自主平台運營經理，應該自主決定」（我問他選哪篇論文 draft = 違反 [[feedback_dont_ask_do]]，已糾正：自主推方向 B）。

**這是持續流程，不是一次性**（monetization-direct：策略 = 付費 tier 可見度 + 平台可信度）。

**既有上架流程/gate**（docs/strategy-registry.md + `.claude/skills/autonomous-research/references/add-strategy-guide.md`）：
1. 同期間 Sharpe ≥ 已上架中位數（~2.0）
2. Sensitivity（±20% 參數 → Sharpe 不降 >30%）
3. MDD < −20%
4. cross-OOS + Codex review
5. **Sharpe 遠高於 baseline → 先懷疑 bug + lookahead**（CLAUDE.md 硬規則）
- 上架：`uv run python scripts/list_new_strategy.py --key <k>`（一鍵 DB+metrics+sparkline+sync+verify）；先加 `STRATEGY_REGISTRY`（`scripts/daily_update.py` 頂部）
- 查狀態：`list_new_strategy.py --list-all`
- 下架：績效異常 → 卡片注記「近期顯著偏離歷史」**不下架**；只有結構性問題（bug/停牌/邏輯錯）才 `is_active=False`

**3 檔高 Sharpe inactive 候選 — audit 完成（2026-06-21）→ 全部拒絕上架，維持 inactive**：
- `tz_tw_jp_5050`(3.46)、`taiwan_spy_momentum`(3.23)、`global_vt_tz`(2.91) 的高 Sharpe 是 **c2c measurement artifact** — 78% alpha 來自無法捕捉的隔夜開盤跳空；可交易的 o2o 版 Sharpe~0.87 **FAIL Harvey t>3**。
- 證據：k274（"not a trading strategy, a measure of price discovery efficiency"）、k286（uncapturable overnight gap, o2o~0.87, Gap R²=0.35）、k502/k238。`daily_update.py:576-621` 標 `⚠️ I8 BIASED`。
- **教訓**：高 c2c Sharpe ≠ 可交易 edge；上架=把假象賣給付費用戶。維持 inactive 正確。「Sharpe 遠高於 baseline 先懷疑 bug」如預期運作。
- 詳見 docs/strategy-registry.md「上架候選 audit 結果」段。**未來新策略候選一律先驗 o2o/lagged Harvey 再談上架。**

**How to apply**：idle tick 主動跑此 lifecycle（新策略實驗 → evaluate → gate → list/document）；不等 boss 逐次指示。關聯 [[feedback_strategy_listing_quality]] [[project_platform_profitability_goal]]。
