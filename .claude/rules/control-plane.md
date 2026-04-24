---
paths:
  - "src/volpred/ops/**/*"
  - "storage/ops/**/*"
  - "config/runtime_schedules.json"
  - "scripts/session_startup.md"
  - "docs/project_improvement_status.md"
---

# Control Plane Rules

## 核心控制面規則

- 優先順序固定：`user-assigned > scheduled > agent-discovered`
- 正式 runtime：**單一主線程 Claude Code** + **按需啟動的 Codex rescue / subagent**；不把 `claude-worker` / `codex-worker` 視為 standing worker runtime
- 排程唯一來源 `config/runtime_schedules.json`；不讓舊 guide / 歷史報告成為另類 source of truth
- `storage/ops/` 內 task / approval / execution / rollback 檔案是控制面資料，**不手動亂改收尾**
- `storage/next_tasks.json` = legacy planning / working list，**不是 canonical queue**，不可覆蓋 `storage/ops/` 狀態
- `uv run volpred ops scheduler-tick` executor lane **目前只做 advisory snapshot**；正式 task claim/finish 必須來自主線程 direct dispatch 或明確 bootstrapped session
- Session cron 與 system crontab **需與 canonical runtime schedule 一致**
- Admin UI 目前是 **observer**；UI 與 canonical spec 不一致時以 canonical spec / local state 為準

## Universal piggy-back scheduler（2026-04-20 canonical）

**macOS host cron daemon 只可靠執行 `0 * * * *` pattern**（驗證於此 machine；所有其他 pattern 含 `* * * * *`、`3 */2`、`0 8 * * 1`、`3 7 * * 2-6` 皆 silently skip）。根本解 = **check_alerts** (`0 * * * *`) 當唯一可靠 trigger，啟動 hook 呼叫 `scripts/run_due_jobs.py` 作 universal dispatcher。

### 運作要點

- Canonical schedule source: `config/runtime_schedules.json`
- Per-job last-run state: `storage/ops/cron_last_run.json`（UTC ISO timestamps）
- Timezone: host crontab 用 local time (`Asia/Taipei`)；scheduler 評估 due 用 LOCAL_TZ
- Subprocess timeout: 600s per job；sequential invocation（避免同時多 yfinance / heavy job）
- Skip list: `check_alerts`（recurse）、`shared_scheduler_tick`（advisory）、`host_crontab_managed: false`

### 工作流

1. Host cron `0 * * * *` fires `cron_check_alerts.sh`（唯一可靠）
2. `check_alerts.py` main() 啟動先呼叫 `run_due_jobs()`
3. Iterate canonical schedule，croniter 評估每 job 的 prev scheduled fire vs last_run
4. Due → subprocess-invoke wrapper，log 寫同檔案、exit code 同 semantics
5. Success 更新 last_run；**failure 不更新**（下小時再評估、避免 silent skip whole day）
6. `run_due_jobs` 尾端再呼叫 `expand_due_event_jobs`（2026-04-20 新增）— 把 `event_jobs.items` 中 `not_before ≤ now ≤ deadline` 的條目 materialize 成 control-plane task
7. `run_due_jobs` 再呼叫 `_write_pending_sessions`（2026-04-25 新增）— 掃 `session_crons.items`，把當下 due 但 session 離線未 fire 的 job 記入 `storage/ops/pending_sessions.json`；下次 session 啟動由 `scripts/session_startup.md §2.0` replay

Why 第 6 步：原設計這由 `shared_scheduler_tick` 呼叫但該項目降級 advisory 後 host 端並未真 fire（`scheduler_tick.log` 自 2026-04-19 起 size=0），缺 trigger → event_jobs populate 後永遠停 pending。Piggy-back 接管後 ~60min latency materialize。

Why 第 7 步：session cron（`CronCreate`）只在 Claude Code session alive 時 fire。macOS CronCreate 本就不可靠，session 又會被 `/exit` 或閒置關閉 → 8 條 session cron 中 spec 列 9 但實務上常只 1 條存活（2026-04-24 觀察）。Piggy-back 雖不能「代替 session 執行」（prompt 型 workflow 需主線程），但能記錄 pending，避免整個 window 靜默漏掉；下次 session 啟動的 replay 機制恢復 continuity。

### Crontab entries 保留
不刪除（harmless，永不 fire，兼 fallback）。不需 `install_host_crontab.sh` 重跑。

### Event_jobs 補充（2026-04-20）

- Populate schema 見 `src/volpred/ops/event_jobs.py::_materialize_task`（必填：`id`、`dedupe_key`、`not_before`、`deadline`、`task_template.{title,description,task_family,priority,preferred_agent,approval_mode,risk_level,public_effect,payload_patch}`）
- 單一事件 entries ≤ 3-4 篇（防 2026-04-13 TSMC 5-fold overdispatch 教訓）；透過 `payload_patch.event_series_slot` 或 priority ordering 控制 slot 衝突
- `_materialize_task` 自動抓 `deadline + 7d` 寫 `gc_after` 到 `storage/ops/event_ledger/<sha256(dedupe_key)>.json`；`gc_event_ledger` 在下次 piggy-back 清過期 ledger，不用手動
- `preview_event_jobs()` 隨時讀 pending/due/materialized 狀態，不改 state（dry-run 安全）

**事件驅動文章 populate 完整 playbook**（FOMC/CPI/NFP/Earnings template、T-series slot 配額表、ROI 優先序、Populate workflow）：見 `.claude/skills/feed-publisher/references/event-article-templates.md`（feed-publisher / publication-candidates skill 觸發時載）。

## Host crontab 維運規則（2026-04-19 確立，防反覆 TCC prompt）

- Host crontab 的 volpred 區段**只能**透過 `bash scripts/install_host_crontab.sh` 重建；**禁止**手動 `crontab -e`、`sed` in-place 改、或直接 `crontab <file>` 塞客製內容
- **命令/參數變動**：改 `config/runtime_schedules.json` 的對應 item（`cron`、`wrapper_script`、`log_path`）→ 跑 `install_host_crontab.sh`（單次 `crontab <file>` 呼叫完成）
- **邏輯變動（flags、env、pre-exec 設定）**：直接改 `scripts/cron_*.sh` wrapper；crontab entry 本身不動，**無需重跑 install**（避免觸發 macOS TCC App Management prompt）
- `scripts/cron_*.sh` 必維持最小結構：`#!/bin/bash` + `cd <repo>` + `exec <command>`；需要 env / PATH 擴展時參考 `scripts/run_scheduler_tick.sh`
- 每個新 wrapper 必 `chmod +x`；install script 檢查到 non-executable 會 fail-fast
- **FDA / macOS TCC（2026-04-19 確立）**：host-cron wrapper 實體檔案**必放** `~/.volpred/bin/cron_*.sh`，**不可**放 `Desktop/volpred-research/scripts/`。macOS TCC 擋 `cron` daemon exec Desktop/ 保護路徑內的 `.sh`（回 `Operation not permitted`），即便 cron 能 read Desktop 檔 + write Desktop log + exec `/opt/homebrew/bin/uv`
  - `scripts/cron_*.sh` 仍是 canonical source，改動後 `cp scripts/cron_*.sh ~/.volpred/bin/ && chmod +x ~/.volpred/bin/cron_*.sh` 同步
  - `config/runtime_schedules.json` 的 `wrapper_script` 欄位**必填絕對路徑**（`/Users/<u>/.volpred/bin/cron_*.sh`）；install script 偵測 `/` 前綴 bypass REPO_ROOT prefix
  - 新增/修改 wrapper 後必跑 `env -i HOME=$HOME PATH=/usr/bin:/bin ~/.volpred/bin/cron_<id>.sh` 模擬 cron env 驗證能 exec
- Install script idempotent：重跑不應產生 crontab diff；若 diff 非預期先查 config，**不為了 match 手改 crontab**
- 不想被 host crontab 管理的 item 在 config 加 `"host_crontab_managed": false`（e.g. `shared_scheduler_tick` 在 v12 已降級 advisory，不納入 host crontab）
- 非 volpred 的既有 crontab entries 由 install script 自動保留（透過 `# volpred-` 標記區隔）
