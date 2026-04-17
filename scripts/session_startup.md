# Session 啟動必建集（shared scheduler + session-only monitor 操作細節）

SessionStart hook 會提醒讀這份。這裡只放**每次新 session 要執行的具體指令**——不是原則、不是教訓（那些留在 CLAUDE.md）。

正式時鐘現在是：

```bash
scripts/install_scheduler_cron.sh
```

下面的 session cron 僅保留為 session-local 提醒 / monitor，**不是正式派工來源**。

**Canonical source**：`config/runtime_schedules.json`
若本檔和其他文件不一致，以該檔為準；本檔只是方便複製執行的操作手冊。

## 1. Session Cron 標準啟動集（台灣時間，直接複製執行）

```python
CronCreate(cron="3 9 * * *", prompt="每日任務審視與執行計劃：(1) 盤點 user queue / scheduled queue / approval backlog (2) 盤點草稿池與今日已發佈文章缺口 (3) 讀 research_program.md 事件日曆，確認今日是否有 CPI/NFP/FOMC/TSMC 等重要事件 (4) 有事件→立即建立或執行事件任務（必要時 status=published）(5) 檢查 research_program.md 行數(<700)、知識索引是否過期(>24h) (6) 用 uv run volpred ops assign 建立今日正式任務")
CronCreate(cron="17 */6 * * *", prompt="會員問題研究")
CronCreate(cron="37 */6 * * *", prompt="平台巡檢：先跑 health + platform-cycle-summary；只有異常或 release_due 才真正執行寫入")
CronCreate(cron="7 */6 * * *", prompt="知識索引檢查：先判斷是否真的需要更新")
CronCreate(cron="23 22 * * *", prompt="Token 用量日報：每日一次 detailed；週五再補 weekly")

CronCreate(cron="0 10 28 * *", prompt="更新 NDC 景氣指標：用 Chrome DevTools MCP 導航 NDC 網站提取最新領先指標和景氣對策信號，更新 storage/macro/tw_dgbas_bci_m.csv，git commit")
```

**不再建立 `*/4 * * * *` 的「繼續研究」heartbeat cron。** 研究續跑改為 **slot-aware**（2026-04-17 放寬，M1 Max 10 核硬體）：
1. 每次觸發先 count 當前 running agents（`.claude/worktrees/` + 背景 task id 數）
2. 若 running >= **3**（建議上限）→ 直接跳過本次，避免資源競爭與編號衝突
3. 有 slot 就挑新任務，優先序：(1) user-assigned pending (2) scheduled (3) discovery
4. **不必等 user queue 清空才 discovery** — slot 有空就可**並行**跑 discovery agent
5. discovery pass 整體節奏最多每 30 分鐘一次（對整個系統的限速，不是每個 slot）
6. 同一個 K 編號 / task id 不得同時被兩個 agent 執行（啟動前 `ls experiments/<k>` + `ls .claude/worktrees/` 檢查）
7. user-assigned pending 永遠優先於 discovery — 下次 slot 空出必須先挑 user

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
drafts_r = [a for a in drafts if a.get('audience') == 'research']
drafts_g = [a for a in drafts if a.get('audience') == 'general']
pub = [a for a in feed if a.get('status') == 'published' and a.get('published_at')]
if len(drafts) < 12: alerts.append(f'Draft pool: {len(drafts)} (<12, target 12)')
if len(drafts_r) < 4: alerts.append(f'Research drafts: {len(drafts_r)} (<4)')
if len(drafts_g) < 8: alerts.append(f'General drafts: {len(drafts_g)} (<8)')
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

### 本機控制面入口
- `uv run volpred ops assign ...`：建立正式 task
- `uv run volpred ops claim-next --agent claude|codex`：agent claim 任務
- `uv run volpred ops heartbeat --agent claude|codex`：更新 session 心跳
- `uv run volpred ops control-plane-summary`：檢查 queue / agent 狀態
- `uv run volpred ops rollback create`：建立回滾點

### Monitor 使用規則
- **stdout 要精簡**：必須 `grep --line-buffered` 過濾，不可 pipe raw log
- `persistent=True` 用於 session 級監控（不自動超時）
- 非 persistent 預設 5 分鐘超時，最長 1 小時
- 其他場景：長時間 agent 實驗、daily_update/supabase_sync log 監控 → 臨時用非 persistent
