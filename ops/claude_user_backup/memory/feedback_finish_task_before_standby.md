---
name: feedback_finish_task_before_standby
description: 任務不得做一半就待機/排程；必須完成當次任務（含部署+驗證+確認）才能進待機
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 9b03f82f-4b5a-4fd1-8247-88240cdbc856
---

用戶 2026-06-23 硬性要求：**以後任務不得做一半待命，一定要完成「當次任務」後才能待命**。

**Why**：當天我答完 feed.json 問題後，把「base64 內嵌圖修補」標成「下個 tick 再收」並排 ScheduleWakeup 待機 — 這正是 CLAUDE.md 禁止的「先記下來等下次再修」反模式。用戶當場糾正：排程待機 ≠ 完成任務。

**How to apply**：
- 一個 user-assigned 任務（或自己拆出的子項）只要還有「已識別且本回合做得完」的步驟，就**繼續做到底**，不可中途排 ScheduleWakeup / 待機 / 交回 ops loop。
- 「完成」的定義含：程式改完 + **build/test 通過 + 部署上線 + 線上驗證 + 回報確認**。改完 code 還沒 deploy/verify 不算完成。
- 唯一可待機的時機：當次任務**真正完成並驗證**後，或遇到不可回復風險須問用戶、或外部 blocker（額度/權限）擋住。
- 與 [[feedback_resume_ops_loop_after_user]] 的關係：那條講「答完用戶後流回 ops loop 不要停在等下一句」；這條更嚴 — 流回 loop 前**先把當次任務做完**，不是答到一半就排 wakeup。
- 與 [[feedback_dont_deflect_act_on_repeated_complaints]] 同源：被指出的問題要實做到完，不 defer 不 deflect。

已同步寫入 CLAUDE.md「平台運營經理自主迴圈」段（autonomous-loop 待機條件）。
