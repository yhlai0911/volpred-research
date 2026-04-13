# Session 啟動必建集（cron + Monitor 操作細節）

SessionStart hook 會提醒讀這份。這裡只放**每次新 session 要執行的具體指令**——不是原則、不是教訓（那些留在 CLAUDE.md）。

## 0. 去重檢查（每次啟動必做，放在 cron/Monitor 之前）

Session cron 和 Monitor **不會自動去重**。在新增前必須先檢查：

```python
# 檢查是否已經有 cron 和 Monitor（避免重複）
CronList()  # 看現有 cron 列表
TaskList()  # 看現有 Monitor（description 含 "Article pool + file bloat"）
```

**決策規則**：
- **沒有任何 cron** → 全量執行第 1 段
- **已有部分 cron（例如 session 續跑）** → 跳過已有，只補缺的
- **有重複（例如兩個相同 prompt 的 cron）** → 用 `CronDelete(cronId)` 刪多的再重建
- **Monitor 已存在** → 不要重複啟動；若要重啟，先 `TaskStop(taskId)` 再 `Monitor(...)`

### 跨 session 並行的限制
- 同一台機器開**兩個 session 並行**時，各 session 的 CronList 彼此**看不見對方的 cron**（各自獨立）
- 因此並行 session 會導致雙份 cron 跑同樣任務 → 撞 git、撞 `next_tasks.json`
- **建議實務**：盡量只保留一個 active session；若需多 session，至少讓其中一個**關閉 session cron**（只做手動操作），讓主 session 獨佔 cron
- 偵測方法：開新 session 時檢查 `ps aux | grep claude` 是否已有其他 session 在跑

## 1. Session Cron 標準啟動集（台灣時間，直接複製執行）

```python
CronCreate(cron="3 9 * * *", prompt="每日任務審視與執行計劃：(1) 盤點草稿池數量、今日已發佈文章（一般4/研究2/每日1）、草稿 buffer ≥4 (2) 讀 research_program.md 事件日曆，WebSearch 確認今日是否有 CPI/NFP/FOMC/TSMC 等重要事件 (3) 有事件→立即寫事件文章（--status published）(4) 檢查 research_program.md 行數(<700)、知識索引是否過期(>24h)、next_tasks 是否為空 (5) 根據缺口用 TaskCreate 列出今日必做清單 (6) 文章撰寫前必做 LanceDB 語義查重 + grep (7) 輸出今日計劃告訴用戶")

CronCreate(cron="11 */2 * * *", prompt="繼續研究：(1) 讀 storage/next_tasks.json 取最高優先任務 (2) 分配編號前先 ls experiments/ 確認該編號目錄不存在，已存在則跳到下一個可用編號。同時檢查 .claude/worktrees/ 確認沒有 agent 在用該編號 (3) 啟動 agent 執行 (4) 完成後從 research_program.md 補充 next_tasks (5) next_tasks 空了才讀 research_program.md 全文。絕對不可只 check status。注意：若前一個任務還在進行中，直接跳過不重複啟動")

CronCreate(cron="17 */6 * * *", prompt="會員問題研究")

CronCreate(cron="47 */4 * * *", prompt="每4小時 git commit + sync remote：(1) git add 有意義的變更 (2) git commit (3) git pull --no-rebase origin main (4) git push origin main。必須 push，防止本地與雲端巡檢分叉。用 merge 不用 rebase，避免多 session 並行時 rebase 衝突")

CronCreate(cron="7 */3 * * *", prompt="知識索引更新")

CronCreate(cron="23 0,6,12,18 * * *", prompt="Token 用量日報：(1) python scripts/token_usage_report.py --detailed (2) 將結果存檔到 storage/token_reports/ (3) 週五額外 --weekly (4) >40% 標記高消耗警告 (5) 摘要告訴用戶")

CronCreate(cron="0 10 28 * *", prompt="更新 NDC 景氣指標：用 Chrome DevTools MCP 導航 NDC 網站提取最新領先指標和景氣對策信號，更新 storage/macro/tw_dgbas_bci_m.csv，git commit")
```

## 2. Monitor 啟動（persistent，每 30 分鐘檢查，只異常通知）

```python
Monitor(
  description="Article pool + file bloat health (emit only on alert)",
  persistent=True,
  timeout_ms=3600000,
  command="""cd /Users/yhlai0911/Desktop/volpred-research && while true; do
  python3 -c "
import json, os, subprocess
from pathlib import Path
from datetime import datetime, timezone

alerts = []
k_size = os.path.getsize('storage/memory/knowledge.json')
f_size = os.path.getsize('storage/reports/feed.json')
if k_size > 5_242_880: alerts.append(f'knowledge.json: {k_size/1024/1024:.2f}MB (>5MB)')
if f_size > 7_340_032: alerts.append(f'feed.json: {f_size/1024/1024:.2f}MB (>7MB)')

feed = json.loads(Path('storage/reports/feed.json').read_text())
drafts = [a for a in feed if a.get('status') == 'draft']
pub = [a for a in feed if a.get('status') == 'published' and a.get('published_at')]
if len(drafts) < 3: alerts.append(f'Draft pool: {len(drafts)} (<3)')
now = datetime.now(timezone.utc)
latest = max((datetime.fromisoformat(a['published_at'].replace('Z','+00:00')) for a in pub), default=None)
if latest:
    h = (now - latest).total_seconds() / 3600
    if h > 3: alerts.append(f'No publish in {h:.1f}h')

wt = subprocess.run(['ls', '.claude/worktrees/'], capture_output=True, text=True)
wts = [x for x in wt.stdout.strip().split('\n') if x and x.startswith('agent-')]
if len(wts) > 3: alerts.append(f'Orphan worktrees: {len(wts)}')

if alerts:
    ts = now.strftime('%H:%M')
    for a in alerts: print(f'[{ts}] ALERT: {a}', flush=True)
" 2>/dev/null
  sleep 1800
done"""
)
```

## 3. 參考資料（不是啟動指令，僅供查閱）

### 永久任務（系統 crontab，不需重啟）
```
0 15 * * 1-5   collect_tw_data.py      # 15:00 台股收盤後（0050.TW 日頻+5min、VIXTWN）
3 7 * * 2-6    collect_us_data.py      # 07:03 美股收盤後（SPY/GLD/TLT/QQQ/EEM/VIX/VIX3M/N225）
3 8 * * 2-6    daily_update.py         # 08:03 策略計算+Supabase sync
3 */2 * * *    release-pool-by-settings # 每 2 小時 1 篇文章池釋出
```
查看：`crontab -l`

### RemoteTrigger（雲端巡守，不需重啟）
**⚠️ cron 表達式 = UTC，不是台灣時間。新增時必須「台灣時間 - 8 小時」換算。**

| trigger | cron (UTC) | 台灣時間 | 說明 |
|---------|-----------|---------|------|
| `platform-ops-patrol` | `0 */6 * * *` | 每 6 小時 | 平台巡檢 `trig_01HzWX2ZUmsGHnzwciGpHeNz` |
| `token-usage-daily-report` | `43 14 * * *` | 22:43 | Token 日報 `trig_015iaE6yv3V9V1opjUAA5R2V` |

### Monitor 使用規則
- **stdout 要精簡**：必須 `grep --line-buffered` 過濾，不可 pipe raw log
- `persistent=True` 用於 session 級監控（不自動超時）
- 非 persistent 預設 5 分鐘超時，最長 1 小時
- 其他場景：長時間 agent 實驗、daily_update/supabase_sync log 監控 → 臨時用非 persistent
