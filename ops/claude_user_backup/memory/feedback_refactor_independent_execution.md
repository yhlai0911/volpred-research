---
name: feedback_refactor_independent_execution
description: 重構執行必須獨立軌（main_thread lane + 專屬 session），不得排入一般 hourly 派工
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 330d83e4-6ab1-4f47-83f1-12e3ae8c2ce3
---

2026-07-20 owner 糾正：「重構的執行不是應該獨立運作，怎麼會排入一般排程任務呢？」— 當時我把
ops master refactor（`docs/refactor_plan_ops_master_2026_07.md`）的 12 筆任務用 `ops assign`
排進一般佇列，急件 fire 立刻讓 3 個 hourly agent 同時在**共用 main checkout** 改
`task_pool_claim.py`／supervisor／publisher，與主線程賽跑。

**Why**：重構對象正是派工機器本身（佇列狀態機、supervisor、派工邏輯）。讓排程 agent 改自己的
執行機器 = 未隔離的自我改造，重演 PHASE-Z ownership 病灶（[[project_loop_engineering_layer]]；
WS-B producer-scoped isolation 要根治的正是這件事）；且 50min scope 的排程 agent 做深層重構
易產出表層 patch，違反 three-strike 禁令。

**How to apply**：
- 任何「改運營機器本身」的任務（dispatch/queue/supervisor/hooks/gates/發佈 gateway）一律
  `dispatch_lane: "main_thread"`，由主線程專屬 refactor session 逐 Phase 執行
- 動到 supervisor／佇列機器的改動在 worktree 隔離做、gate 綠才 merge；supervisor code 靠
  selfreload 生效
- 一般排程只消化「與執行機器無關」的常規任務（內容/研究/資料）
- 誤入一般佇列時的回收 SOP：release claims → flip lane → TERM 重構 worker（例行 cron 不動）→
  主線程逐簇驗證 agent 半成品（測試綠收養、殘的退回）
