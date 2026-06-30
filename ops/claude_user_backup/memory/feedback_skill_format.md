---
name: feedback_skill_format
description: 建立新 skill 必須遵循 Claude Code 規範的 frontmatter 格式
type: feedback
---

建立新 skill 時必須使用正確的 frontmatter 格式（hyphen 不是 underscore）：

```yaml
---
name: skill-name
description: >
  描述...
user-invocable: true
---
```

**Why:** 用戶指出我沒有遵循 Claude Code skill 規範，手動建立的 skill 缺少 frontmatter。

**How to apply:**
- 欄位名用 hyphen（`user-invocable`）不是 underscore（`user_invocable`）
- 必須有 `name` 和 `description`
- skill 內容放 `skill.md`，詳細實作放 `references/`
- 主要邏輯/方法論在 skill.md，具體程式碼和參考資料在 references/
