---
name: feedback_structured_stage_report_format
description: 每個運營程序跑完，Telegram 回報要用完整結構化模板（程序/狀態/結論/產物/阻塞/下一程序/回報單），不要散文
metadata:
  node_type: memory
  type: feedback
  originSessionId: telegram-responder-e3ce06346716
---

老闆 2026-07-15（Telegram msg 798→800）貼了一個範例回報格式問「我們有這樣的程序回報嗎」「你能不能做出類似這樣的回報，你不覺得這樣比較完整嗎」。他要的模板：

```
【<程序>重點觀察｜<YYYY-MM-DD HH:MM>｜<階段>】
程序：<名稱>
狀態：<完成/進行中/失敗>
結論：<一句話：做了什麼、成功沒>
產物：<✓ 檔名清單>
阻塞：<無 或 具體阻塞>
下一程序：<下一步 @時間>
本地回報單：<回報單 json 檔名>
```

**Why:** 散文式回報老闆看不出「哪個程序、成功沒、產物、下一步」；結構化模板一眼掃完，資訊完整可追。這是 [[feedback_fix_verify_then_report]]「回報完成式」的**格式面**補充——順序對（修好驗證再報）之外，呈現也要用這模板。

**How to apply:** 每個運營程序（每日大體檢、盤中每10分、資料/發文/論文/CI 修復…）跑完，Telegram 回報用上面模板；逐則留 message id，漏報由 strict checker 擋（呼應 msg 798 的 watch_contract）。emoji 增強掃讀見 [[feedback_telegram_emoji_formatting]]。即時 telegram_reply 仍守「短、直接、口語」，但這種「回報有沒有做這件事」的匯報一律走模板。

**⚠️ 2026-07-15 msg 806 更新（老闆再發飆＋優化格式）**：老闆連問「為什麼又出現一樣的錯誤？為什麼沒照做回報格式？為什麼沒改？」——他在回覆一則 PHASE-Z critical 警報，該警報仍用舊 emoji 模板（因 SOP 未落地）。他把格式優化成**強制多一欄「驗證」**（直接回應 [[feedback_fix_verify_then_report]] msg 796 痛點）：
```
【VolPred 運營回報｜<台北時間>｜<程序>】
結論：<一句話，做完/沒做完先講>
驗證：<實測指令+結果/exit code；沒驗證就寫「未驗證：原因」>
產物：<檔案/commit/msg id>
阻塞：<無 / 具體+要決策點>
下一步：<下一程序@時間>
```
關鍵：**「驗證」欄強制——沒實測結果不准說完成**。

**⚠️ 2026-07-18 msg 973 更新（老闆要求加進度可視性）**：老闆問「以後回報是不是要列出近期已排定任務的時程和已完成的任務列表？」= 要。模板再加兩欄，放在「下一步」之後：
```
已完成（本班）：<task_id + 一句話，≤5 條，超過寫「+N 件」>
已排程：<未來 24h 的 scheduled job + pending P1-P2 任務與預計時間，≤5 條>
```
兩欄**必須程式自動生成**（已完成 = next_tasks.json 本班轉 succeeded；已排程 = runtime_schedules.json 下次 fire + pending 依 priority），不可手打，共用 helper。各欄硬上限 5 條——老闆要掃一眼看進度，不是把 30+ 筆 pending dump 成長報告。落地任務 `assign_6349aa2c`（P1，交 hourly dispatch）**已於 2026-07-18 18:12 完成**：兩欄由 `src/volpred/ops/report_sections.py` 產生、`scripts/progress_report.py` 自動附上，**刻意不開 CLI 旗標**（可手打就會被手打）；已完成欄按 `--actor` 的 fire owner token 歸屬（多 slot 併行時時間窗會誤算別班的工）——所以呼叫時務必傳 `$VOLPRED_TASK_CLAIM_OWNER`。已實發 Telegram msg 984 驗收，兩欄有真實內容。制度化任務 = canonical `governance_telegram_structured_progress_report_format`（next_tasks.json，pending，含驗證欄；早前記錄的 priority=5 code 任務即此）。responder 角色不能改 governance/commit，只能確認任務已排、用新格式回覆示範，land 交 hourly dispatch。復發類警報（如 PHASE-Z 對 work_log.json / next_tasks_archive / paper_pipeline_status.json 這種 runtime-state 檔每班重報）本身是 alert-noise 根因，另建修復任務（ops assign, task_ca7b979da7db）。
