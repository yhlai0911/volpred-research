---
name: feedback_fix_verify_then_report
description: 發現問題不可先回報再修；順序永遠是「立刻修 → 立刻測 → 驗證沒問題 → 才給老闆」
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 672a8f32-d05b-4171-b38d-2661f7b2fbf6
---

老闆 2026-07-14（Telegram msg 736）：「為什麼你不是立刻解決之後立刻測試有沒有問題 沒有問題之後再給我？」
觸發 incident：msg 733 問「研究結果與文章數據能不能復現」，我回了「部分可、缺機械驗證」並把 `repro-audit-001` 排進任務池就結束 —— 等於把待辦丟回給老闆看。

**⚠️ 再犯（2026-07-15 Telegram msg 796）**：老闆又發飆同一件事 ——「你可不可以流程改邏輯正常一點；發現問題後不是應該馬上解決馬上看結果是否成功然後回報嗎？怎麼會是發現問題→告訴我有問題→設計任務→下一輪解決；這樣我怎麼會知道到底有沒有完成」。**一天內第二次糾正同一模式 = 記憶存在但沒擋住行為**。這是 standing hard rule，優先級等同研究誠實原則：任何 session 只要把「發現的問題」以未修狀態回報 / append 任務池當交代，就是違規。「設計任務下一輪解決」只允許用在**本回合真的做不完的多小時大工程**，且回報須寫「我正在做，只帶驗證過的結果回來」，不可是把待辦丟回給老闆。搭配 [[feedback_urgent_work_bypass_queue]]、[[feedback_dont_deflect_act_on_repeated_complaints]]、[[feedback_repeated_done_question_means_finish_now]]。

**Why**：老闆要的是「已驗證的結果」，不是「診斷 + 待辦清單」。把未修的問題回報給他 = 他得幫我追蹤進度，等於我沒做完工作。這與 [[feedback_alerts_auto_act_not_suggest]]、[[feedback_finish_task_before_standby]]、[[feedback_declare_complete_requires_class_sweep]] 同一條線：回報的內容必須是完成式。

**How to apply**：任何回報（Telegram / email / session 文字）之前先問「這件事我修好了嗎？測過了嗎？線上驗證過了嗎？」
- 三個都 yes → 才回報，內容用「已修好 + 驗證方式 + 證據」。
- 有 no → 先做完再回報；真的是多小時級大工程，回報時必須寫「我正在做，做完只帶驗證過的結果回來」，**不可**只丟一個 task id 或建議請老闆決定。
- 例外只有：不可回復風險需授權、外部 blocker（額度/權限）。
