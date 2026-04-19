
---
paths:
  - "src/volpred/ops/**/*"
  - "storage/ops/**/*"
  - "config/runtime_schedules.json"
  - "scripts/session_startup.md"
  - "docs/project_improvement_status.md"
---

# Control Plane Rules

- 本機控制面優先順序固定：`user-assigned > scheduled > agent-discovered`。
- 目前正式 runtime 是：`單一主線程 Claude Code` + `按需啟動的 Codex rescue / subagent`；不要再把 `claude-worker` / `codex-worker` 視為 standing worker runtime。
- 排程唯一來源是 `config/runtime_schedules.json`；不要讓舊 guide 或歷史報告變成另類 source of truth。
- `storage/ops/` 內的 task / approval / execution / rollback 檔案是控制面資料，不要手動亂改收尾。
- `storage/next_tasks.json` 只屬 legacy planning / working list，不是 canonical queue，也不可覆蓋 `storage/ops/` 狀態。
- `uv run volpred ops scheduler-tick` 的 executor lane 目前只做 advisory snapshot / would-dispatch 報告；正式 task claim/finish 必須來自主線程 direct dispatch 或明確 bootstrapped session。
- Session cron 與 system crontab 需與 canonical runtime schedule 一致。
- Admin UI 目前是 observer；如果 UI 與 canonical spec 不一致，以 canonical spec / local state 為準。
