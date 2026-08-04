# VolPred 優化任務接續文件

更新日期：2026-08-03

用途：在 Codex 額度不足或 Codex session 暫停時，交由 Claude Code 繼續 VolPred 的「專案優化任務」。本文件不作為例行任務、文章生產或一般研究任務的派工說明。

## 1. 交接結論

Claude Code 應接續既有 Operations Core／Matt Pocock 優化計畫，不應重新規劃，也不應從一般 `storage/next_tasks.json` pending 任務開始挑 daily article、routine alert 或一般 experiment。

GitHub issue 負責優化 roadmap 與 acceptance criteria；若某張優化 ticket 已 materialize 到 `storage/next_tasks.json`，才使用 task-pool 的 claim/start/complete 作為執行 receipt。不得建立第二套 pending queue，也不得直接手改歷史 JSON 收尾。

## 2. 已完成、不要重做的工作

### Issue #7 已結案

Issue #7「Work Coordinator Shadow Replay」已是：

- GitHub state：CLOSED
- status：`root_cause_fixed_and_verified`
- final remediation commit：`dc46b62aa`
- 已完成 Standards／Spec 雙軸 review
- 已完成 selector/replay、model-router、adjacent、PostgreSQL 與 full-suite regression

原本的 `Issue #7 handoff` 對話可以作為歷史背景，但不能再用 `/implement #7` 重新開工。Issue #7 明確把七日觀察與 ownership cutover 留給 Issue #9。

## 3. 目前不可重疊的工作

目前有另一個 Codex session 正在處理 Graphify／resource-aware dispatch 優化，已修改或可能修改：

- `scripts/model_router.py`
- `scripts/compute_queue.py`

Claude Code 開工前必須重新檢查 live worktree、active session 與最近 commit；在該 session 的變更尚未形成明確 checkpoint 前，不得修改上述路徑、不得回退 dirty changes。

Graphify 相關工作屬於優化任務 #54 的範圍，與 Operations Core cutover chain 平行，但不能由兩個 session 同時改相同路徑。

## 4. 優化 roadmap 與依賴鏈

核心順序如下，實際是否可開工仍以 live GitHub blocking edges 與 readiness gate 為準：

```text
#9  Queue Ownership Cutover
 └─ #13 Incident Lifecycle
     ├─ #21 Warm Standby
     ├─ #24 Formal Commit / Effect Workers
     └─ #28 Scheduler Ownership Cutover
         ├─ #44 Producer Isolation / PHASE-Z retirement
         └─ #45 Termination recovery
             └─ #46 Global Legacy Execution Retirement
```

目前的優化工作原則：

1. 先回讀 #9 的 live clean window、`ready_for_cutover` 與 owner evidence。
2. 若 #9 尚未通過 gate，處理 #9 內仍未完成且不衝突的 bounded slice；不可只因 `blocked_until` 到期就手動 unblock。
3. #9 通過後，依 blocking graph 逐步推進 #13、#21、#24、#28、#44、#45。
4. #46 只在各 capability 完成 owner、cutover、rollback、downstream acknowledgement 與 sustained-clean evidence 後進行。
5. #12、#16、#17、#20、#25–#36、#54 等其他 Plan ticket，依 live dependency graph 插入，不得因 issue 編號或例行任務優先度任意跳號。

## 5. Claude Code 每輪工作契約

每輪只做一張 ticket 或一個可完整驗證的 bounded slice：

1. 讀取 `AGENTS.md`、`storage/ops/handoff_latest.md`、`docs/agents/ownership.md`、`docs/error_log.md`。
2. 讀取 master plan 的對應段落與 GitHub issue 全文、comments、blocking edges。
3. 檢查 active session、worktree、dirty paths、最近 commit 與 task claim，確認沒有路徑衝突。
4. 固定 base checkpoint，使用隔離 worktree；不要在 shared main 做大範圍修改。
5. 依 `implement → TDD → Standards review → Spec review` 實作。
6. 跑 targeted regression；高風險架構切片再跑相鄰或完整 scoped suite。
7. 以 live config、process、API、database、hash、receipt 或 downstream acknowledgement 做回讀。
8. 更新 GitHub issue、必要的 canonical docs 與 execution receipt。
9. 只有完整通過五步 Gate 才能標 `root_cause_fixed_and_verified`；否則只能標 `contained`。

## 6. 不可做的事

- 不要重做 Issue #7。
- 不要把例行任務池當成優化 roadmap。
- 不要直接改 `storage/next_tasks.json`、knowledge JSON、feed JSON 或歷史資料修結果。
- 不要手動刪除 blocker、手動補 receipt 或把一次成功當 sustained-clean。
- 不要在另一個 session 尚未 checkpoint 時修改其 owned paths。
- 不要 big-bang 刪除 legacy execution、rollback artifact 或 wrapper。
- 不要 push；由 owner／主線程統一處理。
- 不要關閉 umbrella issue，除非該 issue 的全部 acceptance criteria 與五步 Gate 都已完成。

## 7. 完成回報格式

每輪結尾必須明確回報：

```text
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

本文件只負責接續上下文；真正的 acceptance criteria 仍以 master plan 與 GitHub issue 的 live state 為準。
