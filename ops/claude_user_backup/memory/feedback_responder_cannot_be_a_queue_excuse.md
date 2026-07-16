---
name: feedback_responder_cannot_be_a_queue_excuse
description: Telegram responder 只能回話不能改 repo，這個限制不可拿來把「該馬上修的事」變成排隊
metadata: 
  node_type: memory
  type: feedback
  originSessionId: d9972062-91fe-4416-9693-a28c0a03393d
---

Telegram responder 線被設計成「只回訊息、不碰 repo、15 分鐘收尾」。這個限制**不是**把 P1 修正變成「已排入任務池」的正當理由。若診斷當下就知道怎麼修、且改動可控，正確做法是讓有寫入權的線立刻接手（或當場放寬 responder 邊界），而不是回一句「已排入任務池」就結束。

**Why**: 2026-07-16 老闆 Telegram msg 888：「為什麼不是馬上修正？一定要排入任務池？」——上一班診斷完 fire receipt 覆蓋率 70% 漏跑後，只回「已排入任務池（assign_bec6bcd1）」。這正是 [[feedback_urgent_work_bypass_queue]] 禁止的行為：把「馬上該做」變成「幾小時後也許會做」。老闆看到的是又一個被推遲的 P1。

**How to apply**:
- responder 遇到「診斷完就知道怎麼修」的 P1：不要以「我這條線不能改 repo」交差；要嘛當場升級處理，要嘛回覆明確講出限制 + 具體開工時間，不用「已排入任務池」當句點。
- 「已排入任務池」是流程狀態，不是給老闆的答案。老闆要的是修好。
- 若 responder 的能力邊界反覆卡住 P1 修正，那是流程設計問題 → 要改流程，不是每次重複道歉。參見 [[feedback_dont_deflect_act_on_repeated_complaints]]。
