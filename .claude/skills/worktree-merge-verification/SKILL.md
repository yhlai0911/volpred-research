---
name: worktree-merge-verification
description: >
  Diagnose or complete integration of a returned experiment worktree. Use only
  when an experiment worktree is ready for merge, a merge was rejected, or
  post-merge artifact identity must be verified.
user-invocable: false
---

# Experiment Worktree Integration Alias

Post-experiment intake 已由 `agent-result-verification` 統一擁有。先讀：

- `.claude/skills/agent-result-verification/SKILL.md`
- `.claude/skills/agent-result-verification/references/worktree-intake.md`
- `.claude/skills/autonomous-research/references/operations-core-contract.md`

每次 invocation 都先執行：

```bash
uv run python scripts/task_pool_control.py status
```

然後依 canonical intake 順序完成：

1. 驗證 result/spec/code trace/review identity。
2. Main thread 經 canonical writer/K1259 寫 knowledge 並回讀。
3. 跑 experiment gates 與 `scripts/check_experiment_artifacts.py`。
4. 只用 `bash scripts/merge_worktree.sh <worktree-name>` 整合。
5. 在 main 回讀 artifact hash 與 gates。

Merge 失敗時保留 worktree 和完整輸出；不得自行執行 branch manipulation、commit
拼接或 worktree cleanup。需要保存合法的 exact-path 變更時使用
`scripts/git_writer_lock.py`；本 alias 不維護另一套 recovery 流程。
