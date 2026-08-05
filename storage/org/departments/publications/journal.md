# publications 工作日誌（append-only）

## 2026-08-05T08:41:36Z（台灣 16:41）— 部門首次啟動：KPI 基線建立

**outcome=noop**（收件匣 0 件，未自創工作）——但完成 bootstrap 應有的 KPI 基線，並依決策鏈把
portfolio 全面 stall 的裁決需求上報經理。

### 做了什麼

- 收件匣 0 件；`state.json` 為 `health=new` / `last_run=null`，確認這是部門第一次執行。
- 依章程收尾契約「state.json 需含 KPI 快照」，讀取 `storage/paper_pipeline_status.json`
  並跑 `scripts/paper_pipeline_check.py`（機械 stall 檢查，非人工估算）建立基線。

### 基線事實（來自機械檢查，generated_at 2026-08-05T08:40:49Z）

- 總論文 13 篇，`stall_days` 門檻 7 天 → **stalled_count = 13（全部）**，`data_issues = 0`
- 最久 `days_in_stage = 76.7` 天（prg-periodic-garch、volatility-absorption、vt-insurance-cost）
- stage 分布：revision 10、draft 2、multi_round_review 1；`do_not_advance=true` 2 篇
  （leverage-direction、taiwan-vt）
- **2026-08 至今推進 = 0 篇**（今天是 8 月第 5 天，尚未逾月，非 KPI 失敗，是本月未開始）
- 2026-07 只有 5 篇有可驗證的推進敘述；另 8 篇 `last_advance_at=2026-07-01` 與
  `_meta.baseline_set_at` 同日且無對應敘述證據，**疑為 audit 批次填寫，不採計為 KPI 達成**

### 口徑更正（避免誇大）

`days_in_stage` 是「停在同一 stage 多久」，不是「多久沒有任何動作」。後者看 `last_advance_at`，
最近一次是 2026-07-19（17 天前）。回報時兩者分開講，不混用。

### 未做什麼（以及為什麼）

沒有自行啟動任何 review round。啟動哪一篇牽涉部門間優先序與資源，屬經理職權；且
vt-insurance-cost 的投稿時機還牽涉「兩篇 VT letter 不得同時投 FRL」的排序決策。依組織通則
「遇到需要決策的事一律問經理，並附證據與建議選項」，已送 P1 report 到 manager/inbox，
附三個具選項與成本評估的裁決方案（建議 A：prg-periodic-garch v7 review cycle）。

### 下一步（等經理裁決）

經理指派後即可開工；論文部不自行排班（min_cadence=on-demand）。
