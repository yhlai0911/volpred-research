# Worktree Intake

## Before merge

1. 確認 agent 返回的 worktree name、task id、K-id 與唯一 write scope。
2. 確認該 tree 沒有 shared-state modifications。
3. 在 worktree experiment path 檢查 README、entrypoint、result、spec、review verdict。
4. 從 spec 回讀 code/result identity。
5. Main thread 完成 claim verification 與 canonical knowledge write。
6. 在 worktree path 跑 artifact checker；任何 gate failure 都先保留 worktree。

## Integration

唯一入口：

```bash
bash scripts/merge_worktree.sh <worktree-name>
```

該 script 擁有 merge safety、artifact certification、conflict handling與 cleanup。不要用
另一組 Git 指令重做它的工作。

若 command 回報 no-commit、conflict、drift 或 post-merge mismatch：

- 保留 worktree，不做清理
- 保存完整 stdout/stderr、task id、worktree name、K-id
- 回讀 experiment artifact identity
- 將狀態標 blocked 或 contained
- 交給 `merge_worktree.sh` owner 做根因修復與 regression

## After merge

在 main tree 回讀：

- 五個必備 artifact
- canonical result/spec/entrypoint hash
- `review_verdict.json` 的 pinned surface
- knowledge item id
- `experiment_gates.py run`
- `check_experiment_artifacts.py check`

Pre-merge 與 post-merge identity 必須一致。只看到目錄存在或 merge exit 0 不足以結案。
