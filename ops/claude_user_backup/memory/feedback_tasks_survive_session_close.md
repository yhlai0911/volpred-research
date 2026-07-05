---
name: feedback_tasks_survive_session_close
description: 關掉 session/終端後，下次打開要能接續所有定時+非定時任務（含巡檢）；backbone 必須 session-independent
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 77a63c95-6fbc-4cb3-bde4-2847b559951d
---

用戶 2026-06-24 硬性要求：**關掉 session 或終端機後，下次打開時要能接續所有定時與非定時任務，包含巡檢。**

**Why**：互動 session 的 ScheduleWakeup autonomous loop chain 會在 `/exit` / 終端關閉時斷掉（2026-05-29 已知 gap）。不能讓平台運營依賴「互動 session 一直開著」。

**How to apply — backbone 必須 session-independent（OS cron / LaunchAgent，不依賴互動 session）**：
- **定時任務**：OS crontab（17 行）+ LaunchAgent（collect/release/memory-health/fred-guard 等）— session-independent ✓
- **非定時派工 + 巡檢**：`com.volpred.dispatch-supervisor` LaunchAgent（常駐 daemon，2026-07-04 cutover 取代 com.volpred.hourly-dispatch）每小時 :07 spawn headless `claude -p`（prompt = `scripts/cron_hourly_dispatch_prompt.md`）做 dispatch + ops cycle — session-independent ✓（RunAtLoad+KeepAlive，比舊 StartCalendarInterval 更強壯）
- **巡檢**：`ops_dashboard`（:30 LaunchAgent+crontab）+ `check_alerts`（hourly LaunchAgent+crontab）獨立巡檢 — session-independent ✓。停掉雲端 patrol（[[project_cloud_agent_git_divergence]]）後，本地這兩個 cron + hourly-dispatch 主 agent 巡檢接手，不靠雲端。
- **互動 autonomous loop**（ScheduleWakeup chain）= enhancement，session 開著時更頻繁；斷了有上述 OS backbone 兜底；下次開 session 由 CLAUDE.md「Session start 自動啟動」規則自動恢復（2026-06-24 驗證 CLAUDE.md 7 處提及該機制）。

**驗證結論（2026-06-24）**：backbone 已 session-independent，關終端不會中斷定時/非定時/巡檢。每次動到排程或停用某個 cron/routine 時，必須重新確認 backbone 仍完整覆蓋（特別巡檢不可只剩互動 session）。

**已知風險**：`config/runtime_schedules.json` 的 `host_crontab_managed` 只標 8 項，但實際 crontab 有 17 行手動維護 → `install_host_crontab.sh` 跑下去會刪 9 個運作中 cron（地雷）。config↔crontab drift 待 audit；在 audit 修好前**不可跑 install_host_crontab.sh**。

**重開機恢復（2026-06-24 驗證）**：
- **crontab**：cron daemon 開機自啟、crontab 持久 → ✅ 無條件恢復。
- **LaunchAgent（15 個）**：plist 在 `~/Library/LaunchAgents/`，是 **user-level** → **必須使用者 GUI 登入**才由 launchd 載入。多數 `RunAtLoad=false`（正常，StartCalendarInterval 排程登入後照常生效，false 只是不在載入瞬間多跑一次）。
- **關鍵 gap = auto-login**：若 Mac Studio 設「系統設定→使用者與群組→自動登入」= 重開機完全自動恢復；若沒設 = 停在登入畫面，要有人登入才恢復巡檢/派工。**待用戶確認/開啟 auto-login**（我查不到，需 sudo 讀 com.apple.loginwindow）。
- **autonomous loop**：重開機後一定要有人開 Claude Code session 才恢復（OS backbone 兜底巡檢+派工）。
- 更 robust 但更複雜的選項：關鍵 LaunchAgent 改 LaunchDaemon（系統級、免登入），但 headless claude 需 user 環境的 auth token，LaunchDaemon 無 user session 可能失敗 → **auto-login 是最務實解**。
