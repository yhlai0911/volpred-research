---
name: feedback_review_artifacts_outside_worktree
description: 認證審查的 prompt/transcript 不能寫進被審的 worktree，否則撞自己的 clean-tree gate
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 0cc62900-e5b9-4bcb-9ddb-d1c355c69e90
  modified: 2026-07-28T20:56:28.138Z
---

委外審查（Codex bounded review）時，commissioning prompt 與 raw transcript **不可**寫進正在被
認證的 worktree。要嘛放 worktree 外（/tmp 或 canonical repo），要嘛在 reviewer 讀 `git status`
之前就先 commit。

**Why:** K1715 recert round 3（2026-07-29）就是這樣 FAIL 的。四個 round-2 defect 有三個已關、
最關鍵的科學問題（BFGS min-NLL guard 是否改變參數選擇）也拿到獨立 PASS，唯一的 blocking defect
是 `.recert3_prompt.md` 和 `codex_recert3_raw.log` 在審查進行中還是 untracked，於是 reviewer
回讀時 `git status --porcelain` 非空，D4「乾淨認證面」判定不過。**「任何未提交檔案都讓認證面不穩」
的 gate，和「審查會往被審的樹裡寫檔」的流程，在定義上互斥。**這是流程自傷，不是實驗缺陷，但 gate
寫得是絕對條件，reviewer 照字面執行是對的。

**How to apply:** 派審查前先決定 artifact 落點。commissioning prompt 寫 `/tmp/`；raw log 也導到
worktree 外；審完再把兩者 commit 進去當 provenance。另外，會自己寫報告的 checker（例如
`verify_recert2_defects.py` 寫 `recert2_defect_closure.json`）本質上是 fixed point——它一跑就把樹
弄髒——所以 exclusion 必須比對**精確 repo-relative path**，不是 `line.endswith(basename)`（後者會
放行任何同檔名的誘餌），而且讀 porcelain 不能 `.strip()`，否則第一行的狀態前導空格被吃掉、path
整體位移一格。相關：[[feedback_five_step_closure_gate]]、[[feedback_gates_smooth_no_deadlock]]、
[[feedback_no_cd_into_worktree_before_merge]]
