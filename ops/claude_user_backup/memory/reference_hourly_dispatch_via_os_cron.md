---
name: 每小時派工走 OS cron 不靠 ScheduleWakeup
description: 本地 session ScheduleWakeup 在 idle 不可靠地觸發；架構修法 = OS crontab `7 * * * *` 觸發 `claude -p` headless session 派 1 agent
type: reference
originSessionId: 91283b9e-7227-43f5-88bb-9d92168d243a
---

> **SUPERSEDED／禁止照做（2026-07-30 physical retirement）**：hourly dispatch
> 已由 Operations Core scheduler + `com.volpred.dispatch-supervisor` 接管；
> legacy LaunchAgent、live copy、canonical plist與正式wrapper都已移除。下方是事故
> 歷史，不是操作手冊。**不得**依下方步驟複製wrapper、reload crontab或bootstrap
> legacy label；需要rollback時只能回復退役前Git commit、重新跑owner reconciliation
> 與unique-owner audit，不可讓新舊clock並存。

**Historical architectural fact（已退役）**: Hourly dispatch trigger 曾由
**OS crontab** 負責，不靠 session-level ScheduleWakeup。

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

**歷史操作（不可執行）**：舊版曾把canonical wrapper複製到
`~/.volpred/bin/`並reload crontab。此路徑會繞過Operations Core的single-clock、
receipt與owner contract，已由repository retirement gate阻止復活。現行排程只看
`config/runtime_schedules.json`，部署／稽核走
`scripts/reconcile_schedule_owners.py`。

**相關記憶 / 規則**:
- `feedback_one_dispatch_per_hour.md` — 每小時 1 agent + diversity rule
- `feedback_task_end_summary_format.md` — 派工結束標準 6 項摘要
- `.claude/rules/agent-delegation.md` — 派工 type 多樣化 + monetization sanity

**Commit**: `8c8d1ec1` (2026-05-12 14:17 CST), feature commit `feat(scheduling)`.
