# Skill / Rule / CLAUDE.md Compliance Audit — 2026-04-17

**Overall: 87%** (14/16 skills + 5/5 rules + CLAUDE.md)

## Critical (P1)
- `academic-finance-reviewer/` **缺 SKILL.md** (canonical + rendered 都無)
  - 目錄有 assets/references/ 但無 frontmatter
  - settings.json 有登錄但 skill 無 trigger phrases / scope

## Medium (P2)
- 2 skills 用 lowercase `skill.md` (應該 SKILL.md): `member-questions`, `taiwan-macro-data`

## Low (P3)
- Render process 未 documented (無顯著 render script at repo root)

## 優點
- Frontmatter 合規 100% (16/16 existing skills)
- Rules 全用 `paths:` YAML frontmatter 限定作用域
- CLAUDE.md 246 行 (acceptable < 300)
- Canonical/rendered 一致, auto-gen headers 完整
- Skill 'Do not use for' 交叉引用清楚

## Action items
| Priority | Task | Files |
|---|---|---|
| P1 | Create academic-finance-reviewer SKILL.md | agent-specs/ + .claude/ |
| P2 | Rename skill.md → SKILL.md | member-questions, taiwan-macro-data |
| P3 | Document render process | .claude/RENDER_PROCESS.md |

Full report in agent output. Date: 2026-04-17.
