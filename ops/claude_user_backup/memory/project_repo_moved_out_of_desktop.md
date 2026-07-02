---
name: project-repo-moved-out-of-desktop
description: 2026-07-02 repo 已從 ~/Desktop/volpred-research 搬到 ~/volpred-research（根除 TCC 問題）；symlink 安全網已於同日 14:16 移除（老闆核准），舊路徑引用會 fail-loud
metadata: 
  node_type: memory
  type: project
  originSessionId: 84ae09c8-9673-48d4-b7bc-6113766e22dc
---

2026-07-02 老闆指示「徹底解決」後，repo 從 `~/Desktop/volpred-research` 遷移到 `~/volpred-research`。動機：macOS TCC 只保護 Desktop/Documents/Downloads，claude CLI 每次自動更新（每 1-2 天）都會讓新版本 binary 失去 Desktop 授權，導致所有 launchd 排程在凌晨更新後全滅數小時（2026-07-02 05:00-10:48 事故，見 docs/error_log.md ROOT CAUSE CONFIRMED entry）。

**Why**: 搬出 TCC 保護區後，launchd 排程不再需要任何 TCC 授權——連無授權的 `/bin/sh`/`/bin/ls` 都驗證可正常執行。claude/uv/git 未來怎麼更新都不影響排程。

**How to apply**:
- 一切新路徑引用一律用 `/Users/yhlai0911/volpred-research`；發現 `Desktop/volpred-research` 殘留引用直接改掉，不依賴 symlink
- 舊路徑 `~/Desktop/volpred-research` 的 symlink 安全網已於 2026-07-02 14:16 移除（老闆確認後遺症巡檢清零後核准）— 任何殘留舊路徑引用現在會 fail-loud（優於 silent 走 Desktop 重入 TCC）。歷史 results JSON / feed charts provenance 內的舊路徑字串是死路徑但屬歷史記錄，不影響 runtime；re-publish 舊文章時 `audit_details_chart_paths` 會警告。若極端情況需臨時復原：`ln -s /Users/yhlai0911/volpred-research /Users/yhlai0911/Desktop/volpred-research`
- **更正（2026-07-02 13:23）**：上午宣稱「已遷移」的 backbone（42 shim / 6 plist / 15 crontab）實測**當時並未完成** — 13:17 檢查全部仍指 Desktop 舊路徑，13:22 才真正 sed 替換 + launchctl 重載 + grep/curl 驗證清零（見 error_log 2026-07-02 13:23 entry）。教訓：遷移完成以實測清零為準
- 同日已遷移：`~/.codex/config.toml`、repo 內 321 個功能性檔案、repo scripts/cron_*.sh、CLAUDE.md、worktree `~/volpred-refactor`（已 repair）、Claude 專案記憶（複製到 `-Users-yhlai0911-volpred-research` slug）
- 刻意不改：experiments 的 `*_results.json`、`.log`、`docs/archived/`、`docs/handoffs/`（歷史紀錄，研究誠實原則）
- **後遺症全面巡檢完成（2026-07-02 14:15）**：13 agent workflow 巡檢發現 13:23 清零之外還有 5 層活殘留（venv 全層 / git hooksPath+worktree pointers / home 全域含 memory 分岔 / VS Code window-restore / 模板 runbook），全數修復 + 全系統 grep 驗證清零（見 error_log 2026-07-02 14:15 entry）。日後路徑遷移的完整驗收清單已寫入 `docs/host-migration.md`
- 舊專案目錄 `~/.claude/projects/-Users-yhlai0911-Desktop-volpred-research/memory` 已改為 symlink 指向新目錄（原內容備份在 `memory.pre-migration-backup-20260702`）— 即使 session 從 symlink 路徑開啟，memory 寫入也自動統一
- 相關 memory：[[reference-frontend-nested-git-repo]]（nested repo 隨遷移一起搬）
