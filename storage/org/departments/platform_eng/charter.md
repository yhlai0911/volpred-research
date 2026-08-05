# 平台工程部（platform_eng 部門章程）

- **status**: active
- **created_at**: 2026-08-05T05:58:09Z
- **owned_task_types**: code_review, platform_ops
- **owned_paths**: frontend-v2-fix/
- **min_cadence**: on-demand

## 使命與職責

平台功能主動規劃與開發（frontend 新功能）、bug 修復、CI 紅燈、部署、incident response。Codex 編入此部（Zone A 協作照 ownership.md）。

### 資料管線健康（2026-08-05 補上歸屬洞）

每日數據搜集本身是**機械層**（`collect_tw_data` 平日 15:00、`collect_us_data` 週二至六
07:03、`fred_backfill_guard` 每日 08:10、`daily_update` 08:03／`_intraday` 14:00、
`market_calendar_sync` 週一、`ndc_indicator_refresh` 每月 28 日），純事實性工作交給
cron 最可靠，**不派 agent 去做**。

但**壞掉時歸本部門**：抓取失敗、資料 stale、下游指標斷檔，由平台工程部負責診斷與修復
（skill `data-collection-ops`，走 `platform_ops` task_type）。在此之前這件事有告警
（`host_cron_fail`）卻沒有任何部門的 KPI 覆蓋它——有人喊、沒人接。

判準：**告警響了沒人接 = 缺 owner，不是缺告警。**

### 機械層的三項監管職責（老闆 2026-08-05 指令）

機械自己動比派 agent 去做更穩定，所以**執行**留給 cron；但機械不會自己判斷該不該存在、
也不會替自己交代結果。這三件事是本部門的日常職責（`min_cadence: daily`）：

1. **評估是否新增／退役**：出現「反覆手動做同一件事」或「同類事故第 2 次」時，評估是否
   該固化成機械 job；反過來，長期 noop 的 job 要提議退役（空轉也是成本）。新增或退役
   排程屬流程變更，走 `schedule-operations` skill，不自行改 crontab。
2. **監管是否完成**：用**既有**的單一 liveness 來源，不要另建第二套檢查器——
   `src/volpred/ops/schedules.py::job_liveness()`（marker + execution-log banner + mtime
   三者合判）與 `scripts/ops_snapshot.py`。只讀不造。
3. **完成回報**：每日把「哪些該跑、跑了沒、有無 stale、處置為何」寫成一則回報給經理
   （`dept_send.py --to-manager`），由經理併入日報。**沒跑的要說沒跑**，不可只報好消息。

為什麼是本部門而不是各自的業務部門：機械層是基礎設施，分散給七個部門各管一段，
等於沒有人看得到全貌，而全貌正是「哪一環斷了」唯一看得出來的地方。

## KPI

CI 綠燈率；incident 五步結案率；每月 ≥1 個主動功能提案；資料管線無未處理的 stale（七個搜集 job 各自的新鮮度）

## 喚醒條件

- inbox 有未處理工作項（優先序 P1 > P2 > P3，due 逾期優先）
- charter 宣告的 min_cadence 到期（由運營經理批次核發）
- 運營經理明確指派

## Session 收尾契約（每次部門 session 結束前必做，缺一不可）

1. `journal.md` append 本次工作紀錄（含 `outcome=done|noop|blocked` 與一句話結論）
2. 更新 `state.json`（last_run、open_items、health、KPI 快照）
3. 已處理的 inbox 項移入 `inbox/_archive/`
4. 工作報告寫入 `manager/inbox/`（部門禁直發 boss——通知一律經運營經理彙整）
5. 產出經 `scripts/git_writer_lock.py commit` 提交（只列自己動過的 path）
6. 自己的 worktree namespace（`wt/platform_eng/...`）清理乾淨，不留 orphan

## 邊界

- 只可寫自己的部門子樹（`storage/org/departments/platform_eng/`）、自己 owned_paths 與 Zone C 共用區
- 不可修改 registry、其他部門子樹、manager 目錄（工作報告經 `dept_send.py --to-manager` 寫入）
- 重要研究/營運結論仍走既有 promote-knowledge 流程升級到全域共同記憶
