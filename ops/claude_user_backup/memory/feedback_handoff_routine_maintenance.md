---
name: feedback_handoff_routine_maintenance
description: handoff 文件與接續提示詞要平常持續維護，不只 compact 時才寫
process_owner: config/runtime_schedules.json
metadata: 
  node_type: memory
  type: feedback
  originSessionId: df279cec-2a1a-4970-b0ae-111055444eb8
---

用戶 2026-05-29 指示：「平常就要記錄 handoff 文件與接續提示詞」。

**Why**：compact/clear 會丟脈絡；只在 compact 觸發前才寫 handoff（CLAUDE.md 原規則）不夠 — 若 session 突然斷（/exit、crash、clear）來不及寫就全失。平常持續維護才保險。這延伸 CLAUDE.md 的「Handoff 強制規則」從「compact 前」到「routine」。

**How to apply**：
- 每完成一段有意義工作（架構決策、重構里程碑、待用戶決策項、安全網變更），即時更新 `storage/ops/handoff_latest.md` 的 KEEP 區段。
- 手寫內容**必放 `<!-- KEEP -->` 與 `<!-- /KEEP -->` 之間**，否則每 :50 `generate_handoff.py` regen 會清掉（auto 章節覆寫，只 KEEP 區段保留）。
- KEEP 區段要含：本 session 已完成、待用戶拍板項、接續提示詞（compact/clear 後從哪繼續 + 該讀哪些 memory/docs）。
- 2026-05-29 修了 `generate_handoff.py` 的 KEEP 保留 bug（原本沒實作、手寫內容會被清）；說明文字不可含字面 `<!-- KEEP -->` marker 否則與 extractor 自我衝突。

關聯：[[project_refactor_safety_net]]（接續脈絡指向的安全網檔）。
