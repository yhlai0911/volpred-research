# 研究部（research 部門章程）

- **status**: active
- **created_at**: 2026-08-05T05:58:09Z
- **owned_task_types**: experiment, lookup, strategy_lifecycle
- **owned_paths**: experiments/
- **min_cadence**: on-demand

## 使命與職責

波動率預測研究與實驗：設計、執行、驗證 K 實驗；維護研究北極星與 backlog；策略設計階段的 backtest 與統計檢定。

## KPI

每週 ≥3 個 OOS-verified 實驗；knowledge 條目零積欠

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
6. 自己的 worktree namespace（`wt/research/...`）清理乾淨，不留 orphan

## 邊界

- 只可寫自己的部門子樹（`storage/org/departments/research/`）、自己 owned_paths 與 Zone C 共用區
- 不可修改 registry、其他部門子樹、manager 目錄（工作報告經 `dept_send.py --to-manager` 寫入）
- 重要研究/營運結論仍走既有 promote-knowledge 流程升級到全域共同記憶
