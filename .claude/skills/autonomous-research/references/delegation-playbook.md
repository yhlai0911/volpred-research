# Research Delegation Playbook

本文件補充 `.claude/rules/task-routing.md`。Task type、concurrency 與 capability 以 rule
及 `scripts/model_router.py` 為準；本檔不複製 inventory。

## Dispatch preflight

每次 claim、派工或建立 follow-up 前：

1. 執行 `uv run python scripts/task_pool_control.py status`。
2. 依 `operations-core-contract.md` 判斷是否允許 queue mutation。
3. 確認 K-id 已由 registry 保留。
4. 確認沒有另一個 active task/worktree 擁有相同 K-id。
5. 宣告每個 agent 的唯一寫入範圍。

Queued mode 的既有任務：

```bash
uv run python scripts/task_pool_claim.py claim \
  --id <task-id> --owner "<owner-token>"
uv run python scripts/task_pool_claim.py start --id <task-id>
```

Owner token 使用 dispatcher 提供的 retry-stable identity；不自訂固定 session 名稱。

## 何時拆 agent

適合平行：

- 不同 K-id、不同 experiment trees
- Literature search 與 code implementation
- Independent review 與不修改受審 tree 的 evidence reconstruction

留在主線程：

- Shared memory writer
- `research_program.md` synthesis
- Paper body / narrative decision
- Worktree integration
- 需要使用者授權的外部 action

兩個 agent 會碰同一路徑時，不平行派工。

## Brief 必備欄位

使用 `agent-brief-template.md`，至少包含：

- WHAT / WHY
- reserved experiment id 與 task id
- related K 與文獻
- inputs、期間、樣本與 availability
- error-log 防錯條目
- 唯一 write scope
- runtime artifact contract
- formal success/failure criteria
- 回報格式

Experiment agent 必讀 `experiment-preamble.md`。

## Timeout 後

執行已開始且 timeout 時：

1. 保留 partial artifact 與 receipt，不能當 completed。
2. 將剩餘工作切成至少兩個 bounded stages。
3. 每段各有唯一輸出、時限、parent id 與 acceptance。
4. 重新讀 task-pool mode，再決定能否 materialize follow-up。
5. 所有 stages 收斂後重新跑完整 artifact/review gate。

Auth/quota 在執行前即拒絕時，可在能力恢復後重試原 brief；仍需新的 runtime receipt。

## Agent 返回後

1. 不採信 summary 數字。
2. 執行 `agent-result-verification`。
3. Worktree 由該 skill 的 integration 分支走 `merge_worktree.sh`。
4. Main thread 經 canonical writer/K1259 寫 knowledge。
5. 回讀 main artifact、knowledge item 與 task terminal receipt。

Task 完成：

```bash
uv run python scripts/task_pool_claim.py complete \
  --id <task-id> --status succeeded --result "<artifact and read-back summary>"
```

只有整張 issue acceptance 與五步 incident gate 都過，才能另外要求 close。

## Fail-closed 情況

- task-pool mode unreadable或 restore 中
- K-id 未 reservation 或 ownership 衝突
- agent 修改 shared state
- result/spec/code trace 不一致
- review verdict 對不上現有 bytes
- partial worktree 找不到完整 artifact identity

以上都保留 evidence 並回報 blocked；不以清 queue、刪 worktree或重派同一大任務掩蓋。
