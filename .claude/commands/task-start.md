---
description: "開工前 workflow/context 邊界檢查。用法: /task-start [workflow id 或任務描述]"
---

目標 workflow 或任務：$ARGUMENTS

請用繁體中文、精簡完成開工前檢查，只根據目前對話、status line、`docs/workflow-index.md` 與 `config/token_policy.json`，不要先讀長 skill 全文，也不要重掃 repo。

`config/token_policy.json` 是 context 門檻 canonical source。只需要讀：
- `context_boundaries.normal_max_pct`
- `context_boundaries.compact_min_pct`
- `context_boundaries.clear_min_pct`

輸出內容：
1. 推定 workflow_id
2. 對應 detail path
3. 目前 context 百分比；若看不到 status line 就明說
4. 固定決策：
   - `< normal_max_pct`：可直接開始
   - `normal_max_pct - compact_min_pct`：若要載入新長 skill / noisy side task，先 `/compact` 或 fork
   - `compact_min_pct - clear_min_pct`：先 `/compact`
   - `> clear_min_pct` 或要切換 workflow：建議 `/clear` / 新 session
5. 最後一句只給下一步動作：
   - `直接開始：讀 <detail path>`
   - 或 `先 /compact`
   - 或 `先 /clear`
