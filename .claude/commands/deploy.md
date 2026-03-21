---
description: "部署 VolPred 網站到 Zeabur 或更新本地端。用法: /deploy"
---

# VolPred 網站部署

## 架構

```
本地端（即時）                    Zeabur（每小時更新）
┌──────────────┐                ┌──────────────────┐
│ Next.js dev  │                │ 靜態 HTML (out/)  │
│ port 3737    │                │ volpred-research  │
│   ↓ proxy    │                │ .zeabur.app       │
│ FastAPI      │                │                   │
│ port 8787    │                │ 讀 public/data/   │
│   ↓          │                │ (build 時打包)     │
│ storage/     │                └──────────────────┘
│ (JSON files) │                        ↑
└──────────────┘                  每小時 rebuild
        ↑                        + deploy
  Publisher 即時寫入
```

## 本地端（即時更新）

Publisher 寫入 `storage/` → FastAPI 讀取 → 前端 SWR 30 秒自動刷新。
**不需要 rebuild，不需要 deploy。**

### 啟動本地端
```bash
# 1. 啟動 API 後端
PYTHONPATH=src uv run uvicorn api.main:app --host 127.0.0.1 --port 8787 &

# 2. 啟動前端（dev 模式，proxy 到 API）
cd frontend && npx next dev -p 3737 &

# 前端: http://localhost:3737
# API:  http://localhost:8787
```

### 發佈新內容（即時出現在本地端）
```python
from volpred.publisher.publisher import Publisher
pub = Publisher()
pub.publish_milestone(title='...', description='...', phase='...', details={...})
# → 即時出現在 http://localhost:3737（SWR 30 秒刷新）
```

## Zeabur（每小時靜態部署）

### Zeabur 配置
- **Project ID**: `69b5743e75c26871ff4c5e61`
- **Service ID**: `69b5744875c26871ff4c5e63`
- **Domain**: `volpred-research.zeabur.app`
- **Region**: Taipei (tpe1)

### 部署流程（每小時一次或手動）
```bash
# 1. 同步 storage/ 到 frontend/public/data/
uv run python scripts/daily_update.py

# 2. Build 靜態網站（需要 STATIC_EXPORT=1）
cd frontend
STATIC_EXPORT=1 npm run build

# 3. 從 out/ 目錄部署到 Zeabur
cd out
npx zeabur@latest deploy \
  --project-id 69b5743e75c26871ff4c5e61 \
  --service-id 69b5744875c26871ff4c5e63 \
  --json
```

### 一鍵部署腳本
```bash
# 從專案根目錄執行
uv run python scripts/daily_update.py && \
cd frontend && STATIC_EXPORT=1 npm run build && \
cd out && npx zeabur@latest deploy \
  --project-id 69b5743e75c26871ff4c5e61 \
  --service-id 69b5744875c26871ff4c5e63 \
  --json
```

## next.config.js 雙模式

```javascript
// STATIC_EXPORT=1 → 靜態導出（Zeabur）
// 無環境變數 → dev 模式（API proxy 到 localhost:8787）
```

前端 `api.ts` 自動偵測：
1. 先嘗試 `/api/...`（API 模式，本地端）
2. 失敗則讀 `/data/...`（靜態模式，Zeabur）

## 重要注意事項

1. **本地端發佈是即時的** — 不需要 rebuild
2. **Zeabur 更新有延遲** — 需要手動觸發或每小時 cron
3. **靜態導出要用 `STATIC_EXPORT=1`** — 否則會是 dev 模式（有 API proxy）
4. **`generateStaticParams`** 在 `reports/[id]/page.tsx` 中從 `feed.json` 讀取 ID 列表
5. **新發佈的報告** 要在 Zeabur rebuild 後才有獨立頁面（在此之前 feed 卡片仍可點開）
