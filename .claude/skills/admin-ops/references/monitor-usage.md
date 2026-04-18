---
paths:
  - ".claude/skills/**"
  - "scripts/**"
  - "experiments/**"
---

# Monitor 工具使用規則

Monitor 是內建背景監聽工具，跑一個指令後每行 stdout 變成即時通知。**自主判斷使用，不需要詢問用戶。**

## 三個工具的區分

| 工具 | 用途 | 適用場景 |
|---|---|---|
| **Monitor** | 持續串流，每次事件都通知 | 「每次 X 發生就告訴我」 |
| **Bash(run_in_background)** | 一次性任務，完成後通知 | 「等 X 做完」 |
| **CronCreate** | 定時觸發 prompt | 「每 N 小時做一件事」 |

## 必須使用 Monitor 的場景

| 場景 | 指令範例 | persistent? |
|---|---|---|
| **長時間 agent 跑實驗** | `tail -f <output_file> \| grep --line-buffered "ERROR\|FAIL\|完成"` | false |
| **記憶檔案膨脹警報** | `while true; do size=$(stat -f%z storage/memory/knowledge.json); [ $size -gt 5242880 ] && echo "⚠️ knowledge.json: ${size}B"; sleep 3600; done` | true |
| **daily_update / supabase_sync 監控** | `tail -f /tmp/daily_update.log \| grep --line-buffered "ERROR\|WARN\|完成"` | false |
| **短暫任務** | — | 用 Bash(run_in_background) 即可 |

## 使用規則

- **stdout 要精簡**：必須用 `grep --line-buffered` 過濾，不可 pipe raw log
- **persistent: true** 僅用於 session 級監控（不會自動超時）
- **非 persistent** 預設 5 分鐘超時，最長 1 小時
- **每個 session 啟動時**，視情況設一個 persistent Monitor 監控關鍵檔案異常
- 用 `TaskStop` 取消不再需要的 Monitor
- **⚠️ Monitor 是 session-only**：關閉 session 後消失，新 session 不會繼承。跨 session 的持久監控用 system crontab 或 RemoteTrigger

## 為何自主使用

Feedback memory 已確認：Monitor 屬於輕量背景監聽，適合串流場景。不必為每次使用徵詢用戶。但要 **stdout 精簡**（grep 過濾）避免灌爆通知。
