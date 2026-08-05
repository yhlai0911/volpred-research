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
