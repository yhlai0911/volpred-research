---
name: knowledge_index_update_discipline
description: knowledge.json → lancedb 索引更新規則：先檢查 mtime，只用 update 不用 build
type: feedback
originSessionId: 4660c31b-efe5-4a79-89cf-a0dc091e8401
---
更新 knowledge 索引前必做：
1. **先比 mtime**：只有 `storage/memory/knowledge.json` 的 mtime **比 lancedb 索引新**才更新，否則 skip
2. **用增量**：`uv run python scripts/build_knowledge_index.py update`
3. **禁止全量**：不要跑 `build`（全量 rebuild）

**Why**：全量 `build` 會對 knowledge.json 所有 K entries 重新呼叫 Gemini embedding API，直接炸 Gemini 免費額度 / 付費 quota。增量 `update` 只處理 diff。

**How to apply**：
- memory-health / 自動化索引維護 / session startup 檢查到 knowledge.json 改動時
- 任何「更新知識索引」「rebuild knowledge」類任務 — 預設走 update，除非用戶明指 build
- cron job 或 skill 裡若有 rebuild 路徑，應加 mtime check gate
