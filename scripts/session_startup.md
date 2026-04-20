# Session 啟動必建集（VS Code supervisor / worker terminals）

SessionStart hook 會提醒讀這份。這裡只放**每次新 session 要執行的具體指令**——不是原則、不是教訓（那些留在 CLAUDE.md）。

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

## 2. Session Cron 標準啟動集（7 條，台灣時間，直接複製執行）

**2026-04-18 回復 4/11 版本 — supervisor 3-terminal workflow 已廢棄。**

```python
CronCreate(cron="3 9 * * *", prompt="每日任務審視與執行計劃：(1) 盤點 user queue / scheduled queue / approval backlog (2) 盤點草稿池與今日已發佈文章缺口 (3) 讀 research_program.md 事件日曆，確認今日是否有 CPI/NFP/FOMC/TSMC 等重要事件 (4) 有事件→立即建立或執行事件任務（必要時 status=published）(5) 檢查 research_program.md 行數(<700)、知識索引是否過期(>24h) (6) 用 uv run volpred ops assign 建立今日正式任務")
CronCreate(cron="11 */2 * * *", prompt="繼續任務（每 2 小時，slot-aware）：任務類型不限於研究，涵蓋研究/發文/論文修訂/平台 ops/bug fix/會員問題/文件更新/重構。(1) slot check — `ls .claude/worktrees/ 2>/dev/null | grep -c agent-` + 背景 task；>= 3 slot 滿回「跳過：slot N/3」≤15字 (2) 跑 `uv run volpred ops check-alerts --storage-dir storage`；若 breach 由 alert system 自動 dedup + 寄信 (3) 讀 storage/next_tasks.json 取最高優先任務（P1>P2>P3>P4），不分類型 (4) 若是實驗類任務，分配新 K 編號前必 ls experiments/ + .claude/worktrees/ 確認不衝突 (5) 啟動 agent 或主線程執行（文件/ops 任務主線程做，實驗類派 agent）(6) 完成後從 research_program.md / bug_backlog / next_tasks 補充 (7) queue 空才做 discovery。反空轉：cron 觸發必有新 agent / git diff / 新 knowledge / research_program.md 更新，至少一項。")
CronCreate(cron="17 */6 * * *", prompt="會員問題研究")
CronCreate(cron="37 */6 * * *", prompt="平台巡檢：先跑 health + platform-cycle-summary + check-alerts；若 alert breach 立即寄信（24h dedup），只有異常或 release_due 才真正執行寫入")
CronCreate(cron="47 */4 * * *", prompt="每 4 小時 git commit + sync remote：(1) git status 看有意義變更 (2) git add 指定檔（不用 -A）(3) git commit (4) git pull --no-rebase origin main（merge 不 rebase，避免多 session 並行衝突）(5) git push origin main。必須 push，防本地與雲端巡檢分叉。遇 conflict 先 resolve 不可強推。")
CronCreate(cron="7 */3 * * *", prompt="知識索引更新：真需更新檢查用 `find storage/knowledge_index -type f -newer storage/memory/knowledge.json 2>/dev/null | head -1`（lancedb 寫內層 _transactions/_versions，parent dir mtime 不會更新；用 find 找新檔才正確）；若 find 有輸出 = lancedb 內已有更新，SKIP；若無輸出 = 真需 update，跑 `uv run python scripts/build_knowledge_index.py update` 增量，不要 `build` 全量（炸 Gemini 額度）")
CronCreate(cron="23 0,6,12,18 * * *", prompt="Token 用量日報：每 6 小時一次 --detailed；週五再補 --weekly；>40% 標記高消耗警告")

CronCreate(cron="0 10 28 * *", prompt="更新 NDC 景氣指標：用 Chrome DevTools MCP 導航 NDC 網站提取最新領先指標和景氣對策信號，更新 storage/macro/tw_dgbas_bci_m.csv，git commit")
```

**繼續任務 cron 規則（`11 */2 * * *` 低頻 heartbeat + slot-aware，任務類型不限於研究）**：
1. 每次觸發先 count 當前 running agents（`.claude/worktrees/` + 背景 task id 數）
2. 若 running >= **3**（建議上限）→ 直接跳過本次，回「跳過：slot N/3」≤15 字
3. 有 slot 就挑新任務，優先序：(1) user-assigned pending (2) scheduled (3) discovery
4. **不必等 user queue 清空才 discovery** — slot 有空就可**並行**跑 discovery agent
5. discovery pass 整體節奏最多每 30 分鐘一次（對整個系統的限速）
6. 同一個 K 編號 / task id 不得同時被兩個 agent 執行（啟動前 `ls experiments/<k>` + `ls .claude/worktrees/` 檢查）
7. user-assigned pending 永遠優先於 discovery
8. **禁止**建立 `*/4` 或更密的高頻 heartbeat — `*/20` 曾被試但節奏過密、`11 */2` 才是正確頻率
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
平台巡檢摘要：先跑 ops health + platform-cycle-summary + check-alerts；若 alert breach 立即寄信（24h dedup），只有異常或 release_due 才建立/執行後續任務
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
