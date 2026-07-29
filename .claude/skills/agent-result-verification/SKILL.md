---
name: agent-result-verification
description: >
  Verify a completed experiment agent's artifacts and claims before knowledge
  recording or worktree integration. Use when an experiment agent returns
  results, statistics, a verdict, or a completed experiment worktree.
user-invocable: false
---

# Post-Experiment Intake

這是 experiment agent 返回後的唯一 intake owner。它驗證 artifact、claims、review、
knowledge provenance 及 worktree delivery；不設計新研究、不發文。

## Preflight

先讀：

- `.claude/skills/autonomous-research/references/operations-core-contract.md`
- `.claude/rules/experiments.md`
- `references/claim-verification.md`
- Worktree 返回時再讀 `references/worktree-intake.md`

每次 invocation 都先回讀：

```bash
uv run python scripts/task_pool_control.py status
```

Mode 不影響 evidence verification；但任何 task complete、follow-up 或 refill 都必須依本次
mode 分支。

## Intake sequence

### 1. Freeze identity

記下：

- task、agent、worktree、reserved K-id
- agent 宣告的 artifact paths
- canonical result、spec、entrypoint 與 review verdict identity
- agent summary 原文

Artifact identity 尚未固定時不開始 knowledge/publishing handoff。

### 2. Verify artifact set

至少確認：

- README、entrypoint、canonical result、`reproduce_spec.json`
- Results 可解析且由 spec 指定
- `results.code_trace` 與 spec entrypoint 指向同一次 bytes
- seeds、inputs、period、sample count、started/finished time 可重建
- 已 pin entrypoint 若漂移，存在原始 `gate_history` evidence

先用 `scripts/reproduce_check.py inventory` 檢查 repository 對這個 experiment 的
reproduce contract 判讀；不要另寫一個 spec parser 當第二個 owner。

缺 runtime spec 或 code trace 時，不能事後人工補成「已驗證」。

### 3. Rebuild every claim

依 `references/claim-verification.md`，從 canonical result 程式化重建 agent summary 的
所有 numeric、direction、significance、uniqueness 與 verdict claims。固定指標表只能當
提示，不能取代 full-population audit。

任何不一致：

- 保存 agent claim 與 artifact actual value
- 以 artifact 為證據修正敘述
- 若差異影響 verdict，回到 code/review，不能直接改 README 收尾

### 4. Run methodology and review gates

```bash
uv run python scripts/experiment_gates.py run \
  --path experiments/<experiment_id>
```

`review_verdict.json` 必須由 gate template 建立並 pin 現有 claim surface。Review 後修改
任何 claim-surface bytes，都要重審。完整 artifact checker 同時檢查 main-thread
knowledge half，因此在下一步 canonical writer read-back 後執行。

### 5. Main-thread knowledge write

只有 artifact 與 reviewer verdict 都有效時：

1. 從 canonical result 程式化組成 knowledge record。
2. 加入 experiment id/path、verdict、evidence 與 reviewer provenance。
3. 經 `src/volpred/memory/system.py` 的 canonical memory writer/K1259 寫入。
4. 回讀 item id。
5. 執行 `scripts/validate_knowledge_provenance.py`。
6. 再跑 `scripts/check_experiment_artifacts.py check`，確認 knowledge half gate 通過。

Agent 或 worktree 不得寫 shared memory。

### 6. Integrate worktree

只有 worktree 返回才執行。依 `references/worktree-intake.md`：

- pre-merge 在 worktree tree 跑 artifact gate
- 整合只走 `bash scripts/merge_worktree.sh <worktree-name>`
- 失敗時保留 worktree與完整輸出
- merge 後在 main 回讀 artifact hash及 gate

不自行改 branch、拼接 commit 或刪 worktree。

### 7. Close or hand off

Task complete 前必須有：

- artifact identity
- rebuilt-claim report
- methodology/review verdict
- knowledge item read-back
- worktree merge/read-back（如適用）

若要新增 follow-up，重新執行 task-pool status，再依 mode 選 canonical producer。
Publication/paper 只收到 verified artifact handoff，不在本 skill 執行。

## Completion status

- `verified`：artifact identity、所有 claims、review、knowledge及必要 merge 都回讀成功。
- `blocked`：缺原始 bytes、spec、review 或無法重建 claim。
- `contained`：只保存 worktree、修正 summary 或暫停傳播，底層問題尚未修復。

不得把「JSON 可以讀」或「merge command exit 0」單獨當成 verified。
