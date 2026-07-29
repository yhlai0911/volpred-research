# Loop Trend Triage

此 reference 只幫單次 ops pass 判讀「同類錯誤是否在改善」，不觸發工作或寫治理 state。

## Read

```bash
uv run volpred ops loop-health
```

需要跨日 pattern 時，讀已存在的最新 dreaming report 與其 evidence refs；不要在 triage
中啟動會產生工作、通知或治理 mutation 的 branch。

四類訊號：

- `first_pass_success`：成功工作是否一次完成，連同 coverage 解讀。
- `task_outcome`：終態 success／fail／blocked 分布。
- `error_recurrence`：同 signature 是否持續出現。
- `correction_trend`：人工糾正是否上升。

`unknown`／low coverage 代表證據不足，不是健康。breach 要回到 exact incident receipts
定位 owner；重複模式交給 `pdca-operations` 做根因修正與制度化。

## Handoff contract

若 finding 需要新 work：

1. 先讀 live task-pool mode。
2. 使用 canonical ingress，保存 admission receipt。
3. admission 被拒絕時保留 reason，不改寫 queue。
4. 外部效果完成後仍需 provider／reader readback。

本 reference 不保存 detector 清單、cadence、notification matrix 或 enforcement map；
那些資訊分別由 implementation、Operations Core 與治理文件擁有。
