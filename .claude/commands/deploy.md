---
description: "部署 VolPred 網站到 Zeabur 或更新本地端。用法: /deploy"
---

# VolPred 網站部署

## Canonical source of truth

Active frontend、Zeabur project / service、站點網址一律以
`config/project_targets.json` 為準。**不要**在 skill / 程式中 hardcode 任何 ID。
若要切換 target，先改 config，再改程式與文件。

目前 active target（2026-04）：
- active_frontend: `frontend-v2-fix`（Next.js SSR，Docker 部署）
- deploy.active_service: `volpred-v3`
- 站點：`https://volpred.zeabur.app`

## Zeabur 部署（唯一安全入口）

```bash
cd frontend-v2-fix
./scripts/deploy-zeabur-safe.sh
```

這支腳本做了：
1. 驗 `frontend-v2-fix/.env.production` 存在且含所有 required keys
2. 複製到 staging dir，繞過 `.gitignore` 對 `.env.production` 的排除
3. 同步 Zeabur service env vars（build-time 也需要 `NEXT_PUBLIC_*`）
4. 上傳到 Zeabur 並輪詢到 `RUNNING`
5. 實打 `/api/publications/feed` 與 `/api/strategy-overview` 驗證非空後才宣告成功

完整緣由與 fail-mode 請讀：`docs/zeabur-safe-deploy.md`。

### 絕對不要

- 不要直接 `npx zeabur@latest deploy --project-id ... --service-id ...`
  — 會踩到 2026-03-24 的 `.env.production` 0-byte image 問題。
- 不要從 `config/project_targets.json` 以外的地方複製 service ID。
- 不要跳過 `./scripts/deploy-zeabur-safe.sh`，就算只是「小改」。

### 查目前 active target

```bash
jq '.active_frontend, .deploy.active_service, .deploy.services[.deploy.active_service], .site.default_remote_url' config/project_targets.json
```

## 本地端（不需要 deploy）

Publisher 寫 `storage/` → FastAPI 讀 → 前端 SWR 自動刷新。發文不用 rebuild。

```bash
# API
PYTHONPATH=src uv run uvicorn api.main:app --host 127.0.0.1 --port 8787 &

# Frontend
cd frontend-v2-fix && npm run dev
```

## Troubleshooting

- 部署後 `/api/*` 回空資料 → 先看 `docs/zeabur-safe-deploy.md` 的「0-byte env.production」節。
- `deploy-zeabur-safe.sh` 找不到 required env key → 補進 `frontend-v2-fix/.env.production`，不要 bypass。
- 想部到別的 service → 先 PR 改 `config/project_targets.json` 的 `active_service`，再跑 deploy。
