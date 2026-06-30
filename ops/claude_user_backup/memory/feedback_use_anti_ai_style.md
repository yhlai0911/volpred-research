---
name: 寫文章必用 anti-ai-style skill
description: 任何 zh-Hant reader-facing 文章（feed / trending_repost / daily_article / member_qa / FB hook）寫前讀 prompt-templates，寫後跑 editor-sop 9-checklist，禁略過
type: feedback
originSessionId: 91283b9e-7227-43f5-88bb-9d92168d243a
---
**Rule**: 寫任何 zh-Hant reader-facing 文章（feed article / trending_repost / daily_article / event_article / member_qa 答覆 / FB hook / push notification）必須使用 `.claude/skills/anti-ai-style/` skill：

1. **寫前**：讀 `references/prompt-templates.md`，在 AI 生成 prompt 開頭貼 5 原則模板（年齡降級 / 長文裁切 / 資訊密度 / 負向約束 / 蘇格拉底對槓）
2. **寫中**：對照 `references/8-landmines.md` 8 大地雷自查；參考 `references/bad-vs-good.md` 改寫範例
3. **寫後**：跑 `references/editor-sop.md` 3 階段 9 checklist；任一 fail 不 publish
4. **3-model gate 擴充**：Gemini 一審 prompt 必加問 anti-AI-style check（「是否仍有 AI 味？指出最像 AI 的 3 句並建議改寫」）

**Why**:
- 用戶 2026-05-15 明確指示：「未來寫文章時 要參考使用 anti-ai-style 來寫作」
- AI 味文章直接打擊 Mission Goal 1（文章寫好）+ Goal 5（曝光流量）— 讀者回訪率與分享率硬指標
- 沒 enforce 容易遺忘 — skill 已建好但被忽略 = 白做

**How to apply**:
- 派 feed-publisher / trending-repost / daily_article agent 時，brief 必含 `.claude/skills/anti-ai-style/` 路徑 + 「寫前讀 prompt-templates、寫後跑 editor-sop」明文要求
- 主線程自己寫 zh-Hant 文章內容（少數情境，agent 不適合）時也同樣套用
- 論文場景：`latex-academic-reviewer` 範疇豁免地雷 1（不是…而是）+ 地雷 8（吊書袋學術術語），其他 6 條仍 enforce

**例外（不適用）**：
- Commit message / 內部 work_log / m.think 思考紀錄 / code comment — 這些不是 reader-facing
- Code 本身（log / error message / variable name）
- Data table 純數據呈現
- 英文文章（本 skill 鎖定 zh-Hant；英文有不同的 AI 味 pattern，未來補英文版 skill）

**Skill 路徑**：
- 主檔：`.claude/skills/anti-ai-style/SKILL.md`
- 5 references：8-landmines / prompt-templates / editor-sop / bad-vs-good / sources
- Co-trigger paths（已設 frontmatter）：feed-publisher / trending-repost skill 啟動時自動 surface
