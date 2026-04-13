# 自動化排程

**所有時間統一標註台灣時間（UTC+8）。** 系統 crontab 和 session cron 本機執行，直接用台灣時間。
**雲端 RemoteTrigger 的 cron 表達式固定 UTC — 設定時必須「台灣時間 - 8 小時」換算。**

## 永久任務（系統 crontab — 無人值守也會跑，台灣時間）
```
0 15 * * 1-5   collect_tw_data.py      # 15:00 台股收盤後
3 7 * * 2-6    collect_us_data.py      # 07:03 美股收盤後
3 8 * * 2-6    daily_update.py         # 08:03 策略計算+Supabase sync（含 market_status）
3 */2 * * *    release-pool-by-settings # 每 2 小時 1 篇文章池釋出
0 8 * * 1      market_calendar sync    # 每週一 08:00 延展未來 30 天交易日曆
```

## 雲端觸發（RemoteTrigger，無需 session 活躍）

| trigger | cron (UTC) | 台灣時間 | 說明 |
|---------|-----------|---------|------|
| `platform-ops-patrol` | `0 */6 * * *` | 每 6 小時 | `trig_01HzWX2ZUmsGHnzwciGpHeNz` |
| `token-usage-daily-report` | `43 14 * * *` | 每日 22:43 | `trig_015iaE6yv3V9V1opjUAA5R2V` |

## 標準 Session Cron（每次新 session 重建）
```
CronCreate(cron="3 9 * * *", prompt="每日任務審視與執行計劃")
CronCreate(cron="11 */2 * * *", prompt="繼續研究")
CronCreate(cron="17 */6 * * *", prompt="會員問題研究")
CronCreate(cron="47 */4 * * *", prompt="git commit + sync remote")
CronCreate(cron="7 */3 * * *", prompt="知識索引更新")
CronCreate(cron="23 0,6,12,18 * * *", prompt="Token 用量日報")
CronCreate(cron="0 10 28 * *", prompt="更新 NDC 景氣指標")
```

## 反空轉規則
每次「繼續研究」cron 觸發後，必須滿足以下至少一項：
1. 有新 agent 在背景跑
2. 有實際的 git diff
3. 有新的知識庫/經驗庫記錄
4. 有新的 research_program.md 更新

禁止連續兩次 cron 觸發都只回覆 status check。
