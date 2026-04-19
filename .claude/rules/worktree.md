---
paths:
  - ".claude/worktrees/**"
  - "scripts/merge_worktree.sh"
  - "scripts/bootstrap_agent_session.sh"
  - "experiments/**/*"
---

# Worktree / Agent 規則

當 Claude 觸及 `.claude/worktrees/**`、`scripts/merge_worktree.sh`、`scripts/bootstrap_agent_session.sh`、或 `experiments/**` 路徑時自動觸發。

## Worktree agent 禁忌（硬規則）

1. **只能產出 `experiments/<kXXX>/` 內的檔案**（實驗三件套：README.md / kXXX.py / kXXX_results.json + 圖表）。
2. **禁止修改共享狀態**：
   - `storage/reports/feed.json`（feed 主文件）
   - `storage/memory/knowledge.json`（研究發現）
   - `storage/memory/thinking_journal.json`（思考記錄）
   - `storage/memory/experiment_experiences.json`（經驗索引）
   - Supabase / Mirror sync 流程（`scripts/supabase_sync.py` 等）
3. **禁止動 `paper/*/body.tex` / `main*.tex`** — 論文寫作由主線程負責（`.claude/rules/paper-workflow.md` L188 加強條款）。

## 合併流程

1. Worktree agent 完成後**必須 commit** 它產出的檔案到 worktree branch。
2. 主線程用 `bash scripts/merge_worktree.sh <worktree-name>` 合併。
3. **絕對禁止** `git worktree remove --force` — 以免未 merge 的 commits 消失（2026-04-18 K1032 教訓有記）。
4. Merge 後**主線程手動 check**：`git log --oneline -5` 驗證 commits 真的進了 main；不信 merge_worktree.sh 的 "no commits" 判定（feedback_merge_worktree_fallthrough）。

## Agent brief 規範

- Brief 必含 6 要素（任務 / 動機 / context 指引 / 規範引用 / 成功標準 / scope 限制）— 完整說明見 `.claude/rules/agent-delegation.md`。
- 標準 template：`.claude/skills/autonomous-research/references/agent-brief-template.md`
- **Claude-based agent** 引用 `.claude/skills/*.md` 路徑
- **Codex agent** 引用 `.agents/skills/*.md` 路徑（Codex 讀不到 `.claude/`）

## 踩過的坑

- K1032 worktree agent commits 存在但 `merge_worktree.sh` 判定 no-commits → 實驗檔案遺失。修復：主線程手動 check reflog + 補 cherry-pick。
- Session 停止時 `git worktree remove --force` 清掉未 merge worktree → 重要 session recovery 永遠走 reflog 不走 remove force。
