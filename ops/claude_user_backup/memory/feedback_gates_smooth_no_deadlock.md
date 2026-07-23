---
name: feedback_gates_smooth_no_deadlock
description: gate 設計硬規：檢查要流暢不中斷流程、block 型 gate 必有出口不可變死局
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 330d83e4-6ab1-4f47-83f1-12e3ae8c2ce3
  modified: 2026-07-20T09:18:11.607Z
---

2026-07-20 owner 硬規（ops master 重構期間下達）：「所有檢查關卡要合理且流暢，不能為了
檢查而造成流程中斷或浪費；gate 不能卡到最後變成死局。」

**Why**：重構加了大量機械 gate（NEXT-TASKS-ROUTING、vocab、certify、claim lane、
dedup、release audit…）。gate 的目的是擋壞東西，不是擋工作 — 歷史上 release deadlock、
mile_47c4bc3e 被 skip 20 次無出口、觀察期掛 18 天無決策，都是「有 gate 沒出口」的死局型浪費。

**How to apply**：
- 每個 **block 型 gate 必須有明確出口**：自動修復路徑（remediation task／requeue）、
  時限寬限（blocked_until／deadline）、或升級裁決點（needs_review／owner decision）三選一
- gate 觸發時**開單不只擋**（actuator 原則：audit exit 1 必須伴隨 findings→任務）
- 檢查放在**寫入邊界一次做完**，不在流程中段反覆攔（避免為檢查而中斷）
- 新 gate 上線清單多一項：「死局測試」— 注入最壞情境，證明工作最終能流出（過/修/裁決），
  不會永久卡住
- 相關：[[feedback_refactor_independent_execution]]、observation_ledger（F5，逾期自動 breach）
