---
name: feedback_progressive_disclosure
description: CLAUDE.md 瘦身必須用 skill 漸進揭露，不是單純搬走資訊。Skill 在 system prompt 中有一行摘要，觸發時才展開全文。
type: feedback
originSessionId: 9807aa33-4474-474b-a251-55893d3d71e9
---
CLAUDE.md 瘦身的正確做法是「漸進揭露」（progressive disclosure），不是「搬走」。

**Why:** CLAUDE.md 每次 API call 都載入（~4000 tokens）。把詳細內容移到 skill 後，system prompt 仍然包含每個 skill 的一行描述（~50 tokens），只在觸發時才載入全文。這比「見 docs/xxx.md」好——因為 skill 描述在 system prompt 裡，Claude 知道它存在且知道何時觸發；但「見 docs/xxx.md」只是一行指引，容易被忽略。

**How to apply:**
- CLAUDE.md 只保留「每次 API call 都需要的核心規則」（~70 行）
- 詳細資訊轉成 skill，每個 skill 有明確的 trigger description
- Skill 的 trigger description 要寫得夠具體，讓 Claude 能自動判斷何時載入
- **不是搬到 docs/xxx.md 然後在 CLAUDE.md 說「見 XXX」**——那不是漸進揭露，只是搬家
- 驗證標準：backup CLAUDE.md 中的每一段重要內容，都必須在某個 skill 的 SKILL.md 中找到對應
