# Deploy And Runtime

這份文件是 `admin-ops` 的 runtime / deploy 入口。

在以下情況先讀它：

- Zeabur redeploy
- worker / job / health 巡檢
- session 啟動後要建 cron / monitor
- 想判斷這次改動需不需要 redeploy
- 想快速確認服務 ID、project ID、runtime ownership

## 先判斷是不是平台層

這份文件只處理：

- deploy
- runtime health
- session automation
- 平台層 verification

如果是：

- 研究實驗設計
- 論文內容修訂
- feed 文章內容寫作

先切回對應 skill，不要直接從 deploy 入口處理。

## 開工前先查

1. `docs/error_log.md`
2. `references/architecture.md`
3. `references/session-cron-workflows.md`
4. `scripts/session_startup.md`

如果是 OAuth / proxy 問題，再看 `docs/zeabur-oauth-gotcha.md`

## 系統地圖

- 前端線上版：`frontend-v2-fix/`
- 主要服務：`volpred-v3`
- 平台資料源頭：`storage/`
- 平台寫入口：`uv run volpred ops ...`
- DB / Auth：Supabase
- 記憶鏡像：Mirror API

完整事實以 `references/architecture.md` 與 `docs/architecture.md` 為準。

## 什麼情況不用 redeploy

以下情況預設 **不需要 redeploy**：

- 文章內容更新
- feed / question / paper metadata 更新
- PDF 上傳
- paper trading / metrics 重算
- 一般 `ops` CLI 同步

這些通常只需要：

- `uv run volpred ops ...`
- 或 `daily_update.py` / `recalc_metrics.py` / `supabase_sync.py`

## 什麼情況可能需要 redeploy

通常要 redeploy 的是：

- `frontend-v2-fix/` 前端邏輯或 UI 變更
- runtime 環境變數變更
- 服務層設定變更
- 確認是部署產物而不是資料問題

先問自己：

1. 這是資料問題還是程式問題？
2. 如果是資料問題，能不能走 ops surface 修正？
3. 只有在程式或環境真的變了時才 redeploy

## Zeabur 目前識別資訊

- Project ID: `69b5b264800a475a1f82b073`
- Environment ID: `69b5b2646853f6f4f5f6a16d`
- `volpred-web`: `69b5b279e0a0c18cef9d780d`
- `volpred-v2`: `69b8ed895a53b5901a3c8d25`
- `volpred-v3`: `69be521a1066986b9a1692be`

## 常用命令

```bash
npx zeabur@latest auth status
npx zeabur@latest service list --project-id 69b5b264800a475a1f82b073 --json
npx zeabur@latest service redeploy --id <service_id> -i=false -y
cd frontend-v2-fix && ./scripts/deploy-zeabur-safe.sh
uv run volpred ops health
uv run volpred ops jobs --status queued
uv run volpred ops job-show <job_id>
uv run volpred ops worker --poll-interval 10
```

## Session automation 規則

- session cron / Monitor 都是 session-only
- 每個新 session 都要重建
- 固定 cadence 與 prompt 以 `scripts/session_startup.md` 為準
- 若工作是 question rerank / content release / 平台巡檢，先讀 `session-cron-workflows.md`

## Deploy 後驗證

至少做以下檢查：

1. `uv run volpred ops health`
2. 需要時看 Zeabur service / deployment log
3. 前端頁面或 `/admin/*` 是否反映預期變化
4. 若是內容/策略/paper 相關變更，確認其實有沒有只需要 ops sync 而非 redeploy

## 反模式

- 遇到資料不同步就先 redeploy
- 直接手改 DB / JSON 當成正常運營路徑
- 把研究問題誤當成 deploy 問題
- session 沒重建 cron / monitor 卻以為自動化還在
