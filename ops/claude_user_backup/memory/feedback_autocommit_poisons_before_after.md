---
name: feedback_autocommit_poisons_before_after
description: "dispatch-supervisor 的 PHASE-Z auto-commit (git add -A) 會把主線程未 commit 的修改捲進 HEAD，使 `git show HEAD:file` 取到的「修正前」其實是「修正後」→ before/after 對照實驗靜默失效"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: fe77621b-b0fe-4ec4-ada2-9e0826eb6367
---

在主 checkout（`~/volpred-research`）做 before/after 對照實驗時，**不可**用
`git show HEAD:<path>` 或 `git show <recent-sha>:<path>` 取「修正前」版本。
背景的 dispatch-supervisor PHASE-Z safety-net 每班會 `git add -A` + auto-commit
（commit 訊息形如 `ops(dispatch-supervisor HH:MM): PHASE-Z safety-net auto-commit
(agent left uncommitted)`），把主線程**還沒 commit 的修改**一起捲進 HEAD。

**Why**：2026-07-10 診斷 `stat -f` 可攜性 bug 時，我在容器裡跑
`git show HEAD:scripts/check_skills_complete.sh`（以為是原始版）對比新版，兩者
輸出完全相同 → 差點寫下「原版在 Linux 也正常」的錯誤結論。實際上 daemon 已在
幾分鐘前把我的 helper commit 進 HEAD，兩個「版本」是同一份程式碼。對照實驗
**沒有報錯，只是安靜地失去鑑別力** —— 這正是 `.claude/rules/experiments.md`
禁止的那種無效 audit。

**How to apply**：
1. 取「修正前」版本時，錨定到**動手之前就記下的 SHA**，或用 `<auto-commit>^`；
   取完立刻 `grep` 驗證它真的**不含**你新加的符號（例如 `grep -c file_mtime_epoch`
   應為 0）。不驗證就不算取到。
2. 對照組兩份檔案跑出**相同**結果時，先懷疑「兩份是同一份」，再懷疑結論。
3. 需要乾淨、不被 daemon 干擾的 working tree 時，用 worktree 或
   `/private/tmp` 副本，不要在主 checkout 上跟 daemon 搶。
4. 同理，`git status` / staged 狀態隨時可能被 daemon 清空 —— 改完要**立刻**
   commit，並事後用 `git show HEAD:<path>` 確認交付真的落在 HEAD 裡（daemon
   幫你 commit 了也算落地，但要親眼確認）。

相關：[[feedback_declare_complete_requires_class_sweep]]、
[[feedback_no_cd_into_worktree_before_merge]]、[[reference_hourly_dispatch_via_os_cron]]
