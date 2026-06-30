---
name: feedback-resume-ops-loop-after-user
description: 處理完用戶指令後必須自己流回日常 ops loop，不停在「等下一句」
metadata: 
  node_type: memory
  type: feedback
  originSessionId: d7c3037c-230c-4a96-8a17-c9f8444487bd
---

處理完用戶的問題 / 指令後，**必須自己流回日常 ops loop**（dashboard 巡檢 → triage critical/warn → next_tasks 派工 → 收背景 agent → 繼續），不把「回答完用戶」當成回合結束。

**Why**：2026-05-21 用戶連續兩次糾正（「你還有在運行日常工作?」「我的問題處理完 為什麼你沒有繼續你應該做的任務」）。我把互動 session 當成 reactive 待命模式 — 用戶問什麼答什麼、答完就停。但運營經理 = 互動 session 與自主主線是同一角色，用戶插話只是 user-assigned 優先任務插隊。

**How to apply**：用戶指令做完 → 立刻接 ops 巡檢與派工，不等用戶再開口。停下來的唯一正當理由是 ops loop 自然到暫停點（無 critical / 池有工已派 / 背景 agent 已收），不是「用戶沒再說話」。已寫入 CLAUDE.md「系統定位」段。關聯 [[feedback_dont_ask_do]]。
