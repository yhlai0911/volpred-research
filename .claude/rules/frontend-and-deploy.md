
---
paths:
  - "frontend-v2-fix/**/*"
  - "config/project_targets.json"
  - "config/runtime_schedules.json"
  - "docs/architecture.md"
  - "docs/zeabur-safe-deploy.md"
  - "frontend-v2-fix/scripts/deploy-zeabur-safe.sh"
  - ".claude/commands/deploy.md"
---

# Frontend / Deploy Rules

> ## ⚠️ 最重要：`frontend-v2-fix/` 是**獨立巢狀 git repo**，主 repo `.gitignore` 忽略它
> 改完前端要 commit 時：**`cd frontend-v2-fix && git add ... && git commit`** 或 `git -C frontend-v2-fix ...`。
> **在主 repo 根目錄 `git add frontend-v2-fix/...` 會報「ignored by .gitignore / no changes」**（`.gitignore` 第 40 行 `frontend-v2-fix/`）。前端有自己的 `.git`、自己的 commit 歷史（deploy 從這 repo 出）。
> 這是反覆踩過的坑（error_log 2026-04-27 + 2026-06-05）—— 看到這條就直接 `cd frontend-v2-fix` 再 commit，別在主 repo 試。

- active frontend、active Zeabur service、paper public dir、Mirror target 都以 `config/project_targets.json` 為準。
- 若目標 service / frontend 要切換，先改 config，再改程式與文件。
- `frontend-v2-fix/` 是現行線上 target；除非任務要求 redesign，否則延續既有視覺與資訊架構。
- Admin 目前是 observer，不是 canonical control plane；不要把 admin UI 當 source of truth。
- 排程頁與 control-plane 視圖應讀 canonical config / live readout，不要 reverse-parse guide 文件。
- 部署**一律**走 `frontend-v2-fix/scripts/deploy-zeabur-safe.sh`；不要直接 `npx zeabur deploy` 也不要硬編碼 service ID。完整原因看 `docs/zeabur-safe-deploy.md`。
- 查 active target 與 service ID 用 `jq '.active_frontend, .deploy.active_service, .site.default_remote_url' config/project_targets.json`，不要從 skill / 歷史 commit 複製。
