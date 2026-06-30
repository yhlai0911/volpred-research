---
name: feedback_skill_structure
description: Claude Code Skill 只放可重用方法論，研究結果放 research_program.md 和 references/
type: feedback
---

Skill 是「個人可重用工具包」，不是「專案結果倉庫」。

**Why:** 用戶指出 SKILL.md 混入了大量研究具體數字（Sharpe 2.0, $17.4M, 94% violations 等），這些是研究結果而非通用方法論，不符合 Claude Code Skill 的設計原意。

**How to apply:**
- SKILL.md：研究流程、通用規則、工具指引（~120 行）
- references/models.md：模型細節、γ 規則、window size 研究結果、VaR 發現
- references/strategies.md：Hybrid VT 數字、危機保護、timing test、失敗策略
- research_program.md：研究進度、結論、下一步方向
- storage/memory/knowledge.json：可查詢的累積知識
- CLAUDE.md：專案架構、CLI 指令、部署說明
