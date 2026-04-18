<!-- AUTO-GENERATED FROM agent-specs/. Edit canonical sources instead. -->

# Session Cron Workflows

這份文件給本地 **Claude Code / Codex + local control plane** 使用。目的不是定義研究內容，而是把**平台層工作**包成穩定、可重複採用的節奏。

## 原則

- 先讀摘要，再決定是否執行寫入
- 沒有需要就不要每天重做整站操作
- ranking / release 都要保留可觀測結果
- user-assigned 任務永遠高於 scheduled / agent-discovered
- 先寫正式 queue task，再執行；不要只靠聊天上下文記住待辦
- 若治理文件需要被刪除或改寫，先停下來取得使用者同意

## 1. 6 小時會員問題重排

建議節奏：

- 每 6 小時跑一次
- 先讀工作包
- 只有 `pending_questions > 0` 時才進入評分

### Step 1: 讀工作包

```bash
uv run python -m volpred.cli ops question-ranking-workflow --limit 20
```

回傳重點：

- `ranked_table`
- `pending_questions`
- `candidate_pool`
- `evaluation_template`
- `workflow_steps`
- `next_commands`

### Step 2: 用 LLM 評分待評分題目

評分時遵守：

- 只插入新題目
- 舊榜單彼此相對順序不可改
- `researching` 題目維持優先
- 表格欄位固定為：
  - 排名
  - 前次排名
  - 主題
  - 提出者
  - 狀態

### Step 3: 執行 stable insertion rerank

```bash
uv run python -m volpred.cli ops question-rerank --evaluations-json /path/to/evaluations.json
```

### 建議的 session cron prompt 骨架

1. 跑 `question-ranking-workflow`
2. 若 `pending_questions` 為 0，記錄略過原因後結束
3. 若大於 0，依 `evaluation_template` 產生 `evaluations.json`
4. 執行 `question-rerank`
5. 檢查回傳：
   - `evaluated`
   - `updated`
   - 是否有異常題目未寫回

## 2. 內容池節奏釋出

建議節奏：

- 每日或每 6 小時檢查一次
- 先讀平台摘要
- 只有符合釋出條件時才真正 release

### Step 1: 讀平台摘要

```bash
uv run python -m volpred.cli ops platform-cycle-summary --storage-dir storage --limit 20
```

回傳重點：

- `release_preview`
  - `mode`
  - `release_due`
  - `draft_count`
  - `scheduled_count`
  - `next_due_at`
  - `items`
- `question_ranking`
- `suggestions`

### Step 2: 判斷是否釋出

只有以下情況才釋出：

- `mode != manual`
- `release_due = true`
- 有可釋出的 `items`

### Step 3: 依設定釋出

```bash
uv run python -m volpred.cli ops release-pool-by-settings --storage-dir storage
```

### Step 4: 視需要補管理通知

若剛完成真正發布，可補送：

```bash
uv run python -m volpred.cli ops send-article-notification <pub_id>
```

若當天已有多篇發布，且目前是固定摘要時間點，可補送：

```bash
uv run python -m volpred.cli ops send-daily-digest --target-date YYYY-MM-DD
```

注意：

- 管理通知預設是短版（標題 + 摘要 + 連結）
- 若 `sent=false`，代表通知已建立，但尚未真正送出
- 未配置 SMTP 時不要把它當成真正完成外寄

### 建議的 session cron prompt 骨架

1. 跑 `platform-cycle-summary`
2. 若 `release_due = false`，記錄略過原因後結束
3. 若 `release_due = true`，先讀 `items` 與 `suggestions`
4. 確認沒有更高優先的人工暫停指令後，再跑 `release-pool-by-settings`
5. 釋出後再次讀 `/admin/content` 或 content snapshot，確認文章池狀態已更新
6. 若這次是正式發布且需要管理提醒，再執行單篇通知或每日摘要

## 3. 綜合平台巡檢

若 session cron 當前要做的是「平台層巡檢」，建議順序：

1. `uv run python -m volpred.cli ops health`
2. `uv run python -m volpred.cli ops platform-cycle-summary --storage-dir storage --limit 20`
3. 必要時讀：
   - `/api/admin/analytics/summary`
   - `/api/admin/questions/summary`
   - `/api/admin/health`

## 4. 論文修訂交付（低頻，不需固定高頻 cron）

這不是一般內容池節奏工作，也不是研究本身。適合在論文修訂完成後執行。

### 建議流程

1. 先完成論文編譯：

```bash
cd paper/<name> && xelatex main.tex && xelatex main.tex
```

2. 更新論文 metadata（若有變）

```bash
uv run python -m volpred.cli ops paper-upsert ...
```

3. 上傳新版 PDF

```bash
uv run python -m volpred.cli ops paper-upload-pdf --paper-id <id> --file paper/<name>/main.pdf
```

4. 驗證

- `uv run python -m volpred.cli ops paper-list`
- 檢查 `/paper`

### 規則

- 若只是 PDF / metadata 更新，**不要預設 redeploy**
- 只有論文頁前端邏輯或欄位變更時才考慮部署
- 論文寫作與學術審查仍屬研究層，不是 `admin-ops` 主體工作

## 5. 什麼時候不要自動執行

以下情況只讀不寫：

- 正在排查網站錯誤
- 內容池設定剛被人工改動但尚未確認
- 問題榜單出現大量異常狀態
- 需要改動治理文件內容

## 6. 推薦的最小採用方式

v2 建議的最小啟動集：

```
CronCreate(cron="13 */6 * * *", prompt="會員問題研究")     # 6 小時重排
CronCreate(cron="37 */6 * * *", prompt="平台巡檢")         # 6 小時巡檢（health + cycle summary）
CronCreate(cron="3 9 * * *", prompt="每日任務審視與執行計劃") # 每日計劃與 queue 補單
CronCreate(cron="7 */6 * * *", prompt="知識索引檢查")         # 6 小時檢查
CronCreate(cron="23 22 * * *", prompt="Token 用量日報")      # 每日一次
```

先讓本機 agent 養成：

- 先讀摘要（`platform-cycle-summary` / `question-ranking-workflow`）
- 再決定是否寫入
- 寫入前先建立正式 queue task（`uv run python -m volpred.cli ops assign ...`）
- 寫入後留可觀測結果（snapshot / execution receipt 存 `storage/ops/`）

**標準「繼續任務」cron 為 `11 */2 * * *`（每 2 小時 slot-aware heartbeat）**。任務類型不限於研究（涵蓋發文/論文/ops/bug fix/會員問題/文件/重構）。禁止高於 `*/20` 的密度，避免資源爆衝。
