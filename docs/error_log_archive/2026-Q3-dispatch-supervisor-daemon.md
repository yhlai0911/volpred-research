# 2026 Q3 Error Log Addendum — Dispatch Supervisor Daemon

## 2026-07-26 19:01 — Operations Core 稽核綠燈時 dispatch-supervisor 實際未載入

**Class**: A（dispatch / daemon 生命週期）。**嚴重度**：CRITICAL。  
**狀態**：`root_cause_fixed_and_verified`。

### 證據化症狀

- `reconcile_schedule_owners.py` 當時回報 `ok=true`、49 個 Operations Core jobs、
  0 conflict、0 legacy per-job LaunchAgent。
- 同一時間 `launchctl print gui/501/com.volpred.dispatch-supervisor` 回報 service not found；
  `storage/ops/dispatch_state.json.last_heartbeat_at` 停在 `09:21:35Z`。
- `runtime_schedules.json.daemons` 仍把 `volpred-dispatch-supervisor` 宣告為 active
  `launchd_keepalive_daemon`。因此不是「這個 daemon 已退役」，而是 owner audit 漏看一個
  canonical active surface。

### 根因

`build_owner_plan → audit_owner_plan → apply_owner_plan` 只管 Operations Core business clock、
host cron 與 legacy per-job LaunchAgents，完全沒有把 `runtime_schedules.json.daemons`
納入 plan。結果是新 scheduler clock 活著就足以讓稽核綠燈，即使真正執行派工的
KeepAlive daemon 已消失。至於是哪一個先前 cutover/cleanup 動作 bootout 它，沒有足夠
receipt 可證明，故不虛構；可證實且已修的是控制面允許它靜默消失的 enforcement 根因。

### 修復與驗證

1. 先以 canonical plist bootstrap 止血；launchctl 回讀 `state=running`，heartbeat 恢復前進，
   alert parser 回讀 `breached=false`。
2. owner plan 現從 canonical config 建立 `required_daemons`；缺任一 active
   `launchd_keepalive_daemon` 時 audit 必須轉紅。`daemons` 容器、row、type 與 active
   identity 任一 malformed 都 fail-closed，不可用 omission 讓 audit 假綠。
3. `--apply` 對缺失 daemon 先驗 repo-relative path 與 plist Label，再 atomic replace
   `~/Library/LaunchAgents` 並 bootstrap；已載入者不重啟。並行 reconcile 若在
   print→bootstrap 間由另一 process 完成恢復，會以 exact-label readback 認定已收斂；
   bootstrap 失敗且仍未載入才維持失敗。
4. 首次 live `--apply` 又揭露 canonical plist 註解含 `--dry-run`，macOS `plutil` 接受但
   Python XML parser 拒絕。改由系統 plist parser 驗 Label，對應 regression 先 RED 後 GREEN；
   第二次 live apply 成功，host crontab unchanged、49 jobs、0 conflict。
5. 相鄰 scheduler／launchd／dispatch alert suites 全綠。新架構 dispatch-supervisor 的
   所有 email title 另在單一 `_send` seam 統一加 `[新架構派發]`，避免 owner 看到
   `supervisor restart` 時誤判為退役舊架構。

T09 的 sustained-clean 長窗仍是獨立 umbrella gate；本 incident 的「漏查 active daemon」
根因與當下服務恢復已完成五步，不把 umbrella 觀察窗偷換成已結案。
