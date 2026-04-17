#!/bin/bash
# Session Cron Setup Script
# Run this at the start of each local agent session to restore recurring tasks
#
# Usage (in Claude Code / Codex):
#   CronCreate(cron="3 9 * * *", prompt="每日任務審視與執行計劃")
#   CronCreate(cron="17 */6 * * *", prompt="會員問題研究")
#   CronCreate(cron="37 */6 * * *", prompt="平台巡檢")
#   CronCreate(cron="7 */6 * * *", prompt="知識索引檢查")
#   CronCreate(cron="23 22 * * *", prompt="Token 用量日報")
#
# This file documents the queue-first session cron jobs. CronCreate is session-only,
# so these need to be re-created each session.
#
# Canonical source of truth:
#   config/runtime_schedules.json
# If this helper comment block and other docs disagree, follow the JSON spec.
#
# Permanent tasks (system crontab, survives across sessions):
#   crontab -l  # to see
#   - 5-min data collection: weekdays 10pm
#   - Daily update: every day 8am

echo "=== VolPred Session Cron Setup ==="
echo "System crontab (permanent):"
crontab -l 2>/dev/null
echo ""
echo "Session crons need to be created via CronCreate in your local agent session."
echo "High-frequency 'continue research' heartbeat is deprecated; use queue-first idle continuation instead."
echo "See this script for the commands to run."
