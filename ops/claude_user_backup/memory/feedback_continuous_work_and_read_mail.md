---
name: feedback_continuous_work_and_read_mail
description: autonomous loop 要持續做實事不是心跳空轉；老闆 mandate 要直接讀 Gmail 最新信，不靠 lagging polled task
metadata: 
  node_type: memory
  type: feedback
  originSessionId: df279cec-2a1a-4970-b0ae-111055444eb8
---

用戶 2026-06-07 連兩次重話糾正（「一個小時二十分鐘不間斷工作 看來你是沒做了」+「信沒讀到 對吧」+「幹」）。兩個 recurring 失敗：

## 失敗 1：autonomous tick 心跳空轉，不是工作
- 我的 loop 一直是：check dashboard → email「健康」→ sleep 60min。**那是心跳,不是工作**，違反 CLAUDE.md「idle is failure / 不可空轉 / 每次 idle pass 必產可驗證輸出」。
- hourly-dispatch cron 在做事 ≠ 我的 main loop 在做事。**我自己每個 tick 都要推進實事**（派研究/寫文/論文 review/清 backlog），產出可驗證 output。
- **不間斷工作 = 持續產出**：短 wakeup（不是睡 60min）、每 tick 都 dispatch/收一個真任務，直到真的沒 actionable（那也要主動生研究議題 per [[feedback_proactive_research_posture]]），不是「全綠→睡」。
- 「mandate 19 分鐘衝完就 idle」也違背「不間斷」—— 老闆要的是**持續**工作滿整個窗口，不是 burst + idle。

## 失敗 2：沒讀老闆最新 Gmail mandate
- 老闆 14:41 寄「接下來 1h20min 不間斷執行任務 全部 opus 4.8 1M 最大 effort ultramax」，我**沒讀到**（依賴 lagging polled email_reply task，gmail_poll 還沒抓到）。
- 同錯誤 2026-06-06 已犯過一次（台灣夜盤崩盤回信也漏看）。
- **規則**：老闆說「處理我回信 / 看信」或任何 mandate 跡象 → **直接用 Gmail MCP `search_threads from:yihao.lai@gmail.com newer_than:Xh` 讀最新那封**，不要只看 next_tasks 的 polled task（poll 有 lag）。

**How to apply**：每個 autonomous fire 開頭 (a) 撈 Gmail 最新未讀回信（不只 polled task），(b) 推進一個真任務產出，(c) 短 wakeup 續工，不心跳空轉。

## 失敗 3（2026-06-08 復發）：Gmail 查詢 filter 把老闆回信濾掉了
- 我每 tick 用 `from:yihao.lai@gmail.com newer_than:35m -subject:Alert -subject:新文章 -subject:Summary -subject:Report` 查回信。
- **致命**：老闆回覆 Boss Report 時主旨是「**Re: [VolPred Boss Report]**」→ 被我自己的 `-subject:Report` 濾掉。系統 auto-send 和老闆 reply 在**同一條 thread / 同一 subject 家族**，用 subject 排除 = 連老闆回信一起盲掉。
- 後果：老闆 09:15 P1「立刻徹底解決 warning」我隔 ~50 min（下個非 filter 路徑偶然發現 claimed email task）才處理。email_reply task 被 auto-claim 但 instruction 沒執行。
- **正確做法**：查 Gmail 時**不要用 `-subject:` 排除 Report/Summary/Alert**（那會盲掉老闆對這些的 reply）。改用：`from:yihao.lai@gmail.com newer_than:Xh` 撈全部，再**看每條 thread 最新一封是不是老闆親寫**（snippet 開頭不是「VolPred 管理通知 / VolPred Boss Report」這種 auto-send banner，而是老闆的短指令文字；或 labelIds 含 UNREAD 且非系統 SENT 模板）。auto-send 與 boss reply 都來自同 address，**靠 subject 分不出來，要看 body/snippet 內容**。

相關：[[feedback_proactively_complete_red_alerts]]、[[feedback_proactive_research_posture]]、[[feedback_autonomous_loop_email_summary]]、[[feedback_resume_ops_loop_after_user]]。
