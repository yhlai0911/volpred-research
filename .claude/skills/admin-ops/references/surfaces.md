# Platform Surfaces

這份文件是 `admin-ops` skill 的快速索引，目的是讓 Claude Code 先知道：

- 現在哪些平台入口已存在
- 哪些入口適合真人
- 哪些入口適合本地 Claude
- 哪些功能仍是雛形或只完成部分

## 原則

- 本地研究與決策主體仍是 `Claude Code + session cron + 活文件`
- 平台層負責：發文、同步、策略管理、問答管理、會員摘要、讀者分析、站務觀測
- 能用既有 CLI / API / UI 就不要直接手改 DB
- 舊治理文件不得直接覆寫；若要改 `CLAUDE.md`、`research_program.md`、`.claude/skills/`、`docs/` 既有內容，先取得使用者同意

## 人工 UI（`frontend-v2-fix/src/app/admin`）

- `/admin`
  - 管理首頁
- `/admin/ops`
  - jobs / audit / 手動建立平台工作
- `/admin/users`
  - 管理員與角色管理
- `/admin/content`
  - 文章池、排程發布、發布節奏設定、最近內容事件
- `/admin/strategies`
  - 策略 metadata、啟用/停用
- `/admin/questions`
  - 會員問題排行觀測、研究候選池
- `/admin/analytics`
  - 讀者與文章分析、內容方向建議
- `/admin/papers`
  - 論文 metadata 管理、PDF 上傳、Storage 驅動交付
- `/admin/health`
  - 站務健康監看台：概覽指標、Session Cron 工作包、內容釋出節奏、Analytics/問答摘要、最近平台工作、failed sync 樣本、workflow 快照狀態、下一步建議
- `/admin/schedules`
  - 排程管理：session cron 定義（from CLAUDE.md + skills）、system crontab 即時讀取（`crontab -l`）、核心永久任務覆蓋檢查、判讀建議
- `/admin/paper-trading`
  - Portfolio / 策略績效面板

## Admin API（`frontend-v2-fix/src/app/api/admin`）

- `GET /api/admin/session`
  - 判斷目前登入者是否具 admin 權限
- `GET /api/admin/jobs`
  - 取得 job 列表
- `POST /api/admin/jobs`
  - 建立 job
- `GET /api/admin/jobs/[id]`
  - 讀單筆 job 與 logs
- `GET /api/admin/audit`
  - 稽核紀錄
- `GET /api/admin/content`
  - 內容工作台 snapshot
- `PUT /api/admin/content`
  - 更新發布節奏設定
- `GET /api/admin/papers`
  - 論文管理 snapshot
- `POST /api/admin/papers`
  - upsert 論文 metadata
- `POST /api/admin/papers/upload`
  - 上傳 PDF 到 Supabase Storage 並更新 `papers` row
- `GET /api/admin/strategies`
  - 策略管理 snapshot
- `GET /api/admin/users`
  - 使用者/角色列表
- `GET /api/admin/analytics`
  - 完整分析 snapshot
- `GET /api/admin/analytics/summary`
  - 給 Claude / 後台讀的精簡摘要
- `GET /api/admin/health`
  - 站務健康監看台：local + jobs + workflows + content_release + analytics + questions + suggestions
- `GET /api/admin/schedules`
  - 排程管理：session cron 定義 + system crontab 即時讀取 + 覆蓋檢查
- `GET /api/admin/questions/candidates`
  - 研究候選池
- `POST /api/admin/questions/candidates`
  - 加入候選池
- `PATCH /api/admin/questions/candidates`
  - 候選池 lifecycle：`queued/claimed/completed/cancelled`
- `GET /api/admin/questions/summary`
  - 會員問題排行摘要、待評分題目、建議

## 本地 CLI（`uv run python -m volpred.cli ops ...`）

- `ops health`
- `ops sync-all`
- `ops daily-update`
- `ops recalc-metrics`
- `ops publish-milestone`
- `ops release-pool`
- `ops release-pool-by-settings`
- `ops unpublish`
- `ops cleanup-post`
- `ops strategy-upsert`
- `ops strategy-set-active`
- `ops question-answer`
- `ops paper-list`
- `ops paper-upsert`
- `ops paper-upload-pdf`
- `ops paper-migrate-storage`
- `ops question-ranking-summary`
- `ops question-ranking-workflow`
- `ops question-rerank`
- `ops platform-cycle-summary`
- `ops jobs`
- `ops job-show`
- `ops enqueue`
- `ops worker`

## 已產品化 vs 尚未完全產品化

### 已可用

- admin auth 與管理頁框架
- 文章池 / 排程 / 發布節奏設定
- Portfolio 聚合 API 與首屏優化
- 會員問題排行欄位：
  - `current_rank`
  - `prev_rank`
  - `score`
  - `score_breakdown`
- 研究候選池 lifecycle
- 讀者/文章 analytics summary
- 站務健康面板（`/admin/health`）：local + jobs + workflows + content_release + analytics + questions
- 排程管理面板（`/admin/schedules`）：session cron 定義 + system crontab 即時讀取 + 核心任務覆蓋檢查
- Session cron 驅動的 6 小時會員問題重排（CLI + API + workflow snapshot 全通過 2026-03-21 測試）
- 雲端 trigger 驅動的平台巡檢（`platform-ops-patrol`，每 6 小時，已遷移至 RemoteTrigger）
- 論文頁 DB 驅動 + PDF Storage 交付（metadata / PDF 更新不必 redeploy）

### 尚未完全產品化

- 文章池自動釋出（CLI 已可用，但尚未正式接入 session cron 自動執行）
- 完整會員中心（`/me` 基本功能已有，但缺完整 BI）
- 完整 BI / cohort / funnel analytics
- 完整 editorial workflow（review / approve / reject）

## 下一步讀什麼

- 若要實際操作平台 API / CLI：讀 [platform-api-manual.md](./platform-api-manual.md)
- 若要把平台工作包裝成 session cron：讀 [session-cron-workflows.md](./session-cron-workflows.md)
- 若要做會員問題 6 小時重排：先讀 `question-ranking-summary` 與 `question-rerank` 小節
- 若要做內容釋出：先讀 `publish-milestone`、`release-pool-by-settings` 小節
