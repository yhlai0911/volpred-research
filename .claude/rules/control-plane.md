<!-- AUTO-GENERATED FROM agent-specs/. Edit canonical sources instead. -->

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
- 排程唯一來源是 `config/runtime_schedules.json`；不要讓舊 guide 或歷史報告變成另類 source of truth。
- `storage/ops/` 內的 task / approval / execution / rollback 檔案是控制面資料，不要手動亂改收尾。
- Session cron 與 system crontab 需與 canonical runtime schedule 一致。
- Admin UI 目前是 observer；如果 UI 與 canonical spec 不一致，以 canonical spec / local state 為準。
