# Project Improvement Status

Last updated: 2026-04-18

## VolPred 雙 Agent 最終優化方案 v11

### Summary

- 本方案只在**目前 `volpred-research` 專案基礎上增量調整**，不重做網站、不替換 `storage/` / `ops` / `frontend-v2-fix/` / Supabase / Mirror / Admin 主架構。
- 優先序正式鎖定為：**正確性 > 穩定性 > token 效率 > 吞吐量**。
- 運作模式鎖定為：**Claude Code = 協調者 / 規則主導者 / brief builder；Claude 與 Codex = 執行者；control plane = 唯一狀態來源。** repo 目前仍保留 `shared scheduler` 這條 `cron-driven` 過渡路徑，但校正後的目標 runtime 是 VS Code supervisor / worker sessions。
- `2026-04-18` 依 user story 校正後，**正式操作故事應是 VS Code 三終端機模式**：1 個 Claude supervisor 管理排程 / brief / 狀態，1 個 Claude worker + 1 個 Codex worker 在已登入 OAuth 的互動 session 內認領並完成任務。
- shared scheduler 跑在 **macOS `crontab`**；Claude 既有 session cron **退役為非執行時鐘**，只保留提醒與 monitor；`idle_policy` 僅作為 slot-aware continuation / selection policy，不是另一個主時鐘。
- shared scheduler 對 live manual agent session 採保守策略：若偵測到非 scheduler 擁有的 Claude/Codex session 仍在線，則不會搶同一個 agent。
- 目前 repo 仍殘留 `scheduler -> subprocess.run(["claude", "-p", ...]) / subprocess.run(["codex", "exec", ...])` 的 headless 路徑；這是**偏離 user story 的過渡期實作**，不應視為最終 runtime contract。
- Claude 與 Codex **都可以提出 cron / schedule 需求**，但只有 **Claude coordinator** 可以把需求落成正式 canonical schedule、調整排程策略、安裝或移除 cron。
- 每輪任務都必須符合 **codebase grounding contract**：在 repo root 啟動、先讀必要背景、用結構化 brief 控制上下文；拿不到足夠背景就 fail closed。
- 一次性任務與事件前後任務正式納入 canonical schedule，新增 `event_jobs`；不再只靠 prompt 或自由文字文件記憶。
- **Brief 生成策略固定為 `C`：模板優先，Claude 協調輪只處理例外。**
- brief 模板固定放在 **`config/brief_templates/<task_family>.yaml`**。
- Claude coordinator 的 JSON brief 固定採 **pydantic 驗證 + fenced JSON 抽取 + 最多 2 次重試**；第 3 次失敗即標記 `brief_status=needs_manual_review`。
- brief 過期規則固定為：**`task.updated_at > brief_payload.generated_at` 或 template hash 改變**。
- scheduler cron 安裝與移除腳本化處理：**`scripts/install_scheduler_cron.sh`**、**`scripts/uninstall_scheduler_cron.sh`**。
- v1 **不做 task dependency graph**；事件鏈先靠 `not_before/deadline` + preconditions + fail-closed preflight 控制。
- **存檔目標**鎖定為 `docs/project_improvement_status.md`；本檔即為最終規格版本。

### Implementation Status

- 已完成：
  - Phase 6 provider skills render 修正
  - Phase 3 最小 schema 擴充
  - Phase 1 session lifecycle wrappers
  - Phase 2 auto routing
  - Phase 4 `experiment_id` 並發防撞
  - Phase 5 `agent-spec sync` alias
  - Phase 5b `event_jobs` / event ledger / preview / GC
  - Phase 7a shared scheduler tick、self-lock、scheduler state、cron wrapper scripts
  - Phase 7b execution brief、template-first policy、prior findings、fail-closed preflight
  - Phase 7c 基礎 observability：CLI、health snapshot、control-plane summary、admin ops/health 指標
  - scheduler 與 live manual Claude/Codex session 共存護欄：目標 agent 已被真人 session 佔用時，tick 會跳過並回報 `no_runnable_work`
  - `preconditions` 已落地為實際派工護欄：scheduler 會跳過未滿足前置條件的 task，executor preflight 也會把手動 claim 的 task 重新排回 queue
  - schedule governance contract 已落地：`payload.governance_area=schedule` / `payload.schedule_proposal` 會被系統辨識，並強制收斂到 Claude 作為治理 owner
  - schedule proposal 任務已有專用 brief template，`/admin/ops` 也能直接看到 `governance schedule` badge
  - `uv run volpred ops propose-schedule ...` 已提供正式 CLI 提案入口，Claude/Codex 都可用同一個 contract 建立 schedule proposal task
  - `/admin/ops` 建立本機 task 表單已補齊 `member` / `strategy` family、`public_effect` 欄位與「Schedule Proposal 範本」快捷按鈕
  - `storage/next_tasks.json` 的定位已正式收斂為 **legacy planning / working list**；canonical orchestration 仍以 `storage/ops/` control plane、`config/runtime_schedules.json`、`event_jobs` / `event_ledger` 為準
  - session worker flow 已補強：`next-task --emit-brief` 現在只會返回可執行 task，會跳過尚未被 supervisor brief 化或 preconditions 未滿足的 queued task
  - supervisor 已可用 `uv run volpred ops brief-show` / `brief-set` 正式查看與寫入 manual brief，不必手改 `storage/ops/tasks/*.json`
  - canonical `system_crontab` spec 已補上 `shared_scheduler_tick`，並把既有 `market_calendar sync` 納回 canonical，避免 install script、live crontab 與 `/admin/schedules` 的 source of truth 分裂
  - shared scheduler 已實際安裝進本機 `crontab`，目前 canonical system tasks 與 live crontab 對齊（`schedule-report` = `6/6` matched）
  - `/admin/schedules` 的心智模型已更新：shared scheduler / system crontab 為正式時鐘，session cron 僅保留為 legacy session convenience
  - coordinator / executor subprocess 已補 timeout fail-closed 護欄，避免 `claude -p` / `codex exec` 卡住時長時間占住 scheduler self-lock
  - 已新增 `uv run volpred ops scheduler-smoke` 隔離 smoke helper：自備最小 prompt / brief template，mock 掉真實 `claude -p` / `codex exec`，可在不碰 live queue 的前提下驗證 coordinator 與 executor 鏈路
  - 已新增 `uv run volpred ops scheduler-live-smoke`：用隔離 storage 真正呼叫本機 Claude/Codex CLI 做最終 smoke；Claude 走 no-persistence + no-tools，Codex 走 read-only sandbox + ephemeral，避免碰 live queue 與 repo 內容
  - 已補 execution brief CLI 相容性修正：Claude `-p --output-format json` result envelope / 純文字錯誤可正確解包；Codex output schema 已符合新版 `additionalProperties=false` 與 full required set 規則
  - 已新增 agent CLI readiness snapshot：`scheduler-live-smoke` 會把 Claude/Codex live path 分類成 `ready / auth_required / free_text_response / schema_mismatch / timeout` 等狀態，寫入 `storage/ops/agent_cli_health.json`，`ops health` / `/admin/health` 可直接觀察
- 已驗證：
  - `uv run pytest tests/test_shared_lock.py tests/test_execution_brief.py tests/test_scheduler.py tests/test_agent_spec.py tests/test_local_control_plane.py tests/test_stale_reclaim.py tests/test_session_ops.py tests/test_event_jobs.py tests/test_runtime_schedules.py`
  - `uv run python -m volpred.cli ops scheduler-preview`
  - `uv run python -m volpred.cli ops event-preview`
  - `uv run python -m volpred.cli ops scheduler-tick`
  - `uv run python -m volpred.cli ops control-plane-summary`
  - `uv run python -m volpred.cli ops health`
  - `uv run python -m volpred.cli ops schedule-report`
  - `bash scripts/install_scheduler_cron.sh`
  - `bash scripts/run_scheduler_tick.sh`
  - `cd frontend-v2-fix && npm run typecheck`
  - `uv run pytest tests/test_execution_brief.py tests/test_scheduler.py`
  - `uv run python -m volpred.cli ops agent-spec check --target all`
  - `uv run python -m volpred.cli ops propose-schedule --title ... --description ... --proposal-json ... --storage-dir /tmp/...`
  - `uv run python -m volpred.cli ops task-show <task_id> --storage-dir /tmp/...`
  - `uv run python -m volpred.cli ops scheduler-smoke --mode both --cleanup`
  - `uv run python -m volpred.cli ops scheduler-live-smoke --mode all --cleanup`
  - `2026-04-18` live smoke 實測：Codex executor path 已通過（read-only sandbox、`files_touched=[]`）；Claude coordinator / executor 目前仍會輸出自由文字而非 schema-valid JSON，因此 helper 已能穩定暴露這個剩餘 gap
  - `cd frontend-v2-fix && npm run typecheck`
- 尚未執行：
  - 將正式執行路徑從 headless scheduler subprocess 收斂回 VS Code supervisor / worker session 模式，並退役或降級 `claude -p` / `codex exec` 直跑 task 的舊路徑
  - Claude live structured-output compatibility remediation（`scheduler-live-smoke` 已確認 gap，可作為後續修正入口）
  - 最終 commit / deploy

### User Stories

- 作為專案 owner，我希望打開 VS Code 後能建立 3 個終端機：1 個 Claude supervisor、1 個 Claude worker、1 個 Codex worker；全部都用 OAuth 訂閱登入的互動 session，而不是背景另外開 headless process。
- 作為專案 owner，我希望平台能在**不犧牲正確性與穩定性**的前提下持續推進任務，而不是為了並行而增加錯誤與重工。
- 作為專案 owner，我希望 **Claude 負責協調與規則判斷**，而 Claude 或 Codex 都可以根據任務類型成為執行者。
- 作為專案 owner，我希望每輪任務都能讀到**剛好夠用的 codebase 背景**，而不是每次都重掃整個 repo 浪費 token。
- 作為專案 owner，我希望 recurring 任務、一次性任務、事件前後任務都能由同一套 canonical schedule 管理，不再分散在 session cron、prompt 與活文件裡。
- 作為專案 owner，我希望 Codex 持續參與系統，但主要聚焦在 **code/review/ops/bug rescue**，而不是一開始就和 Claude 完全對等搶任務。
- 作為專案 owner，我希望所有 mutating 任務都能追溯到 session、rollback point、brief、execution receipt，失敗時可以完整恢復。
- 作為專案 owner，我希望導入新 orchestration 後，網站上的文章、策略績效、會員問答、工具頁仍照常運作。
- 作為專案 owner，我希望從 `/admin/ops`、`/admin/health`、CLI 看到 scheduler、event materialization、agent session、approval、rollback、brief 狀態的實際情況。
- 作為 Claude 協調者，我希望能用最少 token 先把任務變成低歧義、可執行、可驗證的 brief，再決定交給 Claude 或 Codex。
- 作為 Claude supervisor，我希望能在互動 session 中查看 task、補 manual brief、調整 queue，然後由 worker terminals 去 claim 與完成任務。
- 作為 Codex 執行者，我希望接到的是已經定義好目標、必讀檔案、成功標準、禁止整檔讀取清單的任務，而不是模糊探索題。
- 作為平台維運者，我希望 scheduler 空轉時幾乎不耗 token，只有真的有可做任務時才喚起 LLM。
- 作為事件任務管理者，我希望 CPI / NFP / FOMC / TSMC 財報前後任務能被正式展開、去重、觀測，而不是靠記憶與臨場判斷。

### Key Scenarios

#### 1. 每日自動運作

- `crontab` 定時執行 `scripts/run_scheduler_tick.sh`。
- wrapper 腳本負責切到 repo root、載入 `.env.local`、補 PATH、執行 `uv run volpred ops scheduler-tick`。
- `scheduler-tick` 一開始先取 **`shared_state_lock("scheduler_tick")` 非阻塞鎖**；拿不到就直接退出 0，代表上一輪還在跑。
- 若目標 agent 已被 live manual session 佔用，該輪視為 `no_runnable_work`，不強行覆蓋 agent session。
- 若 task 的 `preconditions` 尚未成立，該輪也視為不可執行，不會進入 coordinator/executor。
- scheduler 再做 queue、stale reclaim、event expander、approval backlog、slot 檢查。
- 沒有可做任務就直接退出；有任務才喚起 Claude 或 Codex。

#### 2. recurring 任務

- 例子：平台巡檢、會員問題、知識索引檢查、token 日報。
- scheduler 依 recurring 規則找到 task family，直接載入 `config/brief_templates/<task_family>.yaml`。
- 模板足夠時不跑 Claude 協調輪。
- 模板 preflight 不成立時直接 fail-closed，不用 LLM 補猜。

#### 3. 一次性任務

- `event_jobs.trigger_mode=one_shot` 定義只跑一次的任務。
- scheduler 到時間後 materialize 成正式 task。
- `dedupe_key` 保證同一任務只建立一次。
- materialize 同時寫入 event ledger，避免下一輪 tick 重建。

#### 4. 事件前後任務

- 例子：CPI / NFP / FOMC / TSMC 財報前後的資料抓取、分析、文章、會員問答。
- `event_jobs.trigger_mode=relative_to_event` 用 `not_before` / `deadline` 控制窗口。
- `event_key` 固定為 `{type}_{yyyymmdd}_{variant?}`。
- `dedupe_key` 固定為 `{event_key}:{task_family}`。
- v1 不做 `depends_on_task_ids`；改用時間窗錯開與 preconditions 檢查產物是否存在。

#### 5. 模糊或跨領域任務

- 模板不足、brief 缺失、brief 過期、事件複雜、跨模組、研究 discovery、高風險任務，先喚起 Claude 協調輪。
- 協調輪輸出 schema-valid JSON brief。
- 若重試 2 次仍不合法，task 轉 `brief_status=needs_manual_review` 與 `status=blocked`。

#### 6. Code Review / Bug Rescue

- 若任務明確屬於 code/review/ops，且 brief 已就緒，直接派給 Codex。
- 若背景不清楚、跨多模組、或 risk 高，先由 Claude 補 brief，再交 Codex。
- Codex 不需要重掃整個 repo，只讀 `required_files` 與少量 `recommended_files`。

#### 7. 任務中斷與恢復

- 某個 agent session 中斷或超過 stale threshold。
- 後續 tick 執行 stale reclaim，把 task 釋回 queue。
- scheduler 下一輪重新分派，不讓任務永久卡死。

#### 8. 高風險公開行為

- 正式發文、會員可見回答、策略 runtime 變更等高影響任務進入 approval gate。
- 先建立 rollback、生成 brief、跑 preflight、等 approval。
- 通過後才對外落地。

### Final Architecture

#### Scheduler

- 唯一 clock，透過 `crontab` 執行 `scripts/run_scheduler_tick.sh`。
- 僅負責機械節奏、event expander、cheap preflight、派工判斷。
- `scheduler-tick` 使用專用 self-lock，避免雙 tick 併發。
- scheduler 是 **中立執行層**，不是 Claude/Codex 任一方私有的時鐘；但排程治理權歸 Claude coordinator。

#### Coordinator

- 預設由 Claude fresh-context 執行。
- 僅在模板不足、brief 缺失/過期、事件複雜、任務模糊或高風險時啟動。
- 輸出必須是**可驗證的 JSON brief**。
- Claude 也是 **schedule governance owner**：
  - 接收 Claude/Codex 提出的 cron 需求
  - 決定是否納入 `config/runtime_schedules.json`
  - 決定 `event_jobs` / recurring 規則 / cadence 調整
  - 決定是否執行 `install_scheduler_cron.sh` / `uninstall_scheduler_cron.sh`

#### Executors

- Claude：研究、內容、會員、模糊或高判斷任務。
- Codex：code、review、ops、bug rescue、明確結構化任務。
- Codex 不做開放式 discovery，只接已 brief 化任務。
- 因此「排程由 Claude 治理」**不等於**「所有 cron-triggered 任務都只能由 Claude 實作」；若任務 brief 清楚，仍可由 Codex 作為 executor。

#### Control Plane

- 任務、session、approval、rollback、execution receipt 的唯一協調層。
- scheduler、Claude、Codex 都只能透過 ops layer 改共享狀態。

#### Grounding

- brief 是 worker 的正式執行入口。
- executor 必須先讀 `required_files`。
- `forbidden_large_files` 是 prompt 級禁止整檔讀取清單。
- 必要背景不足時不得硬做。

### Public Interfaces / Data Contracts

#### New CLI

- `uv run volpred ops session-bootstrap --agent claude|codex`
- `uv run volpred ops next-task --agent claude|codex [--emit-brief]`
- `uv run volpred ops finish-task --agent claude|codex --task-id ...`
- `uv run volpred ops session-shutdown --agent claude|codex`
- `uv run volpred ops brief-show <task_id>`
- `uv run volpred ops brief-set <task_id> --brief-json ... --actor ...`
- `uv run volpred ops requeue-task --task-id ... --actor ... --reason ...`
- `uv run volpred ops agent-spec sync --from claude|codex`
- `uv run volpred ops scheduler-tick`
- `uv run volpred ops scheduler-preview`
- `uv run volpred ops scheduler-smoke [--mode coordinator|executor|both] [--cleanup]`
- `uv run volpred ops scheduler-live-smoke [--mode coordinator|claude-executor|codex-executor|all] [--cleanup]`
- `uv run volpred ops event-preview`

#### New Scripts

- `scripts/run_scheduler_tick.sh`
- `scripts/install_scheduler_cron.sh`
- `scripts/uninstall_scheduler_cron.sh`

#### New Config / Template Paths

- `config/runtime_schedules.json`
  - 新增 optional section：`event_jobs`
- `config/brief_templates/<task_family>.yaml`
- `config/agent_prompts/claude_coordinator.txt`
- `config/agent_prompts/claude_executor.txt`
- `config/agent_prompts/codex_executor.txt`

#### TaskRecord 新欄位

- `session_id: Optional[str]`
- `rollback_point_id: Optional[str]`
- `public_effect: Optional[str]`
- `brief_status: Optional[str]`
- `brief_payload: Optional[dict]`

#### AgentSession 新欄位

- `session_rollback_point_id: Optional[str]`

#### ExecutionReceipt 新欄位

- `session_id: Optional[str]`
- `rollback_point_id: Optional[str]`

#### `brief_status` 列舉

- `pending`
- `ready`
- `stale`
- `needs_manual_review`

#### `brief_payload` 固定欄位

- `generated_at`
- `source_type`: `template | coordinator`
- `template_id`
- `template_hash`
- `coordinator_run_id`
- `task_summary`
- `goal`
- `success_criteria`
- `repo_root`
- `required_files`
- `recommended_files`
- `forbidden_large_files`
- `relevant_commands`
- `prior_findings`
- `rollback_point_id`
- `why_this_agent`

#### `event_jobs` 固定欄位

- `id`
- `event_key`
- `trigger_mode`: `one_shot | relative_to_event`
- `not_before`
- `deadline`
- `dedupe_key`
- `preferred_agent`
- `public_effect`
- `task_template`

#### `task_template` 固定欄位

- `title`
- `description`
- `task_family`
- `priority`
- `preferred_agent`
- `approval_mode`
- `risk_level`
- `payload_patch`
- `brief_template`
- `preconditions`

#### Event Ledger

- materialize 後必寫到 `storage/ops/event_ledger/`
- 為避免 path 字元問題，檔名用 `sha256(dedupe_key).json`
- ledger 內容至少包含：
  - `dedupe_key`
  - `event_key`
  - `task_family`
  - `task_id`
  - `materialized_at`
  - `deadline`
  - `gc_after`
- `gc_after` 固定為 `deadline + 7 days`
- expander 以 ledger 作為是否已 materialize 的唯一判斷來源
- scheduler 每次 tick 只做便宜 GC；刪除已過 `gc_after` 的 ledger

#### Compatibility Rules

- 所有新欄位都必須向後相容：`Optional[...] = None`
- 所有舊 JSON 讀取時一律 `.get(...)`
- 不做 migration
- `payload` 本 phase 只認 `payload["experiment_id"]` 單數字串

### Brief Generation Policy

- 策略固定為：**模板優先，Claude 協調輪只處理例外**
- recurring、明確、低歧義 task family：使用 `config/brief_templates/<task_family>.yaml`
- schedule governance 任務：優先使用 `config/brief_templates/schedule-governance.yaml`，且 scheduler 先走 Claude 協調輪
- 事件任務：先試事件模板；模板不足才跑 Claude 協調輪
- 研究 discovery、跨模組、模糊或高風險任務：跑 Claude 協調輪
- JSON 保證機制：
  - 抽取 fenced JSON 或第一個合法 JSON object
  - 用 pydantic schema 驗證
  - 最多重試 2 次
  - 第 3 次失敗：`brief_status=needs_manual_review`
- brief 過期規則：
  - `task.updated_at > brief_payload.generated_at`
  - 或 `brief_payload.template_hash != current_template_hash`
  - 任一成立即把 `brief_status` 轉為 `stale`
- `prior_findings` 自動填入規則：
  - `--emit-brief` 時自動讀取該 `task_id` 最近 3 筆 `ExecutionReceipt`
  - 收集非空 `summary` 與關鍵 `error`
  - 組成 `prior_findings` list
  - coordinator 如有更精確內容，可覆蓋或追加
- executor prompt 預設採**self-contained 模式**
  - 即使 `claude -p` 會載入 skills，也不把 auto-loaded skills 當正確性前提
  - Phase 0 會 smoke test `claude -p` 的 skills 可用性，但 Phase 7b 的執行面仍以 self-contained brief 為準
  - skill 名稱可作為提示，不作必要依賴

### Cron Governance Policy

- Claude 與 Codex 都可以提出：
  - 新 recurring 任務需求
  - 新 `event_jobs` 需求
  - cadence / interval 調整建議
  - 停用、延後、加嚴 preconditions 的建議
- 但正式落地只走 Claude coordinator：
  - 修改 `config/runtime_schedules.json`
  - 修改 `scripts/run_scheduler_tick.sh`
  - 執行 `scripts/install_scheduler_cron.sh`
  - 執行 `scripts/uninstall_scheduler_cron.sh`
  - 調整 shared scheduler 的 routing / policy
- Codex 不直接擁有 cron 安裝權，也不直接成為 canonical schedule 的最終作者。
- 若 Codex 發現需要排程變更，應產出：
  - task / brief / code review finding / schedule proposal
  - 再由 Claude coordinator 審核後納入 canonical
- schedule proposal 的 payload contract：
  - `governance_area: "schedule"`
  - `schedule_proposal: {...}`
- 一旦符合上述 contract，即使建立 task 的人是 Codex，control plane 也會把正式治理任務收斂到 Claude
- v1 的保守預設：
  - schedule discovery 可以來自兩邊
  - schedule governance 只由 Claude
  - schedule-triggered 任務若模板足夠，可直接派給 Codex executor
  - 但任何 schedule 規則變動仍需 Claude 寫回 canonical

### Fail-Closed Policy

#### Global Tick Failure

- `scheduler-tick` 在 claim 前若發現 repo root 錯誤、runtime config 無法讀取、scheduler self-lock 未取得：
  - 直接退出
  - 不變更任何 task 狀態
  - 寫 scheduler log

#### Task-Scoped Preflight Failure

- repo root mismatch / agent-spec drift / skills render 壞：
  - task 轉 `blocked`
  - `last_error` 記錄原因
  - 清掉 claim
  - 寫 execution receipt，`result_status=blocked_preflight`
- brief missing / stale：
  - `brief_status=stale`
  - 若 task 已被 claim，釋放 claim 並回 `queued`
  - 下輪 scheduler 重新生成 brief
- `required_files` 不存在：
  - task 轉 `failed`
  - `last_error` 記錄缺檔
  - 清掉 claim
- coordinator 3 次 retry 全失敗：
  - `brief_status=needs_manual_review`
  - task 轉 `blocked`
  - 清掉 claim
- `blocked` 不是 terminal，但 scheduler 不會自動重跑 blocked task
- blocked task 修復後，需透過 `ops requeue-task` 明確回到 `queued`

### Event Layer Policy

- `event_key` 固定格式：`{type}_{yyyymmdd}_{variant?}`
- `dedupe_key` 固定格式：`{event_key}:{task_family}`
- v1 不做 `depends_on_task_ids`
- 替代方案：
  - 事件任務用 `not_before/deadline` 錯開
  - `task_template.preconditions` 檢查必要檔案 / 產物 / 狀態
  - preconditions 不成立時不派工或 fail-closed
- 若未來實務上真的出現 race，再升級到 dependency graph

### Implementation Plan

#### Phase 0: Baseline 與回滾起點

- 建立 named rollback baseline
- 記錄：
  - `uv run volpred ops agent-spec check --target all`
  - `uv run volpred ops control-plane-summary`
  - `uv run volpred ops health`
  - Claude/Codex CLI skills warnings
  - `claude -p "list skills you have access to in this repo"` smoke 結果
- 每 phase 結束固定執行：
  - `pytest`
  - `uv run volpred ops agent-spec check --target all`
  - `uv run volpred ops health`
  - git commit

#### Phase 6: Provider Skills Render 修正

- 修 `src/volpred/ops/agent_spec.py` 的 header 注入點
- 所有 provider-rendered `SKILL.md` 第一行都必須是 `---`
- `.claude/skills/**` 與 `.agents/skills/**` 一起修
- provider-visible `skill.md` 一律 render 成 `SKILL.md`
- 驗證時本機同時檢查 `.claude/skills/**` 與 `.agents/skills/**` 第一行
- 注意 `.agents/skills/**` 為本機 render 產物，PR 主要只會看到 `.claude/` diff

#### Phase 3: 最小 Schema 擴充

- `TaskRecord` 增加 `session_id`, `rollback_point_id`, `public_effect`, `brief_status`, `brief_payload`
- `AgentSession` 增加 `session_rollback_point_id`
- `ExecutionReceipt` 增加 `session_id`, `rollback_point_id`
- `public_effect` 固定枚舉：
  - `none`
  - `draft_only`
  - `published`
  - `member_visible`
  - `prod_runtime`

#### Phase 1: Session Lifecycle Wrappers

- `session-bootstrap`
  - 驗證 `VOLPRED_ACTOR == args.agent`
  - 建立 session rollback point
  - 執行 `agent-spec check`
  - 寫入 heartbeat / session metadata
- `next-task`
  - heartbeat
  - claim-next
  - 繼承 `session_id` / `session_rollback_point_id`
  - 需要時輸出 execution brief
- `finish-task`
  - 成功與失敗都寫 execution receipt
- `session-shutdown`
  - 標 offline，必要時釋放 claim
- `requeue-task`
  - 僅允許 `blocked` task 回到 `queued`
  - 記錄 actor 與 reason

#### Phase 2: Auto Routing

- 保留現有 `task_family`
- `preferred_agent=auto` 時映射：
  - `research/content/member -> claude`
  - `code/review/ops/strategy -> codex`
- scheduler 先看 `brief_status`
  - 未 brief / stale / 模糊 / 事件任務：先交 Claude 協調
  - 已 brief 且 `preferred_agent=codex`：可直接交 Codex

#### Phase 4: `experiment_id` 並發防撞

- claim 流程新增 guard：
  - 若 queued task 的 `payload.experiment_id` 已被另一個非 terminal task 佔用，則本輪跳過

#### Phase 5: `agent-spec sync` Alias 正式化

- 新增 `ops agent-spec sync --from claude|codex`
- 內部等價於：
  - `import --from <provider>`
  - `render --target all`
  - `check --target all`

#### Phase 5b: Event Layer

- 在 `config/runtime_schedules.json` 增加 `event_jobs`
- 新增 event expander
  - 讀 `event_jobs`
  - 判斷 `not_before` / `deadline`
  - 用 `dedupe_key` 與 ledger 防重複 materialize
  - 依 `task_template` 建立 control-plane tasks
- 新增 `storage/ops/event_ledger/`
- scheduler 每 tick 執行 event ledger 輕量 GC
- `research_program.md` 保留事件敘事，但不再作為 scheduler 唯一事件來源

#### Phase 7a: Shared Scheduler Tick

- 新增 `src/volpred/ops/scheduler.py`
- `scheduler-tick`
  - 非阻塞取得 `shared_state_lock("scheduler_tick")`
  - 讀 `runtime_schedules.json`
  - stale reclaim
  - event expander
  - cheap preflight：queue / approvals / discovery / slots
  - 無可做任務時直接退出
  - 有任務時決定本輪走 coordinator 或 executor
- `scheduler-preview`
  - 回報本輪會做什麼，不執行
- scheduler 部署層固定為 **macOS `crontab`**
- system crontab 既有永久任務保留，只新增 orchestration tick
- scheduler 自身 logging 改用 `RotatingFileHandler(10MB, backupCount=5)`

#### Phase 7b: Execution Brief 與 Grounding Contract

- 新增 `src/volpred/ops/execution_brief.py`
- recurring task family 先查 `config/brief_templates/`
- 例外 task 再跑 Claude coordinator
- `forbidden_large_files` 在 executor prompt 中轉成 `DO NOT read these files in full`
- `required_files` 必須足以完成任務；若不足則回 `needs_manual_review`
- 大檔沿用既有 token discipline，禁止整檔讀

#### Phase 7c: Observability 與 Cron 退役整理

- `/admin/ops` 與 `/admin/health` 增加：
  - active agents
  - approval backlog
  - latest rollback point
  - recent execution receipts
  - agent-spec drift
  - scheduler heartbeat / last tick
  - event materialization 狀態
  - brief_status 分布
- Claude session cron 退役為非執行時鐘
- `scripts/setup_session_crons.sh` 與 `scripts/session_startup.md` 改寫為：
  - shared scheduler 是正式時鐘
  - session cron 只剩 monitor / 提醒
- 新增：
  - `scripts/install_scheduler_cron.sh`
  - `scripts/uninstall_scheduler_cron.sh`
- cron 安裝必須 idempotent，可重跑、不重複插入
- install script 用固定 tag comment，例如 `# volpred-scheduler-tick`
- uninstall script 依 tag comment 清除

### Runtime Behavior After Completion

- `crontab` 定時執行 `scripts/run_scheduler_tick.sh`
- `run_scheduler_tick.sh` 固定內容：
  - `cd /Users/yhlai0911/Desktop/volpred-research`
  - `set -a; source .env.local 2>/dev/null || true; set +a`
  - `export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"`
  - `exec uv run volpred ops scheduler-tick`
- 正式派工由 `crontab -> shared scheduler tick` 驅動；`idle_policy` 只決定 slot 空出時如何挑 user / scheduled / discovery 任務，不是獨立自動觸發器
- 建議 cron line：
  - `*/10 * * * * /Users/yhlai0911/Desktop/volpred-research/scripts/run_scheduler_tick.sh # volpred-scheduler-tick`
- scheduler 先做便宜檢查與 event 展開
- recurring/固定模式任務先查模板；模板足夠就直接派工
- 模糊、事件複雜、研究 discovery 任務才喚起 Claude 協調輪生成 brief
- Claude 是協調者，不是每輪都必經的人肉轉接站
- Codex 主要處理被明確 brief 化的任務
- 系統在**機器開著且 `crontab` 生效**時可穩定持續推進；睡眠期間 tick 會跳過，醒來後從下一輪恢復

### Delivery Plan

#### Work Session 1（約 4 小時）

- Phase 0 / 6 / 3 / 1 / 2
- 目標：skills render 修正、schema optional fields、session wrappers、auto routing 都可用
- 結束標準：turn-based 雙 session 流程已穩，無 scheduler 也能手動跑完一輪

#### Work Session 2（約 4 小時）

- Phase 4 / 5 / 5b
- 目標：experiment guard、agent-spec sync alias、event layer 上線
- 結束標準：once-only / event-relative 任務可 materialize 成 control-plane tasks

#### Work Session 3（約 10 小時）

- Phase 7a / 7b / 7c
- 目標：shared scheduler、brief system、grounding enforcement、observability、session cron 退役整理
- 結束標準：shared scheduler 可持續推進 Claude/Codex 工作，且不依賴舊 session cron

### Test Plan

- 結構測試
  - `.claude/skills/**/SKILL.md` 與 `.agents/skills/**/SKILL.md` 第一行都是 `---`
  - render outputs 不再出現小寫 `skill.md`
- Schema 相容測試
  - 舊 task / agent / execution JSON 沒有新欄位時仍能讀取
- Session 測試
  - `VOLPRED_ACTOR` 不符時 `session-bootstrap` fail fast
  - 同一 session 多個 mutating task 預設繼承同一 rollback point
- Routing 測試
  - `preferred_agent=auto` 依 `task_family` 正確分派
  - `brief_status` 未完成時不直接把模糊任務丟給 Codex
- Event 測試
  - one-shot 任務只 materialize 一次
  - relative-to-event 任務在 `not_before` 前不展開、超過 `deadline` 不再展開
  - `dedupe_key` 可防雙重建立
  - event ledger 會正確寫入與 GC
- Scheduler 測試
  - queue 空時不呼叫 LLM
  - `scheduler-preview` 能準確顯示本輪決策
  - cron wrapper 能正確載入 repo root、env、PATH
  - self-lock 能避免雙 tick 併發
- Brief 測試
  - 模板任務不需要跑 Claude 協調輪
  - 例外任務會得到 schema-valid 的 Claude JSON brief
  - `forbidden_large_files` 真的進入 executor prompt
  - `task.updated_at > brief_payload.generated_at` 時 brief 轉 stale
  - 模板 hash 改變時 brief 轉 stale
  - coordinator 最多重試 2 次，第 3 次轉 `needs_manual_review`
  - `prior_findings` 會自動帶入最近 3 筆 receipt 摘要
- Fail-Closed 測試
  - preflight fail 會轉 `blocked`
  - brief stale 會釋放 claim 並回 `queued`
  - 缺檔會轉 `failed`
  - blocked task 可由 `requeue-task` 回復
- Grounding 測試
  - repo root 錯誤、brief 缺失、必要檔缺失、agent-spec drift 時必須拒絕執行
  - brief 的 `required_files` 足以完成任務，且不要求 broad scan
- 回歸測試
  - `pytest`
  - `uv run volpred ops agent-spec check --target all`
  - `uv run volpred ops health`
  - `daily_update`
  - `recalc_metrics`
  - `release-pool-by-settings`
  - `question-ranking-workflow`
  - 前端 regression verifier

### Assumptions / Defaults

- 優先目標是**正確、穩定、token 效率**，不是最大吞吐量
- v1 架構採 **Claude 協調、Claude/Codex 執行**，不採雙主並行自治
- shared scheduler 層固定選 **macOS `crontab`**
- 目前系統是 **`cron-driven shared scheduler + slot-aware idle policy`**，不是純 idle-driven runtime
- Claude session cron 正式退役為非執行時鐘
- Brief 生成策略固定為 **模板優先，Claude 協調輪只處理例外**
- brief 模板固定放在 **`config/brief_templates/*.yaml`**
- Claude coordinator JSON 驗證固定採 **pydantic + fenced JSON 抽取 + 最多 2 次重試**
- brief 過期規則固定為 **`task.updated_at > brief_payload.generated_at` 或 template hash 改變**
- 所有新欄位 optional，讀取用 `.get(...)`，不做 migration
- `rollback_point_id` 預設由 session rollback 繼承，只有高價值或 destructive task 才另建
- `config/runtime_schedules.json` 繼續是唯一排程母本，並新增 `event_jobs`
- v1 **不做 task dependency graph**；事件鏈依賴先靠時間窗與 preconditions
- `claude -p` 是否自動載入 skills 會在 Phase 0 smoke 測試，但執行面不依賴它作為正確性前提
- 正式落檔目標是 `docs/project_improvement_status.md`
- 技術前提仍對齊最新官方能力：Claude 有 hooks / IDE integration；Codex CLI/IDE 目前無官方明確等價的 session cron，因此持續運作依賴 shared scheduler  
  https://code.claude.com/docs/en/vs-code  
  https://code.claude.com/docs/en/settings  
  https://code.claude.com/docs/en/sub-agents  
  https://help.openai.com/en/articles/11369540-using-codex-with-your-chatgpt-plan/  
  https://github.com/openai/codex
