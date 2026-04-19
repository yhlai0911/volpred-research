# 系統架構

補充總覽文件：`docs/system_handbook.md`。若你要一次看完整系統架構、功能、資料流、排程、control plane、前後台與維運邏輯，先讀這份再回來查本檔細節。`2026-04-19` v12 架構已收斂為**單一主線程 Claude Code session 作為唯一 orchestrator**；不再有常駐 supervisor / worker terminal pool。舊的 3-terminal / supervisor-worker 構想（`docs/multi-agent-terminal-workflow-codex.md`）已 deprecated，僅保留歷史。

## 網站架構（v4 Supabase + Admin CMS + Mirror API）
- **前端 target 設定**：`config/project_targets.json`（唯一來源；目前 `active_frontend=frontend-v2-fix`、`active_service=volpred-v3`）
- **排程 target 設定**：`config/runtime_schedules.json`（唯一來源；host crontab + session cron + `event_jobs` spec。v12 下 session cron 是正式的 queue 推進時鐘，host crontab 處理資料收集與外部世界 trigger）
- **前端（目前線上版）**：`frontend-v2-fix/`（Next.js 15 + React 19 + Supabase，部署於 volpred-v3 服務）
- **Legacy 前端快照**：舊版已自 root retire；如需參考請看 `archive/root-clutter/local/舊前端/`
- **Mirror API**：`mirror-api.zeabur.app`（研究記憶檔案鏡像，減少 Supabase egress）
- **資料庫**：Supabase（PostgreSQL + Auth + REST API + RPC）
- **Zeabur Project / Service IDs**：見 `config/project_targets.json`
- **線上網址**：https://volpred.zeabur.app
- **舊版**：https://volpred-old.zeabur.app（過渡期保留）

### 前端 v4 架構（frontend-v2-fix/）
- **SSR + CSR 混合**：首頁用 Server Component 初始載入 → `FeedBrowser` 用 `useSWRInfinite` 無限滾動
- **Admin CMS**（12 個面板）：analytics / content / health / ops / paper-trading / papers / program / questions / schedules / strategies / thinking / users
  - `/admin/schedules` 讀 canonical schedule spec + live `crontab -l`，不再從 rendered guide 逆向解析
- （原 legacy `program` 已重新啟用為主面板之一；`thinking` 為 Claude 思考日誌檢視器）
- **用戶專區** `/me`：書籤、提問歷史、活動摘要
- **API 路由 45+**：含 `/api/admin/*`（12 端點）、`/api/me/*`（3 端點）、`/api/strategy-overview`、`/api/portfolio-overview`
- **認證**：`admin-auth.ts` 支持 secret-based + session-based 雙模式，角色：admin/user/guest
- **Feed RPC**：`feed_page()` + `feed_tag_counts()` 伺服器端分頁+標籤計數，取代 client-side filter
- **互動追蹤**：`ArticleEngagement` 組件（瀏覽、按讚、收藏、分享）
- **策略視覺化**：`PaperTradingChartIsland` + sparkline 走勢圖（Recharts）
- **論文管理**：`/admin/papers` + `/api/admin/papers` + `/api/admin/papers/upload`，論文頁 metadata 與 PDF 交付都可走平台層

### 資料流
- `storage/` → 本地唯一源頭（JSON）
- **文章採 Contentlayer 模式（2026-04-18 起）**：
  - `storage/reports/feed.json` 是**唯一 canonical 文章源**，git-tracked，保留完整 audit trail
  - Supabase `articles` 表是**唯讀 projection**，寫入只允許 `service_role`（migration 022 RLS 物理阻擋前端/admin CMS 反向寫）
  - **寫入只走三條 path**：`publisher.publish_milestone` / `ops release-pool` / `ops feed-sync`
  - 三者內部都先改 feed.json，再呼叫 `sync_article(...)` / `_delete_where(...)` 把變動推 Supabase
  - 歷史的 `storage/reports/mile_*.json` 個別檔案已廢除，全部移到 `storage/reports/_archive_mile_files/`，不再被任何 code 讀寫
  - 漂移偵測：`uv run volpred ops feed-sync --dry-run` 或 session Monitor 每小時檢查 `feed.json ↔ Supabase`
- `scripts/supabase_sync.py` → Supabase 同步工具（由 daily_update.py 呼叫，不需獨立 cron）
  - **文章同步**：只讀取 `storage/reports/feed.json`（唯一源頭，`storage/feed.json` + `mile_*.json` 全部已廢除）
  - **Paper trades 同步**：自動剝離市場數據（spy_close/gld_close 等），只存策略 weights + returns
  - **Draft 同步**：用 `published_at OR created_at` 過濾（支持 draft sync）
- `scripts/daily_update.py` → 每日 08:03 台灣時間（crontab `3 8 * * 2-6`，美股收盤後）計算策略權重 + 同步 Supabase + 重算績效指標 + Supabase heartbeat
- `scripts/recalc_metrics.py` → 從 paper_trading.json 重算 Sharpe/MDD 等（daily_update 自動呼叫）
- `config/project_targets.json` + `src/volpred/config/runtime.py` → 控制 active frontend、Zeabur deploy service、paper public dir、strategy metrics local sync target、預設 remote/mirror URL
- `config/runtime_schedules.json` + `src/volpred/config/schedules.py` → 控制 canonical session cron / host crontab / `event_jobs` spec（v12 單主線程架構）
- **Paper Trading 資料結構**：
  - `paper_trading.json` 是唯一源頭，不可手動修改歷史數據
  - `daily_update.py` 正確使用 next-day return（K692 驗證），forward tracking 自動修正
  - `recalc_metrics.py` 每次執行自動 sync 到 Supabase `strategy_metrics_cache`
  - `recalc_metrics.py` 也會同步到 active frontend 的 configured metrics target（目前 `frontend-v2-fix/data/strategy_metrics.json`）
  - **不修改歷史數據**：歷史 entries 反映當時追蹤的結果，隨新的正確條目累積 metrics 自然收斂
  - 市場數據統一存在 `_market_daily`（key=日期），不在每個 entry 重複
- **新策略評估**：
  - 必須用 `scripts/evaluate_new_strategy.py` 在 COMMON_START（2023-01-04）~ 今天的同期間比較
  - 與已上架策略的 paper_trading actual returns 做公平比較（同期間、同 lag、同 TX cost）
  - 通過同期間比較 + cross-OOS 才能進入上架流程
- `src/volpred/ops/` + `uv run volpred ops ...` → agent-first 操作層（真人與本機 agent 共用）
- `uv run volpred ops experiments ...` → `experiments/` 結構治理工具；v2 採「新規先行 + touched-file migration」，不一次性批量搬歷史散檔
- 前端從 Supabase 讀取策略 metadata，不需靜態檔案同步
- **Mirror 資料流**：`MemorySystem._sync_to_remote()` 直接呼叫 Mirror API（預設 URL 由 `config/project_targets.json` 提供，可被 `VOLPRED_MIRROR_URL` 覆蓋）
  - 平時：增量 append（POST，只送新 entry）
  - 初始/復原：整檔覆蓋（PUT，`reconcile_remote()`）
  - Mirror 存：thinking_journal / knowledge / experiments / research_log（4 個大型記憶檔案）
  - Supabase 存：articles / questions / papers / paper_trades / strategy_signals（產品面向資料）
  - 本地 frontend data mirror 預設不啟用；只有 `project_targets.json` 明確配置 `local_data_sync_dirs` 才會寫入
  - Rollout 文件：`docs/research-mirror-rollout.md`

### 策略管理（DB 驅動，無需重新部署）
- 策略 metadata 唯一來源：`daily_update.py` 頂部的 `STRATEGY_REGISTRY`（display_name, is_active, order）
- Registry 驅動三件事：Feed 文章（只列 active）、Supabase 同步、Paper trading
- **新增策略**：(1) 加入 STRATEGY_REGISTRY (2) 加計算邏輯到 strat_list (3) `add_strategy.py` 寫 DB
- **下架策略**：改 STRATEGY_REGISTRY 的 `is_active=False`（面板隱藏、文章不列、paper trading 繼續記錄）
- **績效指標**：每日由 `daily_update.py` 自動重算 → `storage/strategy_metrics.json` → active frontend configured target
- 詳細流程見 `.claude/skills/autonomous-research/references/add-strategy-guide.md`

### 發佈流程
1. 研究系統優先寫入 `storage/`，再依需求選擇：
   - `立即發布`
   - `放入文章池草稿（draft）`
   - `排程發布（scheduled）`
2. 平台層釋出優先走：
   - `uv run volpred ops publish-milestone`
   - `uv run volpred ops release-pool-by-settings`
   - `/admin/content`
3. 文章真正進入 `published` 後，平台層會準備管理通知：
   - 單篇新文章通知
   - 每日發文摘要
   - 若未配置 SMTP，會先寫入 `storage/notifications/`，不算真正寄出
4. Feed 發文用 `feed-publisher` skill；若涉及文章池、排程、節奏釋出、下架、釋出規則、管理通知，轉交 `admin-ops`
5. 改前端代碼時：Zeabur CLI 部署 `frontend-v2-fix/`（見下方 Zeabur CLI 指令）
6. 新增策略用 `add_strategy.py`（只寫 DB，不需部署）
7. 測試貼文清理優先走 `uv run volpred ops cleanup-post <pub_id>`，不要手改 feed/DB

### Agent-first Ops Layer（v12 單主線程架構，2026-04-19）

**核心模型**：整個本地 control plane 只有**一個持久的執行者** — 主線程 Claude Code single session。v11 的 3-terminal worker pool（supervisor + claude-worker + codex-worker）已於 git commit `e64a1907` 拆除；不再有常駐 T2/T3 worker terminal、也不再依賴 headless `claude -p` / `codex exec` subprocess。舊架構詳見 `docs/multi-agent-terminal-workflow-codex.md`（已 DEPRECATED）。

**角色分工**：

- **主線程 Claude Code（唯一 orchestrator）**：負責研究、派工、審查、修文件、發佈、governance。所有正式執行一律發生在這個 session 內。
- **Codex（ephemeral subagent）**：透過 `codex:codex-rescue` / `codex:review` 等 subagent 以 **ad-hoc** 方式被主線程派遣。共用 runtime、一次一個、任務結束即退出；**不是常駐 session，也不會主動 poll queue**。
- **Worktree agents（ephemeral）**：僅產出 `experiments/kXXX/`，完成後由主線程 `scripts/merge_worktree.sh` 合併；不可寫共享狀態。
- **Cloud triggers（遠端/host 層）**：Session cron 與 host crontab 只負責**把事件放進 queue**，不直接完成 task。

**Queue 語意**：control-plane queue (`storage/ops/`, `event_jobs`, `storage/next_tasks.json`) 在 v12 下是 **proposal / backlog**，不是 worker poll target。主線程在每輪 cron 或 idle pass 時**主動消化** queue。沒有 worker daemon loop 去認領 task。

**排程 / 時鐘層級**（全部 source of truth 在 `config/runtime_schedules.json`）：

- **Session cron（Claude Code `CronCreate` durable）**：`*/4` 分鐘觸發「繼續任務」prompt，驅動主線程自動推進 queue。這是 v12 的正式執行時鐘。
- **Host crontab（5 entries + 1 hourly）**：
  - 資料收集：`collect_tw` / `collect_us`
  - 每日更新：`daily_update`（08:03 TPE）
  - Pool 釋出：`release_pool`
  - 日曆同步：`market_cal`
  - 每小時：`check_alerts`（email alert subsystem）
- **Event jobs**：由 cron / signal 觸發的 one-shot 事件（例如 FOMC、CPI release），materialize 成 control-plane task 由主線程消化。

**Alert subsystem**（`src/volpred/ops/alerts.py` + `.claude/rules/alert.md`）：

- 3 條件：`release_pool_gap` / `draft_pool_low` / `host_cron_fail`
- 三段 body：觸發條件 / 影響 / 建議行動
- Dedup 避免重複轟炸；CLI 支援 `--force` 強制發信
- 由 host crontab hourly `check_alerts` 入口驅動

**CLI 首選入口**：`uv run volpred ops ...`（agent + 真人共用同一套操作）

已統一的操作：
- `ops publish-milestone`
- `ops release-pool-by-settings`
- `ops send-article-notification`
- `ops send-daily-digest`
- `ops unpublish`
- `ops cleanup-post`
- `ops sync-all`
- `ops daily-update`
- `ops recalc-metrics`
- `ops strategy-upsert`
- `ops strategy-set-active`
- `ops question-ranking-summary`
- `ops question-rerank`
- `ops question-answer`
- `ops health`

**Job Queue**（`src/volpred/ops/jobs.py`）：
- Supabase-backed 任務佇列（`ops_jobs` 表）
- lifecycle: `queued` → `running` → `succeeded|failed`
- 支援 dedupe key、dry-run、priority
- CLI: `ops jobs` / `ops job-show` / `ops enqueue` / `ops worker`
- **`ops worker` 定位（v12 更新）**：手動觸發用的本地執行 helper，不是常駐 daemon；主線程才是正式 orchestrator

**Web Admin**（`frontend-v2-fix/src/app/admin/ops/`）：**Observer only**。OpsConsole 做瀏覽器端 job 監看；canonical control plane 是 `storage/ops/` + 主線程 session state，UI 不是 source of truth。

**Claude 可直接讀的 summary surfaces**：
- `/api/admin/analytics/summary`
- `/api/admin/questions/summary`
- `/api/admin/content`

**核心原則重申**：同一套 `ops` CLI，真人與主線程 agent 共用；v12 下真人 UI 是監看層，主線程才是正式執行者，不再有第二個平行 Claude / Codex session 持續消化 queue。

## 程式碼架構
- **Python CLI (volpred)**：研究引擎（實驗、評估、記憶、發佈）
- **config/project_targets.json**：前端 / 部署 / Mirror target 的版本控制設定
- **src/volpred/config/runtime.py**：程式側讀取 runtime target 的 helper
- **storage/**：唯一資料源頭（JSON），跨 session 保存
- **frontend-v2-fix/**：Next.js 15 前端（線上版，volpred-v3 服務）
- **archive/root-clutter/local/舊前端/**：legacy snapshot 存放處；不參與 active code path / deploy
- **scripts/supabase_sync.py**：資料同步到 Supabase
- **src/volpred/ops/jobs.py**：Supabase-backed job queue（agent + human 共用）
- **research_program.md**：研究策略文件（北極星）
- **paper/**：學術論文（按子目錄組織）

### Supabase 資料庫表
| 表名 | 用途 |
|------|------|
| `articles` + `article_tags` | 文章（feed）+ 標籤 |
| `strategy_signals` | 策略即時信號（權重、VIX、sigma） |
| `paper_trades` | Paper trading 每日記錄 |
| `strategy_metrics_cache` | 預計算的績效指標 + sparkline |
| `questions` + `question_articles` | 會員問答系統 |
| `memory_entries` | 研究記憶（thinking/knowledge/experiments） |
| `profiles` + `quota_usage` | 用戶角色（admin/premium/free）+ 配額 |
| `article_impressions` + `article_reactions` | 互動追蹤（瀏覽/按讚/收藏） |
| `ops_jobs` + `ops_job_logs` + `ops_audit_logs` | Job queue + 審計紀錄 |
| `papers` | 論文 metadata（論文頁 DB 驅動） |
| RPC: `feed_page()`, `feed_tag_counts()` | 伺服器端分頁查詢 |

### Supabase Migrations
- `004_deep_efficiency.sql` — 索引 + feed RPC + strategy_metrics_cache
- `005_ops_control_plane.sql` — ops_jobs + audit logs
- `006_reload_postgrest_schema.sql` — schema refresh
