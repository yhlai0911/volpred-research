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
# (hourly cadence, diversity, monetization sanity) are loaded from
# CLAUDE.md + .claude/rules + memory automatically.
/Users/yhlai0911/.local/bin/claude -p "Hourly dispatch trigger (OS cron). 規則：
1. 跑 \`uv run python scripts/continue_task_dispatch.py --report\` 看 dispatch state + agentable candidates。
2. 多樣性檢查：\`jq '[.[-5:] | .[] | .task_type]' storage/work_log.json\` — 從 10 type 池選**不在 last-3** 的 type（experiment / paper_decision / paper_body / paper_review / event_article / daily_article / member_qa / strategy_lifecycle / platform_ops / governance）。
3. 為該 type 找最高 monetization-leverage task（agentable / main_thread / 主動生 brief 都可）。Mission 5-sanity (M1/M2/M3/M4/M5) + monetization angle 必考量。
4. 派 1 個 background agent（general-purpose 或對應 specialized），brief 含 task title/description + experiment skill 規範 + lookahead 防錯 + Codex 審核要求 + Mission sanity check。Worktree isolation 用於實驗類；發文/論文類直接 main repo。
5. 派完 end summary 格式（per memory feedback_task_end_summary_format）：結束時間 / 總時間 / 本次 token / 完成項目 / 本週 Max 20x quota % (跑 \`uv run python scripts/weekly_quota_estimate.py\`) / 下次任務時間。
6. 若 last-3 涵蓋了所有有 candidates 的 type → 派沒做過的 type，必要時主動生 brief / 文章。「沒事做」**永不可接受**。
7. 嚴禁: force push, --no-verify, 寫 knowledge.json from agent (K1259), 假數字。研究誠實 > 一切。"

echo "=== hourly-dispatch end $(date '+%Y-%m-%d %H:%M:%S %Z') ==="
