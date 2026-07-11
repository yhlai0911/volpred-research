---
name: feedback_hermetic_git_in_tests
description: 任何驅動 git 的測試必須隔離 git 環境變數，否則在共用 checkout 上會誤操作真 repo（曾把 sandbox commit 推上真 origin/main）
metadata: 
  node_type: memory
  type: feedback
  originSessionId: f4c8c346-b658-4afa-8fd1-2135e2b63765
---

驅動 `git` 的測試（`git init` / `commit` / `push` 一個 `/tmp` sandbox）**必須先 hermetic 隔離 git 環境**，否則繼承來的 `GIT_DIR` / `GIT_WORK_TREE` / `GIT_INDEX_FILE` 會讓 `git -C sandbox ...` 改對**真 repo** 執行。

在測試 setup 早段（建 sandbox 後、第一個 git 命令前）加：
```sh
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_OBJECT_DIRECTORY \
      GIT_ALTERNATE_OBJECT_DIRECTORIES GIT_COMMON_DIR GIT_NAMESPACE \
      GIT_CONFIG GIT_CONFIG_GLOBAL GIT_CONFIG_SYSTEM
export GIT_CONFIG_NOSYSTEM=1 GIT_TERMINAL_PROMPT=0 GIT_EDITOR=true
export LC_ALL=C LANG=C          # 別讓 git 說在地化訊息，斷言才穩
export HOME="$SANDBOX"          # 隔絕 global gitconfig（含 core.hooksPath）
```

再兩條配套：
- **斷言看機器狀態，不看 git 散文**（HEAD sha 有沒有動、`.git/MERGE_HEAD` 在不在），因為 git 訊息會被 `LC_ALL` 翻成 zh_TW，prose grep 在不同 locale 下會漏。
- **別用 `printf "$big" | grep -q pat`**：`set -o pipefail` 下 grep 命中即退、printf 吃 EPIPE，pipeline 偽失敗（平行負載下 ~1/10 flake）。改純 shell `case "$hay" in *"$needle"*)`。

**Why**：本 repo 的 main checkout 是多 session 共用一棵真 tree（dispatch agent / 互動 session / codex_loop / cron 全在上面）。測試假設 `git -C sandbox` 只碰 sandbox，就跟 `git add -A` 假設單一寫入者一樣，在共用現實下破功。

**How to apply**：寫或改任何 `scripts/tests/*.sh`（或 `.py`）裡會 spawn `git` 的測試前，先確認上面 unset 區塊在。canonical 範例：`scripts/tests/test_pre_push_pushed_tree.sh`。同家族根因見 [[feedback_finish_task_before_standby]] 上游的共用-checkout 寫入者所有權問題；incident 全紀錄在 `docs/error_log.md` 2026-07-10「非 hermetic git 測試把 sandbox commit 推上真 origin/main」。
