---
name: 每小時派工走 OS cron 不靠 ScheduleWakeup
description: 本地 session ScheduleWakeup 在 idle 不可靠地觸發；架構修法 = OS crontab `7 * * * *` 觸發 `claude -p` headless session 派 1 agent
type: reference
originSessionId: 91283b9e-7227-43f5-88bb-9d92168d243a
---
**Architectural fact**: Hourly dispatch trigger 由 **OS crontab** 負責，**不**靠 session-level ScheduleWakeup。

**Why**:
- 2026-05-12 多次發現 ScheduleWakeup at 14:12 沒 fire（session idle 時不可靠）
- 用戶 explicitly demanded: "從底層邏輯、流程、程式架構徹底改進"
- OS cron = reliable, fires regardless of interactive session state

**架構**:
1. `crontab` entry: `7 * * * * /Users/yhlai0911/.volpred/bin/cron_hourly_dispatch.sh # volpred-hourly-dispatch`
2. Canonical source: `scripts/cron_hourly_dispatch.sh`
3. TCC bypass copy: `~/.volpred/bin/cron_hourly_dispatch.sh`（macOS FDA 限制下 cron 走 `~/.volpred/bin/` wrapper）
4. Log: `storage/logs/cron/hourly_dispatch.log`
5. 每小時 :07 fire → `claude -p "<dispatch prompt>"` headless → 跑 dispatch logic → exit
6. Documented in `config/runtime_schedules.json` cron_jobs array

**How to apply**:
1. **不**依賴 session ScheduleWakeup 做 hourly trigger — OS cron 才是 source of truth
2. Session ScheduleWakeup 仍用於：(a) task-notification 後 follow-up reset, (b) sub-hourly emergency wake (≤30 min)
3. 改 cron behavior：先改 `scripts/cron_hourly_dispatch.sh` → `cp` 到 `~/.volpred/bin/` → reload crontab
4. 排程衝突檢測：每次 cron fire 開新 claude session，與當前 interactive session 並存 — 兩邊都能派 agent；diversity rule 跨 session 不共享 work_log 即時更新，但寫入 storage/work_log.json 的 entries 是 cross-session shared
5. Reliability test：每天看 `tail -50 storage/logs/cron/hourly_dispatch.log`，缺漏 fire 立刻 debug crontab

**相關記憶 / 規則**:
- `feedback_one_dispatch_per_hour.md` — 每小時 1 agent + diversity rule
- `feedback_task_end_summary_format.md` — 派工結束標準 6 項摘要
- `.claude/rules/agent-delegation.md` — 派工 type 多樣化 + monetization sanity

**Commit**: `8c8d1ec1` (2026-05-12 14:17 CST), feature commit `feat(scheduling)`.
