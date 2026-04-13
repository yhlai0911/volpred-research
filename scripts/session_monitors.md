# Session 啟動必建 Monitor（每次新 session 貼上執行一次）

Monitor 是 session-only，關 session 就消失。每次新 session 啟動時，除了設 cron，也要設這個 persistent Monitor。只在異常時發通知，正常運作無干擾。

## 標準啟動指令（複製給 Monitor 工具）

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
# 1. 檔案膨脹
k_size = os.path.getsize('storage/memory/knowledge.json')
f_size = os.path.getsize('storage/reports/feed.json')
if k_size > 5_242_880: alerts.append(f'knowledge.json: {k_size/1024/1024:.2f}MB (>5MB)')
if f_size > 7_340_032: alerts.append(f'feed.json: {f_size/1024/1024:.2f}MB (>7MB)')

# 2. 文章池 + 發佈新鮮度
feed = json.loads(Path('storage/reports/feed.json').read_text())
drafts = [a for a in feed if a.get('status') == 'draft']
pub = [a for a in feed if a.get('status') == 'published' and a.get('published_at')]
if len(drafts) < 3: alerts.append(f'Draft pool: {len(drafts)} (<3)')
now = datetime.now(timezone.utc)
latest = max((datetime.fromisoformat(a['published_at'].replace('Z','+00:00')) for a in pub), default=None)
if latest:
    h = (now - latest).total_seconds() / 3600
    if h > 3: alerts.append(f'No publish in {h:.1f}h')

# 3. Worktree orphan
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

## 監控門檻

| 項目 | 門檻 | 原因 |
|------|------|------|
| `knowledge.json` | >5MB | LanceDB 索引成本暴增，需瘦身或分表 |
| `feed.json` | >7MB | Token 節約規則禁止整檔讀取，容易被漏讀 |
| Draft 池 | <3 篇 | Buffer 過低，釋出後池可能空 |
| 最新發文 | >3 小時前 | 網站停更警告（CLAUDE.md: 池不可空超過 3 小時） |
| Worktree | >3 個 | Agent 未合併累積，`merge_worktree.sh` 漏合 |

## 為什麼要寫進 SessionStart 流程

Monitor 是 session-only，每次新 session 都要重建。不列入必建清單會忘記——2026-04-13 第一次遺漏是用戶主動問「有在 monitor 嗎」才發現。

不放在 CLAUDE.md inline 是因為 CLAUDE.md 是每次 session 都載入的核心 context，珍貴 token 不應該被 Monitor 程式碼佔用。放這裡，SessionStart hook 提醒 Claude 來讀。
