# Claude Code 接續提示詞：VolPred 專案優化

請直接複製以下內容給 Claude Code：

```text
你要接續的是 VolPred 的專案優化任務，不是例行任務。

工作目錄：/Users/yhlai0911/volpred-research
接續文件：docs/handoffs/2026-08-03_volpred_optimization_continuation.md

先讀取：
- AGENTS.md
- storage/ops/handoff_latest.md
- docs/agents/ownership.md
- docs/error_log.md
- docs/refactor_plan_ops_master_2026_07.md
- docs/handoffs/2026-08-03_volpred_optimization_continuation.md

核心目標：
沿用既有 Issue #3 → Operations Core master plan → Plan T tickets，持續完成架構優化與 legacy execution retirement。不要重新規劃，不要從一般 daily article、routine alert、一般 experiment 或 email_reply 任務開始。

重要前提：
1. Issue #7 Work Coordinator Shadow Replay 已 CLOSED，final remediation commit 是 dc46b62aa，status 是 root_cause_fixed_and_verified。不要重新 implement #7。
2. 目前另一個 Codex session 正在處理 Graphify/resource-aware dispatch，可能修改 scripts/model_router.py 與 scripts/compute_queue.py。在 live checkpoint 明確形成前，不要修改、回退或覆蓋這兩個檔案。
3. GitHub issue 是優化 roadmap 與 acceptance source；若 ticket 已 materialize 到 storage/next_tasks.json，才使用 task_pool claim/start/complete 作 execution receipt。不要建立第二套 queue。

優先依 live blocking edges 檢查：
#9 Queue Ownership Cutover
#13 Incident Lifecycle
#21 Warm Standby
#24 Formal Commit / Effect Workers
#28 Scheduler Ownership Cutover
#44 Producer Isolation / PHASE-Z retirement
#45 Termination recovery
#46 Global Legacy Execution Retirement

第一步：先對 Issue #9 做 live read-back。
- 檢查 clean window、owner evidence、ready_for_cutover、blocked_until 與 downstream acknowledgement。
- blocked_until 到期不等於 ready；必須由正式 live assessment 判定。
- 如果 #9 尚未 ready，處理一個不衝突的 bounded slice，不得手動解除 blocker。
- 如果 #9 ready，也只能依既有 cutover／rollback contract 執行，不得直接刪 legacy path。

每輪只做一個 bounded slice，嚴格執行：
live symptom evidence → root cause layer →底層可重播修正 → regression + live/API/DB/hash/downstream read-back →制度化寫回。

實作流程：
implement → TDD → Standards review → Spec review → targeted regression → live read-back → issue/doc/receipt update。

操作限制：
- 先檢查 active sessions、dirty paths、最近 commit 與 worktree ownership。
- 使用隔離 worktree，不在 shared main 做大範圍修改。
- 不要回退其他 session 的變更。
- 不要直接修改歷史 JSON、knowledge.json、feed.json 或手動清除 blocker。
- 不要 push。
- 不要因一次測試成功就關閉 umbrella issue。

狀態規則：
- 五步 Gate 未全過：只能回報 contained。
- 五步 Gate、review、live read-back、下游 acknowledgement 都完成：才可回報 root_cause_fixed_and_verified。
- slice 完成但 umbrella 尚有 blocker：保持 issue open，留下證據與下一個 blocker。

結尾請用以下格式回報：
ticket / slice:
base checkpoint:
changed paths:
root cause:
implementation:
tests:
live read-back:
review: Standards PASS/FAIL; Spec PASS/FAIL
status: contained | root_cause_fixed_and_verified
issue disposition: keep open | close
next blocker:
```
