---
name: 每次任務結束標準摘要格式
description: 每個 background agent 任務結束（task-notification handle 完）必輸出 4 項摘要：結束時間 / 總時間 / 完成項目 / 下次任務時間
type: feedback
originSessionId: 91283b9e-7227-43f5-88bb-9d92168d243a
---
**Rule**: 每次 background agent 完成 + 主線程處理完（commit + queue follow-up）後的回覆**最後必含**標準 6 項摘要區塊：

```
🕐 結束時間：YYYY-MM-DD HH:MM CST
⏱️ 本次任務總時間：X 分鐘 (agent runtime + 主線程處理)
🎫 本次 token：agent X,XXX (from task-notification <usage>) + 主線程估 Y,YYY ≈ Z 萬 tokens
✅ 完成任務項目：
  - <commit hash> <一句話描述>
  - <follow-up queued>
  - <metric impact e.g. reproduce gate 95.3%→95.4%>
📊 本週 Max 20x quota：XX.X% used / X.XX% remaining — 跑 `uv run python scripts/weekly_quota_estimate.py` (anchor: 42% @ 2026-05-12 13:18 CST)
⏭️ 下次任務時間：HH:MM CST（hourly rule, next 整點喚醒）
```

**Quota estimation note**:
- 用 `scripts/weekly_quota_estimate.py`，從 `token_usage_report.py --weekly` 抓 billable token 累計，除以 anchor-implied weekly cap (94.07M tokens for Max 20x)
- Anchor 校準點 = 用戶 2026-05-12 截圖 Settings → Usage → All models = 42% used
- Anchor 失效時機：(a) Anthropic 改 plan cap，(b) reset 後第一輪需要新 anchor，(c) 估值漂離實際 >5% 時用戶提供新截圖重 anchor
- Reset 週期：每週 Sun 3:59 PM 用戶本地時 (per Claude Desktop UI)

**Why**:
- 用戶 2026-05-12 明確指示：「每次任務結束都要列出 結束時間 本次任務總時間 完成任務項目 下次任務時間」
- 一致的 closure metadata 讓用戶不必滑回去找 agent dispatch 時間
- 也驅動我自己對「本次 hourly slot 真做了什麼」keep accountability

**How to apply**:
1. End time = 主線程處理完最後一個動作（commit / queue）後的當前時間
2. 總時間 = agent dispatch 到主線程 commit 完成的 wall-clock span（從 task-notification metadata `duration_ms` + 主線程處理時間估算）
3. 完成項目 = bullet list，含 commit hash + 一句話 + metric/state impact
4. 下次任務時間 = 從 ScheduleWakeup return 的 `Next wakeup scheduled for` 或 hourly rule 推算
5. 即使是 skip 也要寫（標 "本次任務 skip per hourly rule" + 下次時間）
6. emoji 可選但格式 4 項必齊
