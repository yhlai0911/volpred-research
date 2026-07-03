---
name: feedback_fix_silent_fallback_immediately
description: git-push-backup 因 silent fallback hold push 時當場立刻修，不丟給下一班 hourly
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 01833e1e-c221-472e-be13-f9d828e38cc4
---

2026-07-03 老闆回 `[VolPred Alert][WARN] git-push-backup: push held — 3 new silent fallback(s)`：**「以後自己立刻修」**。

該 alert 的 body 原本寫「下一班 hourly dispatch 必須先修」——老闆不接受這種「偵測到就報告、等下一輪」的處理方式。

**Why**：silent fallback gate 擋住 push = 本地研究 commit 積壓、沒備份上雲（dual-source 分岔 incident 的根治靠這條 push line）。有明確修法（每處加 `from volpred.ops.diagnostics import warn` / `_warn_*` 再 fallback，或標 `# silent-ok: 理由`）+ 明確驗證（`audit_silent_fallbacks.py --strict --baseline` 讓 `new=0`）的問題，就是「發現即修」而非「報告等排程」。呼應 [[feedback_alerts_auto_act_not_suggest]] + [[feedback_proactively_complete_red_alerts]] + [[feedback_dont_deflect_act_on_repeated_complaints]]。

**How to apply**：
1. 收到 push-held / silent-fallback / 任何**有明確修法**的 alert，當場（互動 session 或 autonomous fire）修完，不寫「下一班先修」。
2. 修法：per `.claude/rules/no-silent-fallback.md` — observable trace（`warn(...)` / `_warn_*(...)`）或 `# silent-ok: <reason>`（放 silent statement 的行範圍內，audit 才認）。
3. 驗證 gate：`uv run python scripts/audit_silent_fallbacks.py --strict --baseline storage/qa/silent_fallback_baseline.json` → `new=0` EXIT=0；真的減少了就 `--write-baseline` 降 baseline。
4. 端到端解封：`bash scripts/cron_git_push_backup.sh` 確認 `pushed N commit(s) OK` + `git rev-list --count origin/main..main`=0，不等 2 小時後的 cron。
5. push-backup wrapper 邏輯在 `scripts/cron_git_push_backup.sh`（讀 audit `new=N`，>0 就 hold）。
