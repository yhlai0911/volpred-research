<!-- AUTO-GENERATED FROM agent-specs/. Edit canonical sources instead. -->

# 自動化排程

**Canonical source**：`config/runtime_schedules.json`

**所有時間統一標註台灣時間（UTC+8）。** 系統 crontab 和 session cron 本機執行，直接用台灣時間。
**雲端 RemoteTrigger 的 cron 表達式固定 UTC — 設定時必須「台灣時間 - 8 小時」換算。**

## 永久任務（系統 crontab — 無人值守也會跑，台灣時間）
```
0 15 * * 1-5   collect_tw_data.py      # 15:00 台股收盤後
3 7 * * 2-6    collect_us_data.py      # 07:03 美股收盤後
3 8 * * 2-6    daily_update.py         # 08:03 策略計算+Supabase sync（含 market_status）
3 */2 * * *    release-pool-by-settings # 每 2 小時 1 篇文章池釋出
```

## 雲端觸發（RemoteTrigger，無需 session 活躍）

| trigger | cron (UTC) | 台灣時間 | 說明 |
|---------|-----------|---------|------|
| `platform-ops-patrol` | `0 */6 * * *` | 每 6 小時 | `trig_01HzWX2ZUmsGHnzwciGpHeNz` |
| `token-usage-daily-report` | `43 14 * * *` | 每日 22:43 | `trig_015iaE6yv3V9V1opjUAA5R2V` |

## 標準 Session Cron（每次新 session 重建）
```
CronCreate(cron="3 9 * * *", prompt="每日任務審視：執行 daily-planning-maintain --stub-if-no-work；若有 planning gap 再建立正式 task")
CronCreate(cron="13 */4 * * *", prompt="繼續任務（slot-aware）：執行 continue-task-maintain --stub-if-no-work；若有 dispatch candidate 再處理 1 個正式 task")
CronCreate(cron="17 */6 * * *", prompt="會員問題研究：執行 question-ops-maintain --stub-if-no-work；若有 pending 再看 workflow")
CronCreate(cron="37 */6 * * *", prompt="平台巡檢：執行 platform-patrol-maintain --stub-if-no-work；若有訊號再看 detail CLI")
CronCreate(cron="7 */6 * * *", prompt="知識索引維護：執行 knowledge-index-maintain --stub-if-no-work；若有動作再回報 after summary")
CronCreate(cron="23 22 * * *", prompt="Token 用量日報：執行 token-usage-maintain --stub-if-no-work；只有缺日報或週報時才生成並回報 after summary")
CronCreate(cron="0 10 28 * *", prompt="更新 NDC 景氣指標：執行 ndc-indicator-maintain --stub-if-no-work；只有 canonical CSV 落後時才展開人工更新流程")
```

## Idle-driven continuation（取代高頻 heartbeat）
- 不再建立 `*/2 * * * *` 或更密的「繼續任務」heartbeat cron（標準是 `13 */4` 每 4 小時 slot-aware；2026-04-26 12h→4h）
- agent 完成主任務後，先檢查 `user queue`
- `user queue` 為空，再檢查 `scheduled queue`
- queue 都空了，才允許做一輪 discovery / research continuation
- discovery pass 最多每 30 分鐘一次
- 只要 queue 裡存在 `user-assigned` 任務，discovery 直接停用

## 反空轉規則
每次 idle-driven continuation 或 discovery pass 後，必須滿足以下至少一項：
1. 有新 agent 在背景跑
2. 有實際的 git diff
3. 有新的知識庫/經驗庫記錄
4. 有新的 research_program.md 更新
5. 有新的正式 task / approval / execution receipt 寫入本機控制面

禁止只做 status check 然後空轉離開。
