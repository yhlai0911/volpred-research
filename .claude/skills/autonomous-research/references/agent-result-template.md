# Experiment Agent Result Template

## Identity

- Task id：
- Experiment id：
- Agent/worktree：
- Reserved id evidence：
- Exact write scope：

## Execution

- Command：
- Started / finished：
- Seeds：
- Data source、period、sample count：
- Retrieval/vintage：
- OOS split：

## Artifact inventory

| Artifact | Path | Identity / status |
|---|---|---|
| README | | |
| Entrypoint | | code trace |
| Canonical result | | hash / bytes |
| Reproduce spec | | parse/status |
| Figures / sidecars | | |
| Review verdict | | reviewer / pinned surface |

## Claims

每一個 numeric 或 verdict claim 都列 canonical JSON path：

| Claim | Value | Result JSON path | Direction / baseline |
|---|---:|---|---|
| | | | |

不得只提供摘要或 README 行號。

## Diagnostics

- Missing/duplicate/extreme observations：
- Convergence：
- Parameter boundaries：
- Lag/information-set verification：
- Cost verification：
- Formal-test assumptions：
- Unexpected results：

## Gate results

- `finalize_experiment`：
- `experiment_gates.py run`：
- `check_experiment_artifacts.py check`：
- Review verdict：
- Entrypoint drift / preserved gate blob：

貼出 exit status 與最小必要輸出；「沒有 exception」不是 gate evidence。

## Interpretation

- Brief 原始問題：
- Evidence-supported answer：
- Mechanical / empirical distinction：
- Null / limitation：
- Prohibited overclaim：

## Main-thread actions requested

- Claim verification：
- Knowledge proposal（不得直接寫 shared memory）：
- Worktree integration：
- Follow-up proposal：

後續 task 只能由主線程在重新讀取 task-pool mode 後 materialize。
