# Experiment Agent Brief Template

主線程填完所有欄位後才派工。Experiment agent 同時必讀
`experiment-preamble.md` 與 `operations-core-contract.md`。

## Identity

- Task id：
- Owner token：
- Reserved experiment id：
- Worktree / agent identity：
- 唯一 write scope：`experiments/<experiment_id>/`

## WHAT

[可推翻的研究問題、模型、資料、baseline、主要 metric 與正式檢定]

## WHY

- 要支援哪個研究或決策問題：
- Related K 與已知結論：
- 本次增量：
- 正面結果代表：
- Null 結果代表：
- 失敗/資料不足代表：

## Data contract

- Source / series：
- Retrieval/vintage：
- Availability timestamp：
- Period：
- 預期樣本數：
- Proxy 與偏誤：
- Input identity 要如何寫入 reproduce spec：

## Method contract

- Empirical / theoretical / simulation / descriptive：
- Forecast origin 與 target horizon：
- Train/OOS split：
- Lag convention：
- Transaction cost：
- Seeds：
- Formal tests / multiple-testing correction：
- Relevant error-log rules：

## Artifact contract

- `README.md`
- `<experiment_id>.py`
- `<experiment_id>_results.json`
- `reproduce_spec.json`，由 runtime `finalize_experiment` 同步建立
- 圖表、loss sidecar、diagnostics（如適用）

Agent 不寫 shared memory、task pool、feed、paper、frontend 或 remote systems。

## Acceptance

- 成功：
- Null：
- Blocked：
- 必須停止的 anomaly：
- Gate commands：

## Review-only override

若此 brief 是 review，而非 execution，逐字加入：

> READ ONLY. Do not execute the reviewed experiment. Reconstruct claims only from
> existing artifacts. If a verdict needs a missing run, return an execution request
> to the main thread. Do not modify the reviewed tree except for the gate-generated
> review verdict explicitly authorized by the brief.

Review prompt/transcript 寫在受審 worktree 外。

## Required reading

- `.claude/skills/autonomous-research/references/experiment-preamble.md`
- `.claude/skills/autonomous-research/references/operations-core-contract.md`
- `.claude/rules/experiments.md`
- `docs/error_log.md` 的指定條目
- [本題其他 primary references]

## Return format

使用 `agent-result-template.md`。所有 numeric claims 同時提供 canonical result JSON path；
主線程會獨立重建，不會採信 summary。
