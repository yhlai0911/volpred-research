---
description: "發佈研究成果到 Web 平台（本地 + Zeabur）。用法: /publish"
---

發佈主題: $ARGUMENTS

先讀 `config/token_policy.json` 的 `context_boundaries`，再做 session boundary gate：
- 若 status line `>= compact_min_pct`，先回覆 `先 /compact，再開始 feed-write`，不要先載入長 skill。
- 若 status line `> clear_min_pct` 或目前顯然正在另一個 workflow，先建議 `/clear` / 新 session。

只有在適合直接開始時，才依 `docs/workflow-index.md` 走 `feed-write`，再讀 `feed-publisher` skill 執行發佈流程。
