---
name: project_cloud_agent_git_divergence
description: 雲端 Claude agent 每 6h push ops 報告到 GitHub origin/main，與本機研究主線分岔；2026-06-24 已同步，待決定分工
metadata: 
  node_type: memory
  type: project
  originSessionId: 77a63c95-6fbc-4cb3-bde4-2847b559951d
---

存在**第二個 Claude 實例**在 GitHub `yhlai0911/volpred-research` 上 commit：雲端 scheduled agent（author/committer = `Claude <noreply@anthropic.com>`），每 6 小時 push "Ops patrol report"（檢查 ARTICLE_POOL / STRATEGY_METRICS_FRESHNESS / ERROR_LOG / PAPER_TRADING_GAPS / GIT_STATUS / KNOWLEDGE_SIZE）+ 每日 token usage report，寫 `storage/ops_alerts/*`、`storage/ops_patrol_report.json`、`storage/reports/token_usage/daily_*`。它跑在 Anthropic 雲端，本機（Mac Studio）碰不到它的 prompt/config。

**Root cause（dual-source）**：本機 Mac Studio（主研究線，本地 cron + 我）與雲端 agent 從 **2026-06-04** 起在同一個 `origin/main` 上各自 commit、無協調 → history 永久分岔。雲端某次還 force 改寫過遠端 history（`70ad4b3d→a3a6bbbeb`）。本機這條線從 6/14 後**從未 push**（無自動 push 機制），到 6/24 積壓 1100+ commit 只存在本機（備份 gap）。

**2026-06-24 14:15 已處理**：merge 保留兩邊（本機研究 + 雲端 ops 報告）+ push，遠端本地完全同步（領先 0/0）。衝突只有 `ops_patrol_report.json`（取遠端最新）。治理檔（CLAUDE.md/rules）未被回退。

**分岔害處（兩條）**：(1) 雲端發現的 alert 本機主線看不到；(2) **假警報污染**——雲端報 `strategy_metrics.json missing since 5/31 (critical)`，但該檔在本機好好的（每日更新），雲端只是分岔看不到本機檔就誤報。

**已解決（2026-06-24，用戶決定停雲端）**：
- 透過 `/schedule` skill + RemoteTrigger API 把 4 個 cloud routines 全部 `enabled=false`（兩個 push-main 的：`platform-ops-patrol` trig_01HzWX2ZUmsGHnzwciGpHeNz、`token-usage-daily-report` trig_015iaE6yv3V9V1opjUAA5R2V；另兩個本就停用）。RemoteTrigger 可 disable 但**不能 delete**（要刪去 https://claude.ai/code/routines）。雲端 routine 管理入口 = `/schedule` skill（不是 computer-use；computer-use MCP 當時 disconnected）。
- 建本機 `~/.volpred/bin/cron_git_push_backup.sh`（crontab `17 */2 * * *`）接手備份：本地為唯一 push 源 → 永遠 fast-forward；偵測 behind>0 分岔則 send-alert 不強推、絕不 force。端到端測過（nothing-to-push / 真 push / 同步 0-0）。
- `config/runtime_schedules.json` 已同步：system_crontab.items 加 `git_push_backup`，remote_triggers 兩個標 `enabled:false`+disabled_reason。

**未來重啟雲端 agent 前必讀**：任何雲端 routine 都**不可**再 `git push origin main`（會重啟分岔）。若要雲端 off-site watchdog，改 email-only 或 push 專用 branch `ops-cloud/*`。
