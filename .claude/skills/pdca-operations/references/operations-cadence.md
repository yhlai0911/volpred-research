# Operations Ownership Handoff

PDCA 不保存 cadence 表。需要「何時跑、誰觸發」時，依序讀：

1. `config/runtime_schedules.json.schedule_materialization`
2. 對應 `system_crontab.items`／`event_jobs`
3. `storage/ops/schedule_receipts.json` 的 exact fire receipt
4. `docs/architecture.md` 的 Operations Core contract

需要「接下來做哪個工作」時，讀 `storage/ops/task_pool_mode.json`，並呼叫 canonical
ingress／claim surface；PDCA 不建立 pending queue。

需要「學到了什麼」時，走 memory workflow 與 provenance gate；PDCA 只提供已驗證的
incident evidence，不直接成為 memory writer。

任何週期、task mode 或 owner 名稱若和本 reference 衝突，以 live canonical files 與
receipts 為準。
