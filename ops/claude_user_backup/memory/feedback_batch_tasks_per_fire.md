---
name: feedback-batch-tasks-per-fire
description: 老闆 2026-07-21 硬性指令：一班 fire 要連續跑多個任務直到預算用盡，不是做一張就停
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 330d83e4-6ab1-4f47-83f1-12e3ae8c2ce3
  modified: 2026-07-21T07:39:33.741Z
---

老闆 2026-07-21 指令（看到每班只跑 6-16 分鐘就收工後）：「你每班只跑一個任務？為什麼你不能一班跑多個任務 跑久一點？」

**Why**：50min slot 只做一張 8 分鐘的任務 = 白丟 42 分鐘；任務池 170+ 張時這是吞吐的最大浪費源。

**How to apply**：
- Enforcement owner = `scripts/cron_hourly_dispatch_prompt.md` 的「Batch-drain 原則」hard rule：每張完成（過完整完成 gate）後，距 cap ≥12 分鐘就回選擇流程接下一張；收班條件僅 (a) 無可派任務 (b) 預算不足收尾一整張。
- 批次單位是**完整任務** — 「做一半丟下一班」照樣禁止（feedback_finish_task_before_standby 不變）。
- 與 [[feedback-one-dispatch-per-hour]] 相容：一班一個 worker agent，worker 內多任務。
