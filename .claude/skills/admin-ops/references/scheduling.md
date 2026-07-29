# Operations Core Schedule Observation

正式 business clock 唯一 owner 是
`config/runtime_schedules.json.schedule_materialization` 所指定的 Operations Core。
Admin 與互動 skill 只觀察、提案或診斷，不建立第二個 clock。

## Read

```bash
jq '{
  generation: .schedule_materialization.generation,
  mode: .schedule_materialization.mode,
  daemon_label: .schedule_materialization.daemon_label,
  receipt_path: .schedule_materialization.receipt_path,
  enabled_jobs: [.system_crontab.items[] | select(.enabled != false) | .id],
  activation_evidence: (.schedule_materialization.active_jobs | keys)
}' config/runtime_schedules.json
uv run volpred ops schedule-report
```

`mode=active` 時 Operations Core 擁有所有 enabled jobs；`active_jobs` 是逐 job cutover
evidence，不是另一份可執行 allowlist。

以 spec generation + job id + scheduled UTC 組成的 fire identity，對照
`schedule_materialization.receipt_path` 指向的 terminal receipt。沒有 receipt 不能從
process 存活或 UI 綠燈推論 job 已完成。

## Change boundary

- 新 cadence／job 先修改 canonical spec 或走 `uv run volpred ops propose-schedule`。
- materialization、owner cutover 與 rollback 交給 Operations Core reconciler transaction。
- rollback 必須是 generation／mode／active-set 的 owner transaction，並驗下一次正式
  receipt；單獨恢復某個 legacy executor 不構成 rollback。
- task queue 與 business clock 是兩個 domain；schedule success 不代表 task admission
  或 delivery success。

完成條件：spec、materialized owner、terminal fire receipt 與 downstream
acknowledgement 使用同一 fire identity。
