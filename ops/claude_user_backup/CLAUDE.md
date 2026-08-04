# User Profile

- Name: 賴奕豪 (Yi-Hao Lai)
- Affiliation: 大葉大學財務金融學系 副教授 (Associate Professor, Department of Finance, Da-Yeh University)

## Task completion speech

完成一項使用者指派任務、且必要驗證都通過時，在 final text 最後獨立加入
`<!-- task-done:不超過24字的極簡任務名 -->`。只回覆狀態、尚未完成、失敗、等待確認或等待
背景工作時禁止加入。這是 user-level Stop hook 的機械語音 receipt；不要自行執行 `say`。

# Session 防污染（全域規則，所有專案適用）

通用紀律（何時開 worktree、完成後 test→review→commit→merge 流程、收尾紀律）的唯一
母本是 `~/AGENTS.md`（codex/agy 經 symlink 讀同一份），此處 import：

@~/AGENTS.md

## Claude Code 專屬機械層：主 checkout 互斥鎖（enforcement owner）

- 全域 PreToolUse hook `~/.claude/hooks/main-checkout-lock.sh` 攔 Edit/Write/NotebookEdit：
  同一 repo 主 checkout 同時只允許一個 session 寫入；後到的寫者被 deny 並引導進 worktree。
  鎖閒置 45 分鐘自動失效；linked worktree 內寫入不受鎖限制。
- **被 deny 時的正確反應**：呼叫 EnterWorktree 到隔離 worktree 繼續，**不要用 Bash
  （sed -i / 重導向）繞過**——繞過 = 製造這條規則要防止的污染。
- Opt-out（有自己併發治理的 repo）：`~/.claude/session-locks/optout.conf` 每行一個 repo
  絕對路徑（per-machine），或 repo 內放 `.claude/no-session-lock`（隨 clone 走）。
  目前 opt-out：`~/volpred-research`（已有 git_writer_lock + path ownership + 24/7
  backbone，互斥鎖會干擾其 headless ops session）。專案自己的併發規則優先於本節。
