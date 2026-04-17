---
paths:
  - "paper/**/*"
  - "docs/paper-guide.md"
---

# Paper Workflow Rules

- 論文 `.tex` 寫作與方法論決策留在主線程；不要丟給 background agent 直接改寫。
- 標準流程：審查 → 修正 → 編譯 → `uv run volpred ops paper-update --paper-id <id>`。
- 修訂時保留 review、diff、版本化檔案，不要只覆蓋舊版。
- 期刊 metadata、PDF slug、同步細節看 `docs/paper-guide.md`。
- 若涉及實驗數據或引用檢查，主線程應明確調用 `latex-academic-reviewer`、`citation-verifier`、`paper-update` 等技能。
