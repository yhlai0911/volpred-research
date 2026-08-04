---
name: reference_global_session_lock_hook
description: 全域主 checkout 互斥鎖 hook 已上線（2026-08-04）；volpred 在 optout 名單，勿在 volpred 內期待或重建此鎖
metadata: 
  node_type: memory
  type: reference
  originSessionId: 87923af3-c390-4c70-8280-3169e50c7efc
  modified: 2026-08-04T05:07:49.647Z
---

2026-08-04 依老闆指示落地「全域 session 防污染」機制（整合另一專案的 mutex 提案 + 本專案評估的三個修正）：

- **機械層**：`~/.claude/hooks/main-checkout-lock.sh`（PreToolUse: Edit|MultiEdit|Write|NotebookEdit，註冊於 `~/.claude/settings.json`）。同一 repo 主 checkout 同時只允許一個 session 寫入；後到者被 deny 並引導 EnterWorktree。TTL 45 分鐘（不用 PID 判活——hook 的 $PPID 語義未驗證）、mkdir 原子取鎖（macOS 無 flock(1)）、fail-open。
- **Opt-out 兩層**：`~/.claude/session-locks/optout.conf`（per-machine，每行一個 repo 絕對路徑）或 repo 內 `.claude/no-session-lock`。**volpred-research 在 optout.conf 內**——它有 git_writer_lock + path ownership + 24/7 headless backbone，互斥鎖會鎖死自主運營。
- **判斷層 prose — 單一母本架構（2026-08-04 同日補完）**：`~/AGENTS.md` 是唯一母本（marker `canon:session-pollution-v1`）；`~/.codex/AGENTS.md` 與 `~/.gemini/AGENTS.md` 是指向它的 symlink；`~/.claude/CLAUDE.md`「Session 防污染」章節以 `@~/AGENTS.md` import 引入並只保留 Claude 專屬互斥鎖段。內容只改母本。三方 headless 實測載入皆 yes（claude -p / codex exec bounded / agy -p；Claude Code 官方不直接讀 AGENTS.md，@import 是正解）。`~/.zshrc` 有 `alias cw='claude --worktree'`。
- 測試：九情境（取鎖/deny/刷新/TTL 接管/兩層 optout/worktree 放行/非 git/壞輸入 fail-open）全過，腳本在當日 scratchpad `test_lock_hook.sh`。

**Why**: 老闆要求跨專案通用的 session 防污染規則；volpred 實測污染主因是收尾殘骸（見 [[feedback_finish_task_before_standby]]），並行寫入才需要鎖，故鎖只給一般專案用。
**How to apply**: 其他專案 session 看到「主 checkout 互斥鎖」deny 時→ EnterWorktree，勿用 Bash 繞過；volpred session 不會遇到此鎖，也不要在 volpred 重建同類 gate（anti-stacking，owner 已存在）。刻意未寫 `worktree.baseRef` 進 settings（本機無法驗證 schema，`claude config list` 會掛住）；接續本地工作前自行確認 worktree 分支基準。
