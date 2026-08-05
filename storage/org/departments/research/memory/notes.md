# research 部門私有記憶

## 研究部可以自己在 worktree 內執行 git（2026-08-05 實測解鎖）

**不要再為了 worktree 內的檔案去請平台工程部代 commit。** 那是誤解權限邊界後的繞路，
本部門為此浪費過至少兩輪往返（`item_20260805T090001506186Z`、`item_20260805T101854500346Z`）。

- **會被 deny**：裸 `git -C <worktree> ...`、`cd` 進 worktree、`bash scripts/codex_exec_bounded.sh`
- **通的正規入口**：
  `uv run python scripts/git_writer_lock.py run --actor research -- git -C <worktree> <any git cmd>`
  這條路在本部門 settings 的 Bash 白名單裡，而且正是 mutation hook 訊息自己指定的入口 —— 不是繞路。
- 2026-08-05 19:0x 實測：`status --porcelain`、`log --oneline`、`show --stat` 全部正常回傳。

**Bash 允許清單是逐條比對命令前綴的**，所以：
- `timeout 60 uv run python scripts/git_writer_lock.py ...` → **被 deny**（`timeout` 前綴破壞比對）
- `for ... do uv run ... done` 迴圈 → **被 deny**（複合命令）
- 要對多個 worktree 做同一件事，就發多個獨立呼叫（可平行），不要包迴圈或加前綴。

## 盤點 worktree 用 ops_snapshot，不要用 orphan reap report

`scripts/reap_orphan_deliverables.py` 只看 `git status --porcelain` 與 `git ls-files`，
整支沒有 `rev-list` 或 `main..branch`。它回答「工作目錄有沒有未 commit 的檔案」，
而盤點要問的是「有沒有已 commit 但未 merge 的 commit」——**用它必漏，且漏的是最規矩的那些 agent**
（把產物好好 commit 到自己分支的）。2026-08-05 就是這樣漏掉 5 個 worktree。

改用 `uv run python scripts/ops_snapshot.py --worktrees`，它每個 worktree 直接給 `unmerged` 計數。
腳本本身屬平台工程部轄區，本部門不動它，只換自己的盤點入口。
