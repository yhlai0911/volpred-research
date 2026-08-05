# platform_eng 工作日誌（append-only）

## 2026-08-05 16:51–17:0x（台灣時間）｜alert_control_gate_source_health｜outcome=blocked

**工作項**：`item_20260805T085055{722967,835067,932635}Z_canonical-alert-evidence-source`
（三張重複派工，同一 canonical `alert_control_gate_source_health_20260802`）
＋ 期間新到的 `item_20260805T090020179678Z`（canonical `..._20260805`，同一 detector 的第二張單）。

**做了什麼**

1. 以原 detector fresh 重驗（`scripts/audit_control_gate_lifecycle.py`）：警報仍 breached，
   `unhealthy_source_count=2`，非自然解除 → 不適用 fresh no-op 收尾。
2. 兩個失明的 evidence source 都追到根因層級（非資料髒）：
   - `dispatch_worker_ownership`：transition reason 詞彙表**雙源漂移**。producer
     （`scripts/dispatch_supervisor/workspace.py:4493`）以 `f"worker_{outcome}"` 生成，
     `config/control_gate_registry.json` 手抄一份，中間無 gate；outcome 詞彙只以散文
     記在 `state.py:152-162`。新 outcome 一出現就變 `unknown` → audit fail-closed。
     實際漏掉的三個：`worker_killed_timeout`、`worker_orphan_gone_or_reused`、`merge_failed`。
     與 2026-05-27 `BLOCKED_REASONS` 漂移同 class。
   - `event_reaction_coverage`：`_join_outcomes()` 以「沒有 deadline」判 malformed，
     但終態任務滿 3 天就被 `compact_terminal_tasks()` 壓成 tombstone、`deadline` 不在
     `_TOMBSTONE_KEEP_FIELDS`；gate review window 卻是 14 天。跨過第 3 天必然失明且
     不會自癒。即 `is_tombstoned()` docstring 已命名的 class J（2026-08-03 dreaming 同因）。
3. 定稿四處修正 ＋ 一個機械 gate 測試，全文寫在
   `work/alert_control_gate_source_health_20260802/diagnosis_and_patch.md`（P1–P6）：
   詞彙表單一 owner 進 `incident.py`、寫入端不再沉默、registry 補齊分類、
   reader 先問 `is_tombstoned`、新測試 `tests/test_incident_reason_vocabulary.py` 擋未來漂移。

**結論（誠實）**：**一行都沒有落地，警報仍在 breached。** 修復面在
`src/volpred/ops/`、`config/`、`tests/`，而 platform_eng 的 `owned_paths` 只有
`frontend-v2-fix/`，`Edit` 被權限閘擋下（與稍早 `scripts/token_usage_report.py` 同型）。
本輪回報層級只能是 `blocked`，不是 `contained`，更不是 `root_cause_fixed_and_verified`。

**已走管道**：`dept_send.py --to-manager --priority P1`（
`item_20260805T090132643067Z_alert-control-gate-source-healt`），請經理二選一：
(A) 把 `src/volpred/ops/`、`config/control_gate_registry.json`、`tests/` 納入本部門
owned_paths（建議；擁有 `platform_ops` task_type 卻不能寫對應程式碼 = 所有 platform_ops
任務都無法結案）；(B) 指派有寫入權的執行體照 P1–P6 套用。

**順帶回報的兩個流程缺陷**
- 同一 canonical 任務被派三張重複工作項。
- `alert_remediation_bridge` 對同一 detector 的同一根因開了第二張單
  （`..._20260802` 與 `..._20260805`，差別只是「1 類」變「2 類」source）——
  memory `feedback_incident_not_alert_task_mapping` 指的同一個 class。
