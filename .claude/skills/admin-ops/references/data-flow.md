---
paths:
  - "storage/**"
  - "scripts/supabase_sync.py"
  - "scripts/daily_update.py"
  - "scripts/recalc_metrics.py"
  - "src/volpred/memory/**"
---

# Data Flow

`storage/` 是本地 source of truth；Supabase、Mirror、frontend cache 與 Admin 都是
projections。正常 mutation 一律走產生資料的 domain workflow 或
`uv run volpred ops ...`，不直接編輯 canonical artifact 或 remote row。

## 診斷順序

1. 以 domain summary 讀 local canonical state 與最新時間戳。
2. 讀同步／outbox／job receipt，確認 exact logical request 是否 terminal。
3. 以 provider API 查 exact row／object。
4. 以 reader-facing API 查 projection 與 cache。
5. 比對 identity、關鍵欄位、資料日期與 aggregate hash。

| mismatch | 根因層 |
|---|---|
| local 已錯 | producer／calculation |
| local 對、provider 錯 | serialization／sync／schema／retry |
| provider 對、public 錯 | query／filter／cache／frontend |
| receipt 說成功但 provider 錯 | acknowledgement contract |

修正 producer 或 projection pipeline 後從正式入口重跑；歷史資料由 backfill／recalc
流程自然修正。完成必同時有 local、provider 與 reader readback。
