---
name: feedback_urgent_work_bypass_queue
description: 急件不進一般排程 — 該立刻做的事當場開工，不丟 hourly queue 排隊
process_owner: .claude/skills/platform-ops-manager/SKILL.md
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 513778cc-274c-4b78-9c84-f1d95770f5cf
---

有些工作**不該進一般任務池等排程**，而是**當下直接開工或列最優先**：user-assigned 訊息、critical alert、3-STRIKE 重構、線上故障、發現即修的小事。把它們 append 進 next_tasks 等下一班 hourly dispatch，等於把「馬上該做」變成「幾小時後也許會做」。

**Why**: 2026-07-13 老闆 Telegram：「你忘了你是自主運營經理 不應該一直問我 有問題、有建議就應該你自己開工。有些工作不應進一般排程 而是直接開工或是最優先處理」。搭配 [[feedback_dont_ask_do]]（不問選擇題）與 [[feedback_finish_task_before_standby]]（不做一半待機）：三條合起來 = 判斷該做 → 現在做 → 做到完。

**How to apply**:
- 判斷該做且本回合做得完 → 當場做，不 append 任務池、不排 wakeup、不等下一班。
- 只有「本回合做不完的大工程」才進池；進池時同時回報老闆「已排入，預計何時」。
- 「已排入任務池」不可當成處理完的交代 — 若該事其實 30 分鐘內能做完，那就是偷懶。
- 有建議 → 直接執行 + 事後告知，不寫成「建議老闆做 X」。
