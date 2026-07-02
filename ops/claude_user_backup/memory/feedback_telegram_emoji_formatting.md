---
name: feedback_telegram_emoji_formatting
description: Telegram 給老闆的訊息要用 emoji 區隔段落/項目符號、加強重點呈現
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 094e6fba-3043-42dd-96b2-fba274589cf9
---

老闆 2026-07-02（Telegram msg 19）指示：傳給 Telegram 的訊息「盡量用 Emoji 來區隔段落與項目符號，加強重點的呈現」。

**Why:** Telegram 是即時聊天介面，純文字段落難掃讀；emoji 當視覺錨點讓老闆快速抓重點。

**How to apply:** 所有 `volpred ops telegram-send` 的訊息 — 段落開頭用主題 emoji（✅ 完成 / ⚠️ 警示 / 📊 數據 / 🔧 修正 / ⏰ 時間 / 🚀 啟動 等），項目符號用 emoji 取代 `-`，關鍵數字/結論加強。仍守 telegram_reply 的「短、直接、口語」原則，emoji 是增強掃讀不是灌水。跟 [[feedback_task_end_summary_format]] 的時間戳要求並存。
