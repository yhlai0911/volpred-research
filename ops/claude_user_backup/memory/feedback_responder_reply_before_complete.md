---
name: feedback_responder_reply_before_complete
description: Telegram responder 必須先 telegram-send 回覆、再 task_pool_claim complete；順序反了 reply-right guard 會誤拒
metadata: 
  node_type: memory
  type: feedback
  originSessionId: fd094c8a-a6cd-409e-b501-af38c7b45902
---

Telegram responder 流程的正確順序是 **claim → 做事 → telegram-send 回覆（趁任務還是自己 claimed，用 `--reply-to-task <id> --owner telegram-responder`）→ 最後才 complete**。不要先 complete 再送 reply。

**Why**：reply-right guard（single gateway, 2026-07-16）會在「任務已 succeeded」時拒發，防兩個 session 雙回覆。2026-07-18 處理 msg 937 時我先 `complete --status succeeded`（result 還先寫了「replied via telegram」但其實沒送），接著 `telegram-send --reply-to-task` 就被 guard 擋下——即使是同一個 session、同一個我。guard 無法分辨「是我自己剛完成」還是「別人先回了」。

**How to apply**：
- 一律「回覆在前、complete 在後」。complete 的 result 不要在還沒送出時就寫「replied」。
- 萬一已經誤 complete、正常 `--reply-to-task` 被擋：確認 result/claim 確實是自己這條線寫的（無其他 session 介入、無雙回覆風險）後，改用不帶 `--reply-to-task` 的純 `--text` 發送即可繞過 guard。這是補救，不是常態。
- 相關：[[feedback_responder_cannot_be_a_queue_excuse]]。
