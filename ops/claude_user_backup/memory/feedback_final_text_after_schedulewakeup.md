---
name: feedback-final-text-after-schedulewakeup
description: 回覆用戶的文字必須是 turn 的最後輸出（ScheduleWakeup 先呼叫、文字最後）；文字後面接工具呼叫會導致用戶看不到回覆
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 84ae09c8-9673-48d4-b7bc-6113766e22dc
---

2026-07-02 老闆連續 6 次質問「為什麼不回應我 / 為什麼不回覆在對話串中」——實際上每次都有回，但回覆文字都寫在 ScheduleWakeup 工具呼叫**之前**，harness 對「後面還接工具呼叫的文字」可能不顯示給用戶，導致老闆完全看不到任何實質回覆，只看到 email/推播。

**Why**: Harness 規則「用戶需要的一切必須在 turn 的最終文字訊息、後面不能再有工具呼叫」與 CLAUDE.md「每 turn 最後一個 tool call 必須是 ScheduleWakeup」表面衝突——解法是順序對調。

**How to apply**: 每個需要回覆用戶的 turn：(1) 先做完所有工具呼叫（含 ScheduleWakeup 排下次喚醒），(2) **最後**輸出回覆文字，文字之後零工具呼叫。純 autonomous tick（無用戶輸入）不受影響，可維持文字在前。

**2026-07-02 13:15 復發（strike 2）**：記 memory 後老闆同日再次質問「給任務後不在 session 回覆」。已升級固化進 `CLAUDE.md` 最高指引段（與 ScheduleWakeup 條款同位階），error_log 同步記錄。另注意：email summary 不能替代 session 內文字回覆。
