# 三 Terminal Supervisor / Worker 模式優化計劃（Codex）

## 文件定位

這份文件是**優化計劃**，不是現況描述。

目的只有一個：把目前 `volpred-research` 的 orchestration，收斂成使用者原始要求的三 terminal 工作模式：

1. VS Code Terminal A：Claude Code Supervisor
2. VS Code Terminal B：Claude Code Worker
3. VS Code Terminal C：Codex Worker

三者都在 **VS Code 終端機內，以已登入 OAuth 的互動 session** 運作。
正式任務由 worker 認領與完成；Supervisor 負責排程、brief、監看、介入與調整。

## 目標 User Story

使用者打開 VS Code，建立 3 個終端機：

- 1 個 Claude Code 作為 **Supervisor**
- 1 個 Claude Code 作為 **Claude Worker**
- 1 個 Codex 作為 **Codex Worker**

完成登入與人工認證後：

- Supervisor 不直接做正式 worker claim
- Supervisor 負責建立任務、補 brief、檢視 queue、調整優先序、監看健康狀態
- Claude Worker 與 Codex Worker 依照 control plane 中的 task queue 認領任務
- 任務開始、完成、失敗、重排都必須正式登記到 `storage/ops/`
- 系統不應再依賴額外 headless `claude -p` / `codex exec` 來代替已登入的互動 terminal

## 核心設計原則

- 正式執行者是 **已登入的 VS Code terminal session**
- `storage/ops/` 仍是唯一 control plane state source of truth
- `brief` 仍是正式執行入口
- shared scheduler 可以保留，但應降級為 **queue / event / cadence / housekeeping**，不是正式 executor
- Supervisor 與 Worker 必須在 control plane 中可區分，不能再共用單一 `claude` slot
- 所有 claim / finish / fail / requeue / approval / receipt 都要可追蹤

## 非目標

- 不重做網站
- 不替換 `storage/`
- 不放棄既有 task / brief / receipt / rollback 架構
- 不把系統退回純 session cron 黑箱模式
- 不再新增第二套平行 control plane

## 現階段要解決的根問題

目前最大的結構問題不是 queue，也不是 brief，而是 **session identity model 不夠細**。

現在 control plane 只有：

- `claude`
- `codex`

這種模型只能表達「一個 Claude、 一個 Codex」。
它無法原生表達：

- `claude-supervisor`
- `claude-worker`
- `codex-worker`

因此目前雖然已有 `session-bootstrap / next-task / finish-task / brief-show / brief-set`，但還不算真正完成三 terminal 架構。

## 目標架構

### 1. Session 身份模型

control plane 應從「每個 agent 一個檔案」改成「每個 session 一個檔案 / 一筆記錄」。

最低需求：

- `session_key`
- `agent_name`
- `role`
- `status`
- `session_id`
- `claimed_task_id`
- `heartbeat_at`
- `session_rollback_point_id`

目標 session 角色至少有：

- `claude-supervisor`
- `claude-worker`
- `codex-worker`

其中：

- `agent_name` 仍是 `claude` 或 `codex`
- `role` 則是 `supervisor` 或 `worker`
- `session_key` 才是唯一識別值

### 2. Supervisor 職責

Supervisor terminal 的正式職責：

- 建立 task
- 看 queue / agent sessions / health
- 為無模板或複雜任務補 manual brief
- 處理 approval / reject / requeue
- 依 worker 執行情況調整優先序
- 產生下一批任務與 schedule proposal

Supervisor **不直接 claim worker task**。

### 3. Worker 職責

Worker terminal 的正式職責：

- `session-bootstrap`
- `next-task --emit-brief`
- 在同一個已登入 terminal 內完成任務
- `finish-task`
- 任務很長時更新 heartbeat
- session 結束時 `session-shutdown`

Worker 不負責重新設計排程策略，也不直接改 canonical governance，除非被 task 明確授權。

### 4. Scheduler 職責

shared scheduler 保留，但其責任應收斂為：

- event materialization
- recurring task enqueue
- stale reclaim
- housekeeping
- health snapshot

shared scheduler **不應再直接跑正式 worker 任務**。

換句話說，最終目標是：

- scheduler 只把工作放到 queue
- supervisor / workers 透過 interactive session 消化 queue

## 分階段實施計劃

### Phase 1：Session Identity 重構

目標：

- 讓 control plane 能同時存在 `claude-supervisor` 與 `claude-worker`

必要修改：

- `storage/ops/agents/` 改為以 `session_key` 命名，不再只用 `agent_name`
- `get_agent_session()` / `list_agent_sessions()` / `heartbeat_agent()` / `session_bootstrap()` 改成支援 `role` 與 `session_key`
- task claim 紀錄加入：
  - `claimed_by_session_key`
  - `claimed_by_agent_name`
  - `claimed_by_role`

驗收標準：

- 同時 bootstrap `claude-supervisor` 與 `claude-worker` 不互相覆蓋
- `codex-worker` 可獨立存在
- `agents` CLI 能正確列出 3 個 session

### Phase 2：Worker Pull Loop 正式化

目標：

- 讓 worker 的正式工作循環完全以 interactive terminal 為主

必要修改：

- `session-next-task` 明確只返回可執行 task
- 若 task 缺 brief 或 preconditions 未滿足，worker 不應卡住
- `finish-task` 成為正式推薦收尾入口
- `complete` / `fail` 保留為底層維修工具

驗收標準：

- Claude Worker 能 claim 一個已 ready task 並完成
- Codex Worker 能 claim 一個已 ready task 並完成
- 每個 receipt 都保留 session 資訊

### Phase 3：Supervisor Brief Loop 正式化

目標：

- 讓 supervisor 成為「唯一互動式 brief manager」

必要修改：

- `brief-show`
- `brief-set`
- 必要時補 `brief-clear` / `brief-reopen`
- 對於需要人工 brief 的 task，明確標示 `requires_supervisor=true`

驗收標準：

- Supervisor 可查看 skeleton brief
- Supervisor 可提交 manual brief
- 提交後 worker 下一次 `next-task --emit-brief` 可以順利拿到該 task

### Phase 4：Headless Executor 退役

目標：

- 把 `scheduler -> subprocess.run(["claude", "-p", ...])`
- 與 `scheduler -> subprocess.run(["codex", "exec", ...])`

從正式主路徑移除。

保留策略：

- 可先用 feature flag 保留舊路徑作診斷
- 但 production / canonical workflow 不再把它視為正式 executor

必要修改：

- `scheduler_tick()` 改為：
  - expand event jobs
  - enqueue / refresh / reclaim
  - optional brief precompute
  - **不直接執行 worker round**

驗收標準：

- scheduler 跑完後只改 queue / state，不直接完成 task
- worker terminal 才是讓 task 進入 `claimed -> succeeded/failed` 的正式途徑

### Phase 5：Observability / Admin 對齊

目標：

- 讓 admin / CLI 能看出 supervisor 與 workers 的角色分工

必要修改：

- `ops agents` 顯示 `session_key` / `role`
- `control-plane-summary` 顯示：
  - active supervisor count
  - active worker count
  - idle workers
  - tasks waiting for supervisor brief
- `/admin/health` / `/admin/ops` 後續對齊 role-aware session model

驗收標準：

- 使用者能一眼看出：
  - 哪個 terminal 是 supervisor
  - 哪些 terminal 是 workers
  - 哪些 task 在等 brief
  - 哪些 task 在執行中

### Phase 6：操作手冊與啟動模板

目標：

- 讓三 terminal 模式可被直接照表執行

必要修改：

- `scripts/session_startup.md`
- `docs/system_handbook.md`
- `docs/project_improvement_status.md`
- 新增 `/supervisor-loop`、`/worker-loop` 類 prompt 模板或固定啟動文案

驗收標準：

- 新 session 打開後，使用者不用猜
- 只要照文件就能正確啟動 supervisor / workers

## CLI 設計建議

建議新增或調整：

- `session-bootstrap --agent claude --role supervisor --session-key claude-supervisor`
- `session-bootstrap --agent claude --role worker --session-key claude-worker`
- `session-bootstrap --agent codex --role worker --session-key codex-worker`
- `next-task --session-key claude-worker --emit-brief`
- `finish-task <task_id> --session-key claude-worker --summary ...`
- `agents`
  - 顯示 `session_key`
  - 顯示 `role`
  - 顯示 `claimed_task_id`

兼容策略：

- 舊的 `--agent claude|codex` 可在過渡期保留
- 但新文件與正式操作應逐步改成 `session_key + role` 模型

## 資料模型建議

TaskRecord 建議新增：

- `claimed_by_session_key`
- `claimed_by_role`
- `supervisor_actor`
- `brief_source_type`

AgentSession 建議新增或強化：

- `session_key`
- `role`
- `terminal_label`

ExecutionReceipt 建議新增：

- `session_key`
- `role`

## 風險與緩解

### 1. 兩個 Claude terminal 共用同一個訂閱帳號

風險：

- rate limit / token 配額共享

緩解：

- supervisor 只做輕量 control-plane 操作
- 大量 token 消耗留給 Claude worker

### 2. 多 session 寫入同一個 working tree

風險：

- 互踩檔案

緩解：

- `experiments/kXXX/` 類優先走 worktree
- 明確規範 worker write scope

### 3. 舊 headless 路徑與新 session 路徑並存

風險：

- 同一 task 被不同 runtime model 誤觸發

緩解：

- feature flag
- rollout 期間將 headless route 降為 disabled-by-default

## 驗證劇本

### 驗證 A：三 terminal 同時上線

1. 開啟 Claude supervisor terminal
2. 開啟 Claude worker terminal
3. 開啟 Codex worker terminal
4. 三者都完成登入
5. bootstrap session
6. `ops agents` 顯示三個 session

### 驗證 B：Supervisor 補 brief

1. 建立一個無模板 task
2. supervisor `brief-show`
3. supervisor `brief-set`
4. worker `next-task --emit-brief`
5. 成功取得該 task

### 驗證 C：Worker 完成 task

1. worker claim task
2. 在互動 terminal 內完成工作
3. `finish-task`
4. `task-show` 顯示完整 receipt

### 驗證 D：Scheduler 不再直接執行

1. 執行 `scheduler-tick`
2. task 狀態應停留在 `queued` 或 brief-related 狀態
3. 只有 worker claim 後才進入 `claimed/running/succeeded`

## 成功標準

只有當以下條件全部成立，才算這個優化計劃完成：

- control plane 正式支援 `claude-supervisor`、`claude-worker`、`codex-worker`
- worker 任務正式由互動 terminal 執行，不再依賴 headless subprocess
- supervisor 可以正式管理 brief / queue / approval / health
- scheduler 降級為節奏與 housekeeping，不再是正式 executor
- 文件、CLI、Admin、測試口徑一致

## 與原檔差異

原檔 `docs/multi-agent-terminal-workflow.md` 混合了：

- 現況描述
- 目標設計
- 部分錯誤 CLI 寫法
- 對 `shared scheduler` 的過度依賴

本檔的用途是把它改寫成：

- **目標導向**
- **可實施**
- **對齊使用者原始 user story**

不是描述現在已經完全做到什麼，而是定義**接下來要怎麼做到**。
