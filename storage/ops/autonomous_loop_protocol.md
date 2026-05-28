# Autonomous Loop Protocol (interactive-session ScheduleWakeup)

**Last updated**: 2026-05-28 15:35 台灣時間 (boss directive)

Interactive session 用 ScheduleWakeup + `<<autonomous-loop-dynamic>>` sentinel 跑自主 ops loop 時，每次 fire 結尾**強制 4 步**：

## Step 1 — Run ops cycle
- Check `storage/ops/dashboard_latest.json` breaches
- Diff `storage/ops/handoff_latest.md` since last fire
- Verify last hourly cron fire (`storage/logs/cron/hourly_dispatch.log` exit code)
- Triage critical email backlog (`scripts/task_pool_claim.py list --status pending` filter email_reply)
- Commit any orphan deliverables (`git status` for uncommitted refactor pieces)
- Dispatch 1 task from next_tasks if pool > 0 and slot < 4

## Step 2 — Summarize to markdown
Write `/tmp/loop_summary_$(date +%Y%m%dT%H%M%S).md` containing:
```markdown
# 自主 loop fire <HH:MM> 台灣時間

## 過去 30 min ops cycle 結論
- breaches: <count or 0>
- hourly fire <last_HH:07>: exit <0/1>
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
| ScheduleWakeup without sending email | Always email first, then schedule |
| Generic email body "loop fire complete" | Concrete summary with breach count, commits, blockers |
| 2 consecutive fires with same idle summary | Expand scope — proactively dispatch task instead |
| Skip ops cycle on idle wake | Even 0-breach fire emits "30 min idle, 0 breaches, X tasks pending, next @ HH:MM" |

## Trigger references
- User-memory: `feedback_autonomous_loop_email_summary`
- This file is auto-loaded by autonomous loop sentinel via path scan
