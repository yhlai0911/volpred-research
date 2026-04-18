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
CronCreate(cron="3 9 * * *", prompt="每日任務審視與執行計劃：(1) 盤點 user queue / scheduled queue / approval backlog (2) 盤點草稿池與今日已發佈文章缺口 (3) 讀 research_program.md 事件日曆，確認今日是否有 CPI/NFP/FOMC/TSMC 等重要事件 (4) 有事件→立即建立或執行事件任務（必要時 status=published）(5) 檢查 research_program.md 行數(<700)、知識索引是否過期(>24h) (6) 用 uv run volpred ops assign 建立今日正式任務")
CronCreate(cron="17 */6 * * *", prompt="會員問題研究摘要：先跑 question-ranking-workflow；只有 pending_questions > 0 才建立/執行後續任務")
CronCreate(cron="37 */6 * * *", prompt="平台巡檢摘要：先跑 ops health + platform-cycle-summary；只有異常或 release_due 才建立/執行後續任務")
CronCreate(cron="7 */6 * * *", prompt="知識索引檢查：先判斷是否真的需要更新")
CronCreate(cron="23 22 * * *", prompt="Token 用量日報：每日一次 detailed；週五再補 weekly")
CronCreate(cron="0 10 28 * *", prompt="更新 NDC 景氣指標：用 Chrome DevTools MCP 導航 NDC 網站提取最新領先指標和景氣對策信號，更新 storage/macro/tw_dgbas_bci_m.csv，git commit")
```

## Idle-driven continuation（取代高頻 heartbeat）
- 不再建立 `*/4 * * * *` 或更密的「繼續任務」heartbeat cron（標準是 `11 */2` 每 2 小時 slot-aware）
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
