# Autonomous Loop Protocol (autonomous-fire only)

**Last updated**: 2026-07-14 03:00 台灣時間

只有最後一則真人訊息是 `<<autonomous-loop-dynamic>>` sentinel 的 autonomous fire 才走本流程。互動 turn 禁用 `ScheduleWakeup`，由文字回覆收尾；24/7 persistence 由 `com.volpred.dispatch-supervisor` 與 host cron 負責。

## Step 1 — Run ops cycle
- **定位一次到位**：`uv run python scripts/ops_snapshot.py`（backbone / queue / pool / alerts / git 一份 JSON；2026-07-14 WS1b 起取代零散 ls / git status / jq 巡檢）
- Diff `storage/ops/handoff_latest.md` since last fire（敘事脈絡）
- Check `storage/ops/dashboard_latest.json` breaches（snapshot 未涵蓋的 dashboard 維度）
- Triage critical email backlog（snapshot.queue 有 email_reply 時才展開）
- Commit any orphan deliverables（snapshot.git.dirty_files > 0 時才跑 git status 細查）
- Dispatch 1 task from next_tasks if pool > 0 and slot < 4

## Step 2 — Summarize to markdown
Write `/tmp/loop_summary_$(date +%Y%m%dT%H%M%S).md` containing:
```markdown
# 自主 loop fire <HH:MM> 台灣時間

## 過去 30 min ops cycle 結論
- breaches: <count or 0>
- dispatch supervisor: heartbeat <ts>; last completion <outcome/exit_code>
- email backlog: <count>
- ...

## 動作
1. <each action with file/commit ref>
2. ...

## 未做 / blocked
- <items needing main thread or boss decision>

## 下次 fire
- ScheduleWakeup: <YYYY-MM-DD HH:MM>
- 預期任務: <what next fire will check>
```

## Step 3 — Email boss
```bash
uv run volpred ops send-alert \
  --level info \
  --title "自主 loop fire <HH:MM> — <一句話要點>" \
  --body-md /tmp/loop_summary_<ts>.md
```
- `--level critical` if any breach
- `--level warn` if action needed by boss

## Step 4 — ScheduleWakeup next fire
```python
ScheduleWakeup(
    delaySeconds=1800,  # default 30 min; adjust per context
    prompt="<<autonomous-loop-dynamic>>",
    reason="<specific watchlist for next fire — not 'watching'>"
)
```

## Anti-patterns (per boss directive 2026-05-28 15:35)

| ❌ Don't | ✅ Do |
|---|---|
| Interactive turn 呼叫 ScheduleWakeup | 以文字回覆收尾；讓 OS backbone 維持 24/7 |
| ScheduleWakeup without sending email | Always email first, then schedule |
| Generic email body "loop fire complete" | Concrete summary with breach count, commits, blockers |
| 2 consecutive fires with same idle summary | Expand scope — proactively dispatch task instead |
| Skip ops cycle on idle wake | Even 0-breach fire emits "30 min idle, 0 breaches, X tasks pending, next @ HH:MM" |

## Trigger references
- User-memory: `feedback_autonomous_loop_email_summary`
- This file is auto-loaded by autonomous loop sentinel via path scan
