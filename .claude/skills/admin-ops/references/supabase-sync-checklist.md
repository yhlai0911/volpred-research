# Supabase Projection Checklist

新增或修改 projection 時，必須同時交付：

1. 明確 primary/conflict identity 與 idempotency semantics。
2. versioned payload/schema contract；未知欄位 fail closed 或由明確 policy 處理。
3. 可重播 backfill／reconcile path，不只處理最新一筆。
4. retryable、terminal failure 與 ambiguous outcome 的 durable receipt。
5. local expected state、Supabase exact row／relationship、reader-facing projection 的
   三段 readback。
6. aggregate evidence identity，把 request、provider acknowledgement 與 public readback
   綁在同一 attempt。

## Diagnosis

- local expected 缺值：修 producer。
- local 對、Supabase 缺／錯：修 serializer、migration、conflict key 或 retry。
- Supabase 對、public 錯：修 query、relationship、filter 或 cache。
- receipt delivered、provider 不符：修 acknowledgement contract 並將既有結果降級為
  `contained`。

任何 repair 都走同一 projection adapter／reconcile CLI。不要直接補 remote row，也不要
用成功 exit code代替 exact readback。
