---
paths:
  - "src/volpred/ops/**/*"
  - "storage/ops/**/*"
  - "config/runtime_schedules.json"
  - "scripts/session_startup.md"
  - "docs/project_improvement_status.md"
  # 2026-07-10 加：dispatch_supervisor 是 storage/ops/dispatch_state.json 這份
  # canonical 控制面 state 的 writer。舊 paths 只涵蓋「被寫的資料」、不涵蓋「寫它的
  # 程式」，於是「審 daemon 程式碼」這整個階段本規則從不 load —— 當日連續四輪 audit
  # 都在 scripts/dispatch_supervisor/ 裡進行，控制面規則一次都沒 surface（silent
  # skip，同 2026-04-20 publish-checklist incident 的 path-trigger 時序錯誤）。
  # cron_review / check_alerts 同理：它們是這份 state 的 reader，監控 drift 就發生在此。
  - "scripts/dispatch_supervisor/**/*"
  - "scripts/cron_review.py"
  - "scripts/check_alerts.py"
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

## 控制面 audit 的完成門檻（2026-07-10，幽靈欄位 strike 3 後補）

審查任何控制面 state / 監控 / 排程時，**「我改的東西通過測試」不等於完成**。完成的門檻是
**「這個 bug class 在整個 population 上都不存在，且有機械 gate 擋住復發」**。

- **Full-population audit 是硬規則，不限實驗**。規範正文在 `.claude/rules/experiments.md`
  §「Audit methodology hard rule」（掃描範圍 / blind-spot 分析 / 可驗證 evidence 三段）——
  它寫的是「任何 ledger / dataset / output JSON」，控制面 state 完全適用。**該規則的 paths
  不含 `storage/ops/**`，過去審 ops state 時不會 auto-load**，故在此立指標。
  修完一個欄位 / 一個 reader / 一個監控前，先問：**同類還有幾個？**（2026-07-10 實例：補了
  `supervisor_pid` 就宣告幽靈欄位解決，漏掉同樣有 writer 卻未宣告的 `fire_requested_at` /
  `fire_request_reason`；隔一輪才被抓出來。子集 audit 把 false negative 留在盲區。）
- **散文不是處置**。同一 bug class 第二次出現起，交付物必須是**機械 gate**（AST / invariant
  test / CI script），不是 docstring 或 rule 裡的一段提醒。既有範例：
  `scripts/tests/test_dispatch_state.py::test_every_written_field_is_declared_in_empty_state`
  （AST 掃 `data[...]` 寫入，斷言全部宣告於 `_empty_state()`）。**新 gate 一律收編進既有
  owner，不新增第二層 watchdog**（anti-stacking）。
- **Cutover 會製造孤兒，孤兒不會自己叫**。退役一個執行路徑（LaunchAgent / wrapper / script）時，
  必須一併 grep 出**所有仍讀寫它的 reader**（監控、告警、boss report、被它獨家 wire 的工具），
  否則監控會安靜地驗證一具屍體。已發生四次：2026-07-08 `cron_review` 讀死 LaunchAgent label；
  2026-07-10 `dispatch_binary_health` grep 已退役的 `cron_hourly_dispatch.sh`；
  同日 `hourly_dispatch_pregate.py` 因只 wire 在 legacy shell 而被孤立整整六天；
  同日 `git_conflict_guard.py` 同一根因、同樣六天。
  **本條散文已於第 4 次後機械化** → `scripts/tests/test_cutover_orphans.py`（斷言 legacy wrapper
  執行的每個 `scripts/*.py` 都已被 supervisor 引用，或列入 `_RETIRED_BY_DESIGN` 附理由）。
  再退役其他執行路徑時，為該路徑推廣同型 gate；這段散文只是 pointer。
- **靜默的守門員最危險**。`git_conflict_guard` 比 pregate 更晚被發現，因為它在乾淨樹上**無輸出、
  無 side-effect log** —— 「沒在跑」與「跑了但沒事」在觀測上同形，沒有任何被動訊號。凡
  **fail-open + 乾淨時 no-op** 的防護元件，上線當下就要同步立「它是否仍被呼叫」的機械 gate。
- **「程式碼寫完」不等於「上線」—— 已由 daemon 自己收尾，不再是你的紀律**。常駐 daemon 跑的是
  開機時載入的記憶體副本，改 `scripts/dispatch_supervisor/**` 的**程式碼**必須重啟才生效
  （只有 `config/` 是每 tick 熱重載）。
  **Enforcement owner（唯一，anti-stacking 勿加第二層）**：`scripts/dispatch_supervisor/selfreload.py`
  —— health loop 每 30s 比對 `*.py` mtime 與 `supervisor_started_at`，發現自己在跑舊碼且
  **當下沒有 in-flight job** 時，寫 planned-restart marker 後 SIGTERM 自己，launchd `KeepAlive`
  用新碼把它接回來。你 commit 完就不用管了。
  手動重載仍走 `bash scripts/reload_dispatch_supervisor.sh --reason <why>`（趕時間、或要跳過
  90s quiesce 時用）；**禁止裸 `kickstart -k`**（漏寫 marker → 老闆收部署噪音 alert）。
  **為什麼要做到這一步**：這條規則 2026-07-10 寫下**當天就被違反三次**（quota no-retry /
  fire-request race / restart noise 三個修復全部寫完、commit、task 標 succeeded，daemon 卻跑了
  三小時舊碼）；當天補的 `dispatch_supervisor_stale_code` 告警**只會發信叫人去按按鈕**，於是
  2026-07-13 又漏了兩次（15:19 procutil、21:53 phase_z）—— 後者讓老闆整整 23 分鐘每 64 秒收一封
  「我們已經修好」的那個 bug 發出的警報。**跑舊碼的 daemon 與健康的 daemon 觀測上完全同形**
  （心跳新鮮、任務照跑、零告警），所以散文撐不過交接，告警也撐不過「人沒空按」。偵測器與重載器
  兩邊本來都是對的，缺的只是它們之間那條線。
- **驗證 gate 會不會咬，不可在 production checkout 上做**。「故意弄壞再看 gate 是否 FAIL」是
  必要紀律（兩邊都會過的測試等於沒有測試），但 `scripts/dispatch_supervisor/**` 正是常駐
  daemon 開機時讀取的來源。2026-07-10 我以 `perl -pi` 就地改壞 `health.py` / `state.py` /
  `worker.py` / `phase_z.py` 各數秒後還原 —— 那幾秒內若 launchd 因任何原因重啟，載入的就是
  被我故意弄壞的程式碼。**改用臨時 worktree**（`git worktree add /tmp/gate-check HEAD`）或
  temp 複本做 break-then-verify，不要在 daemon 腳下抽地毯。

## Error-log 320 sweep control-plane invariants（2026-07-06）

`docs/governance/2026-07/error_log_review_320_2026-07-06.md` reviewed the
latest 20 error-log entries and found the same control-plane failures recurring.
Treat these as standing rules:

- **Reusable entity identity needs a machine-readable source of truth.** Series,
  strategy registry state, event slots, paper status, runtime schedules, and
  other cross-session entities must be read from `config/`, registry files, or
  canonical local state. Do not infer identity from title text, K-id naming,
  old handoffs, or conversation memory when a registry/config exists or should
  exist.
- **Content/state changes must verify the canonical status field first.**
  `published_at` is not proof of `published`; stale single-report JSON is not
  canonical feed; mirror API ownership is not frontend sync ownership. Load the
  current source and exact `status` / owner field before retitle, unpublish,
  dedup, sync, or audit decisions.
- **Canonical JSON writes must be pre-serializable and recoverable.** For
  `storage/next_tasks.json`, feed, paper-trading state, queue records, and other
  control-plane files, serialize/validate the whole payload before truncate or
  replace; free-text CLI result fields must be surrogate-safe. A writer failure
  must not leave partial JSON.
- **Claim metadata is active ownership only.** `claimed_by`, `claimed_at`, and
  `claim_session_id` belong on active claimed/in-progress rows. Terminal rows,
  deprecated rows, and true blocked rows must not retain stale claim metadata.
- **Historical verification must not leave main detached.** Prefer a temporary
  worktree for historical commit checks. If the main worktree is detached for
  any reason, reattach with `git checkout main` before committing, and verify
  `HEAD == refs/heads/main` before push/commit closeout.
- **Worktree merge/remove paths fail closed.** Ambiguous "0 commits", git-log
  errors, dropped modified files, or branch/self-compare anomalies must preserve
  the worktree/branch and surface a fatal error. Never remove a worktree after a
  fallback comparison.

## Task pool 三軌：agentable / main_thread / blocked（2026-05-04 修流程）

**問題**：dispatcher 原本只分 `agentable / main_thread`，stale candidates（auth-blocked / prior-failure / self-optional）反覆被推薦、main thread 反覆 silent skip → slot 永遠空、pool 看似有工實際無工可派。

**修整**：

1. **`blocked` bucket** — `scripts/continue_task_dispatch.py::categorize` 新增第三類，filter 掉再列 candidates
2. **Hard block schema** — 任務帶 `blocked_reason` (controlled vocab) + `blocked_at` + `blocked_until` (auto-recheck) + `blocked_note`
3. **Soft block 自動偵測** — title/description 含 `(optional)` / `否則跳過` / `only if truly new` → 自動歸類 `self_tagged_optional`
4. **Hard-block CLI** — `scripts/mark_task_blocked.py --id <id> --reason <vocab> --note "..." [--until YYYY-MM-DD]`；`--unblock` 反向
5. **Main-thread handoff CLI** — `uv run python scripts/task_pool_claim.py handoff-main-thread --id <id> --note "..."`；用於已 claim 後才確認屬 `paper_body` / `paper_decision` / 其他主線程專屬任務，將 task 轉成 `pending_main_thread` 並清除 claim，禁止用 `blocked` 假裝收尾

**Controlled vocabulary**（`BLOCKED_REASONS` — single source `src/volpred/ops/blocked_reasons.py`，2026-05-27 統一）：
- `awaiting_external_data` — 缺 auth / credentials / 原始資料（GCP, Dropbox 等）
- `awaiting_interactive_session` — 需 Chrome MCP / FB auth / 其他 interactive-only session；hourly cron 無法自行完成
- `compute_runtime_incompatible` — experiment runtime > background agent timeout（K1100g_d9 IS-fits hang 案例）
- `self_tagged_optional` — task 自標 optional / skippable
- `kid_collision` — K-id 重用，需改名才能派
- `prior_attempts_failed` — 反覆失敗，需主線程 debug
- `deprecated` — 被其他 task 取代 / 失去 relevance
- `codex_quota_reset_pending` — ChatGPT-account daily quota 用完；搭配 `blocked_until` ISO 日期 auto-recheck
- `paid_data_source_decision_pending` — task 卡在 user/admin 對 paid API（Polygon/IEX 等）的採購決定
- `diversity_rule_post_null_quartet` — per CLAUDE.md ML novel-method NULL-quartet 規則暫停 novel-method experiment

**新增 vocab 唯一路徑**：改 `src/volpred/ops/blocked_reasons.py`；`mark_task_blocked.py` 與 `continue_task_dispatch.py` 自動繼承。禁止在兩處各自維護 set（2026-05-27 vocab drift 教訓）。

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
- **⚠️ 派工執行體的程式改動規則（2026-07-05 更新 — 執行體已從 shell wrapper 換成 supervisor daemon）**：hourly dispatch 自 2026-07-04 cutover 起由 `com.volpred.dispatch-supervisor`（`scripts/dispatch_supervisor/*.py` 常駐 daemon）執行；legacy `cron_hourly_dispatch.sh` 已 launchctl-disabled（留作一鍵回滾 artifact，Deliverable 8 歸檔前勿刪）。改 supervisor code 的規矩：(a) daemon 常駐，**改完必重載才生效**——一律走 `bash scripts/reload_dispatch_supervisor.sh`（2026-07-10 機械化：內建 current_job==null in-flight guard + 寫 planned-restart marker 抑制部署噪音 INFO alert + `kickstart -k`；`--force` 才覆蓋 guard）；**禁止手動裸 `kickstart -k`**（漏寫 marker → 老闆收部署噪音 alert，見 error_log 2026-07-10）；(b) in-flight guard 已由 wrapper enforce（restart 的 orphan-cleanup 會 kill in-flight worker）；(c) `scripts/cron_hourly_dispatch_prompt.md` 改動不需重載（每次 fire 重讀）。歷史脈絡（bash wrapper 邊執行邊 re-read、2026-07-02 21:07 incident）見 error_log；其他仍在用的 `cron_*.sh` wrapper 若要「fire 內改自己」仍適用舊禁令原理。
- `scripts/cron_*.sh` 必維持最小結構：`#!/bin/bash` + `cd <repo>` + `exec <command>`；需要 env / PATH 擴展時參考 `scripts/run_scheduler_tick.sh`
- 每個新 wrapper 必 `chmod +x`；install script 檢查到 non-executable 會 fail-fast
- **FDA / macOS TCC（2026-04-19 確立；2026-07-02 現況更新）**：host-cron wrapper 實體檔案**必放** `~/.volpred/bin/cron_*.sh`。原因（歷史）：repo 曾在 `~/Desktop/volpred-research`，macOS TCC 擋 `cron` daemon exec Desktop/ 保護路徑內的 `.sh`（回 `Operation not permitted`）。**2026-07-02 起 repo 已搬到 `~/volpred-research`（非 TCC 保護區），TCC 不再適用於 repo 本身**——但 wrapper 留在 `~/.volpred/bin` 的慣例**維持不變**（獨立於 repo 移動 / rename 的穩定執行點 + 與 log 同層）。舊 Desktop 路徑留有 symlink 安全網，任何殘留引用仍可解析（但在 launchd context 走 symlink 會重新經過 Desktop TCC，發現殘留引用一律改為新路徑，不依賴 symlink）
  - `scripts/cron_*.sh` 仍是 canonical source，改動後 `cp scripts/cron_*.sh ~/.volpred/bin/ && chmod +x ~/.volpred/bin/cron_*.sh` 同步
  - `config/runtime_schedules.json` 的 `wrapper_script` 欄位**必填絕對路徑**（`/Users/<u>/.volpred/bin/cron_*.sh`）；install script 偵測 `/` 前綴 bypass REPO_ROOT prefix
  - 新增/修改 wrapper 後必跑 `env -i HOME=$HOME PATH=/usr/bin:/bin ~/.volpred/bin/cron_<id>.sh` 模擬 cron env 驗證能 exec
- Install script idempotent：重跑不應產生 crontab diff；若 diff 非預期先查 config，**不為了 match 手改 crontab**
- 不想被 host crontab 管理的 item 在 config 加 `"host_crontab_managed": false`（e.g. `shared_scheduler_tick` 在 v12 已降級 advisory，不納入 host crontab）
- 非 volpred 的既有 crontab entries 由 install script 自動保留（透過 `# volpred-` 標記區隔）
