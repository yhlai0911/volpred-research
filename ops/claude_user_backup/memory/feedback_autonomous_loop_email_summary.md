---
name: feedback-autonomous-loop-email-summary
description: Autonomous ScheduleWakeup loop 每次 fire 結尾必寄 email summary 給老闆 + 排下次 wakeup
metadata: 
  node_type: memory
  type: feedback
  originSessionId: b53cb2b5-27a5-433a-a987-4803ac9edc7e
---

每次 autonomous `<<autonomous-loop-dynamic>>` fire 跑完 ops cycle 後，**必須** 寄 email summary 給老闆才能 ScheduleWakeup 排下次 fire。

**Why**：老闆 2026-05-28 15:35 硬性指示「安排完任務 就發信讓我知道」。Autonomous loop 對老闆是不可見的（他不在 interactive session）— 若不寄 email 通知，他無從得知我做了什麼、是否有問題、下次何時 fire。Email = 透明度 + 信任 + Mission 5 平台可問責。

**How to apply**（每次 autonomous fire 結尾固定 4 步）：

1. **總結本輪 ops cycle**：dashboard breaches / handoff diff / hourly fire status / triage / commit / 派工 — 寫成 markdown summary（≤500 字）
2. **寄 email**：
   ```bash
   uv run volpred ops send-alert --level info \
     --title "自主 loop fire: <HH:MM> — <一句話本輪要點>" \
     --body-md /tmp/loop_summary_<timestamp>.md
   ```
   - Level 視結果：normal info / breaches 觸發 warn / 重大問題 critical
   - Title 含時間戳 + 本輪 1 句要點（不是空泛 "loop fire complete"）
   - Body 含：本輪做了什麼、發現什麼、未做什麼、下次 fire 時間
3. **ScheduleWakeup 排下次**（傳 `<<autonomous-loop-dynamic>>` sentinel）：
   - 預設 30 min interval
   - 接近 hourly :07 fire 時可改 short interval pre-flight check
   - 重大 incident 處理中可 60 min 給 cron / worker 充足時間
4. **reason 欄位** 寫具體（不寫「watching」）— e.g. 「16:07 hourly fire 後 verify badge diversity + commit any orphan worker_daemon deliverable」

**禁止**：
- Fire 完 schedule 下次但不寄 email → 違反此規則，老闆失去能見度
- Email 含 generic 「無事發生」→ 至少報「過去 30 min idle, 0 breaches, next fire @ HH:MM」也好
- 連 2 次 fire summary 同樣 → 沒新 info 該擴大 ops scope (e.g. 主動派 task)

**Related**: [[reference_hourly_dispatch_via_os_cron]] (hourly LaunchAgent 是另一層 24/7 autonomous，不衝突)
