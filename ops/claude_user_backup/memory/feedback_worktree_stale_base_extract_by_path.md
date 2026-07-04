---
name: feedback_worktree_stale_base_extract_by_path
description: Agent worktree 從 stale base 分出使 merge_worktree guard abort 時，用 path-scoped checkout 抽取實驗檔，不硬 merge
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 2ae7d924-7f1e-4953-9134-6ca575368347
---

實驗 agent 的 `isolation:worktree` 可能從**數小時前的 stale main commit** 分出（因 codex_loop daemon 持續對 main 自動 commit，實驗跑 20 分鐘期間 main 可前進數十個 commit）。此時 `merge_worktree.sh` 的 shared-state guard 會正確 abort（偵測 `knowledge.json`/`work_log.json` 等 diff = naive merge 會回捲 main 的工作，正是 K1032/K1618 data-loss 場景）。

**Why**：worktree tip 與 main tip 的 `git diff` 會顯示巨大回捲（例：72 檔、-19728 行），但那**不是**實驗改動，而是 main 領先 merge-base 28 commit 的落差。硬 merge = 資料遺失。

**How to apply**（2026-07-04 K1619 實測 recovery，零遺失）：
1. 確認 `git merge-base main <worktree-branch>` 落後 main 多少 commit + worktree tip 距 merge-base 幾 commit（通常 +1 = 只有實驗 commit，乾淨）
2. 確認 main working tree 未被 worktree 改動污染：`git status --porcelain scripts/ src/`（期望 0）
3. **只抽實驗目錄**：`git checkout <worktree-branch> -- experiments/kXXXX/`（新目錄無衝突，純 addition）
4. 對照 `results.json` 驗證 agent 回報數字（K1016）→ 寫 knowledge（canonical Python writer 非 jq，K1259）→ work_log → complete task → PHASE Z commit
5. `git worktree remove <path>`（非 --force）+ `git branch -D <worktree-branch>`（實驗已抽取，內容一致，安全）

不 cd 進 worktree（[[feedback_no_cd_into_worktree_before_merge]]）。若此模式**每班 fire 都復發** → 觸 3-strike，改流程（實驗 agent 派工前 rebase worktree base 到當前 HEAD，或暫停 codex_loop 對 main 的高頻 commit）。
