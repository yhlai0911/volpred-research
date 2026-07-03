---
name: feedback_no_cd_into_worktree_before_merge
description: 主線程操作 worktree 前勿 cd 進 worktree 目錄；用絕對路徑，否則持久 cwd 汙染會使 merge_worktree.sh 誤刪未合併工作
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 8137f494-ce08-4097-882f-a6f9dd9d6bc5
---

主線程處理 worktree（尤其 merge / remove）**前**，Bash 工具的持久 cwd **絕不可停在該 worktree 內部**。一律用 repo 絕對路徑操作，需要時先 `cd $REPO_ROOT`；**永不從 worktree 內部觸發 `merge_worktree.sh`**。

**Why**：Bash 工具 cwd 跨呼叫持久。若我先 `cd` 進 worktree（例如為了在該目錄跑 codex review），之後 `merge_worktree.sh` 移除該 worktree → shell cwd 失效 → 後續 `git rev-list`/`diff-tree` 因「cannot read current working directory」失敗回空 → 腳本把 git 失敗 silently 當成「0 commits / experiments 空 → 可安全移除」→ 未 merge 就砍 worktree。K1032（首次）+ K1618（2026-07-04 第 2 次）皆此 root cause，K1618 靠 branch 存活 + `git checkout <branch> -- experiments/K1618/` 救回。

**How to apply**：
1. 跑 Codex review / 讀 worktree 檔案：用**絕對路徑**（`cat $WT/experiments/...` / codex 指令帶絕對路徑），不要 `cd $WT && ...`。
2. merge 前若不確定 cwd，先 `cd /Users/yhlai0911/volpred-research`。
3. merge 後**必驗** main repo 檔案實際存在（`ls experiments/kXXX/`）— worktree-merge-verification skill 的 K1032 checklist，本次靠此即時抓到遺失並救回。

治本進行中：`platform_ops_fix_merge_worktree_silent_revlist`（P1，讓腳本對 git 指令失敗 fail-loud/ABORT 而非當 empty=safe）。詳見 error_log 2026-07-04 04:25。相關 [[feedback_finish_task_before_standby]]。
