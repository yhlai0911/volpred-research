---
name: feedback_refactor_independent_execution
description: 重構執行必須獨立軌（main_thread lane + 專屬 session），不得排入一般 hourly 派工
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 330d83e4-6ab1-4f47-83f1-12e3ae8c2ce3
  modified: 2026-07-21T17:41:15.101Z
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

**⚠️ 2026-07-21 補：main_thread lane 目前是死 lane，不可當「已派工」交代**（老闆 msg 1239
「你現在交下去 他還是排後面啊」）。實查：`status="pending_main_thread"` 被 hourly dispatcher
完全跳過（`src/volpred/ops/next_tasks.py:171` 註解「queued, main-thread only」），且
`volpred.ops.task_urgency` 把它算成 `deferred_main_thread` 而非 urgent lane ——
當天該 lane 已積 **27 張**，其中 8 張是 7/20 建的 refactor-master P1。
急件 `request_fire` 照樣觸發（dispatch_state `fire_reason=requested:user:assign_10927b4e`），
但被叫醒的 worker 跑 A0 時 urgent lane 回 0，於是去做別的舊任務 → 「fire 了卻沒人做」。
- 所以 handoff 進 main_thread lane **只有在同一回合就有互動 session 要接手時**才成立；
  否則等於無限期擱置。responder 這類不能改 repo 的 session 尤其不可用它當出口
  （= [[feedback_responder_cannot_be_a_queue_excuse]] 的變形）。
- 回收指令：`scripts/task_pool_claim.py release --id <id>` 會把 `pending_main_thread`
  轉回 `pending`（`annotate --set status=` 被 lifecycle guard 擋，別走那條）。
  驗證用 `python -m volpred.ops.task_urgency` 看 `urgent` 有沒有 +1。
- 待解的結構問題：main_thread lane 需要**真正的執行者或到期自動降轉**，否則 27 張會一直躺著。
  參見 [[feedback_gates_smooth_no_deadlock]]（gate 必須有出口，禁死局）。

**⚠️ 2026-07-22 補：重構的正解出口是「handoff 文件 + 提示詞」，不是任何 lane**
（老闆 msg 1287「我不是說寫出handoff文件和提示詞 我丟主線跑？」）。當時我把 killpg／pid-reuse
根因重構交給 hourly dispatch，等同上面已被否決的那條路。
- **How to apply**：responder／任何不能改 repo 的 session 遇到重構級任務時，產出一份**寫在
  repo 外**（如 `~/.volpred/run/<workdir>/handoff_<topic>.md`）的 handoff：事實與已查證時序、
  根因假說、分 Phase 的執行步驟、完成定義、紀律提醒；再在 Telegram 附上**可直接複製貼上的
  提示詞**，由老闆丟進主線 session。任務池的原單維持原狀不動，由主線收尾。
- 這條同時繞開 main_thread lane 是死 lane 的問題 —— 執行者就是老闆當場開的主線 session。
