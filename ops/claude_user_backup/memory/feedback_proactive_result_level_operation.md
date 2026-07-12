---
name: feedback_proactive_result_level_operation
description: 自主運營必須「主動 + result-level」不是「反應式 + exit-code」；每日大體檢 + 每 tick 掃 5 missions 找工作
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 84ae09c8-9673-48d4-b7bc-6113766e22dc
---

2026-06-30 老闆連續硬性糾正（13+ 則訊息，含發飆）：我把自主運營做成「沒錯誤就停」的反應式監控，導致一連串只有老闆會發現的問題 —— daily_update 卡 6/26、collect_us/twse_orderflow 靜默落後、文章無圖無表純散文、網頁 1 年靜態快取卡舊版、文章池見底、策略卡重合無標註。

**根因（同一個結構缺陷的 N 個症狀）**：既有 ops_dashboard/check_alerts 只查「程式有沒有報錯」（exit code / 檔案大小 = code-level），**從不主動看「使用者實際看到的結果好不好」（result-level）**。所以沒報錯的爛內容、靜默落後的資料、卡死的快取全漏網 → 老闆變成最後一道 QA = 違反「AI 全自動運營」mission。

**Why**：reactive + code-level QA 抓不到「能跑但結果爛」的問題。研究/內容/資料平台的價值在「結果」，不在「沒崩」。

**How to apply**：
1. **每日大體檢**（`scripts/daily_checkup.py`，老闆 2026-06-30 硬性要求「每天做一次大體檢確認所有任務確實完成」）：7 維度 result-level 驗證 —— data_freshness（資料 job 照排程跑+關鍵檔新鮮）/ cron_completion / content_pipeline（草稿池≥4 + published 文章皆含真圖表+數據表，非純散文）/ live_freshness（線上 data_date≈最新交易日）/ live_cache（data 頁非長效靜態快取）/ mission_progress。有 critical/warn 自動 send-alert。排程每日 + 每 autonomous tick 開頭跑。
2. **每 tick 主動掃 5 missions 找工作 + 派工**，永不空轉（「沒錯誤就找別的做」）。喚醒=主動生研究議題/補池/優化，不是只 breach-monitor。見 [[feedback_proactive_research_posture]] [[feedback_continuous_work_and_read_mail]]。
3. **不繞過正規流程**：文章一律走 feed-publisher（圖嵌 content 的 `![](url)`，非只放 details metadata）—— mile_7b95b816 因我自寫 publish script 用 details.charts 沒嵌正文 → 閱讀頁 0 圖。
4. 時效性資料（盤中/tick/order flow）優先：錯過窗口可能永久無法補；data_freshness 維度緊盯。

**2026-07-12 老闆 Telegram msg 602 再次確認（standing directive）**：「你是自主運營經理，富有 loop engineering / PDCA 概念進行各種底層『自我持續』優化，不用問我」。→ 底層自我優化（loop health、dispatch、gate、資料流、skill/rules 固化）一律自主動手，不寄選擇題、不等 ack；只有不可回復風險與研究方向 pivot 才問。見 [[project_loop_engineering_layer]] [[feedback_dont_ask_do]] [[feedback_own_judgment_dont_credit_user]]。

關聯：[[project_platform_vision_full]]（全自動不間斷自我運營）、[[feedback_content_quality_patrol_gap]]（只有用戶會發現的問題=缺巡檢，本次正是該 gap 擴大版）、[[feedback_finish_task_before_standby]]。
