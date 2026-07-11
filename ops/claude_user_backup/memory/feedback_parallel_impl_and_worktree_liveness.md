---
name: feedback_parallel_impl_and_worktree_liveness
description: ops/infra 修復缺 claim 機制導致同日三次平行實作；worktree liveness 要用 lsof 不是 mtime
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 89dc521f-9708-432d-bd38-b88abab2aab8
---

**A. ops/infra 修復沒有 claim 機制 → 同日三次平行實作（2026-07-10）**

同一天，三組不同 agent 各自重做同一件事：
1. `claude/upbeat-rhodes-ffaad8` vs main 的 HEADERS 重構（error_log commit a501db92b 判定「不可 merge」）
2. `claude/eloquent-chatterjee-32e858` vs main 的 test-isolation（85d69e2d3 + f5f3d210b 獨立落地同樣修復）
3. `claude/prepush-commit-gate` vs in-flight worker 的 pre-push gate 改寫（128 行 vs 151 行，同日同主題）

**Why**：研究側有 `scripts/topic_claim.py` + `scripts/kid_reserve.py`（fcntl 原子 claim）防止兩 agent 搶同一個 K；
**ops/infra 修復完全沒有對應機制** —— 任何 agent 都能開一個 worktree 重寫 `check_alerts.py` / `conftest.py` / `pre-push`。

**How to apply**：
- 接到 infra 修復任務時，**先 grep 近 24h 的 commit 與 `git branch --list 'claude/*'`** 看有沒有人在做同一主題，再開工。
- 評估孤兒 branch 是否 merge 時，**先問「main 是否已獨立落地等價修復」**，用 `git cherry main <branch>`（`-` = patch 已在 main）而不是看標題。
- **Agent 對 branch 價值的宣稱要親自 grep 驗證。** 2026-07-10 兩個 agent 都宣稱 eloquent 有 `_write_output_atomically`，實際四個 ref 全部 0 命中 —— 是幻覺。

**B. worktree/agent liveness 判斷：用 lsof，不是檔案 mtime**

清理孤兒 worktree 時，「近 60 分鐘無檔案寫入」**不是** idle 的證據 —— agent 可能在思考或等 API。
2026-07-10 差點誤刪 `funny-cartwright-d6471a`，`lsof -a -d cwd +D <path>` 顯示有活著的 claude process（已跑 4h50m）。

正確判定：`lsof -a -d cwd +D <worktree>` 有輸出 = ACTIVE，不可動。

**C. 清 worktree 的零遺失流程（remove 不刪 branch）**

`git worktree remove` 只移除工作目錄，**branch 與其 commit 完全保留**。所以：
1. `git -C <worktree> add -A && commit`（把未提交工作存進 branch）
2. `git cat-file -e <branch>:<新檔>` 驗證確實在 branch 上
3. `git worktree remove <path>`（**絕不加 `--force`**，那是 L1 hook deny）
4. `git worktree prune` 清 stale 註冊

2026-07-10 用此流程救下 641 行（cronmarker）+ 517 行（eloquent）+ 128 行（prepush），零遺失。
dispatcher 的 slot = `.claude/worktrees/` 目錄數 + active agent records（`continue_task_dispatch.count_active_slots`），
cap 4 —— 孤兒目錄堆到 6 個就派工停擺，這是 2026-07-10 發文脫班的結構性成因。

相關：[[feedback_no_cd_into_worktree_before_merge]]、[[feedback_worktree_stale_base_extract_by_path]]、[[feedback_declare_complete_requires_class_sweep]]
