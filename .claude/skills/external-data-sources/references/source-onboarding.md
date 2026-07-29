# External Source Onboarding

## Source contract

新增provider前記錄：

- Official URL / owner
- Dataset、series、field與units
- Frequency、history、timezone、release/vintage
- Authentication、rate limit、license
- Schema/version與revision policy
- Missing/duplicate/idempotency規則

## Collector contract

- Bounded fetch和bounded backfill
- Atomic output與parse read-back
- Raw/source identity及retrieval metadata
- Stable schema或explicit migration
- Retry不產生duplicate effect
- Freshness metric與downstream acknowledgement
- Tests包含schema drift、empty/partial response與rerun

Path由config、manifest、collector option或runtime resolver取得。Repository skill不保存
machine-specific absolute path。

## Operations integration

Recurring source：

1. 實作collector與tests。
2. 定義canonical output owner。
3. 更新`config/runtime_schedules.json`。
4. 接入Operations Core terminal receipt。
5. 接入freshness checker與downstream read-back。
6. 等待natural fire，驗證exact input/output identity。

不要讓wrapper或interactive agent成為另一個schedule owner。

## Task admission

每次materialize onboarding/fix task前重新執行
`scripts/task_pool_control.py status`：

- queued execution：走canonical producer/writer。
- direct execution：保留proposal，不新增legacy task identity。
- restore/unreadable：fail closed。
