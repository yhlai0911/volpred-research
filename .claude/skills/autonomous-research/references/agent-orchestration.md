# Research Agent Orchestration

`autonomous-research` 使用本文件選 topology；正式 task type 與 concurrency 仍由
`.claude/rules/task-routing.md` 決定。

## Owner boundary

- Research design/execution：`autonomous-research`
- Post-run claim verification：`agent-result-verification`
- Worktree integration：`agent-result-verification` 的 worktree branch
- Data source selection：`external-data-sources`
- Data freshness incident：`data-collection-ops`
- Shared memory health/write：`memory-health` 與 canonical writer
- Publishing、paper、deployment：交給各自 owner

## Topology

| 情況 | Topology |
|---|---|
| 單一 K、單一路徑 | 一個 worktree agent |
| 多個互不依賴 K-id | 每個 K 一個 worktree，可在 slot 內平行 |
| 只查 repository facts | read-only explorer |
| 只查文獻 | read-only research agent，回傳 primary sources |
| 需要 independent verdict | fresh-context reviewer，不修改被審 tree |
| 需要 shared-state synthesis | 主線程 |

Agent 之間有資料依賴時按 stage 排序，不為了填 slot 強行平行。

## Dispatch sequence

1. 重讀 task-pool mode。
2. Reserve K-id。
3. 寫自足 brief 與唯一 write scope。
4. 派工並保留 task/agent/worktree identity。
5. 等待完整返回；不把「agent 已啟動」當成果。
6. 走 post-run verification、knowledge writer、merge、read-back。

詳細命令與 timeout 行為見 `delegation-playbook.md`。

## Review independence

- Reviewer 只讀 frozen claim surface。
- Commissioning prompt 與 raw transcript 放在 worktree 外。
- Reviewer 不執行實驗；缺少 run 時回報 execution request。
- Verdict 由 gate template 產生。
- 修正任何 claim-surface artifact 後重新 review。

## Completion

Orchestration 完成必須能連回：

- task/agent/worktree identity
- reserved K-id
- canonical result/spec identity
- reviewer verdict
- main-thread knowledge item
- merge/read-back evidence

任一段缺失時不 complete task。
