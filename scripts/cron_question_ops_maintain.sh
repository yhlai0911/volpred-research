#!/bin/bash
exec >> /Users/yhlai0911/Desktop/volpred-research/storage/logs/cron/question_ops_maintain.log 2>&1
# Canonical source. cron-exec target at ~/.volpred/bin/cron_question_ops_maintain.sh
# After editing this file, sync with:
#   cp scripts/cron_question_ops_maintain.sh ~/.volpred/bin/ && chmod +x ~/.volpred/bin/cron_question_ops_maintain.sh
cd /Users/yhlai0911/Desktop/volpred-research
echo "=== question-ops-maintain $(date '+%Y-%m-%d %H:%M:%S') ==="
exec /opt/homebrew/bin/uv run volpred ops question-ops-maintain --source user --auto-create-task --stub-if-no-work
