---
name: 不要刪 CLAUDE.md 的一句話版本 / 核心 mnemonic
description: 精簡 CLAUDE.md 時保留「一眼掃讀的核心原則摘要」，即使內容上面有詳細版重複
type: feedback
originSessionId: 4742deae-8cbd-477f-a560-11e57f03099f
---
CLAUDE.md 裡的「一句話版本」/「核心原則摘要」類型段落（例如 5 條 one-liner 列出系統定位、先後順序、研究誠實核心），即使上面有詳細版重複，**也不要刪**。

**Why:** 這類段落的價值不在內容獨特（都是上面詳細版的濃縮），而在「掃一眼就能重新記住」的 mnemonic 功能。刪除看似省 tokens（實際只 200 tokens 左右）但失去 at-a-glance memorization value。用戶 2026-04-20 在 token-optimization refactor 時指正我刪 L309-315「一句話版本」這 5 條（系統由 AI 運營 / 先查 error_log 知識庫文獻 / 先修流程不修資料 / Codex 審代碼 / 無關任務開 sub-agent）。

**How to apply:**
- 精簡 CLAUDE.md 時，重複內容是否可壓縮 → 看是 **詳述段落重複**（可壓）還是 **掃讀摘要重複**（保留）
- 掃讀摘要判斷標準：整段 ≤ 10 行、每行 ≤ 30 字、無細節與例子、功能是快速 refresh mental model → 一律保留
- Token 省不到 500 tokens 的精簡若會損失 mnemonic value → 不划算，別做
- 例子：研究誠實原則 13 條 → 壓成 6 條群組（可做，因為 13 條太長不是 mnemonic 而是 detail）；但 5 條 one-liner mnemonic → 不壓

**與既有 feedback 的關係：**
- `feedback_claudemd_keep_inline.md` 已說「CLAUDE.md 不拆分，參考資料保持 inline」
- 此則進一步：inline 的「核心原則 mnemonic」也不要刪，即使上面有詳述版重複
