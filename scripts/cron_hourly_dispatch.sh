#!/bin/bash
# Hourly dispatch trigger via OS-level cron (not session ScheduleWakeup).
#
# Why: ScheduleWakeup in interactive Claude Code session unreliably fires
# when idle. OS cron is reliable. Each invocation spawns a fresh claude
# session with -p (headless mode), runs the slot-aware dispatch prompt,
# dispatches 1 agent per hourly rule, exits.
#
# Canonical source: scripts/cron_hourly_dispatch.sh
# TCC bypass copy at: ~/.volpred/bin/cron_hourly_dispatch.sh
# After editing: cp scripts/cron_hourly_dispatch.sh ~/.volpred/bin/ && chmod +x ~/.volpred/bin/cron_hourly_dispatch.sh
#
# Cron entry (already installed):
#   7 * * * * /Users/yhlai0911/.volpred/bin/cron_hourly_dispatch.sh >> storage/logs/cron/hourly_dispatch.log 2>&1

exec >> /Users/yhlai0911/Desktop/volpred-research/storage/logs/cron/hourly_dispatch.log 2>&1
cd /Users/yhlai0911/Desktop/volpred-research || exit 1

echo "=== hourly-dispatch $(date '+%Y-%m-%d %H:%M:%S %Z') ==="

# Headless invocation. The prompt is self-contained: dispatch rules
# (hourly cadence, diversity, monetization sanity, compute queue split) are
# loaded from CLAUDE.md + .claude/rules + memory automatically.
/Users/yhlai0911/.local/bin/claude -p --dangerously-skip-permissions "Hourly dispatch trigger (OS cron). 規則 (token-conserving split architecture)：

PHASE A — 檢查 compute queue 有無 completed 待 followup：
1. 跑 \`uv run python scripts/compute_queue.py list --completed-pending-followup --json\`。
2. 若有 entries → 優先處理：對最舊一條讀 \`result_artifact\` 路徑 + agent \`claude_followup.brief\` 文字，派 Claude interpretation agent 解讀（~25K tokens, light），不再做 compute。派完跑 \`uv run python scripts/compute_queue.py mark-followup-dispatched --id <id> --next-task-id <task_id>\` 防重派。**結束本小時派工**。
3. 若無待 followup → 進 PHASE B。

PHASE B — 派新工：

**本週優先方向（2026-05-12 audit 後鎖定）**：4 篇 paper R1 待修堆 3 週沒動（taiwan-vt 6 SEVERE / vt-trend-following 7 HIGH / leverage-direction 2 CRITICAL / volatility-absorption 5 SEVERE）= 直接 M3 + monetization 護城河阻塞。本週剩 4 天 + 56% quota，**全力推 paper R1 修正**，不再 reactive 派 K-experiment autogen brief（90% 是垃圾 NULL ML / 缺資料 / duplicate id）。

1. 跑 \`uv run python scripts/continue_task_dispatch.py --report\` 看 dispatch state + agentable candidates。
2. 多樣性檢查：\`jq '[.[-5:] | .[] | .task_type]' storage/work_log.json\` — 從 10 type 池選**不在 last-3** 的 type（experiment / paper_decision / paper_body / paper_review / event_article / daily_article / member_qa / strategy_lifecycle / platform_ops / governance）。
3. **優先序（per 2026-05-12 audit）**：
   a. 若 last-3 沒包 paper_review / paper_body / paper_decision → **強制挑 paper_* 類**，派 agent 修一篇 R1 reviewer feedback（worktree=false; main repo + 一個 specific SEVERE/HIGH/CRITICAL issue）。每 paper R1 issue 拆 brief 派 1 agent。**這是本週 M3 monetization 主軸**。
   b. 否則為 type 找最高 monetization-leverage task — Mission 5-sanity 必考量，**M3 (paper) 永遠優先於 M1/M2/M4/M5**（per audit finding 1）。
4. **嚴禁**：reactive 派 K-experiment autogen brief（K1310-K1314 GARCH-to-Neural / HAR-GNN 等 ML novel-method NULL 4 連後 diversity decline）。**Override**：若 candidate id ∈ {K1310..K1330} 且 title 含 GARCH-Neural / GNN / Transformer / KAN / Conformal → skip 改派 paper_review。
4. **分流決策（重要 token 節省規則）**：
   - 若任務本質是 **heavy compute**（GARCH MLE / Bootstrap / data fetch / 全期 backtest / pooled-MLE multistart 等 CPU 密集純運算）→ **NOT** 派 Claude agent，改 \`uv run python scripts/compute_queue.py enqueue --script <path> --title <T> --result-artifact <path> --followup-brief '<解讀任務 brief>' --followup-task-type paper_review --timeout 3600\`。Compute worker cron */15 min 會接手；產生 result.json 後下次 hourly fire 自動派 interpretation agent（**省 60-70% tokens**）。注意：腳本必須**完整已寫**才能 enqueue（不能讓 worker 寫 script）。需要先寫 script 的也派 Claude agent（一次性，包含 design + run + interpret）。
   - 若任務是 **decision / writing / narrative** → 派 Claude agent 正常流程（worktree for experiments；main repo for articles/paper body）。
5. Brief 含 task title/description + skill 規範 + lookahead + Codex 審核要求 + Mission sanity check。
6. 派完 end summary 格式（per memory feedback_task_end_summary_format）：結束時間 / 總時間 / 本次 token / 完成項目 / 本週 Max 20x quota % (\`uv run python scripts/weekly_quota_estimate.py\`) / 下次任務時間。
7. 若 last-3 涵蓋所有 candidates 的 type → 派沒做過的 type，必要時主動生 brief / 文章 / compute job。「沒事做」**永不可接受**。
8. 嚴禁: force push, --no-verify, 寫 knowledge.json from agent (K1259), 假數字。研究誠實 > 一切。"

echo "=== hourly-dispatch end $(date '+%Y-%m-%d %H:%M:%S %Z') ==="

# 通知用戶 — 解決「系統有跑但看不到 = 等於沒跑」的信任問題
LATEST_COMMIT=$(/usr/bin/git -C /Users/yhlai0911/Desktop/volpred-research log -1 --pretty=format:'%h %s' 2>&1 | head -c 100)
/usr/bin/osascript -e "display notification \"$LATEST_COMMIT\" with title \"volpred hourly-dispatch $(date '+%H:%M')\" sound name \"Pop\"" 2>/dev/null || true
