# 自我優化修復控制迴路

這條流程把「通知」和「修復」分開，但兩者都留下可回讀證據：

1. `check_alerts` 觀察 detector，內部 breach 交給
   `volpred.ops.alert_remediation.remediate_internal_alert`。
2. incident store 以 episode identity 決定是否建立唯一 bounded repair task；
   task 進入 `storage/next_tasks.json` 後標記 `repair_lane=self_optimization`、
   `dispatch_preempt=true`，並立即呼叫 `dispatch_supervisor.state.request_fire`，
   喚醒 Operations Core；因此不等下一個 cron，也不會排在普通 backlog 後面。
3. dispatcher 仍是唯一 claim／slot／execution owner；ingress 不直接執行
   agent，也不繞過 `task_pool_claim`、execution contract 或 worktree custody。
4. worker 完成後必須以 task receipt、測試／detector read-back、必要時
   `issue_tracker_sync` 回寫；`task_pool_claim complete` 必須帶
   `repair_verification(method/tests/readback)`。incident 只有通過 sustained-clean
   才能 resolved，成功通知也只在這個 gate 後寄出。
5. machine-self repair 僅允許 `incident.MACHINE_SELF_REPAIR_OUTPUT_PATHS`
   登記的 kind；episode 失敗或逾時會升級 root-cause task，不會無限重試。

## GitHub 留言邊界

GitHub comment ingress 是 observation／audit transport，不是任意程式碼 API。

- repo owner 自己的留言只寫入 `ignored_self_authored` durable receipt，**不寄信**、
  不建立 task；因此 agent 的進度留言不會再被當成新的待辦通知。
- 外部留言預設只進 15 分鐘 email batch。
- 只有明確 marker
  `<!-- volpred-repair kind=<registered-incident-kind> -->`
  才會經 `github_comment_repair` 轉成 incident task；kind 不在 execution
  contract registry 內會 fail closed，不能任意指定檔案或命令。
- repair admission receipt 會附在 comment delivery state，供後續 task、測試、
  detector 與 GitHub issue read-back 對帳。

## 驗證與狀態口徑

「已通知」不等於「已解決」。每次回報仍依五步 gate 分成：

- `contained`：已建立 task、喚醒 dispatcher 或止血，但尚未完成 read-back／制度化。
- `root_cause_fixed_and_verified`：根因修復、回歸測試、runtime receipt／下游
  acknowledgement、sustained-clean 與制度化全部完成。

`dispatch_preempt` 不等於無限制 fork：普通 task 數量與 cron 不構成等待條件，
但實體 worker slot、provider quota、single-flight、execution contract 與
incident deadline 仍是硬性安全閘；若資源已滿，系統會留下 durable pending receipt，
而不是偷偷同時啟動第二個修復者。

## 通知契約

修復建立、排隊、進度、逾時或失敗都不寄 owner notification。成功通知只由
`volpred.ops.repair_success.notify_verified_repair_success` 產生，且固定列出：
發生的問題、最終解決步驟／方法、測試證據、detector/runtime read-back 與完成時間。

快速驗證：

```bash
uv run pytest -q tests/test_github_comment_notifications.py \
  tests/test_github_comment_repair.py tests/test_alert_remediation.py
uv run python scripts/graphify_integration.py status
```
