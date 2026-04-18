# 完整系統說明書

Last updated: 2026-04-18

## 目的

這份文件是 `volpred-research` 在 v11 shared scheduler / control-plane 調整後，並於 `2026-04-18` 依實際 user story 校正後的整體說明書。

它要回答 5 件事：

1. 這個專案要解決什麼問題
2. 系統由哪些模組組成
3. 各模組之間如何流動資料
4. 任務如何被建立、排程、分派、執行、驗證與回收
5. 日常維運應該看哪些檔案、CLI、Admin surface

本文件偏向「整體運作手冊」。
若你只要特定主題，仍以既有專門文件為準：

- 架構與部署：`docs/architecture.md`
- 排程 canonical spec：`config/runtime_schedules.json`
- runtime target：`config/project_targets.json`
- 論文流程：`docs/paper-guide.md`
- 策略上架規則：`docs/strategy-registry.md`
- 錯誤與教訓：`docs/error_log.md`
- 優化計劃狀態：`docs/project_improvement_status.md`

## 一句話總結

這是一個以 `storage/` 為本地唯一資料源、以 Supabase 為產品層資料庫、以 Next.js 前端提供網站與 Admin surface、以 `uv run volpred ops ...` 為本地 control plane、以 VS Code 終端機中的 Claude/Codex session 執行任務的自主研究與內容營運系統；repo 內仍保留部分 `shared scheduler` / headless path 作為過渡期機制。

## 核心原則

- 正確性優先於吞吐量
- 永遠修流程，不修資料
- `storage/` 是本地唯一源頭（文章採 Contentlayer 模式：feed.json 唯一 canonical；Supabase 是 read-only projection；mile_*.json 單檔已廢除）
- 正式 user story 是 VS Code `supervisor + worker terminals`
- control plane 是任務狀態唯一來源
- Claude 是排程治理 owner
- Codex 偏向 code / review / ops / bug rescue executor
- template-first，只有例外任務才喚起 coordinator
- fail-closed，背景不足時寧可 blocked / requeue，也不硬做

## Runtime 校正

`2026-04-18` 重新對齊後，目標運作方式是：

1. 在 VS Code 開 3 個終端機
2. 其中 1 個登入 OAuth 的 Claude Code，擔任監督者 / supervisor
3. 另 1 個 Claude Code 與 1 個 Codex 終端機擔任 worker
4. supervisor 負責建立任務、檢視 queue、補 brief、調整排程、監看執行情況
5. worker 只認領已可執行的 task，完成後正式登記結果

這代表：

- 真正執行任務的不是額外開出來的 headless `claude -p` / `codex exec`
- worker 應該在已登入 OAuth、已開啟的 VS Code 終端機內完成任務
- `storage/ops/` 要留下 claim / finish / receipt 紀錄

目前 repo 內仍保留一部分 `scheduler-tick -> subprocess.run(...)` 的舊路徑。
它應視為**過渡期 / 診斷用**能力，而不是校正後的目標 runtime contract。

## 系統邊界

### 系統要做的事

- 波動率研究與實驗管理
- 研究結果發佈成讀者文章
- 策略每日追蹤、績效計算、前端展示
- 會員問題排行、研究、回答與文章連結
- 論文 metadata / PDF 交付
- 平台健康檢查、工作排程、內容節奏、通知與 Admin 操作

### 系統不直接做的事

- 不把 Supabase 當作研究 truth source
- 不把前端靜態檔案當主要資料來源
- 不靠 session prompt 記住排程
- 不允許 worktree agent 直接改共享記憶或發文狀態

## 整體拓撲

```text
本機 repo (volpred-research)
├─ storage/                              ← 本地唯一資料源
├─ src/volpred/                          ← Python 研究引擎 + ops control plane
├─ frontend-v2-fix/                      ← Next.js 前端 + Admin
├─ config/project_targets.json           ← active frontend / service / mirror / paper target
├─ config/runtime_schedules.json         ← canonical schedule spec
├─ config/brief_templates/               ← execution brief templates
└─ scripts/                              ← cron / sync / data collection / deploy helpers

外部系統
├─ Supabase                              ← 產品資料、Auth、RPC、ops_jobs
├─ Mirror API                            ← 研究記憶鏡像
└─ Zeabur                                ← 前端部署與 runtime
```

## Source of Truth 地圖

| 領域 | 唯一/正式來源 | 備註 |
|---|---|---|
| 本地研究資料 | `storage/` | 不手改歷史 JSON 修結果 |
| 任務與派工狀態 | `storage/ops/` | task / session / approval / rollback / receipt |
| 正式排程規格 | `config/runtime_schedules.json` | shared scheduler / system crontab / session cron / event jobs |
| frontend / deploy target | `config/project_targets.json` | active frontend, active service, mirror URL |
| 系統架構說明 | `docs/architecture.md` | 本文件補充全貌 |
| 優化狀態 | `docs/project_improvement_status.md` | 以 v11 為主線 |
| 策略 registry | `STRATEGY_REGISTRY` + `docs/strategy-registry.md` | metadata 與上架 gate |
| 論文版本與 publish path | `docs/paper-guide.md` | paper 層規則 |

`storage/next_tasks.json` 目前只算 legacy planning / working list，不是正式 queue。

## Repository 組成

### 1. `storage/`

本地唯一源頭，主要包含：

- `storage/reports/feed.json`
  - 文章主索引
- `storage/paper_trading.json`
  - 策略每日條目與實際追蹤結果
- `storage/strategy_metrics.json`
  - 績效摘要
- `storage/risk_forecast.json`
  - 風險預報快取
- `storage/memory/*.json`
  - knowledge / thinking / open questions / experiences
- `storage/ops/`
  - control plane 狀態
- `storage/notifications/`
  - 未實際寄出的通知草稿或準備檔

### 2. `src/volpred/`

Python 主程式，分成三大群：

- 研究與資料分析
- 發佈與同步
- ops / scheduler / control plane

### 3. `frontend-v2-fix/`

目前 active 前端，提供：

- 公開網站
- Admin CMS
- `/api/admin/*`、`/api/me/*` 等服務層

### 4. `scripts/`

腳本層，偏向：

- host cron 執行
- data collection
- daily update
- safe deploy

## 外部系統

### Supabase

角色：

- 產品面資料庫
- Auth / role / profile
- feed 與策略展示用資料
- `ops_jobs` queue 與 audit logs

主要表：

- `articles`, `article_tags`
- `strategy_signals`
- `paper_trades`
- `strategy_metrics_cache`
- `questions`, `question_articles`
- `profiles`, `quota_usage`
- `article_impressions`, `article_reactions`
- `ops_jobs`, `ops_job_logs`, `ops_audit_logs`
- `papers`

### Mirror API

角色：

- 大型研究記憶檔鏡像
- 降低把整份研究記憶壓進 Supabase 的需求

主要同步對象：

- thinking journal
- knowledge
- experiments
- research log

### Zeabur

角色：

- 前端部署
- runtime target 管理

active target 由 `config/project_targets.json` 決定，不從舊文件反推。

## 資料流

### 研究資料主流

```text
experiment / analysis
→ 寫入 storage/
→ 必要時寫入 memory / experiences
→ 視情況發佈成 article / question answer / paper material
→ 再同步到 Supabase / Mirror
```

### 每日市場與策略資料流

```text
collect_tw_data.py / collect_us_data.py
→ 更新本地市場資料
→ daily_update.py
→ 更新 strategy weights / signals / paper_trading / metrics
→ scripts/supabase_sync.py
→ Supabase tables
→ frontend 讀取展示
```

### 文章資料流

```text
research result
→ feed-publisher / publish-milestone
→ storage/reports/feed.json
→ sync 到 Supabase articles
→ frontend feed / article page
→ notification 準備或發送
```

### 論文資料流

```text
paper/*.tex / pdf
→ paper-update / admin papers surface
→ papers table metadata + Storage PDF
→ paper page delivery
```

## 前端與產品功能

### 公開網站

由 `frontend-v2-fix/` 提供，核心能力：

- 首頁 feed 瀏覽
- 文章詳情頁
- 策略績效與 overview
- 風險預報
- 會員專區 `/me`
- 論文頁

### Admin surfaces

目前有 12 個主面板：

- analytics
- content
- health
- ops
- paper-trading
- papers
- program
- questions
- schedules
- strategies
- thinking
- users

Admin surface 的定位不是單純 CMS，而是 human operator 對 agent-first system 的監看與介入層。

## 研究層

### 實驗

每個正式實驗應收斂在 `experiments/<id>/`：

- `README.md`
- `<id>.py`
- `<id>_results.json`

研究基本規則：

- 先查 error log / knowledge / 文獻
- 先診斷資料，再做估計
- lookahead bias 視為最高風險
- null result 也要如實保存

### 記憶層

研究記憶分成：

- knowledge：發現了什麼
- experiment experiences：學到了什麼
- thinking journal：過程與判斷痕跡

本地為主，Mirror 為鏡像，不反過來把遠端當主源頭。

## 內容層

### 發佈模式

內容可以有三種生命週期：

- `draft`
- `scheduled`
- `published`

主要操作入口：

- `uv run volpred ops publish-milestone`
- `uv run volpred ops release-pool-by-settings`
- `/admin/content`

### 通知

文章與摘要通知若 SMTP 不可用，先寫到 `storage/notifications/`。
`sent=false` 只代表已準備，不代表真的送出。

## 策略層

### Strategy Registry

策略 metadata 不應散落前後端，而是由 registry 管理。

策略生命週期：

```text
研究與比較
→ 同期間公平評估
→ cross-OOS / gate 檢查
→ 上架 metadata
→ daily_update 持續追蹤
→ frontend 展示
```

### Paper Trading

`storage/paper_trading.json` 是唯一真實追蹤源。

原則：

- 不手補歷史
- 不手改過去條目
- 正確的 future entries 會讓 metrics 自然收斂

## 問答層

### 會員問題流程

```text
會員提問
→ questions table / ranking summary
→ evaluation / rerank
→ candidate pool / researching
→ 回答或轉成 feed article
→ 問題與文章自動連結
```

目前有：

- summary surface
- rerank flow
- workflow snapshot
- Admin question console

## 論文層

論文本身的寫作與方法論決策仍在研究層完成。

平台層負責：

- paper metadata
- PDF upload
- paper page delivery

原則：

- 不再依賴單純替換 `public/` 靜態 PDF
- 優先走 DB row + Storage URL

## Ops Control Plane

### 目標

把「任務、session、approval、rollback、receipt」從 prompt 記憶與零散 cron 中抽離，落成可觀察的本地狀態機。

### 主要位置

- tasks：`storage/ops/tasks/`
- agents：`storage/ops/agents/`
- approvals：`storage/ops/approvals/`
- executions：`storage/ops/executions/`
- rollback points：`storage/ops/rollback_points/`
- scheduler state：`storage/ops/scheduler_state.json`
- live CLI readiness：`storage/ops/agent_cli_health.json`

### Task 排序與 claim

queue 排序規則：

1. `source`
   - `user`
   - `schedule`
   - `agent`
2. `priority`
3. `created_at`

`preferred_agent=auto` 的預設對應：

- `research/content/member -> claude`
- `code/review/ops/strategy -> codex`

任何 `schedule governance` task 會強制收斂到 Claude。

### Task 狀態

主要狀態：

- `queued`
- `claimed`
- `running`
- `awaiting_approval`
- `blocked`
- `succeeded`
- `failed`
- `cancelled`

### Session

session wrapper 提供：

- `session-bootstrap`
- `next-task`
- `finish-task`
- `session-shutdown`
- `brief-show`
- `brief-set`

session 會建立 rollback point，並把 `session_id` / `session_rollback_point_id` 綁到後續 task。

推薦的三終端機操作是：

- supervisor Claude terminal：用 `tasks` / `task-show` / `brief-show` / `brief-set` / `control-plane-summary` / `health`
- Claude worker terminal：`session-bootstrap -> next-task --emit-brief -> finish-task`
- Codex worker terminal：`session-bootstrap -> next-task --emit-brief -> finish-task`

## 排程系統

這裡要分清楚兩件事：

- 校正後的**正式執行路徑**是 supervisor + worker terminals
- repo 內仍存在 `shared scheduler` / cron / headless path，主要是過渡期與輔助自動化機制

### 排程分層

#### 1. `system_crontab`

正式 host-level 永久任務。
目前 canonical 有 6 個：

- `collect_tw_data`
- `collect_us_data`
- `daily_update`
- `release_pool`
- `market_calendar_sync`
- `shared_scheduler_tick`

這些不是先進 shared scheduler queue，而是直接由 host cron 執行。

#### 2. `shared_scheduler_tick`

過渡期自動化與診斷用派工器。
host 每 10 分鐘執行一次 `scripts/run_scheduler_tick.sh`，再進入 `uv run volpred ops scheduler-tick`。

這條路徑目前仍存在，但不應再被理解成校正後的正式 worker runtime。
它不是「每 10 分鐘一定派一個 Claude 與一個 Codex」，而是每 10 分鐘做一次決策：

- 沒任務就 skip
- 任務 preconditions 不成立就 skip
- target agent 被真人 session 佔用就 skip
- 需要 coordinator 的任務，先產 brief
- brief ready 的任務，才交 executor

目前一次 tick 只挑一個最合適的 runnable task。

#### 3. `session_crons`

仍保留 canonical spec，但定位已降級為：

- session convenience
- reminder
- workflow recipe

不是正式自動派工時鐘。

#### 4. `remote_triggers`

雲端 trigger，跨本機 session 存活。
目前有：

- platform ops patrol
- token usage daily report

#### 5. `event_jobs`

事件型與一次性任務層。
功能已建好，但目前 canonical `items` 仍是空的，表示框架完成、內容尚未大量填入。

#### 6. `idle_policy`

`idle_policy` 不是另一個獨立時鐘，而是「slot 空出時如何挑下一個任務」的續跑政策。

目前實際模型是：

- `system_crontab.shared_scheduler_tick` 每 10 分鐘觸發正式派工
- `idle_policy` 決定有空閒 capacity 時，user / scheduled / discovery 哪一類優先被挑
- 所以系統是 `cron-driven scheduler + idle-aware selection policy`
- 不是 agent 一 idle 就一定立刻自動續跑的純 `idle-driven` runtime

### Scheduler 決策流程

```text
crontab
→ scripts/run_scheduler_tick.sh
→ uv run volpred ops scheduler-tick
→ 取得 self-lock
→ expand_due_event_jobs()
→ 掃 queued tasks
→ 過濾 needs_manual_review / unmet preconditions / busy manual session
→ 判斷 coordinator or executor
→ 執行一個 round
→ 回寫 scheduler_state / executions / task status
```

換句話說，目前正式自動化節奏仍以 host cron 為主；`idle_policy` 提供的是挑任務與續跑原則，不會自己取代 `shared_scheduler_tick` 成為主時鐘。

### Event Layer

event job 目前支援：

- `one_shot`
- `relative_to_event`

關鍵欄位：

- `event_key`
- `dedupe_key`
- `not_before`
- `deadline`
- `task_template`

展開後會寫入 event ledger，避免重複 materialize。

## Brief 與 Grounding

### Brief generation

系統採 template-first：

- 有模板：直接從 `config/brief_templates/*.yaml` 生 brief
- 無模板或高風險：走 Claude coordinator

### Brief 內容

固定包含：

- task summary
- goal
- success criteria
- repo root
- required files
- recommended files
- forbidden large files
- relevant commands
- prior findings
- rollback point
- why this agent

### Grounding contract

executor 必須：

- 先讀完 `required_files`
- 不整檔讀 forbidden large files
- 僅在 repo root 內動作
- 背景不足時 fail-closed

## Approval、Rollback、Receipt

### Approval

高風險或公開影響任務可進 approval gate。

### Rollback

session bootstrap 時先建立 rollback point。
高價值任務可再建專屬 rollback point。

### Execution Receipt

每次成功、失敗、blocked preflight 都會寫 receipt，作為：

- audit trail
- prior findings 來源
- scheduler / health / admin observability 基礎

## Observability

### CLI

常用：

- `uv run volpred ops health`
- `uv run volpred ops control-plane-summary`
- `uv run volpred ops brief-show <task_id>`
- `uv run volpred ops brief-set <task_id> --brief-json ... --actor claude-supervisor`
- `uv run volpred ops session-bootstrap --agent claude|codex`
- `uv run volpred ops next-task --agent claude|codex --emit-brief`
- `uv run volpred ops finish-task <task_id> --agent claude|codex --summary ...`
- `uv run volpred ops schedule-report`
- `uv run volpred ops scheduler-preview`
- `uv run volpred ops event-preview`
- `uv run volpred ops scheduler-smoke`
- `uv run volpred ops scheduler-live-smoke`

### 狀態檔

- `storage/ops/scheduler_state.json`
- `storage/ops/agent_cli_health.json`
- `storage/ops/scheduler.log`
- `storage/ops/executions/<task_id>/`

### Admin

主要觀測面：

- `/admin/ops`
- `/admin/health`
- `/admin/schedules`

`/admin/health` 現在會直接顯示 agent CLI readiness snapshot。

## 目前實際運作狀態（2026-04-18）

### 已完成

- shared scheduler 已安裝進本機 `crontab`
- canonical `system_crontab` 與 live `crontab` 目前對齊
- control plane / brief / preflight / event ledger / observability 基本完成
- agent CLI readiness snapshot 已可寫入 health / admin

### 仍待完成

正式未完成項目以 `docs/project_improvement_status.md` 為準，目前只剩：

1. Claude live structured-output compatibility remediation
2. 最終 commit / deploy

### 實務上的剩餘 gap

這些不一定代表 phase 未完成，但目前仍是 rollout gap：

- `event_jobs.items` 仍為空，表示事件框架可用，但 canonical event 任務尚未系統化填入
- 最新 `agent_cli_health` snapshot 可能不是 `ready`
- Claude live path 目前仍可能回自由文字，不一定輸出 schema-valid JSON
- Codex live path 可能受 timeout 影響，需要視當次環境狀態調整

## 建議的閱讀順序

### 新成員快速上手

1. 本文件
2. `docs/architecture.md`
3. `docs/project_improvement_status.md`
4. `config/project_targets.json`
5. `config/runtime_schedules.json`
6. `docs/quick-commands.md`

### 要追任務排程

1. `config/runtime_schedules.json`
2. `src/volpred/ops/scheduler.py`
3. `src/volpred/ops/local_control_plane.py`
4. `src/volpred/ops/execution_brief.py`
5. `storage/ops/scheduler_state.json`
6. `storage/ops/agent_cli_health.json`

### 要追平台資料流

1. `docs/architecture.md`
2. `scripts/daily_update.py`
3. `scripts/supabase_sync.py`
4. `frontend-v2-fix/src/lib/admin-health.ts`
5. `frontend-v2-fix/src/components/OpsConsole.tsx`

## 最後提醒

這個專案目前不是單一網站，也不是單一研究腳本，而是：

- 本地研究系統
- 產品網站
- Admin control plane
- agent orchestration layer
- 發佈與通知系統

五者疊在一起的混合系統。

調整任何一層之前，先確認你改的是：

- 研究 truth source
- 產品資料展示
- 派工與 control plane
- canonical schedule
- 只是觀測面

避免把觀測層改成來源，或把 session convenience 當正式控制面。
