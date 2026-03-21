#!/bin/bash
# Session Cron Setup Script
# Run this at the start of each Claude Code session to restore recurring tasks
#
# Usage (in Claude Code):
#   CronCreate(cron="7 * * * *", prompt="每小時知識索引重建：uv run python scripts/build_knowledge_index.py build")
#   CronCreate(cron="23 */3 * * *", prompt="每3小時同步：uv run python scripts/daily_update.py")
#   CronCreate(cron="37 */6 * * *", prompt="每6小時部署：用 Agent 背景執行 bash scripts/deploy_zeabur.sh")
#   CronCreate(cron="47 */2 * * *", prompt="每2小時 git commit")
#
# This file documents the cron jobs. Claude Code CronCreate is session-only,
# so these need to be re-created each session.
#
# Permanent tasks (system crontab, survives across sessions):
#   crontab -l  # to see
#   - 5-min data collection: weekdays 10pm
#   - Daily update: every day 8am

echo "=== VolPred Session Cron Setup ==="
echo "System crontab (permanent):"
crontab -l 2>/dev/null
echo ""
echo "Session crons need to be created via CronCreate in Claude Code."
echo "See this script for the commands to run."
