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
- `storage/ops/` 內 task / approval / execution / rollback 檔案是控制面資料，**不手動亂改收尾**；`storage/ops/tasks/` 內 TaskRecord 是 **execution receipts / audit trail**（已完成 history），**不是 pending queue**
- `storage/next_tasks.json` = de-facto **pending queue**（2026-05-04 audit 後確認的實際分工：唯一有 pending P1-P4 的池，dispatcher `scripts/continue_task_dispatch.py` 從這挑工）— 完成的 task 同步靠 `scripts/sync_next_tasks_status.py` 反查 experiments + knowledge.json 標 succeeded；原 v12 設計把它標 legacy 但 `storage/ops/tasks/` 從未被任何 caller 用作 pending queue（全是 receipts）→ 2026-05-04 改規則承認此分工
- `uv run volpred ops scheduler-tick` executor lane **目前只做 advisory snapshot**；正式 task claim/finish 必須來自主線程 direct dispatch 或明確 bootstrapped session
- Session cron 與 system crontab **需與 canonical runtime schedule 一致**
- Admin UI 目前是 **observer**；UI 與 canonical spec 不一致時以 canonical spec / local state 為準

## Task pool 三軌：agentable / main_thread / blocked（2026-05-04 修流程）

**問題**：dispatcher 原本只分 `agentable / main_thread`，stale candidates（auth-blocked / prior-failure / self-optional）反覆被推薦、main thread 反覆 silent skip → slot 永遠空、pool 看似有工實際無工可派。

**修整**：

1. **`blocked` bucket** — `scripts/continue_task_dispatch.py::categorize` 新增第三類，filter 掉再列 candidates
2. **Hard block schema** — 任務帶 `blocked_reason` (controlled vocab) + `blocked_at` + `blocked_until` (auto-recheck) + `blocked_note`
3. **Soft block 自動偵測** — title/description 含 `(optional)` / `否則跳過` / `only if truly new` → 自動歸類 `self_tagged_optional`
4. **Hard-block CLI** — `scripts/mark_task_blocked.py --id <id> --reason <vocab> --note "..." [--until YYYY-MM-DD]`；`--unblock` 反向

**Controlled vocabulary**（`BLOCKED_REASONS`）：
- `awaiting_external_data` — 缺 auth / credentials / 原始資料（GCP, Dropbox 等）
- `compute_runtime_incompatible` — experiment runtime > background agent timeout（K1100g_d9 IS-fits hang 案例）
- `self_tagged_optional` — task 自標 optional / skippable
- `kid_collision` — K-id 重用，需改名才能派
- `prior_attempts_failed` — 反覆失敗，需主線程 debug
- `deprecated` — 被其他 task 取代 / 失去 relevance

**Skip-dispatch 必須 mark blocked**（硬規則，不可 silent skip）— 否則 candidate 永遠回到下一輪 dispatch，無限迴圈。

## Pool 永遠有工：自動 refill 機制（2026-05-04 用戶硬規則）

**用戶要求**：「任務池永遠要有待辦任務；定時繼續任務時 取出任務執行 並補進新任務」。流程責任，不靠主線程紀律。

**機制**（`continue_task_dispatch.py::_maybe_refill`）：
- 當 `agentable < REFILL_FLOOR (=4)` 時，dispatcher 自動 invoke `scripts/refill_task_pool.py` 補 `(floor - agentable)` 個新 pending tasks
- Refill source: `storage/publication_candidates.json` 的 `top_10_uncovered` + `missing_research_top5` + `missing_general_top5`（已 184+ uncovered K's，永不缺源）
- 新 task `task_type='daily_article'`、`source='auto_discovered'`、priority 由 candidate score 推導（5+→P1 / 4+→P2 / 3+→P3）
- Idempotent：dup-skip by K-id；重跑安全
- Quiet on no-add：steady-state 不 print noise

**Manual override**：`uv run python scripts/refill_task_pool.py --apply --target N` 強制補 N 個；`--dry-run` 預覽。

**對 Mission 的服務**：池永遠滿 = 連續性研究產出 = Mission #2 (research) + #1 (articles) 不間斷。Pool 空 = 系統空轉 = 違反運營承諾。

### release-task：claimed → queued 退回（2026-04-26 新增）

當 agent claim-next 拉到非預期 task（誤抓 / 優先序變動 / 派工的 agent 工具壞了），**用 `release-task` 不要用 `finish-task --status failed`**：

```
uv run volpred ops release-task <task_id> --reason "claim 誤抓 / codex CLI 過時 / pivot 中" --actor supervisor
```

- claimed | running → queued，`claimed_by*` 全清空，**priority 維持原值**
- 不寫 execution receipt（保留 receipt 純度，false-fail 不污染 audit trail）
- 走 writer log 留 audit（result=`released_from_claimed`）+ `last_error` 記原因
- 對應 P30 task `task_06584aeee667` 修整。

**何時用 `release-task` vs `finish-task --status failed`**：
- `release-task`：task brief 沒問題，但**這次** agent / 時機不對 — 留給未來重派
- `finish-task --status failed`：task brief 本身有問題或無法完成（schema 錯、missing data、constraint violation）— 真實失敗

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
