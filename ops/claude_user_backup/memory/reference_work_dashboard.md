---
name: reference_work_dashboard
description: AI 工作監控 dashboard — 常駐 LaunchAgent，http://127.0.0.1:8787，scripts/work_dashboard_server.py
metadata: 
  node_type: memory
  type: reference
  originSessionId: df279cec-2a1a-4970-b0ae-111055444eb8
  modified: 2026-08-05T09:25:18.934Z
---

用戶 2026-05-29 要求的「可視化監控 AI 過去/進行中/未來工作 + 調整任務」dashboard。**已存在,勿重造。**

- **入口**:http://127.0.0.1:8787(本地)
- **程式**:`scripts/work_dashboard_server.py`(stdlib http.server 零依賴;每 request 讀 live JSON = 永遠最新;15s 自動刷新)
- **常駐**:LaunchAgent `com.volpred.work-dashboard`(RunAtLoad + KeepAlive;plist 在 `~/Library/LaunchAgents/`)。改 server 程式後 `launchctl kickstart -k gui/$(id -u)/com.volpred.work-dashboard` 重啟。
- **顯示**:健康+3 daemon 存活+slot、工作排程(24 cron + 下次fire + 上次執行)、進行中、未來待辦池、過去完成+commits、內容 pipeline(草稿/發佈/釋出/資料新鮮度)
- **任務調整**:block/unblock 按鈕 → POST /api/task → 走既有 `scripts/mark_task_blocked.py`(不繞正式流程)
- **API**:GET /api/work(聚合 JSON)、POST /api/task({action,id})
- **組織全景 `/org`**(2026-08-05 加):經理×部門層級圖 + 任務快訊時間軸(派工/求助/回報/執行紀錄/公告/巡檢,可依類型與部門篩選),點卡片開細節抽屜(KPI/阻塞/收件匣/journal)。資料層 `scripts/work_dashboard_org.py`(同一個 server,勿另起);API `GET /api/org`;離線快照 `uv run python scripts/work_dashboard_org.py --html <out>`。來源全是 `storage/org/` 的 registry / state.json / inbox / journal.md / receipts / bulletin。

未來可加:next-fire 倒數細化、論文 pipeline 狀態、token 用量、email/alert 流。整合進 frontend-v2-fix admin 是更完整但需 deploy 的後續選項。

關聯:[[project_platform_vision_full]](email 回報 + 透過 dashboard 指示)。
