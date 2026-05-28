# Session 啟動必建集（VS Code supervisor / worker terminals）

需要手動做 session 初始化、恢復或檢查 legacy cron 路徑時再讀這份。這裡只放**每次新 session 要執行的具體指令**——不是原則、不是教訓（那些留在 CLAUDE.md）。

> **⚠️ 2026-04-19 架構更新（v12 canonical）**：3-terminal supervisor/worker workflow **已廢棄**（見 `.claude/rules/control-plane.md` + `docs/architecture.md`）。目前正式 runtime = **單一主線程 Claude Code + 按需 subagent dispatch**（claude general-purpose / codex-rescue）。下方第 0 段「三終端機」+ 第 1 段「session-bootstrap 指令」**保留作為歷史 reference 不刪除**（某些 legacy path 仍讀 `storage/ops/agents/claude-worker.json` 等檔），但**新 session 直接跳到 §2「Session Cron 標準啟動集」**。CLAUDE.md §系統定位 + §專案地圖 + `.claude/rules/*` 為最高權威。

校正後的標準 user story（legacy v11，保留 reference）：

1. VS Code 開 3 個終端機
2. 終端機 A：Claude Code supervisor
3. 終端機 B：Claude Code worker
4. 終端機 C：Codex worker

這 3 個終端機都應該是**已完成 OAuth / 人工認證**的互動 session。

## 0. 三終端機最小啟動方式（legacy v11，參考用）

### A. Claude supervisor terminal

不需要 headless `claude -p`。
這個終端機負責：

- `uv run volpred ops tasks`
- `uv run volpred ops task-show <task_id>`
- `uv run volpred ops brief-show <task_id>`
- `uv run volpred ops brief-set <task_id> --brief-json ... --actor claude-supervisor`
- `uv run volpred ops control-plane-summary`
- `uv run volpred ops health`

### B. Claude worker terminal

```bash
export VOLPRED_ACTOR=claude
uv run volpred ops session-bootstrap --agent claude --session-id claude:worker
```

工作循環：

```bash
uv run volpred ops next-task --agent claude --emit-brief
# 在同一個已登入的 Claude Code terminal 內完成任務
uv run volpred ops finish-task <task_id> --agent claude --summary "..."
```

### C. Codex worker terminal

```bash
export VOLPRED_ACTOR=codex
uv run volpred ops session-bootstrap --agent codex --session-id codex:worker
```

工作循環：

```bash
uv run volpred ops next-task --agent codex --emit-brief
# 在同一個已登入的 Codex terminal 內完成任務
uv run volpred ops finish-task <task_id> --agent codex --summary "..."
```

worker session 結束後：

```bash
uv run volpred ops session-shutdown --agent claude
uv run volpred ops session-shutdown --agent codex
```

## 1. 補充：shared scheduler 與 session cron

repo 內仍保留：

```bash
scripts/install_scheduler_cron.sh
```

但這條路徑目前應視為過渡期 / 輔助自動化機制，不是校正後的正式 worker runtime。

下面的 session cron 僅保留為 session-local 提醒 / monitor。

**Canonical source**：`config/runtime_schedules.json`
若本檔和其他文件不一致，以該檔為準；本檔只是方便複製執行的操作手冊。

## 2. Session Cron 標準啟動集（8 條 recurring，台灣時間，直接複製執行）

**2026-04-18 回復 4/11 版本 — supervisor 3-terminal workflow 已廢棄。**

### 2.0 Session 啟動前：replay pending_sessions.json（2026-04-25, 2026-04-27 新增 helper script）

新 session 開啟時**第一步**跑：

```bash
uv run python scripts/session_replay_pending.py
```

該 script 自動 mark 所有 `recorded_count > 0` 且 `replayed_at < recorded_at` 的 job `replayed_at = now`。session 內 in-process cron 會自動 fire高頻 session jobs（如 `continue_task`）— mark 等於聲明「session 已 catch up」，piggy-back recorder 不再重複累積同 window。

**Edge case（低頻 cron）**: ndc-indicator-maintain (月頻) 等若有 pending fire 表示真實 missed work — 主線程必先執行對應 maintain command，再跑 script mark replayed。Dry-run 先 audit：

```bash
uv run python scripts/session_replay_pending.py --dry-run
```

歷史背景（2026-04-27 修流程 incident）：本 SOP 原為主線程手動 jq + Edit 更新 replayed_at，缺乏 enforcement → 連續 3 天 session 啟動沒人跑 replay → pending_sessions.json 累積 110 個 missed fire（continue_task=52 / git_sync=12 / 等）即使 session active 期間 in-process cron 已實質 catch up。Helper script automate 此 step 後，主線程只需記得「啟動跑一次」即可，不必每次手 jq。

該檔由 host-cron piggy-back（每小時 `check_alerts` → `run_due_jobs._write_pending_sessions`）記錄 session 關閉期間 due 但沒 fire 的 session_cron。每個 record 含 `recorded_at` (last fire window) + `replayed_at` (last main-thread acknowledge)。

```python
CronCreate(cron="3 9 * * *", prompt="每日任務審視：執行 daily-planning-maintain --stub-if-no-work；若有 planning gap 再建立正式 task")
CronCreate(cron="*/30 * * * *", prompt="繼續任務（slot-aware）：執行 continue-task-maintain --stub-if-no-work；若有 dispatch candidate 再處理 1 個正式 task")
CronCreate(cron="37 */6 * * *", prompt="平台巡檢：執行 platform-patrol-maintain --stub-if-no-work；若有訊號再看 detail CLI")
CronCreate(cron="47 */4 * * *", prompt="Git sync：執行 git-sync-maintain --stub-if-no-work；若需同步再依 wrapper 建議處理 commit / pull / push")
CronCreate(cron="7 */6 * * *", prompt="知識索引維護：執行 knowledge-index-maintain --stub-if-no-work；若有動作再回報 after summary")
CronCreate(cron="23 22 * * *", prompt="Token 用量日報：執行 token-usage-maintain --stub-if-no-work；只有缺日報或週報時才生成並回報 after summary")
CronCreate(cron="0 10 28 * *", prompt="更新 NDC 景氣指標：執行 ndc-indicator-maintain --stub-if-no-work；只有 canonical CSV 落後時才展開人工更新流程")

註：`question_research` 已於 2026-05-26 遷移到 host cron `0 */6 * * * ~/.volpred/bin/cron_question_ops_maintain.sh`，不再由 session CronCreate 重建。
```

**繼續任務 cron 規則（`*/30 * * * *` 嚴格每 30 分鐘等距 fire，slot-aware heartbeat，任務類型不限於研究）**：
1. 每次觸發先 count 當前 running agents（`.claude/worktrees/` + 背景 task id 數）
2. 若 running >= **3**（建議上限）→ 直接跳過本次，回「跳過：slot N/3」≤15 字
3. 有 slot 就挑新任務，優先序：(1) user-assigned pending (2) scheduled (3) discovery
4. **不必等 user queue 清空才 discovery** — slot 有空就可**並行**跑 discovery agent
5. discovery pass 整體節奏最多每 30 分鐘一次（對整個系統的限速）
6. 同一個 K 編號 / task id 不得同時被兩個 agent 執行（啟動前 `ls experiments/<k>` + `ls .claude/worktrees/` 檢查）
7. user-assigned pending 永遠優先於 discovery
8. **禁止**建立 `*/2` 或更密的高頻 heartbeat；目前正式頻率是 `*/30 * * * *`（2026-04-26 用戶指定 4h→30min 等距，對齊 Claude Code Max $200 plan 1-hour prompt cache TTL — 已於 Anthropic support article 確認 Max=1h、Pro/API=5min；30min 永遠落在 cache window 中央，避免 cache cold miss 同時維持文章池與研究節奏。先試 50min 因 `*/50` 解析為 :00/:50 不等距才改 30min）
9. **反空轉**：每次 cron 觸發必須真的產出（新 agent / git diff / 新 knowledge / research_program.md 更新），只回 status check 視為 cron 失敗

## 3. Monitor 啟動（persistent，每 60 分鐘檢查 feed↔Supabase 漂移，只異常通知）

**2026-04-18 Contentlayer 模式**：Monitor 改查 `feed.json ↔ Supabase` drift（真實同步狀態），不再抓 feed.json.draft（永遠為 0，錯誤 threshold）。

```python
Monitor(
  description="feed.json ↔ Supabase drift alert (hourly)",
  persistent=True,
  timeout_ms=3600000,
  command="""cd /Users/yhlai0911/Desktop/volpred-research.old_20260418 && while true; do
  uv run python -c "
from volpred.ops.feed_sync import compute_diff
import os
from datetime import datetime
d = compute_diff()
drift = len(d['insert']) + len(d['update']) + len(d['delete'])
fsize = os.path.getsize('storage/reports/feed.json') / 1024 / 1024
ts = datetime.now().strftime('%H:%M')
if drift > 0:
    print(f'[{ts}] DRIFT: feed={d[\\\"feed_count\\\"]} db={d[\\\"db_count\\\"]} i={len(d[\\\"insert\\\"])} u={len(d[\\\"update\\\"])} d={len(d[\\\"delete\\\"])}', flush=True)
if fsize > 7.5:
    print(f'[{ts}] SIZE: feed.json {fsize:.2f}MB (>7.5MB)', flush=True)
" 2>/dev/null
  sleep 3600
done"""
)
```

## 3.1 舊 Monitor block（已廢）

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

## 4. 參考資料（不是啟動指令，僅供查閱）

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

`platform-ops-patrol` 建議 prompt：

```text
平台巡檢摘要：先跑 platform-patrol-maintain --stub-if-no-work；若有訊號，再看 check-alerts / platform-cycle-summary / scheduler-summary / log-summary 細節並建立後續任務
```

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
