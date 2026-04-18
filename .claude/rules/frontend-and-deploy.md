
---
paths:
  - "frontend-v2-fix/**/*"
  - "config/project_targets.json"
  - "config/runtime_schedules.json"
  - "docs/architecture.md"
  - "docs/zeabur-safe-deploy.md"
  - "scripts/deploy-zeabur-safe.sh"
---

# Frontend / Deploy Rules

- active frontend、active Zeabur service、paper public dir、Mirror target 都以 `config/project_targets.json` 為準。
- 若目標 service / frontend 要切換，先改 config，再改程式與文件。
- `frontend-v2-fix/` 是現行線上 target；除非任務要求 redesign，否則延續既有視覺與資訊架構。
- Admin 目前是 observer，不是 canonical control plane；不要把 admin UI 當 source of truth。
- 排程頁與 control-plane 視圖應讀 canonical config / live readout，不要 reverse-parse guide 文件。
- 部署優先走安全入口與既有腳本，不要硬編碼舊 service ID 或繞開 target config。
