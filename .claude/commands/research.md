---
description: "自主研究給定資產的波動率預測模型。全自動：資料分析→baseline sweep→微調→統計檢定→發佈。用法: /research SPY"
---

目標資產: $ARGUMENTS (若為空，預設 SPY)

先讀 `config/token_policy.json` 的 `context_boundaries`，再做 session boundary gate：
- 若 status line `>= compact_min_pct`，先回覆 `先 /compact，再開始 research-design`，不要先載入長 skill。
- 若 status line `> clear_min_pct` 或目前顯然正在另一個 workflow，先建議 `/clear` / 新 session。

只有在適合直接開始時，才依 `docs/workflow-index.md` 走 `research-design`，再讀 `autonomous-research` skill 執行完整研究流程。
