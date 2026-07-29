---
name: data-collection-ops
description: >
  Diagnose and recover a VolPred data-collection freshness incident. Use when
  a configured data job, dataset date, market-data snapshot, or downstream
  metric is stale or missing.
---

# Data Collection Freshness Incident

本 skill 處理「資料為什麼沒有準時抵達」；資料欄位與 provider 選擇交給
`external-data-sources`。

## Preflight

先讀：

- `.claude/skills/autonomous-research/references/operations-core-contract.md`
- `config/runtime_schedules.json`

每次 invocation 先執行：

```bash
uv run python scripts/task_pool_control.py status
```

Task mode 只決定是否能建立 follow-up；資料 recovery 本身仍需依使用者交付範圍執行。

## 1. 證據化症狀

先跑 compact summary：

```bash
uv run volpred ops health
```

對疑似 job 設定 `JOB_ID` 後，動態讀 canonical spec：

```bash
JOB_ID="<job-id>"
jq --arg id "$JOB_ID" \
  '.schedule_materialization,
   (.system_crontab.items[] | select(.id == $id))' \
  config/runtime_schedules.json
```

再取得 `.schedule_materialization.receipt_path`，核對該 job 最新 scheduled fire、
attempt、terminal status、generation 與 owner。不要從 skill 的歷史表格推算應跑時間。

同時回讀下游：

- 最新 observation/data date
- row count
- output hash 或 mtime
- 線上/API data date（若該 job有下游）

Scheduler receipt 與資料 freshness 是兩份不同證據。

## 2. 判定根因層級

依證據分類：

| 層級 | 判斷 |
|---|---|
| source availability | Provider 尚未發布、休市、修訂或 rate/auth failure |
| collector logic | Parser/schema/date window/contract selection 錯誤 |
| Operations Core | 沒有 matching fire、lease/retry/timeout/owner conflict |
| wrapper/runtime | Canonical wrapper bytes、環境或權限錯誤 |
| downstream handoff | Collector 成功但 storage、sync、API 沒收到正確 identity |
| monitor/checker | 資料正確，但 freshness rule 或 expected calendar 錯誤 |

根因不明時標 blocked，不把「手動跑成功」當根因。

## 3. Recovery

先判資料是否有不可回補窗口：

- Tick、order flow、短 retention intraday：先保存 provider 可取得範圍與缺口 evidence。
- EOD、FRED、官方歷史資料：使用 collector 支援的 bounded backfill。

Recovery command 從 canonical job 的 wrapper/action 追到 repo implementation；不在 skill
保存 wrapper 絕對路徑或複製 command。手動 recovery 是單次 operator action，不會取得
排程 ownership。

跑完後重做：

1. output parse/read-back
2. max data date與 row count
3. downstream API/storage acknowledgement
4. 重複執行的 idempotency 檢查

只能完成上述 read-back 時才稱資料已 `contained`。

## 4. Root-cause fix

- Collector bug：修 canonical script與 regression fixture。
- Schedule/spec bug：先改 `config/runtime_schedules.json`，再走 Operations Core owner
  reconciliation，等待自然 fire receipt。
- Wrapper drift：修 canonical source，部署正式 wrapper generation，核對 bytes。
- Monitor bug：修 freshness/calendar checker，使同類落後無法靜默。

不要新增第二個 clock、互動 session owner或 wrapper-side scheduler。

## 5. 新增資料 job

1. 資料 source contract 先由 `external-data-sources` 定義。
2. Collector輸出寫到正式 canonical storage surface，並提供 idempotent bounded backfill。
3. 在 `config/runtime_schedules.json` 增加 job spec。
4. 接入 freshness checker、terminal receipt與下游 read-back。
5. 走 Operations Core reconciliation及 natural-fire驗證。

若需要 materialize後續 task，重新讀 task-pool mode；queued mode 才走 canonical producer，
direct/restore/unreadable mode 不新增 legacy task identity。

## Completion

- [ ] Canonical spec與 task mode 都是本次 read-back
- [ ] Scheduler receipt與下游 freshness分開驗證
- [ ] Root cause定位到 source/collector/core/wrapper/handoff/checker
- [ ] Recovery有 idempotent output read-back
- [ ] 底層修正有 regression
- [ ] 自然 Operations Core fire及下游 acknowledgement通過
- [ ] 同類錯誤可被 monitor發現

只有全部完成才可回報 `root_cause_fixed_and_verified`；否則使用 `contained` 或 blocked。
