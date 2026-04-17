<!-- AUTO-GENERATED FROM agent-specs/. Edit canonical sources instead. -->

# Platform API Manual

這份文件給本地 `Claude Code` 使用，目的不是介紹產品，而是讓 agent 能可靠地：

- 讀平台狀態
- 建立與觀測站務工作
- 管理內容池
- 管理論文 metadata 與 PDF 交付
- 管理會員問題排行與研究候選
- 讀讀者/內容分析，回饋研究方向

## 0. 操作原則

- 先讀，後寫
- 先用既有 CLI / API / UI，不直接 patch DB
- 需要修改治理文件時先停下來確認
- 需要發布時，預設先考慮 `draft / scheduled / pool`，不要直接公開

## 1. 權限

### 網站 Admin API

授權方式二選一：

- 已登入的 admin session
- `x-ops-key: <OPS_ADMIN_TOKEN>`
  - 若未獨立設置，系統可 fallback `SUPABASE_SERVICE_ROLE_KEY`

### 本地 CLI

直接在 repo 根目錄執行：

```bash
uv run python -m volpred.cli ops ...
```

本地 CLI 不需要網站登入 session。

## 2. 常用工作流

### A. 看平台全局狀態

1. 站務健康

```bash
uv run python -m volpred.cli ops health
```

2. 工作佇列

```bash
uv run python -m volpred.cli ops jobs --limit 20
uv run python -m volpred.cli ops job-show <job_id>
```

3. 讀者/內容摘要

```bash
curl -sS -H "x-ops-key: $OPS_ADMIN_TOKEN" \
  http://127.0.0.1:3003/api/admin/analytics/summary
```

4. 站務健康摘要

```bash
curl -sS -H "x-ops-key: $OPS_ADMIN_TOKEN" \
  http://127.0.0.1:3003/api/admin/health
```

### B. 內容池與發布

#### 先存入池，不直接發布

```bash
uv run python -m volpred.cli ops publish-milestone \
  --title "..." \
  --description "..." \
  --phase research \
  --status draft
```

#### 排程發布

```bash
uv run python -m volpred.cli ops publish-milestone \
  --title "..." \
  --description "..." \
  --phase member_qa \
  --status scheduled \
  --publish-at "2026-03-21T09:00:00+08:00"
```

#### 依節奏設定釋出文章池

```bash
uv run python -m volpred.cli ops release-pool-by-settings
```

若只是測試是否會釋出，先看 `/admin/content` 裡的節奏設定與內容池清單。

#### 釋出指定文章或少量文章

```bash
uv run python -m volpred.cli ops release-pool --pub-id <pub_id>
uv run python -m volpred.cli ops release-pool --limit 1
```

#### 下架 / 清理

```bash
uv run python -m volpred.cli ops unpublish <pub_id>
uv run python -m volpred.cli ops cleanup-post <pub_id> --hard-delete
```

#### 管理通知與每日摘要

單篇文章通知：

```bash
uv run python -m volpred.cli ops send-article-notification <pub_id>
```

每日發文摘要：

```bash
uv run python -m volpred.cli ops send-daily-digest --target-date YYYY-MM-DD
```

判讀規則：

- `sent=true`：已實際寄出
- `sent=false`：只建立通知或 SMTP 尚未配置/失敗
- 若未配置 SMTP，通知仍會保存在 `storage/notifications/`
- 管理通知預設是短版：標題 + 摘要 + 連結
- 這不是讀者 newsletter 訂閱系統，而是平台管理通知

### B2. 論文 metadata 與 PDF 交付

#### 讀取論文清單

```bash
uv run python -m volpred.cli ops paper-list
```

或：

```bash
curl -sS -H "x-ops-key: $OPS_ADMIN_TOKEN" \
  http://127.0.0.1:3003/api/admin/papers
```

#### 更新論文 metadata

```bash
uv run python -m volpred.cli ops paper-upsert \
  --paper-id leverage-direction \
  --title "..." \
  --authors "Yi-Hao Lai, VolPred Research System" \
  --status working \
  --pages 58 \
  --tags "volatility targeting,GJR-GARCH"
```

#### 上傳新版 PDF

```bash
uv run python -m volpred.cli ops paper-upload-pdf \
  --paper-id leverage-direction \
  --file paper/leverage-direction/main.pdf
```

#### 把舊靜態 PDF 搬到 Storage

```bash
uv run python -m volpred.cli ops paper-migrate-storage --paper-id leverage-direction
```

判讀規則：

- `pdf_url` 若已是 `https://...supabase.co/storage/v1/object/public/...`
  - 代表論文頁已改成 Storage 驅動
- `storage_bucket = papers`
  - 代表 PDF 已在 Supabase Storage
- 如果只是 metadata / PDF 更新：
  - **不需要 redeploy**
- 只有論文頁前端邏輯、樣式、欄位變更時才需要部署

### C. 會員問題 6 小時重排

#### 第一步：讀榜單與待評分題目

CLI：

```bash
uv run python -m volpred.cli ops question-ranking-summary --limit 20
```

Admin API：

```bash
curl -sS -H "x-ops-key: $OPS_ADMIN_TOKEN" \
  http://127.0.0.1:3003/api/admin/questions/summary
```

這會回：

- `ranked_table`
- `pending_questions`
- `candidate_pool`
- `health`
- `suggestions`
- `table_columns`

若要讓 Claude 一次拿到「榜單 + 待評分題目 + evaluation template + 下一步命令」，可直接用：

```bash
uv run python -m volpred.cli ops question-ranking-workflow --limit 20
```

#### 第二步：用 LLM 評估 `pending_questions`

評分 payload 目標格式：

```json
[
  {
    "question_id": "uuid",
    "score": 78,
    "score_breakdown": {
      "研究可行性": 24,
      "讀者價值": 26,
      "研究相關性": 14,
      "預期影響力": 14
    }
  }
]
```

#### 第三步：執行 stable insertion rerank

```bash
uv run python -m volpred.cli ops question-rerank \
  --evaluations-json /path/to/evaluations.json
```

規則：

- 新待評分題目插入既有榜單適當位置
- 舊榜單彼此相對順序不變
- `researching` 題目仍維持在前段
- 會回寫：
  - `score`
  - `score_breakdown`
  - `current_rank`
  - `prev_rank`

### D. 研究候選池

候選池用於把高分但尚未處理的會員問題送進研究流程。

#### 讀候選池

```bash
curl -sS -H "x-ops-key: $OPS_ADMIN_TOKEN" \
  http://127.0.0.1:3003/api/admin/questions/candidates
```

#### 加入候選池

```bash
curl -sS -X POST \
  -H "Content-Type: application/json" \
  -H "x-ops-key: $OPS_ADMIN_TOKEN" \
  http://127.0.0.1:3003/api/admin/questions/candidates \
  -d '{
    "question_id": "uuid",
    "question_snapshot": "問題全文",
    "score_snapshot": 82,
    "linked_articles_count": 0,
    "requested_by": "claude"
  }'
```

#### lifecycle

`PATCH /api/admin/questions/candidates`

`status` 可為：

- `queued`
- `claimed`
- `completed`
- `cancelled`

### E. Session Cron 友善的總入口

若 Claude 在固定節奏中只想先看「現在平台層該不該做事」，可直接用：

```bash
uv run python -m volpred.cli ops platform-cycle-summary --storage-dir storage --limit 20
```

這會一次回：

- `release_preview`
  - 內容池目前模式
  - 是否已到釋出時間
  - 目前草稿/排程數量
  - 下一批可能釋出的文章
- `question_ranking`
  - 問題榜單摘要
  - 待評分題目
  - evaluation template
- `suggestions`
  - Claude 當前可優先執行的下一步

更完整的 session cron 包裝方式，請再讀：

- [session-cron-workflows.md](./session-cron-workflows.md)

### E. 策略管理

#### 更新策略 metadata

```bash
uv run python -m volpred.cli ops strategy-upsert \
  --strategy-key simple_12vix \
  --strategy-name "12/VIX (SPY)" \
  --weights-json '{"SPY":0.48,"cash":0.52}'
```

#### 啟用 / 停用

```bash
uv run python -m volpred.cli ops strategy-set-active simple_12vix --active
uv run python -m volpred.cli ops strategy-set-active simple_12vix --inactive
```

### F. 同步 / 每日站務

```bash
uv run python -m volpred.cli ops sync-all
uv run python -m volpred.cli ops daily-update
uv run python -m volpred.cli ops recalc-metrics
```

## 3. `/api/admin/*` 摘要

### 狀態與觀測

- `GET /api/admin/session`
- `GET /api/admin/jobs`
- `GET /api/admin/jobs/[id]`
- `GET /api/admin/audit`

### 內容與營運

- `GET /api/admin/content`
- `PUT /api/admin/content`
- `GET /api/admin/papers`
- `POST /api/admin/papers`
- `POST /api/admin/papers/upload`
- `GET /api/admin/analytics`
- `GET /api/admin/analytics/summary`

### 問題與候選池

- `GET /api/admin/questions/summary`
- `GET /api/admin/questions/candidates`
- `POST /api/admin/questions/candidates`
- `PATCH /api/admin/questions/candidates`

### 帳號與策略

- `GET /api/admin/users`
- `GET /api/admin/strategies`

## 4. Claude 的建議執行順序

### 內容相關任務

1. 先看 `/api/admin/content` 或 `/admin/content`
2. 判斷是要：
   - 存 draft
   - 排程
   - 立即發布
   - 依節奏釋出
3. 完成後必要時跑 `sync-all`

### 會員問題相關任務

1. 先跑 `question-ranking-summary`
2. 若 `pending_questions > 0`：
   - 用 LLM 產生 evaluations
   - 跑 `question-rerank`
3. 若榜單高分題目尚未連文：
   - 加入候選池
   - 領取 / 研究 / 完成

### 讀者分析相關任務

1. 先讀 `/api/admin/analytics/summary`
2. 再決定：
   - 補哪個 audience
   - 補哪種內容型態
   - 是否優先處理熱門主題或高熱度會員問題

## 5. 不該做的事

- 不要把 `research_program.md` / `CLAUDE.md` 當一般後台欄位直接改
- 不要直接 patch DB 當常規營運手段
- 不要在沒有必要時破壞既有 API contract
- 不要假設所有自動化都已完全收斂；v11 正式治理是 Claude coordinator + shared scheduler，若本機仍有 session cron，只視為過渡期 convenience
