# scripts/_legacy — 已退役的一次性 / 歷史腳本

���裡���**確����� live �����**�����������������2026-07-01 ����������稽核 + 主���������移��������
������������������������� provenance / ���追溯�������被任�� cron / config / skill / pipeline ��������
canonical ���章�����路����� `scripts/publish_draft.py`��+ feed-publisher skill�����

## 2026-07-20 WS-A1b（refactor_plan_ops_master_2026_07 §WS-A）retirements

`docs/audit_next_tasks_writers.md`（A1a 盤點）判定 delete、複核零引用後移入：

- `decompose_drone_series.py` — drone 系列一次性拆解腳本（對應 §1.2 P6 / WS-E E1 的
  `drone_ep*` 死碼群）；帶一條無 helper 的 `next_tasks.json` 手抄 serialize 寫入路徑。
- `graphify_codeonly_pilot.py` — graphify pilot 一次性實驗；`_ensure_followup_task`
  帶 truncate-then-json.dump 寫入路徑。
- `backfill_task_types.py` — task_type 一次性 backfill（已執行完畢）；唯一引用是
  `tests/test_canonical_write_guard.py` 的 ratchet 清單（同 commit 移除）。

三者的 `LOW_LEVEL_OWNERS` 條目已自 `scripts/audit_canonical_writers.py` 移除；
`next_tasks.json` 寫入自此由 helper-routing gate（同 audit 的
`NEXT-TASKS-ROUTING` 檢查）機械封鎖，`_legacy/` 目錄不在掃描範圍。
