# 平台拓樸指標

拓樸唯一母本是 `docs/architecture.md`；本檔只提供讀取順序。

1. 從 `config/project_targets.json` 解析 `active_frontend`。
2. 以該 key 解析 `frontends[key].path`、`frontends[key].deploy_service`。
3. 從 `.deploy.active_service` 解析正式服務名稱，再從 `.deploy.services` 取得 provider
   identity。
4. 從 `.site.default_remote_url` 與 `.mirror.default_url` 解析 live readback endpoints。
5. 排程只讀 `config/runtime_schedules.json.schedule_materialization`；task admission
   只讀 `storage/ops/task_pool_mode.json`。

不要把解析出的 frontend 名稱、服務名稱或 provider ID 寫回 skill。切換 target 時先改
`config/project_targets.json`，再由共用 runtime helper 與安全 wrapper 消費。

平台層的穩定入口：

- local source of truth：`storage/`
- agent CLI：`uv run volpred ops ...`
- human observer：active frontend 的 `/admin/*`
- structured integration：active frontend 的 `/api/admin/*`
- architecture／data flow：`docs/architecture.md`

Admin 顯示與 snapshot 是 projection；若它和 canonical source 不一致，修 projection
pipeline 並以 source + live readback 驗證，不反向修 source 來迎合畫面。
