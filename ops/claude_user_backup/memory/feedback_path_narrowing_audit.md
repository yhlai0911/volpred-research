---
name: Rule path 收窄必先跑觸發矩陣 audit
description: 收窄 .claude/rules/*.md 的 paths frontmatter 前必完成 workflow-stage × paths 矩陣審核，避免 silent skip
type: feedback
originSessionId: 4742deae-8cbd-477f-a560-11e57f03099f
---
動 `.claude/rules/*.md` 的 `paths:` frontmatter 收窄前，必先完整填「Rule × Workflow Stage × Required Paths 矩陣」— 否則規則在該載入的階段沒載入 = silent failure，比原本 paths 過寬更糟。

**Why:** 2026-04-20 publish-checklist.md incident — paths 只覆蓋「已在發文」階段的 path（feed.json / supabase_sync.py），主線程選題階段 query publication_candidates / read memo / ls experiments 時規則完全不 load → 3-layer dedup rule 在最需要它的選題階段 silent skip → 6 次 dispatch 5/6 沒做 dedup。Silent failure 比過寬觸發更難 debug。

用戶 2026-04-20 指示：「path 收窄 但務必全面檢視避免無法觸發的狀態」。

**How to apply:**
審計矩陣強制 6 欄填完才能改 frontmatter：
1. Rule 名稱
2. 應在哪 workflow 階段 auto-load（planning / selection / execution / verification）
3. 該階段會 touch 的所有 paths（query / grep / read / jq / read memo）
4. 當前 paths
5. 需新增（pre-action touches 未涵蓋者）
6. 可移除（該 path 的其他 rule 已 cover 或內容已搬到 skill reference）

**絕不做：**
- 未填矩陣直接改 paths
- 為「簡化」犧牲「觸發正確性」— 寧多一條冗餘 path 也不 silent skip
- 依賴 `paths: ["**/*"]` 當補救 — 等於退回現狀

**改完驗證：** 新開 session 跑典型 workflow（發文 / 跑實驗 / paper review），確認該載的規則有載、不該載的沒載；任何關鍵 rule 在關鍵階段沒載 → 立刻回滾該 frontmatter 補 path 重驗。

參考：CLAUDE.md「Rule path-trigger 時序原則（2026-04-20 補）」段、plan file 的 E.0 審計矩陣格式。
