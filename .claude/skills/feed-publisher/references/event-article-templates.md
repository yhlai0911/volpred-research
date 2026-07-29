# Event Article Content Reference

這份 reference 只協助**區分事件文章各階段的內容角度**。它不是 scheduler spec，也不擁有 `event_jobs`、task materialization、cron 或 Operations Core。

## 先讀 live event state

```bash
uv run volpred ops event-preview
```

事件日期、`event_key`、slot、`not_before`、deadline、priority 與是否已 materialize，全以 `config/runtime_schedules.json` 及 `event-preview` 回讀為準。不要從本文件複製日期、配額或 task identity。

如需新增或修 schedule，交給正式 schedule-governance workflow；內容 producer 不直接改 schedule config。

## 內容角度

| Slot label | 內容責任 | 不可混入 |
|---|---|---|
| T-7 | 背景、歷史 baseline、資料口徑與可觀察情境 | 尚未公布的實際結果 |
| T-2 | 預期值、可驗證情境表、風險與 position-sizing 邊界 | 把預測寫成事實 |
| T+0 | 官方實際值 vs 事前預期、公告時間、第一段市場反應 | 使用公告前 unavailable 的資料 |
| T+1 | 隔日消化、event window、後續 drift 與替代解釋 | same-day signal × same-day return |

slot 是否存在、上限與發布時點均以 live event spec 為準；上表只是寫作分工。

## Primary-source checklist

- FOMC／央行：官方聲明、minutes、dot plot 或正式資料下載
- CPI／NFP：BLS／官方統計機關原表
- 公司財報：IR、SEC filing、公開資訊觀測站
- 交易反應：可重現市場資料與明確 timestamp
- 地緣政治／能源：政府、國際組織、交易所或公司正式公告

每個數字都要留來源、取得時間、期間、樣本與計算方式。尚未公布就明寫 scenario，不可填入預測值冒充 actual。

## Handoff

內容 producer 交付：

- feed draft 與證據路徑
- 若 reader-visible gate 要求，data-bound lazypack plan
- 若 source task 要求 FB，FB-native draft
- event identity 與 `event-preview` snapshot
- anti-AI gate 結果

接著交 `feed-publisher` 走唯一 feed gateway；FB delivery 交 `fb-publishing`。本 reference 不執行 publish、schedule 或 task completion。

## 歷史模板

舊的固定日期、T-series populate 範例與直接修改 config 的步驟只具有 incident/evidence 價值，不再是 active instruction。需要追查歷史時用 git history 與 `storage/ops/event_ledger/`，不要從舊範例重建現行排程。
