---
description: "任務收尾與 context 決策建議。用法: /task-done [任務簡短名稱]"
---

任務簡短名稱：$ARGUMENTS

請用繁體中文、精簡完成收尾，且只根據目前對話、status line 與 `config/token_policy.json`，不要重掃 repo。

`config/token_policy.json` 是 context 門檻 canonical source。只需要讀：
- `context_boundaries.normal_max_pct`
- `context_boundaries.clear_min_pct`

輸出內容：
1. 2-4 句本輪摘要
2. 1 句下一輪 anchor
3. 目前 context 百分比；若看不到 status line 就明說
4. 固定決策：
   - `< normal_max_pct`：留在原 session
   - `normal_max_pct - clear_min_pct`：建議 `/compact`
   - `> clear_min_pct` 或下一輪要切換 task family：建議 `/clear`

語音完成提示由 user-level Stop hook 機械執行；本 command **不要再手動呼叫 `say`**，避免
同一 turn 重複播報。完成摘要最後依 `~/.claude/CLAUDE.md` 加 `task-done` hidden receipt；
Desktop/VSCode hook 驗證 receipt 後才播，SDK/headless/無 receipt 回覆一律靜音。
