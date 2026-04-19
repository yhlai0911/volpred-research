
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

## Host crontab 維運規則（2026-04-19 確立，防反覆 TCC prompt）

- Host crontab 的 volpred 區段**只能**透過 `bash scripts/install_host_crontab.sh` 重建；禁止手動 `crontab -e`、`sed` in-place 改、或直接 `crontab <file>` 塞客製內容。
- **命令/參數變動**：改 `config/runtime_schedules.json` 的對應 item（`cron`、`wrapper_script`、`log_path`）→ 跑 `install_host_crontab.sh`（單次 `crontab <file>` 呼叫完成）。
- **邏輯變動（flags、env、pre-exec 設定）**：直接改 `scripts/cron_*.sh` wrapper；crontab entry 本身不動，**無需重跑 install**（避免觸發 macOS TCC App Management prompt）。
- `scripts/cron_*.sh` 必維持最小結構：`#!/bin/bash` + `cd <repo>` + `exec <command>`；需要 env / PATH 擴展時參考 `scripts/run_scheduler_tick.sh`。
- 每個新 wrapper 必 `chmod +x`；install script 檢查到 non-executable 會 fail-fast。
- **FDA / macOS TCC（2026-04-19 確立）**：host-cron wrapper 實體檔案**必放** `~/.volpred/bin/cron_*.sh`，不可放 `Desktop/volpred-research/scripts/`。macOS TCC 擋 `cron` daemon exec Desktop/ 保護路徑內的 `.sh`（回 `Operation not permitted`），即便 cron 能 read Desktop 檔 + write Desktop log + exec `/opt/homebrew/bin/uv`。
  - `scripts/cron_*.sh` 仍是 canonical source，改動後用 `cp scripts/cron_*.sh ~/.volpred/bin/ && chmod +x ~/.volpred/bin/cron_*.sh` 同步。
  - `config/runtime_schedules.json` 的 `wrapper_script` 欄位**必填絕對路徑**（`/Users/<u>/.volpred/bin/cron_*.sh`）；install script 會偵測 `/` 前綴並 bypass REPO_ROOT prefix。
  - 新增/修改 wrapper 後必跑一次 `env -i HOME=$HOME PATH=/usr/bin:/bin ~/.volpred/bin/cron_<id>.sh` 簡單模擬 cron env 驗證能 exec。
- Install script idempotent：重跑不應產生 crontab diff。若 diff 非預期，先查 config；不要為了 match 手改 crontab。
- 不想被 host crontab 管理的 item 在 config 加 `"host_crontab_managed": false`（e.g. `shared_scheduler_tick` 在 v12 已降級為 advisory，不納入 host crontab）。
- 非 volpred 的既有 crontab entries 由 install script 自動保留（透過 `# volpred-` 標記區隔）。
